"""PAT board-scoping tests (ADR 0024, KAN-1726/1728).

A `personal_access_token_board` row is an allow-list entry: **no rows for a given
PAT means unrestricted** (today's behaviour, and every PAT minted before this
slice or via the existing Tokens UI, unaffected). A PAT with at least one row is
scoped to exactly those boards — a *restriction* layered on top of whatever
access the owning user would otherwise have, so it can only take access away,
never grant it, and it applies even to a board the user directly owns or has an
explicit share on.

There is no API surface yet to mint a scoped PAT (that is the device-flow consent
screen, KAN-1727/1729) — this suite inserts `personal_access_token_board` rows
directly via SQL, mirroring `test_token_scope.py`'s own "legacy row" pattern for
testing a DB state no endpoint produces yet.

Per the suite convention, all ``import app.*`` live inside test bodies.
"""
from __future__ import annotations

TOKENS = "/api/v1/tokens"
BOARDS = "/api/v1/boards"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


def _scope_token(token_name: str, *board_ids: int) -> None:
    """Insert `personal_access_token_board` rows scoping the PAT named
    `token_name` to exactly `board_ids`, via raw SQL (no endpoint exists yet)."""
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        pat_id = conn.execute(
            text("SELECT id FROM personal_access_token WHERE name = :name"),
            {"name": token_name},
        ).scalar_one()
        for board_id in board_ids:
            conn.execute(
                text(
                    "INSERT INTO personal_access_token_board "
                    "(personal_access_token_id, board_id) VALUES (:pat, :board)"
                ),
                {"pat": pat_id, "board": board_id},
            )


def test_unscoped_pat_reaches_every_board_the_user_owns(login_as, client):
    """Zero allow-list rows is unrestricted — the baseline every existing PAT
    (minted before this slice, or via the Tokens UI after it) must keep."""
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    board_b = alice.post(BOARDS, json={"name": "Second"}).json()["id"]
    raw = alice.post(TOKENS, json={"name": "unscoped"}).json()["token"]
    h = _bearer(raw)

    assert client.get(f"{BOARDS}/{board_a}", headers=h).status_code == 200
    assert client.get(f"{BOARDS}/{board_b}", headers=h).status_code == 200
    listed = {b["id"] for b in client.get(BOARDS, headers=h).json()}
    assert listed == {board_a, board_b}


def test_scoped_pat_reaches_only_the_allow_listed_board(login_as, client):
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    board_b = alice.post(BOARDS, json={"name": "Second"}).json()["id"]
    raw = alice.post(TOKENS, json={"name": "scoped"}).json()["token"]
    _scope_token("scoped", board_a)
    h = _bearer(raw)

    assert client.get(f"{BOARDS}/{board_a}", headers=h).status_code == 200
    assert client.get(f"{BOARDS}/{board_b}", headers=h).status_code == 403


def test_allow_list_restricts_even_a_board_the_pat_owner_owns(login_as, client):
    """The restriction applies regardless of the underlying access level — a PAT
    scoped away from a board 403s even though the human who owns it (and could
    reach it with any other credential) is the very principal the PAT resolves
    to."""
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    board_b = alice.post(BOARDS, json={"name": "Second"}).json()["id"]
    raw = alice.post(TOKENS, json={"name": "scoped"}).json()["token"]
    _scope_token("scoped", board_b)
    h = _bearer(raw)

    # Alice owns board_a (MANAGE via ownership) but the PAT isn't scoped to it.
    assert client.get(f"{BOARDS}/{board_a}", headers=h).status_code == 403
    assert client.get(f"{BOARDS}/{board_b}", headers=h).status_code == 200


def test_allow_list_restricts_a_board_shared_via_board_member_too(login_as, client):
    """Not just owned boards — an explicit board_member share is narrowed the
    same way, proving the allow-list gates the PAT's *effective access*, not
    only the ownership rung."""
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    board_id = alice.get(BOARDS).json()[0]["id"]
    unrelated_board_id = alice.post(BOARDS, json={"name": "Unrelated"}).json()["id"]
    bob_id = bob.get("/users/me").json()["id"]
    alice.post(
        f"{BOARDS}/{board_id}/members", json={"user_id": bob_id, "role": "editor"}
    )

    raw = bob.post(TOKENS, json={"name": "scoped"}).json()["token"]
    # Scoped to a real board bob has no access to at all — the allow-list entry
    # itself doesn't grant it (he still 403s there); it just proves the PAT's
    # *shared* board is excluded because it isn't on the list.
    _scope_token("scoped", unrelated_board_id)
    h = _bearer(raw)

    # Without a PAT, bob's editor share reaches the board fine.
    assert bob.get(f"{BOARDS}/{board_id}").status_code == 200
    # With the scoped PAT, the share is narrowed away.
    assert client.get(f"{BOARDS}/{board_id}", headers=h).status_code == 403
    # ...and the allow-listed board bob has no underlying access to stays 403 too
    # (the allow-list restricts; it never grants).
    assert client.get(f"{BOARDS}/{unrelated_board_id}", headers=h).status_code == 403


def test_scoped_pat_list_boards_omits_boards_outside_the_allow_list(login_as, client):
    """`GET /boards` must not name a board a direct `GET` on it would 403 for —
    the list endpoint is narrowed exactly like the single-board read."""
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    alice.post(BOARDS, json={"name": "Second"})
    alice.post(BOARDS, json={"name": "Third"})
    raw = alice.post(TOKENS, json={"name": "scoped"}).json()["token"]
    _scope_token("scoped", board_a)
    h = _bearer(raw)

    listed = {b["id"] for b in client.get(BOARDS, headers=h).json()}
    assert listed == {board_a}


def test_scoped_pat_can_be_allow_listed_for_more_than_one_board(login_as, client):
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    board_b = alice.post(BOARDS, json={"name": "Second"}).json()["id"]
    alice.post(BOARDS, json={"name": "Third"})
    raw = alice.post(TOKENS, json={"name": "scoped"}).json()["token"]
    _scope_token("scoped", board_a, board_b)
    h = _bearer(raw)

    listed = {b["id"] for b in client.get(BOARDS, headers=h).json()}
    assert listed == {board_a, board_b}


def test_cookie_session_is_never_scoped(login_as):
    """A human cookie principal has no `_pat_board_ids` attribute at all — this is
    purely a PAT (bearer) mechanism, and a scoped PAT existing for a user must not
    somehow leak into that user's own browser session."""
    alice = login_as(*ALICE)
    board_a = alice.get(BOARDS).json()[0]["id"]
    board_b = alice.post(BOARDS, json={"name": "Second"}).json()["id"]
    alice.post(TOKENS, json={"name": "scoped"})
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        pat_id = conn.execute(
            text("SELECT id FROM personal_access_token WHERE name = 'scoped'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO personal_access_token_board "
                "(personal_access_token_id, board_id) VALUES (:pat, :board)"
            ),
            {"pat": pat_id, "board": board_a},
        )

    # Alice's own cookie session still reaches both boards unaffected.
    assert alice.get(f"{BOARDS}/{board_a}").status_code == 200
    assert alice.get(f"{BOARDS}/{board_b}").status_code == 200
