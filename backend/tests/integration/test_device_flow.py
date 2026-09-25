"""RFC 8628 device flow tests (ADR 0024, KAN-1727).

`POST /auth/device/code` and `POST /auth/device/token` are both unauthenticated
by design (a CLI with no credential yet is exactly who calls them). There is no
API surface yet to move a device_authorization row to `status = 'approved'` or
`'denied'` (that is the consent screen, KAN-1729) -- this suite reaches those
states directly via SQL, mirroring `test_token_scope.py`'s and
`test_pat_board_scope.py`'s own "no endpoint yet" pattern.

Per the suite convention, all ``import app.*`` live inside test bodies.
"""
from __future__ import annotations

import re

DEVICE_CODE = "/auth/device/code"
DEVICE_TOKEN = "/auth/device/token"
BOARDS = "/api/v1/boards"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def _resolve(client, user_id: str | None, status_: str, **fields):
    """Move the device_authorization row identified by its `device_code` (passed
    in `fields["device_code_hash"]`, already hashed) to `status_`, optionally
    stamping `user_id`."""
    from sqlalchemy import text

    from app.db import engine
    from app.tokens import hash_token

    device_code_hash = hash_token(fields["device_code"])
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE device_authorization SET status = :status, user_id = :uid "
                "WHERE device_code_hash = :hash"
            ),
            {"status": status_, "uid": user_id, "hash": device_code_hash},
        )


def _expire(device_code: str) -> None:
    from sqlalchemy import text

    from app.db import engine
    from app.tokens import hash_token

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE device_authorization SET expires_at = now() - interval '1 second' "
                "WHERE device_code_hash = :hash"
            ),
            {"hash": hash_token(device_code)},
        )


# --- POST /auth/device/code ---------------------------------------------------


def test_create_device_code_returns_the_rfc8628_shape(client):
    r = client.post(DEVICE_CODE, json={})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    }
    assert re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}", body["user_code"])
    assert body["verification_uri_complete"] == (
        f"{body['verification_uri']}?user_code={body['user_code']}"
    )
    assert body["expires_in"] == 900
    assert body["interval"] == 5


def test_create_device_code_requires_no_auth(client):
    """The entry point for a CLI with no credential yet must not itself require
    one -- that would be circular."""
    r = client.post(DEVICE_CODE, json={})
    assert r.status_code == 200


def test_create_device_code_defaults_scope_to_write(client):
    r = client.post(DEVICE_CODE, json={})
    device_code = r.json()["device_code"]
    from sqlalchemy import text

    from app.db import engine
    from app.tokens import hash_token

    with engine.begin() as conn:
        scope = conn.execute(
            text(
                "SELECT requested_scope FROM device_authorization WHERE device_code_hash = :h"
            ),
            {"h": hash_token(device_code)},
        ).scalar_one()
    assert scope == "write"


# --- POST /auth/device/token: the states that don't need approval ------------


def test_poll_before_approval_is_authorization_pending(client):
    device_code = client.post(DEVICE_CODE, json={}).json()["device_code"]
    r = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert r.status_code == 400
    assert r.json() == {"error": "authorization_pending"}


def test_poll_an_unknown_device_code_is_expired_token(client):
    r = client.post(DEVICE_TOKEN, json={"device_code": "not-a-real-code"})
    assert r.status_code == 400
    assert r.json() == {"error": "expired_token"}


def test_poll_too_fast_is_slow_down(client):
    device_code = client.post(DEVICE_CODE, json={}).json()["device_code"]
    first = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert first.json() == {"error": "authorization_pending"}
    second = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert second.status_code == 400
    assert second.json() == {"error": "slow_down"}


