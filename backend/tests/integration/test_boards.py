"""Board integration tests (M3 V7, ADR 0012; owner-gated since V8, ADR 0013).

Covers board CRUD, per-board scoping of cards/epics, per-board positions, cascade
delete, the default-board fallback for board-less writes, and owner capture from
the session — all now exercised **as the board-owning session user**
(``logged_in_client``, which owns the reset fixture's default board via
claim-on-login). The V8 authorization matrix (401/403/list-scoping across users)
lives in test_authz.py.

Per the suite convention, app imports live inside the test bodies.
"""
from __future__ import annotations

BOARDS = "/api/v1/boards"
CARDS = "/api/v1/cards"
EPICS = "/api/v1/epics"


# --- the default board (migration/backfill) ---------------------------------


def test_default_board_exists_and_is_unclaimed():
    # Observed directly in the DB (no human has logged in, so the default board is
    # still unclaimed; V10 removed the SERVICE principal that used to observe it via
    # the API). The fresh testcontainer migration itself proves the backfill (0005's
    # NOT NULL would fail if the seeded cards weren't attached).
    from sqlalchemy import text

    from app.db import engine

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, owner_id FROM board ORDER BY id")).all()
    assert [name for name, _ in rows] == ["Default Board"]
    assert rows[0][1] is None  # unclaimed until a human logs in


def test_card_without_board_id_lands_on_default_board(logged_in_client):
    default_id = logged_in_client.get(BOARDS).json()[0]["id"]
    card = logged_in_client.post(CARDS, json={"title": "no board given"}).json()
    assert card["board_id"] == default_id


# --- board CRUD --------------------------------------------------------------


def test_create_list_get_board(logged_in_client):
    me = logged_in_client.get("/users/me").json()
    created = logged_in_client.post(BOARDS, json={"name": "Marketing"})
    assert created.status_code == 201
    board = created.json()
    assert board["name"] == "Marketing"
    assert board["owner_id"] == me["id"]  # owner captured from the session

    assert logged_in_client.get(f"{BOARDS}/{board['id']}").json()["name"] == "Marketing"
    # The default board was claimed on login, so the owner sees both.
    names = [b["name"] for b in logged_in_client.get(BOARDS).json()]
    assert names == ["Default Board", "Marketing"]


def test_get_missing_board_404(logged_in_client):
    assert logged_in_client.get(f"{BOARDS}/9999").status_code == 404


def test_rename_board(logged_in_client):
    bid = logged_in_client.post(BOARDS, json={"name": "old"}).json()["id"]
    assert logged_in_client.patch(f"{BOARDS}/{bid}", json={"name": "new"}).json()["name"] == "new"


def test_rename_board_rejects_empty(logged_in_client):
    bid = logged_in_client.post(BOARDS, json={"name": "keep"}).json()["id"]
    assert logged_in_client.patch(f"{BOARDS}/{bid}", json={"name": "  "}).status_code == 422


def test_create_board_rejects_empty_name(logged_in_client):
    assert logged_in_client.post(BOARDS, json={"name": ""}).status_code == 422


# --- scoping (all boards owned by the same session user) ---------------------


def test_cards_are_scoped_by_board(logged_in_client):
    c = logged_in_client
    a = c.post(BOARDS, json={"name": "A"}).json()["id"]
    b = c.post(BOARDS, json={"name": "B"}).json()["id"]
    c.post(CARDS, json={"title": "on A", "board_id": a})
    c.post(CARDS, json={"title": "on B1", "board_id": b})
    c.post(CARDS, json={"title": "on B2", "board_id": b})

    titles_a = {x["title"] for x in c.get(CARDS, params={"board_id": a}).json()}
    titles_b = {x["title"] for x in c.get(CARDS, params={"board_id": b}).json()}
    assert titles_a == {"on A"}
    assert titles_b == {"on B1", "on B2"}


def test_epics_are_scoped_by_board(logged_in_client):
    c = logged_in_client
    a = c.post(BOARDS, json={"name": "A"}).json()["id"]
    b = c.post(BOARDS, json={"name": "B"}).json()["id"]
    c.post(EPICS, json={"name": "epic A", "board_id": a})
    c.post(EPICS, json={"name": "epic B", "board_id": b})

    assert [e["name"] for e in c.get(EPICS, params={"board_id": a}).json()] == ["epic A"]
    assert [e["name"] for e in c.get(EPICS, params={"board_id": b}).json()] == ["epic B"]


