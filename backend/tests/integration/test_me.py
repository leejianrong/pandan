"""``GET /api/v1/me`` — who is this credential? (KAN-530, issue #253)

The endpoint exists so a **bearer** holder can resolve itself: fastapi-users'
``/users/me`` is on the async cookie path and won't accept one, and the PAT branch
of ``get_principal`` guards ``/api/v1`` only. Its first consumer is kaya, which
delegates identity to pandan and mirrors the returned UUID locally.

Four things are pinned here, three of them deliberately:

1. The happy paths — a PAT and a cookie session both resolve, to the *same* user.
2. A **legacy** ``kanban_pat_…`` token still resolves (ADR 0018): the resolver's
   fast-path guard accepts every prefix in ``ACCEPTED_TOKEN_PREFIXES``, and a
   prefix assumption without it would 401 every already-issued token. Seeded
   through ``hash_token`` because the mint path only produces the current prefix.
3. No credential → 401, and a *garbage* bearer → 401 (not a 500).
4. **403 is unreachable** — there is no board to authorize against — so the only
   statuses this endpoint can produce are 200 and 401.

Per the suite convention, every ``import app.*`` lives inside a test body (the
PR #17 trap).
"""
from __future__ import annotations

ME = "/api/v1/me"
TOKENS = "/api/v1/tokens"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


# --- happy path --------------------------------------------------------------


def test_pat_resolves_to_its_owning_user(login_as, client):
    """The reason the endpoint exists: a bearer gets back its own id + email."""
    alice = login_as(*ALICE)
    raw = alice.post(TOKENS, json={"name": "kaya"}).json()["token"]

    r = client.get(ME, headers=_bearer(raw))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == ALICE[0]
    assert body["id"] == alice.get("/users/me").json()["id"]


def test_response_carries_exactly_id_and_email(login_as, client):
    """The contract is the *minimum* — id + email and nothing else. Extra fields
    would become a cross-app promise that is awkward to withdraw, so this asserts
    set equality rather than the presence of the two."""
    import uuid

    alice = login_as(*ALICE)
    raw = alice.post(TOKENS, json={"name": "kaya"}).json()["token"]

    body = client.get(ME, headers=_bearer(raw)).json()
    assert set(body) == {"id", "email"}
    uuid.UUID(body["id"])  # a real UUID, not an int or an opaque string


def test_cookie_session_resolves_to_the_same_user(login_as):
    """The endpoint reuses ``get_principal`` unchanged, so the human path works too
    — and must agree with the PAT path about who the user is."""
    alice = login_as(*ALICE)
    raw = alice.post(TOKENS, json={"name": "kaya"}).json()["token"]

    via_cookie = alice.get(ME)
    assert via_cookie.status_code == 200
    assert via_cookie.json() == {"id": alice.get("/users/me").json()["id"], "email": ALICE[0]}
    # Same answer whichever credential asks.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as bearer_only:
        assert bearer_only.get(ME, headers=_bearer(raw)).json() == via_cookie.json()


def test_distinct_users_get_distinct_identities(login_as, client):
    """Two PATs from two accounts must not collapse to one identity — kaya keys its
    local records on this UUID."""
    alice = login_as(*ALICE)
    a_raw = alice.post(TOKENS, json={"name": "a"}).json()["token"]
    bob = login_as(*BOB)
    b_raw = bob.post(TOKENS, json={"name": "b"}).json()["token"]

    a = client.get(ME, headers=_bearer(a_raw)).json()
    b = client.get(ME, headers=_bearer(b_raw)).json()
    assert (a["email"], b["email"]) == (ALICE[0], BOB[0])
    assert a["id"] != b["id"]


def test_read_scoped_pat_can_ask_who_it_is(login_as, client):
    """An observer (``read``-scoped) PAT is restricted to safe methods (V18,
    KAN-251); ``GET /me`` is one, so identity resolution is not a privilege a
    consumer needs a write token for."""
    alice = login_as(*ALICE)
    raw = alice.post(TOKENS, json={"name": "observer", "scope": "read"}).json()["token"]

    r = client.get(ME, headers=_bearer(raw))
    assert r.status_code == 200
    assert r.json()["email"] == ALICE[0]


# --- rebrand: a legacy kanban_pat_ token still resolves here (ADR 0018) -------


