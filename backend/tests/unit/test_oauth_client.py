"""OAuth client identification tests: RFC 7591 DCR + CIMD (ADR 0025/0026,
KAN-1734). Pure-logic unit tests — no DB, no real network (httpx.get is
monkeypatched for every CIMD case)."""
from __future__ import annotations

import httpx
import pytest

from app import oauth_client as oc


class _FakeScalars:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeDB:
    """Just enough of a SQLAlchemy Session for resolve_client's DCR-lookup
    branch: `db.scalars(select(...)).first()`."""

    def __init__(self, row=None):
        self._row = row

    def scalars(self, _stmt):
        return _FakeScalars(self._row)


# --- redirect_uri validation --------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "http://localhost:3000/callback",
        "http://127.0.0.1:3000/callback",
        "http://[::1]:3000/callback",
        "http://LOCALHOST:9999/callback",  # case-insensitive hostname
    ],
)
def test_valid_redirect_uris_accepted(uri):
    oc.validate_redirect_uris([uri])  # must not raise


@pytest.mark.parametrize(
    "uri",
    [
        "http://evil.example.com/callback",  # plain http to a real host
        "ftp://example.com/callback",  # wrong scheme entirely
        "not-a-url",
        "https://",  # https with no host
    ],
)
def test_invalid_redirect_uris_rejected(uri):
    with pytest.raises(oc.InvalidClientMetadata):
        oc.validate_redirect_uris([uri])


def test_empty_redirect_uris_rejected():
    with pytest.raises(oc.InvalidClientMetadata):
        oc.validate_redirect_uris([])


def test_too_many_redirect_uris_rejected():
    uris = [f"https://example.com/cb{i}" for i in range(oc.MAX_REDIRECT_URIS + 1)]
    with pytest.raises(oc.InvalidClientMetadata):
        oc.validate_redirect_uris(uris)


# --- register_client (RFC 7591 DCR) -------------------------------------------


class _FakeSession:
    """Just enough of a Session for register_client: add/commit/refresh."""

    def add(self, obj):
        self._obj = obj

    def commit(self):
        pass

    def refresh(self, obj):
        pass


def test_register_client_mints_a_prefixed_opaque_client_id():
    client = oc.register_client(
        _FakeSession(), redirect_uris=["https://example.com/cb"], client_name="Test App"
    )
    assert client.client_id.startswith(oc.CLIENT_ID_PREFIX)
    assert client.client_name == "Test App"
    assert client.redirect_uris == ["https://example.com/cb"]


def test_register_client_rejects_bad_redirect_uri():
    with pytest.raises(oc.InvalidClientMetadata):
        oc.register_client(_FakeSession(), redirect_uris=["http://evil.com/cb"], client_name=None)


def test_register_client_rejects_overlong_client_name():
    with pytest.raises(oc.InvalidClientMetadata):
        oc.register_client(
            _FakeSession(),
            redirect_uris=["https://example.com/cb"],
            client_name="x" * (oc.MAX_CLIENT_NAME_LEN + 1),
        )


# --- CIMD client_id shape recognition -----------------------------------------


@pytest.mark.parametrize(
    "client_id",
    [
        "https://app.example.com/oauth/client-metadata.json",
        "https://app.example.com/x",
    ],
)
def test_is_cimd_client_id_true_for_https_urls_with_a_path(client_id):
    assert oc._is_cimd_client_id(client_id) is True


@pytest.mark.parametrize(
    "client_id",
    [
        "pandan_client_abc123",  # a DCR-minted opaque id
        "https://app.example.com",  # https but no path
        "https://app.example.com/",  # https, path is just "/"
        "http://app.example.com/x",  # not https
    ],
)
def test_is_cimd_client_id_false_otherwise(client_id):
    assert oc._is_cimd_client_id(client_id) is False


# --- CIMD document fetch + validation ------------------------------------------


CIMD_URL = "https://app.example.com/oauth/client-metadata.json"


def _mock_get(
    monkeypatch, response: httpx.Response | None = None, *, raises: Exception | None = None
):
    def fake_get(url, timeout=None, follow_redirects=None):
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(oc.httpx, "get", fake_get)


@pytest.fixture(autouse=True)
def _clear_cimd_cache():
    oc._cimd_cache.clear()
    yield
    oc._cimd_cache.clear()


def test_resolve_client_fetches_a_valid_cimd_document(monkeypatch):
    doc = {
        "client_id": CIMD_URL,
        "client_name": "Example MCP Client",
        "redirect_uris": ["http://127.0.0.1:3000/callback"],
    }
    _mock_get(monkeypatch, httpx.Response(200, json=doc, request=httpx.Request("GET", CIMD_URL)))

    resolved = oc.resolve_client(_FakeDB(), CIMD_URL)

    assert resolved.client_id == CIMD_URL
    assert resolved.client_name == "Example MCP Client"
    assert resolved.redirect_uris == ("http://127.0.0.1:3000/callback",)


