"""Hosted Streamable HTTP MCP transport tests (ADR 0025, KAN-1732).

Covers the one thing this slice adds that nothing else in the suite touches:
the auth chokepoint in front of ``/mcp`` (``app.mcp_host._BearerAuthMiddleware``)
and the per-request client bridge it feeds (``pandan_mcp.request_auth``) — a
missing/invalid bearer must ``401`` before the MCP session manager ever runs a
tool, and a valid one must resolve to *its own* owning user's data (board
authorization is unaffected — same ``authorize_board`` chokepoint as every
other ``/api/v1`` caller), never the stdio transport's process-wide singleton.

**Why the tool calls here don't need mocking, and why there's only ever one
``TestClient`` in this file.** The MCP tool layer's own outgoing calls go
through a real ``PandanClient``, which normally means a real TCP round-trip
back to this very backend process — not something the socket-less `client`
fixture the rest of this suite uses can serve on its own (there's no bound
port to dial, and looping an in-process ASGI transport back through the same
event loop the MCP SDK's worker-thread tool call is *already* borrowing from
turns out not to be safely reentrant — httpx's `TestClient` transport hits an
internal sync/async assertion when called that way). ``_live_backend_for_mcp_tools``
below instead spins up a **second, real, socket-bound** ``uvicorn`` instance
of this exact same ``app.main.app`` for the tool layer's outgoing calls to
dial, while the ``/mcp`` request under test still goes through the ordinary
in-process ``client``/``TestClient`` fixture. The two never contend over
`app.mcp_host`'s hosted-MCP lifespan slot because the live backend is only
ever asked for ``/api/v1`` — never ``/mcp`` — so its own copy of that slot
just sits unused. The suite's normal ``login_as`` fixture opens a **second,
independent** ``TestClient`` per identity, which — unlike this file's live
backend — *would* collide by entering a second, overlapping ``/mcp`` lifespan
of the same app-level slot, so these tests log in as each identity
**sequentially, on the one `client` fixture itself** (fine, since a PAT, once
minted, needs no active session to use later) via :func:`_login_as` below,
rather than pulling in ``login_as``.
"""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

MCP = "/mcp"
TOKENS = "/api/v1/tokens"
BOARDS = "/api/v1/boards"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@pytest.fixture(scope="module")
def _live_backend_for_mcp_tools():
    """A real, socket-bound ``uvicorn`` instance of this same ``app.main.app``
    — see the module docstring's *why* section for what it's for and why it
    can't collide with the ``/mcp`` request under test."""
    import uvicorn

    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("live backend for MCP-tool calls didn't start in time")

    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            if httpx.get(f"{base_url}/api/health", timeout=1).status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.05)
    else:
        raise RuntimeError("live backend for MCP-tool calls never became healthy")

    yield base_url

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(autouse=True)
def _route_mcp_client_through_live_backend(_live_backend_for_mcp_tools, monkeypatch):
    """Point the MCP tool layer's own config at the live backend above, so its
    ``PandanClient`` calls (``pandan_mcp.server._client_instance``) have a
    real socket to dial instead of the default ``http://localhost:8000``,
    which nothing in this test process is listening on."""
    monkeypatch.setenv("PANDAN_API_URL", _live_backend_for_mcp_tools)


def _login_as(client, monkeypatch, email: str, account_id: str) -> None:
    """Drive the mocked GitHub authorize -> callback flow on ``client`` itself
    (unlike the suite's ``login_as`` fixture, which opens a brand-new
    ``TestClient`` per identity — see the module docstring for why that would
    collide with the hosted-MCP lifespan slot here). Calling this a second
    time with a different identity simply replaces the session cookie, which
    is all that's needed since a PAT, once minted, authenticates on its own."""
    from app import users

    async def fake_get_access_token(code, redirect_uri, code_verifier=None):
        return {"access_token": "gh-access-token", "expires_at": None}

    async def fake_get_id_email(access_token):
        return account_id, email

    monkeypatch.setattr(users.github_oauth_client, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(users.github_oauth_client, "get_id_email", fake_get_id_email)

    authorize = client.get("/auth/github/authorize")
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    client.get(
        "/auth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


def _mcp_post(client, body: dict, headers: dict | None = None):
    hdrs = dict(_MCP_HEADERS)
    if headers:
        hdrs.update(headers)
    return client.post(MCP, json=body, headers=hdrs)


def _parse_sse_json(response) -> dict:
    """The Streamable HTTP transport's response body is an SSE stream (one
    ``data: <json>`` line per JSON-RPC message here) even for a single
    request/response pair — unwrap it to the JSON-RPC envelope."""
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no SSE data line in response body: {response.text!r}")


def _init_session(client, bearer_headers: dict) -> dict:
    """Drive the two-step MCP handshake (``initialize`` then the
    ``notifications/initialized`` ack) and return headers carrying the
    resulting ``mcp-session-id`` for subsequent calls on ``client``."""
    r = _mcp_post(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0.0.1"},
            },
        },
        bearer_headers,
    )
    assert r.status_code == 200, r.text
    session_id = r.headers["mcp-session-id"]
    hdrs = dict(bearer_headers)
    hdrs["mcp-session-id"] = session_id
    notif = _mcp_post(client, {"jsonrpc": "2.0", "method": "notifications/initialized"}, hdrs)
    assert notif.status_code == 202
    return hdrs