def test_legacy_prefix_pat_resolves(login_as, client):
    """A PAT minted before the ``kanban_pat_`` → ``pandan_pat_`` rename resolves at
    ``/me`` too.

    ADR 0018 records that an earlier draft wrongly assumed no prefix guard existed;
    had the prefix flipped without ``LEGACY_TOKEN_PREFIXES``, every already-issued
    token would have 401'd. This endpoint is the one a consumer hits *first*, so a
    regression here reads as "your account doesn't exist" rather than "that token
    is old". Seeded directly through ``hash_token`` — the mint path only ever
    produces the current prefix.
    """
    from sqlalchemy import text

    from app.db import engine
    from app.tokens import LEGACY_TOKEN_PREFIXES, hash_token

    alice = login_as(*ALICE)
    user_id = alice.get("/users/me").json()["id"]

    legacy_raw = LEGACY_TOKEN_PREFIXES[0] + "seeded-legacy-token-value"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO personal_access_token"
                " (user_id, name, token_prefix, token_hash, scope, created_at)"
                " VALUES (:uid, :name, :prefix, :hash, 'write', now())"
            ),
            {
                "uid": user_id,
                "name": "pre-rebrand-bot",
                "prefix": legacy_raw[:15],
                "hash": hash_token(legacy_raw),
            },
        )

    r = client.get(ME, headers=_bearer(legacy_raw))
    assert r.status_code == 200
    assert r.json() == {"id": user_id, "email": ALICE[0]}


# --- unauthenticated / malformed → 401, never 500 ----------------------------


def test_no_credential_is_401(client):
    r = client.get(ME)
    assert r.status_code == 401


def test_garbage_bearer_is_401_not_500(client):
    """Every shape of nonsense a consumer might forward is a clean 401: an unminted
    prefix (short-circuited before any DB lookup), our own prefix with no matching
    hash, an empty bearer, a JWT-shaped string (what a caller that assumed pandan
    mints JWTs would send), and an over-long blob."""
    for raw in (
        "not-even-our-prefix",
        "pandan_pat_not-a-real-token",
        "kanban_pat_not-a-real-token",
        "",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln",
        "pandan_pat_" + "x" * 4000,
        "{}",
    ):
        assert client.get(ME, headers=_bearer(raw)).status_code == 401, raw


def test_revoked_and_expired_pats_are_401(login_as, client):
    alice = login_as(*ALICE)
    live = alice.post(TOKENS, json={"name": "temp"}).json()
    expired = alice.post(
        TOKENS, json={"name": "old", "expires_at": "2020-01-01T00:00:00Z"}
    ).json()["token"]

    assert client.get(ME, headers=_bearer(live["token"])).status_code == 200
    assert alice.delete(f"{TOKENS}/{live['id']}").status_code == 204
    assert client.get(ME, headers=_bearer(live["token"])).status_code == 401
    assert client.get(ME, headers=_bearer(expired)).status_code == 401


# --- 403 is unreachable: there is no board to authorize against --------------


def test_endpoint_only_ever_returns_200_or_401(login_as, client):
    """``/me`` takes no board and never calls ``authorize_board``, so the ownership
    403 that gates every other ``/api/v1`` route cannot fire here. Sweeping the
    credentials that produce a 403 elsewhere documents that: a PAT belonging to
    someone who owns nothing still gets a 200, because there is nothing to be
    forbidden from.
    """
    alice = login_as(*ALICE)
    a_raw = alice.post(TOKENS, json={"name": "a"}).json()["token"]
    bob = login_as(*BOB)  # owns no board — alice claimed the default one on login
    b_raw = bob.post(TOKENS, json={"name": "b"}).json()["token"]
    b_read_raw = bob.post(TOKENS, json={"name": "b-observer", "scope": "read"}).json()["token"]

    seen = {
        client.get(ME, headers=_bearer(raw)).status_code
        for raw in (a_raw, b_raw, b_read_raw, "pandan_pat_nope", "garbage")
    }
    seen.add(client.get(ME).status_code)
    seen.add(alice.get(ME).status_code)
    assert seen == {200, 401}


def test_only_get_is_offered(client):
    """Read-only by construction: /me has no write verbs, so the write-tier
    behaviour (and the observer-scope 403) has no surface to appear on."""
    for method in ("post", "patch", "put", "delete"):
        assert getattr(client, method)(ME).status_code == 405
