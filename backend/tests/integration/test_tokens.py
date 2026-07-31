"""Personal-access-token tests (M3 V9, ADR 0014).

Covers the self-serve lifecycle (create → reveal-once → use → revoke), hashing at
rest (R7.1), per-user list scoping, and that a PAT authenticates as its owning
user and is **owner-gated** exactly like a human (ADR 0013): it reaches its user's
boards and gets 403 on others'. Expired / revoked / bad tokens are 401.

Two client shapes: ``login_as`` gives a cookie-session user (who mints tokens);
the plain cookie-less ``client`` carries only a ``Bearer <pat>`` header, so it
exercises the PAT branch of the resolver in isolation. Per the suite convention,
app imports live inside test bodies.
"""
from __future__ import annotations

TOKENS = "/api/v1/tokens"
BOARDS = "/api/v1/boards"
CARDS = "/api/v1/cards"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


# --- create: secret shown once, hashed at rest -------------------------------


def test_create_returns_secret_once_and_hashes_at_rest(login_as, client):
    from sqlalchemy import text

    from app.db import engine
    from app.tokens import hash_token

    alice = login_as(*ALICE)
    created = alice.post(TOKENS, json={"name": "ci-bot"})
    assert created.status_code == 201
    body = created.json()
    raw = body["token"]
    assert raw.startswith("pandan_pat_")
    assert body["name"] == "ci-bot"
    assert body["token_prefix"] == raw[:15]
    assert body["last_used_at"] is None

    # The list never returns the secret — metadata only.
    listed = alice.get(TOKENS).json()
    assert len(listed) == 1
    assert "token" not in listed[0]
    assert listed[0]["token_prefix"] == raw[:15]

    # At rest: only the hash is stored, and it's the HMAC of the raw (not the raw).
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM personal_access_token")).scalar_one()
    assert stored != raw
    assert stored == hash_token(raw)


# --- list scoping ------------------------------------------------------------


def test_list_only_shows_your_own_tokens(login_as):
    alice = login_as(*ALICE)
    alice.post(TOKENS, json={"name": "alice-1"})
    bob = login_as(*BOB)
    bob.post(TOKENS, json={"name": "bob-1"})

    assert [t["name"] for t in alice.get(TOKENS).json()] == ["alice-1"]
    assert [t["name"] for t in bob.get(TOKENS).json()] == ["bob-1"]


# --- a PAT authenticates as its owner and is owner-gated ---------------------


def test_pat_acts_as_owner_and_is_board_gated(login_as, client):
    alice = login_as(*ALICE)  # owns the default board via claim-on-login
    a_board = alice.get(BOARDS).json()[0]["id"]
    raw = alice.post(TOKENS, json={"name": "agent"}).json()["token"]

    bob = login_as(*BOB)
    b_board = bob.post(BOARDS, json={"name": "bob board"}).json()["id"]

    # The cookie-less client, carrying only the PAT, acts as alice:
    assert client.get(BOARDS, headers=_bearer(raw)).status_code == 200
    assert [b["id"] for b in client.get(BOARDS, headers=_bearer(raw)).json()] == [a_board]
    made = client.post(CARDS, json={"title": "via pat", "board_id": a_board}, headers=_bearer(raw))
    assert made.status_code == 201

    # ... and is forbidden on bob's board, exactly like alice-the-human would be.
    assert client.get(f"{BOARDS}/{b_board}", headers=_bearer(raw)).status_code == 403
    denied = client.post(CARDS, json={"title": "x", "board_id": b_board}, headers=_bearer(raw))
    assert denied.status_code == 403


def test_pat_stamps_last_used_at(login_as, client):
    alice = login_as(*ALICE)
    raw = alice.post(TOKENS, json={"name": "agent"}).json()["token"]
    assert alice.get(TOKENS).json()[0]["last_used_at"] is None

    client.get(BOARDS, headers=_bearer(raw))  # one authenticated call
    assert alice.get(TOKENS).json()[0]["last_used_at"] is not None


