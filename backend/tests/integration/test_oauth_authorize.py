"""OAuth 2.1 authorization_code + PKCE grant tests (ADR 0026, KAN-1735).

Per the suite convention, all ``import app.*`` live inside test bodies.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

REGISTER = "/auth/register"
AUTHORIZE = "/auth/authorize"
AUTHORIZE_INFO = "/auth/authorize/info"
AUTHORIZE_APPROVE = "/auth/authorize/approve"
AUTHORIZE_DENY = "/auth/authorize/deny"
DEVICE_TOKEN = "/auth/device/token"
BOARDS = "/api/v1/boards"
ME = "/api/v1/me"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")

REDIRECT_URI = "http://127.0.0.1:9999/callback"
RESOURCE = "http://testserver/mcp"  # TestClient's default base_url is http://testserver


def _pkce_pair():
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _register_client(client, redirect_uris=(REDIRECT_URI,), name="Test MCP Client") -> str:
    r = client.post(REGISTER, json={"redirect_uris": list(redirect_uris), "client_name": name})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _authorize_params(client_id, challenge, state="xyz", **overrides):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
        "scope": "write",
        "state": state,
    }
    params.update(overrides)
    return params


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# --- GET /auth/authorize ------------------------------------------------------


def test_authorize_unknown_client_is_a_direct_400_not_a_redirect(client):
    _, challenge = _pkce_pair()
    r = client.get(
        AUTHORIZE,
        params=_authorize_params("no-such-client", challenge),
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client"


def test_authorize_unregistered_redirect_uri_is_a_direct_400_not_a_redirect(client):
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    params = _authorize_params(client_id, challenge, redirect_uri="http://evil.example/cb")
    r = client.get(AUTHORIZE, params=params, follow_redirects=False)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_authorize_wrong_response_type_redirects_with_error(client):
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    params = _authorize_params(client_id, challenge, response_type="token")
    r = client.get(AUTHORIZE, params=params, follow_redirects=False)
    assert r.status_code == 302
    q = _query(r.headers["location"])
    assert q["error"] == "unsupported_response_type"
    assert q["state"] == "xyz"


def test_authorize_unsupported_pkce_method_redirects_with_error(client):
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    params = _authorize_params(client_id, challenge, code_challenge_method="plain")
    r = client.get(AUTHORIZE, params=params, follow_redirects=False)
    assert r.status_code == 302
    assert _query(r.headers["location"])["error"] == "invalid_request"


def test_authorize_wrong_resource_redirects_with_invalid_target(client):
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    params = _authorize_params(client_id, challenge, resource="http://testserver/not-mcp")
    r = client.get(AUTHORIZE, params=params, follow_redirects=False)
    assert r.status_code == 302
    assert _query(r.headers["location"])["error"] == "invalid_target"


def test_authorize_success_redirects_to_the_spa_with_params_forwarded(client):
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    params = _authorize_params(client_id, challenge)
    r = client.get(AUTHORIZE, params=params, follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("http://testserver/?")
    q = _query(location)
    assert q["client_id"] == client_id
    assert q["redirect_uri"] == REDIRECT_URI
    assert q["code_challenge"] == challenge
    assert q["resource"] == RESOURCE
    assert q["state"] == "xyz"


# --- GET /auth/authorize/info -------------------------------------------------


def test_authorize_info_requires_auth(client):
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    r = client.get(AUTHORIZE_INFO, params=_authorize_params(client_id, challenge))
    assert r.status_code == 401


def test_authorize_info_returns_the_client_name_and_requested_scope(login_as, client):
    alice = login_as(*ALICE)
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    r = alice.get(AUTHORIZE_INFO, params=_authorize_params(client_id, challenge, scope="read"))
    assert r.status_code == 200
    body = r.json()
    assert body["client_name"] == "Test MCP Client"
    assert body["requested_scope"] == "read"
    assert body["resource"] == RESOURCE


# --- POST /auth/authorize/approve --------------------------------------------


def test_approve_requires_auth(client):
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    r = client.post(AUTHORIZE_APPROVE, json=_authorize_params(client_id, challenge))
    assert r.status_code == 401


def test_approve_rejects_a_board_the_approver_does_not_own(login_as, client):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_board = bob.post(BOARDS, json={"name": "Bob's"}).json()["id"]
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    payload = _authorize_params(client_id, challenge, board_ids=[bob_board])
    r = alice.post(AUTHORIZE_APPROVE, json=payload)
    assert r.status_code == 403


def test_approve_returns_a_redirect_to_with_a_code_and_state(login_as, client):
    alice = login_as(*ALICE)
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    r = alice.post(AUTHORIZE_APPROVE, json=_authorize_params(client_id, challenge))
    assert r.status_code == 200
    body = r.json()
    assert body["redirect_to"].startswith(f"{REDIRECT_URI}?")
    q = _query(body["redirect_to"])
    assert "code" in q
    assert q["state"] == "xyz"


# --- POST /auth/authorize/deny ------------------------------------------------


def test_deny_returns_a_redirect_to_with_access_denied(login_as, client):
    alice = login_as(*ALICE)
    client_id = _register_client(client)
    _, challenge = _pkce_pair()
    r = alice.post(AUTHORIZE_DENY, json=_authorize_params(client_id, challenge))
    assert r.status_code == 200
    q = _query(r.json()["redirect_to"])
    assert q["error"] == "access_denied"
    assert q["state"] == "xyz"


# --- end-to-end: authorize -> approve -> exchange ----------------------------


def _approve_and_get_code(alice, client, client_id, verifier, challenge, **overrides):
    payload = _authorize_params(client_id, challenge, **overrides)
    r = alice.post(AUTHORIZE_APPROVE, json=payload)
    assert r.status_code == 200
    return _query(r.json()["redirect_to"])["code"]


def test_full_authorization_code_exchange_mints_a_working_token(login_as, client):
    alice = login_as(*ALICE)
    alice_id = alice.get("/users/me").json()["id"]
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)

    r = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"].startswith("pandan_pat_")
    assert body["refresh_token"]
    assert body["expires_in"] == 3600
    assert body["scope"] == "write"

    h = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get(ME, headers=h)
    assert me.status_code == 200
    assert me.json()["id"] == alice_id


def test_authorization_code_exchange_works_form_encoded_too(login_as, client):
    """Real OAuth clients (Claude.ai et al.) POST form-encoded, not JSON."""
    alice = login_as(*ALICE)
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)

    r = client.post(
        DEVICE_TOKEN,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"].startswith("pandan_pat_")


def test_authorization_code_exchange_rejects_wrong_pkce_verifier(login_as, client):
    alice = login_as(*ALICE)
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)

    r = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": "wrong-verifier-wrong-verifier-wrong",
            "resource": RESOURCE,
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_authorization_code_exchange_rejects_mismatched_redirect_uri(login_as, client):
    alice = login_as(*ALICE)
    client_id = _register_client(client, redirect_uris=(REDIRECT_URI, "http://127.0.0.1:9999/other"))
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)

    r = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://127.0.0.1:9999/other",
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_authorization_code_is_single_use(login_as, client):
    alice = login_as(*ALICE)
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": RESOURCE,
    }
    first = client.post(DEVICE_TOKEN, json=body)
    assert first.status_code == 200
    replay = client.post(DEVICE_TOKEN, json=body)
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_authorization_code_expiry_is_enforced(login_as, client):
    from sqlalchemy import text

    from app.db import engine

    alice = login_as(*ALICE)
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE device_authorization SET expires_at = now() - interval '1 second' "
                "WHERE code_hash IS NOT NULL"
            )
        )

    r = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_authorization_code_honours_board_scope(login_as, client):
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    board_b = alice.post(BOARDS, json={"name": "Second"}).json()["id"]
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(
        alice, client, client_id, verifier, challenge, board_ids=[board_a]
    )

    body = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    ).json()
    h = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get(f"{BOARDS}/{board_a}", headers=h).status_code == 200
    assert client.get(f"{BOARDS}/{board_b}", headers=h).status_code == 403


# --- grant_type=refresh_token -------------------------------------------------


def test_refresh_token_rotates_and_mints_a_new_working_access_token(login_as, client):
    alice = login_as(*ALICE)
    alice_id = alice.get("/users/me").json()["id"]
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)
    first = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    ).json()

    refreshed = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": client_id,
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["access_token"].startswith("pandan_pat_")
    assert body["access_token"] != first["access_token"]
    assert body["refresh_token"] != first["refresh_token"]

    h = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get(ME, headers=h)
    assert me.status_code == 200
    assert me.json()["id"] == alice_id


def test_refresh_token_is_single_use(login_as, client):
    alice = login_as(*ALICE)
    client_id = _register_client(client)
    verifier, challenge = _pkce_pair()
    code = _approve_and_get_code(alice, client, client_id, verifier, challenge)
    first = client.post(
        DEVICE_TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    ).json()

    refresh_body = {
        "grant_type": "refresh_token",
        "refresh_token": first["refresh_token"],
        "client_id": client_id,
    }
    once = client.post(DEVICE_TOKEN, json=refresh_body)
    assert once.status_code == 200
    twice = client.post(DEVICE_TOKEN, json=refresh_body)
    assert twice.status_code == 400
    assert twice.json()["error"] == "invalid_grant"


def test_unsupported_grant_type_is_rejected(client):
    r = client.post(DEVICE_TOKEN, json={"grant_type": "client_credentials"})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


def test_device_code_grant_is_unaffected_by_the_new_grant_types(client):
    """The existing CLI device-flow polling still works exactly as before —
    grant_type absent defaults to device_code."""
    r = client.post("/auth/device/code", json={})
    device_code = r.json()["device_code"]
    poll = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert poll.status_code == 400
    assert poll.json() == {"error": "authorization_pending"}