def test_create_card_rejects_unknown_board_422(logged_in_client):
    assert logged_in_client.post(CARDS, json={"title": "x", "board_id": 9999}).status_code == 422


def test_create_epic_rejects_unknown_board_422(logged_in_client):
    assert logged_in_client.post(EPICS, json={"name": "x", "board_id": 9999}).status_code == 422


def test_positions_are_per_board(logged_in_client):
    c = logged_in_client
    a = c.post(BOARDS, json={"name": "A"}).json()["id"]
    b = c.post(BOARDS, json={"name": "B"}).json()["id"]
    ca = c.post(CARDS, json={"title": "a0", "board_id": a}).json()
    cb = c.post(CARDS, json={"title": "b0", "board_id": b}).json()
    assert ca["position"] == 0
    assert cb["position"] == 0


def test_move_reorders_only_within_its_board(logged_in_client):
    c = logged_in_client
    a = c.post(BOARDS, json={"name": "A"}).json()["id"]
    b = c.post(BOARDS, json={"name": "B"}).json()["id"]
    b_card = c.post(CARDS, json={"title": "b-todo", "board_id": b}).json()
    a_card = c.post(
        CARDS, json={"title": "a-ip", "board_id": a, "column": "in_progress"}
    ).json()
    c.post(f"{CARDS}/{a_card['id']}/move", json={"column": "todo"})

    assert c.get(f"{CARDS}/{b_card['id']}").json()["position"] == 0


# --- cascade delete ----------------------------------------------------------


def test_delete_board_cascades_its_cards_and_epics(logged_in_client):
    c = logged_in_client
    bid = c.post(BOARDS, json={"name": "doomed"}).json()["id"]
    card = c.post(CARDS, json={"title": "c", "board_id": bid}).json()
    epic = c.post(EPICS, json={"name": "e", "board_id": bid}).json()

    assert c.delete(f"{BOARDS}/{bid}").status_code == 204

    assert c.get(f"{BOARDS}/{bid}").status_code == 404
    assert c.get(f"{CARDS}/{card['id']}").status_code == 404
    assert c.get(f"{EPICS}/{epic['id']}").status_code == 404


def test_delete_board_leaves_other_boards_untouched(logged_in_client):
    c = logged_in_client
    keep = c.post(BOARDS, json={"name": "keep"}).json()["id"]
    drop = c.post(BOARDS, json={"name": "drop"}).json()["id"]
    kept_card = c.post(CARDS, json={"title": "kept", "board_id": keep}).json()
    c.post(CARDS, json={"title": "gone", "board_id": drop})

    c.delete(f"{BOARDS}/{drop}")

    assert c.get(f"{CARDS}/{kept_card['id']}").status_code == 200
    assert {x["title"] for x in c.get(CARDS, params={"board_id": keep}).json()} == {"kept"}


# --- board keys (M8 V51, KAN-972; ADR 0020) ---------------------------------


def test_a_new_board_gets_a_key_derived_from_its_name(logged_in_client):
    board = logged_in_client.post(BOARDS, json={"name": "Engine Room"}).json()
    assert board["key"] == "ENG"


def test_the_default_boards_key_matches_what_the_migration_would_derive(logged_in_client):
    """**This does not test the migration**, and saying so is the point.

    The testcontainer migrates an *empty* database, so 0022's backfill loop touches
    no rows; the default board every other test sees is re-inserted by conftest's
    ``_reset_tables`` with a hardcoded ``'DEF'``. What this pins is that the seed
    stays a faithful stand-in for the real post-migration row — if the derivation
    ever changes, this is the assertion that says the fixture drifted.

    The backfill itself is covered by
    ``test_the_backfill_derives_keys_and_deduplicates_per_owner``, which runs the
    real migration over real rows."""
    default = logged_in_client.get(BOARDS).json()[0]
    assert default["name"] == "Default Board"
    assert default["key"] == "DEF"