# --- revoke / expiry / bad token → 401 ---------------------------------------


def test_revoke_then_401(login_as, client):
    alice = login_as(*ALICE)
    token = alice.post(TOKENS, json={"name": "temp"}).json()
    raw, tid = token["token"], token["id"]
    assert client.get(BOARDS, headers=_bearer(raw)).status_code == 200

    assert alice.delete(f"{TOKENS}/{tid}").status_code == 204
    assert client.get(BOARDS, headers=_bearer(raw)).status_code == 401


def test_expired_token_is_401(login_as, client):
    alice = login_as(*ALICE)
    raw = alice.post(
        TOKENS, json={"name": "old", "expires_at": "2020-01-01T00:00:00Z"}
    ).json()["token"]
    assert client.get(BOARDS, headers=_bearer(raw)).status_code == 401


def test_bad_token_is_401(client):
    assert client.get(BOARDS, headers=_bearer("pandan_pat_not-a-real-token")).status_code == 401
    # A retired-but-accepted prefix is still only a *shape* — the hash must match.
    assert client.get(BOARDS, headers=_bearer("kanban_pat_not-a-real-token")).status_code == 401
    assert client.get(BOARDS, headers=_bearer("not-even-our-prefix")).status_code == 401


# --- rebrand: retired token prefixes keep authenticating (V40, KAN-423) -------


def test_legacy_prefix_token_still_authenticates(login_as, client):
    """A PAT minted before the ``kanban_pat_`` → ``pandan_pat_`` rename still works.

    Regression guard for ADR 0018: verification is a hash lookup over the whole raw
    token, and the resolver's cheap fast-path reject (``app/authz.py``, ``_resolve_pat``)
    accepts every prefix in ``ACCEPTED_TOKEN_PREFIXES`` — not just the current one. A
    prefix flip *without* that tuple would 401 every already-issued token.

    Seeded directly through ``hash_token`` rather than the API, since the mint path
    only ever produces the current prefix.
    """
    from sqlalchemy import text

    from app.db import engine
    from app.tokens import LEGACY_TOKEN_PREFIXES, hash_token

    alice = login_as(*ALICE)
    # Give Alice a board so a successful call has something owner-gated to return.
    alice.post(BOARDS, json={"name": "legacy-pat-board"})
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

    resolved = client.get(BOARDS, headers=_bearer(legacy_raw))
    assert resolved.status_code == 200
    # Owner-scoped to Alice — the claim-on-login default board plus the one made above.
    assert "legacy-pat-board" in [b["name"] for b in resolved.json()]


def test_unknown_prefix_short_circuits_without_a_db_lookup(client, monkeypatch):
    """A bearer matching *no* accepted prefix is rejected before any DB round-trip.

    The fast-path guard exists so a stray Authorization header can't be used to
    generate query load. Asserted by making the lookup itself explode: if the guard
    ever stops short-circuiting, this test fails loudly instead of silently
    regressing into a DB hit per bogus bearer.
    """
    from app import authz

    def _explode(*_args, **_kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("hash_token called for a bearer with an unaccepted prefix")

    monkeypatch.setattr(authz, "hash_token", _explode)
    assert client.get(BOARDS, headers=_bearer("github_pat_11ABCDE")).status_code == 401
    assert client.get(BOARDS, headers=_bearer("pandan-pat-wrong-separator")).status_code == 401


# --- token management is per-user --------------------------------------------


def test_token_management_requires_auth(client):
    assert client.post(TOKENS, json={"name": "x"}).status_code == 401
    assert client.get(TOKENS).status_code == 401


def test_cannot_revoke_another_users_token(login_as):
    alice = login_as(*ALICE)
    tid = alice.post(TOKENS, json={"name": "alice-secret"}).json()["id"]
    bob = login_as(*BOB)
    # 404 (not 403): don't reveal that the id exists.
    assert bob.delete(f"{TOKENS}/{tid}").status_code == 404
    # Alice's token still works.
    assert alice.get(TOKENS).json()[0]["id"] == tid