def _call_tool(client, hdrs: dict, name: str, arguments: dict, *, id_: int = 2) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": id_,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    r = _mcp_post(client, body, hdrs)
    assert r.status_code == 200, r.text
    return _parse_sse_json(r)["result"]


# --- auth chokepoint: no bearer, no session ----------------------------------


def test_missing_bearer_is_401(client):
    r = _mcp_post(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["detail"] == "missing bearer token"


def test_non_bearer_scheme_is_401(client):
    r = _mcp_post(
        client,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "missing bearer token"


def test_unknown_bearer_is_401(client):
    r = _mcp_post(
        client,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        _bearer("pandan_pat_this-was-never-minted"),
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid or expired token"


def test_revoked_token_is_401_over_mcp(client, monkeypatch):
    _login_as(client, monkeypatch, *ALICE)
    created = client.post(TOKENS, json={"name": "hosted-mcp"}).json()
    raw = created["token"]
    client.delete(f"{TOKENS}/{created['id']}")

    init_body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    r = _mcp_post(client, init_body, _bearer(raw))
    assert r.status_code == 401


# --- a valid PAT reaches the tool layer as its own owning user ---------------


def test_valid_pat_reaches_tools_and_resolves_its_own_owner(client, monkeypatch):
    _login_as(client, monkeypatch, *ALICE)
    a_board = client.get(BOARDS).json()[0]["id"]
    raw = client.post(TOKENS, json={"name": "hosted-mcp"}).json()["token"]

    hdrs = _init_session(client, _bearer(raw))
    result = _call_tool(client, hdrs, "list_boards", {})

    assert result["isError"] is False
    board_ids = [b["id"] for b in result["structuredContent"]["boards"]]
    assert board_ids == [a_board]


def test_two_live_hosted_sessions_never_cross_wires(client, monkeypatch):
    """The whole point of the per-request contextvar bridge (KAN-1732): two
    hosted callers sharing this one server process must each see only their
    own boards, proven here with two live MCP sessions interleaved on the one
    `client` rather than each getting a clean slate."""
    _login_as(client, monkeypatch, *ALICE)
    a_board = client.get(BOARDS).json()[0]["id"]
    a_raw = client.post(TOKENS, json={"name": "hosted-mcp-alice"}).json()["token"]

    _login_as(client, monkeypatch, *BOB)
    b_board = client.post(BOARDS, json={"name": "bob board"}).json()["id"]
    b_raw = client.post(TOKENS, json={"name": "hosted-mcp-bob"}).json()["token"]

    a_hdrs = _init_session(client, _bearer(a_raw))
    b_hdrs = _init_session(client, _bearer(b_raw))

    a_result = _call_tool(client, a_hdrs, "list_boards", {})
    b_result = _call_tool(client, b_hdrs, "list_boards", {})

    assert [b["id"] for b in a_result["structuredContent"]["boards"]] == [a_board]
    assert [b["id"] for b in b_result["structuredContent"]["boards"]] == [b_board]


def test_pat_stays_board_gated_over_the_hosted_transport(client, monkeypatch):
    """Hosted MCP is a new door onto the same house: board authorization
    (``app.authz.authorize_board``) isn't re-implemented or bypassed here."""
    _login_as(client, monkeypatch, *ALICE)
    raw = client.post(TOKENS, json={"name": "hosted-mcp"}).json()["token"]

    _login_as(client, monkeypatch, *BOB)
    b_board = client.post(BOARDS, json={"name": "bob board"}).json()["id"]

    hdrs = _init_session(client, _bearer(raw))
    result = _call_tool(client, hdrs, "get_board", {"board_id": b_board})

    assert result["isError"] is True