def test_poll_after_the_interval_elapses_is_not_slow_down(client):
    """Backdates the in-memory poll-cadence clock rather than sleeping for real
    (`DEVICE_POLL_INTERVAL_SECONDS` is 5s; a real sleep would make this the
    slowest test in the suite for no benefit -- the behaviour under test is the
    comparison, not wall-clock time passing)."""
    from app import device_flow
    from app.tokens import hash_token

    device_code = client.post(DEVICE_CODE, json={}).json()["device_code"]
    client.post(DEVICE_TOKEN, json={"device_code": device_code})
    key = hash_token(device_code)
    assert key in device_flow._last_polled_at
    device_flow._last_polled_at[key] -= device_flow.DEVICE_POLL_INTERVAL_SECONDS + 1

    r = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert r.json() == {"error": "authorization_pending"}


def test_poll_after_expiry_is_expired_token(client):
    device_code = client.post(DEVICE_CODE, json={}).json()["device_code"]
    _expire(device_code)
    r = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert r.status_code == 400
    assert r.json() == {"error": "expired_token"}


def test_poll_after_denial_is_access_denied(client):
    device_code = client.post(DEVICE_CODE, json={}).json()["device_code"]
    _resolve(client, None, "denied", device_code=device_code)
    r = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert r.status_code == 400
    assert r.json() == {"error": "access_denied"}


# --- POST /auth/device/token: approved -> mints once, then expires -----------


def test_poll_after_approval_mints_a_pat_exactly_once(login_as, client):
    alice = login_as(*ALICE)
    alice_id = alice.get("/users/me").json()["id"]
    device_code = client.post(DEVICE_CODE, json={}).json()["device_code"]
    _resolve(client, alice_id, "approved", device_code=device_code)

    success = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert success.status_code == 200
    body = success.json()
    assert body["token"].startswith("pandan_pat_")
    assert body["name"] == "Device flow login"
    assert body["scope"] == "write"

    # The minted PAT actually authenticates as alice.
    h = {"Authorization": f"Bearer {body['token']}"}
    assert client.get(BOARDS, headers=h).status_code == 200

    # Single-use: a second poll after success is expired_token, not another mint.
    replay = client.post(DEVICE_TOKEN, json={"device_code": device_code})
    assert replay.status_code == 400
    assert replay.json() == {"error": "expired_token"}


def test_approved_poll_honours_the_requested_scope(login_as, client):
    alice = login_as(*ALICE)
    alice_id = alice.get("/users/me").json()["id"]
    device_code = client.post(DEVICE_CODE, json={"scope": "read"}).json()["device_code"]
    _resolve(client, alice_id, "approved", device_code=device_code)

    body = client.post(DEVICE_TOKEN, json={"device_code": device_code}).json()
    assert body["scope"] == "read"
    h = {"Authorization": f"Bearer {body['token']}"}
    assert client.get(BOARDS, headers=h).status_code == 200  # reads still work
    assert (
        client.post(BOARDS, json={"name": "nope"}, headers=h).status_code == 403
    )  # writes don't


def test_approved_poll_materialises_the_requested_board_scope(login_as, client):
    alice = login_as(*ALICE)
    alice_id = alice.get("/users/me").json()["id"]
    board_a = alice.get(BOARDS).json()[0]["id"]
    board_b = alice.post(BOARDS, json={"name": "Second"}).json()["id"]
    device_code = client.post(
        DEVICE_CODE, json={"board_ids": [board_a]}
    ).json()["device_code"]
    _resolve(client, alice_id, "approved", device_code=device_code)

    body = client.post(DEVICE_TOKEN, json={"device_code": device_code}).json()
    h = {"Authorization": f"Bearer {body['token']}"}
    assert client.get(f"{BOARDS}/{board_a}", headers=h).status_code == 200
    assert client.get(f"{BOARDS}/{board_b}", headers=h).status_code == 403


# --- consent screen backend: GET / approve / deny (ADR 0024, KAN-1729) -------


def test_get_device_authorization_requires_auth(client):
    user_code = client.post(DEVICE_CODE, json={}).json()["user_code"]
    r = client.get(f"/auth/device/{user_code}")
    assert r.status_code == 401


def test_get_unknown_user_code_is_404(login_as):
    alice = login_as(*ALICE)
    assert alice.get("/auth/device/NOPE-NOPE").status_code == 404