def test_the_backfill_derives_keys_and_deduplicates_per_owner():
    """Migration 0022's backfill, over rows that actually exist (V51, KAN-972).

    Every other test in this suite runs against a database migrated while empty, so
    the backfill loop never executes. This one downgrades one revision, inserts
    boards with no key, and upgrades again — the only way to exercise the branch that
    will run exactly once in production, on data that matters.

    ``finally`` re-upgrades unconditionally: a failure mid-test would otherwise leave
    the schema one revision behind and break every test after it, turning one red
    into a hundred.

    **The target is a named revision, not ``-1``.** This test was written with ``-1``
    while 0022 was head, and V52's migration silently changed what that meant — the
    downgrade stopped one revision short and the test failed on assumptions that were
    no longer true. ``-1`` is relative to head, so any migration-bracketing test that
    uses it has a hidden dependency on being the newest one.
    """
    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from app.db import engine

    cfg = Config("alembic.ini")
    command.downgrade(cfg, "a4f5050820ce")  # the revision before 0022_board_keys
    try:
        with engine.begin() as conn:
            owner = conn.execute(
                text(
                    'INSERT INTO "user" (id, email, hashed_password, is_active, '
                    "is_superuser, is_verified) VALUES "
                    "(gen_random_uuid(), 'backfill@example.com', 'x', true, false, true) "
                    "RETURNING id"
                )
            ).scalar_one()
            conn.execute(text("DELETE FROM board"))
            for name in ("Engine Room", "Engineering", "Engines", "Kanban", "曜日"):
                conn.execute(
                    text("INSERT INTO board (name, owner_id) VALUES (:n, :o)"),
                    {"n": name, "o": owner},
                )
            # An unowned board whose name derives the same key as an owned one.
            # NULLs are distinct in a unique index, so it keeps the plain key.
            conn.execute(text("INSERT INTO board (name) VALUES ('Engine Room')"))

        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name, key, owner_id FROM board ORDER BY id")
            ).all()
        owned = [(name, key) for name, key, o in rows if o is not None]
        unowned = [(name, key) for name, key, o in rows if o is None]

        assert owned == [
            ("Engine Room", "ENG"),
            ("Engineering", "ENG2"),  # same derivation, same owner → suffixed
            ("Engines", "ENG3"),
            ("Kanban", "KAN2"),  # reserved, so it walks the collision path too
            ("曜日", "BRD"),  # nothing usable in ASCII → the fallback
        ]
        # The unowned board is exempt from the per-owner dedup and keeps ENG,
        # colliding with the owned ENG only in a way Postgres does not police.
        assert unowned == [("Engine Room", "ENG")]
    finally:
        command.upgrade(cfg, "head")


def test_a_derived_key_suffixes_instead_of_failing(logged_in_client):
    """R1.4: creating a board must never block on naming. Three same-derivation
    names in a row, and every create still returns 201."""
    keys = [
        logged_in_client.post(BOARDS, json={"name": f"Engine Room {n}"}).json()["key"]
        for n in range(3)
    ]
    assert keys == ["ENG", "ENG2", "ENG3"]


def test_an_explicit_key_is_honoured(logged_in_client):
    board = logged_in_client.post(BOARDS, json={"name": "Platform", "key": "PLT"}).json()
    assert board["key"] == "PLT"


def test_two_users_can_each_own_an_eng(login_as):
    """SHAPING D2, and the reason board-local refs resolve board-locally (D3). This
    is the assertion the whole slice exists to make true."""
    alice = login_as("alice-keys@example.com", "gh-alice-keys")
    bob = login_as("bob-keys@example.com", "gh-bob-keys")
    a = alice.post(BOARDS, json={"name": "Engineering", "key": "ENG"})
    b = bob.post(BOARDS, json={"name": "Engine Room", "key": "ENG"})
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["key"] == b.json()["key"] == "ENG"
    assert a.json()["id"] != b.json()["id"]


def test_reusing_your_own_key_is_a_409(logged_in_client):
    """A conflict with stored state, not a malformed request — so 409, not 422. The
    distinction matters to a caller deciding whether to fix the argument or pick
    another key."""
    logged_in_client.post(BOARDS, json={"name": "Platform", "key": "PLT"})
    again = logged_in_client.post(BOARDS, json={"name": "Other", "key": "PLT"})
    assert again.status_code == 409
    assert "PLT" in again.json()["detail"]


