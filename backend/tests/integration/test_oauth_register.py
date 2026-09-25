"""RFC 7591 Dynamic Client Registration + RFC 8414 AS metadata integration
tests (ADR 0025/0026, KAN-1734). No auth on either route — the whole point of
DCR is obtaining a first client identity with nothing to authenticate with yet.
"""
from __future__ import annotations

REGISTER = "/auth/register"
AS_METADATA = "/.well-known/oauth-authorization-server"


def test_authorization_server_metadata_shape(client):
    r = client.get(AS_METADATA)
    assert r.status_code == 200
    body = r.json()
    assert body["issuer"] == "http://testserver"
    assert body["registration_endpoint"] == "http://testserver/auth/register"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]
    assert body["client_id_metadata_document_supported"] is True


def test_register_persists_a_client_row_and_returns_it(client):
    from sqlalchemy import text

    from app.db import engine

    r = client.post(
        REGISTER,
        json={
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "client_name": "Claude",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["client_id"].startswith("pandan_client_")
    assert body["redirect_uris"] == ["https://claude.ai/api/mcp/auth_callback"]
    assert body["client_name"] == "Claude"
    assert body["token_endpoint_auth_method"] == "none"
    assert isinstance(body["client_id_issued_at"], int)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT client_id, client_name FROM oauth_client WHERE client_id = :cid"),
            {"cid": body["client_id"]},
        ).one()
    assert row.client_name == "Claude"


def test_register_with_no_client_name_is_optional(client):
    r = client.post(REGISTER, json={"redirect_uris": ["https://example.com/cb"]})
    assert r.status_code == 201
    assert r.json()["client_name"] is None


def test_register_rejects_bad_redirect_uri(client):
    r = client.post(REGISTER, json={"redirect_uris": ["http://evil.example.com/cb"]})
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_redirect_uri"


def test_register_rejects_missing_redirect_uris(client):
    r = client.post(REGISTER, json={})
    assert r.status_code == 422  # FastAPI's own required-field validation


def test_register_rejects_a_confidential_client_auth_method(client):
    r = client.post(
        REGISTER,
        json={
            "redirect_uris": ["https://example.com/cb"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client_metadata"


def test_register_needs_no_auth(client):
    """No Authorization header at all -- DCR's whole point is obtaining a first
    credential, mirroring the device flow's own no-auth entry points."""
    r = client.post(REGISTER, json={"redirect_uris": ["https://example.com/cb"]})
    assert r.status_code == 201