def test_resolve_client_caches_a_successful_cimd_fetch(monkeypatch):
    doc = {"client_id": CIMD_URL, "client_name": "X", "redirect_uris": ["https://x.com/cb"]}
    calls = []

    def fake_get(url, timeout=None, follow_redirects=None):
        calls.append(url)
        return httpx.Response(200, json=doc, request=httpx.Request("GET", url))

    monkeypatch.setattr(oc.httpx, "get", fake_get)

    oc.resolve_client(_FakeDB(), CIMD_URL)
    oc.resolve_client(_FakeDB(), CIMD_URL)

    assert len(calls) == 1, "the second resolve_client call should hit the cache, not the network"


def test_cimd_client_id_mismatch_is_rejected(monkeypatch):
    doc = {
        "client_id": "https://someone-else.example.com/x.json",
        "redirect_uris": ["https://x.com/cb"],
    }
    _mock_get(monkeypatch, httpx.Response(200, json=doc, request=httpx.Request("GET", CIMD_URL)))

    with pytest.raises(oc.InvalidClientMetadata, match="does not match its URL"):
        oc.resolve_client(_FakeDB(), CIMD_URL)


def test_cimd_document_missing_redirect_uris_is_rejected(monkeypatch):
    doc = {"client_id": CIMD_URL}
    _mock_get(monkeypatch, httpx.Response(200, json=doc, request=httpx.Request("GET", CIMD_URL)))

    with pytest.raises(oc.InvalidClientMetadata, match="redirect_uris"):
        oc.resolve_client(_FakeDB(), CIMD_URL)


def test_cimd_document_with_bad_redirect_uri_is_rejected(monkeypatch):
    doc = {"client_id": CIMD_URL, "redirect_uris": ["http://evil.example.com/cb"]}
    _mock_get(monkeypatch, httpx.Response(200, json=doc, request=httpx.Request("GET", CIMD_URL)))

    with pytest.raises(oc.InvalidClientMetadata):
        oc.resolve_client(_FakeDB(), CIMD_URL)


def test_cimd_non_json_body_is_rejected(monkeypatch):
    _mock_get(
        monkeypatch,
        httpx.Response(200, content=b"not json", request=httpx.Request("GET", CIMD_URL)),
    )
    with pytest.raises(oc.InvalidClientMetadata, match="not valid JSON"):
        oc.resolve_client(_FakeDB(), CIMD_URL)


def test_cimd_non_200_status_is_rejected(monkeypatch):
    _mock_get(monkeypatch, httpx.Response(404, request=httpx.Request("GET", CIMD_URL)))
    with pytest.raises(oc.InvalidClientMetadata, match="404"):
        oc.resolve_client(_FakeDB(), CIMD_URL)


def test_cimd_oversized_document_is_rejected(monkeypatch):
    huge = {
        "client_id": CIMD_URL,
        "redirect_uris": ["https://x.com/cb"],
        "padding": "x" * (oc._CIMD_MAX_BYTES + 1),
    }
    _mock_get(monkeypatch, httpx.Response(200, json=huge, request=httpx.Request("GET", CIMD_URL)))
    with pytest.raises(oc.InvalidClientMetadata, match="size limit"):
        oc.resolve_client(_FakeDB(), CIMD_URL)


def test_cimd_transport_error_is_rejected(monkeypatch):
    _mock_get(monkeypatch, raises=httpx.ConnectError("boom"))
    with pytest.raises(oc.InvalidClientMetadata, match="could not fetch"):
        oc.resolve_client(_FakeDB(), CIMD_URL)


def test_cimd_non_dict_document_is_rejected(monkeypatch):
    _mock_get(
        monkeypatch,
        httpx.Response(200, json=["not", "a", "dict"], request=httpx.Request("GET", CIMD_URL)),
    )
    with pytest.raises(oc.InvalidClientMetadata, match="JSON object"):
        oc.resolve_client(_FakeDB(), CIMD_URL)


# --- resolve_client: the DCR (DB) branch --------------------------------------


def test_resolve_client_looks_up_a_dcr_client_by_id():
    class _Row:
        client_id = "pandan_client_abc"
        client_name = "CLI"
        redirect_uris = ["https://example.com/cb"]

    resolved = oc.resolve_client(_FakeDB(row=_Row()), "pandan_client_abc")
    assert resolved.client_id == "pandan_client_abc"
    assert resolved.client_name == "CLI"
    assert resolved.redirect_uris == ("https://example.com/cb",)


def test_resolve_client_returns_none_for_unknown_dcr_client_id():
    assert oc.resolve_client(_FakeDB(row=None), "pandan_client_does_not_exist") is None