def test_a_reserved_key_is_a_422(logged_in_client):
    """SHAPING D3/D5: a board key that shadowed a canonical prefix would make
    ``KAN-14`` mean two things. Case-insensitive, so the lowercase spelling cannot
    sneak in on its way to being uppercased."""
    for key in ("KAN", "EPIC", "kan", "epic"):
        r = logged_in_client.post(BOARDS, json={"name": "Nope", "key": key})
        assert r.status_code == 422, key


def test_a_malformed_key_is_a_422(logged_in_client):
    for key in ("eng", "E", "ENG-X", "1NG", "EN G", "ABCDEFGHIJK", ""):
        r = logged_in_client.post(BOARDS, json={"name": "Nope", "key": key})
        assert r.status_code == 422, key


def test_a_board_named_kanban_derives_past_the_reserved_key(logged_in_client):
    """Reservation and collision share one mechanism, so the derived path resolves a
    reserved key the same way it resolves a taken one."""
    assert logged_in_client.post(BOARDS, json={"name": "Kanban"}).json()["key"] == "KAN2"


def test_a_key_can_be_changed_by_patch(logged_in_client):
    board = logged_in_client.post(BOARDS, json={"name": "Platform"}).json()
    updated = logged_in_client.patch(f"{BOARDS}/{board['id']}", json={"key": "PLT"})
    assert updated.status_code == 200
    assert updated.json()["key"] == "PLT"
    assert updated.json()["name"] == "Platform"  # unsent fields untouched


def test_patching_a_key_to_its_current_value_is_not_a_self_collision(logged_in_client):
    board = logged_in_client.post(BOARDS, json={"name": "Platform", "key": "PLT"}).json()
    again = logged_in_client.patch(f"{BOARDS}/{board['id']}", json={"key": "PLT"})
    assert again.status_code == 200
    assert again.json()["key"] == "PLT"


def test_patching_a_key_onto_another_of_your_boards_is_a_409(logged_in_client):
    first = logged_in_client.post(BOARDS, json={"name": "Platform", "key": "PLT"}).json()
    second = logged_in_client.post(BOARDS, json={"name": "Other", "key": "OTH"}).json()
    clash = logged_in_client.patch(f"{BOARDS}/{second['id']}", json={"key": "PLT"})
    assert clash.status_code == 409
    assert logged_in_client.get(f"{BOARDS}/{second['id']}").json()["key"] == "OTH"
    assert logged_in_client.get(f"{BOARDS}/{first['id']}").json()["key"] == "PLT"


def test_patching_a_key_to_a_reserved_or_malformed_value_is_a_422(logged_in_client):
    board = logged_in_client.post(BOARDS, json={"name": "Platform"}).json()
    for key in ("KAN", "epic", "eng", "X"):
        r = logged_in_client.patch(f"{BOARDS}/{board['id']}", json={"key": key})
        assert r.status_code == 422, key


def test_a_key_cannot_be_cleared(logged_in_client):
    """Unlike the webhook fields, a null is a 422 rather than "clear it": every
    board has a key, because V52's board-local refs cannot render without one."""
    board = logged_in_client.post(BOARDS, json={"name": "Platform"}).json()
    r = logged_in_client.patch(f"{BOARDS}/{board['id']}", json={"key": None})
    assert r.status_code == 422
    assert logged_in_client.get(f"{BOARDS}/{board['id']}").json()["key"] == "PLA"


def test_a_key_patch_does_not_disturb_the_boards_cards(logged_in_client):
    """Nothing about a card is stored per key — ``ticket_number`` is untouched
    forever (SHAPING D1), which is precisely what makes a key renameable."""
    board = logged_in_client.post(BOARDS, json={"name": "Platform"}).json()
    card = logged_in_client.post(
        CARDS, json={"title": "story", "board_id": board["id"]}
    ).json()
    logged_in_client.patch(f"{BOARDS}/{board['id']}", json={"key": "PLT"})
    after = logged_in_client.get(f"{CARDS}/{card['id']}").json()
    assert after["ticket_number"] == card["ticket_number"]
    assert after["board_id"] == board["id"]