def test_get_expired_user_code_is_404(login_as, client):
    alice = login_as(*ALICE)
    code = client.post(DEVICE_CODE, json={}).json()
    _expire(code["device_code"])
    assert alice.get(f"/auth/device/{code['user_code']}").status_code == 404


def test_get_shows_the_requested_scope_and_pending_status(login_as, client):
    alice = login_as(*ALICE)
    code = client.post(DEVICE_CODE, json={"scope": "read"}).json()
    r = alice.get(f"/auth/device/{code['user_code']}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["requested_scope"] == "read"
    assert body["user_code"] == code["user_code"]


def test_get_reflects_status_after_approval(login_as, client):
    alice = login_as(*ALICE)
    code = client.post(DEVICE_CODE, json={}).json()
    alice.post(f"/auth/device/{code['user_code']}/approve", json={"scope": "write"})
    assert alice.get(f"/auth/device/{code['user_code']}").json()["status"] == "approved"


def test_approve_requires_auth(client):
    user_code = client.post(DEVICE_CODE, json={}).json()["user_code"]
    r = client.post(f"/auth/device/{user_code}/approve", json={"scope": "write"})
    assert r.status_code == 401


def test_approve_unknown_user_code_is_404(login_as):
    alice = login_as(*ALICE)
    r = alice.post("/auth/device/NOPE-NOPE/approve", json={"scope": "write"})
    assert r.status_code == 404


def test_approve_then_poll_mints_with_the_approved_choice(login_as, client):
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    code = client.post(DEVICE_CODE, json={}).json()  # requested unscoped/write

    # The human changes the pre-fill before approving: read-only, one board.
    r = alice.post(
        f"/auth/device/{code['user_code']}/approve",
        json={"scope": "read", "board_ids": [board_a]},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    body = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]}).json()
    assert body["scope"] == "read"
    h = {"Authorization": f"Bearer {body['token']}"}
    assert client.get(f"{BOARDS}/{board_a}", headers=h).status_code == 200


def test_approve_rejects_a_board_the_approver_does_not_own(login_as, client):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_board = bob.post(BOARDS, json={"name": "Bob's"}).json()["id"]
    code = client.post(DEVICE_CODE, json={}).json()

    r = alice.post(
        f"/auth/device/{code['user_code']}/approve",
        json={"scope": "write", "board_ids": [bob_board]},
    )
    assert r.status_code == 403
    # And the code is untouched — still pending, approvable for real afterwards.
    assert alice.get(f"/auth/device/{code['user_code']}").json()["status"] == "pending"


def test_approve_an_already_resolved_code_is_409(login_as, client):
    alice = login_as(*ALICE)
    code = client.post(DEVICE_CODE, json={}).json()
    alice.post(f"/auth/device/{code['user_code']}/approve", json={"scope": "write"})

    r = alice.post(f"/auth/device/{code['user_code']}/approve", json={"scope": "write"})
    assert r.status_code == 409


def test_deny_requires_auth(client):
    user_code = client.post(DEVICE_CODE, json={}).json()["user_code"]
    assert client.post(f"/auth/device/{user_code}/deny").status_code == 401


def test_deny_then_poll_is_access_denied(login_as, client):
    alice = login_as(*ALICE)
    code = client.post(DEVICE_CODE, json={}).json()

    r = alice.post(f"/auth/device/{code['user_code']}/deny")
    assert r.status_code == 204
    assert alice.get(f"/auth/device/{code['user_code']}").json()["status"] == "denied"

    poll = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})
    assert poll.json() == {"error": "access_denied"}


def test_deny_an_already_resolved_code_is_409(login_as, client):
    alice = login_as(*ALICE)
    code = client.post(DEVICE_CODE, json={}).json()
    alice.post(f"/auth/device/{code['user_code']}/deny")

    r = alice.post(f"/auth/device/{code['user_code']}/deny")
    assert r.status_code == 409
