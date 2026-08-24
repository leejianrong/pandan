"""Board-local sequences and the refs rendered from them (M8 V52, KAN-973).

``card.board_seq`` / ``epic.board_seq`` plus the ``ref`` each read carries — ``ENG-14``
for a card, ``ENG-E7`` for an epic. Nothing resolves a ref yet (V53) and nothing
displays one (V54); what is pinned here is that the numbers are **gapless within a
board**, **independent between cards and epics**, **never reused**, and that
``ticket_number`` is untouched.

Per the suite convention, app imports live inside the test bodies.
"""
from __future__ import annotations

BOARDS = "/api/v1/boards"
CARDS = "/api/v1/cards"
EPICS = "/api/v1/epics"


def _board(client, name: str, key: str) -> dict:
    return client.post(BOARDS, json={"name": name, "key": key}).json()


def _card(client, board_id: int, title: str = "story", **fields) -> dict:
    return client.post(
        CARDS, json={"title": title, "board_id": board_id, **fields}
    ).json()


# --- numbering --------------------------------------------------------------


def test_cards_are_numbered_from_one_and_gaplessly(logged_in_client):
    board = _board(logged_in_client, "Engine Room", "ENG")
    seqs = [_card(logged_in_client, board["id"], f"s{n}")["board_seq"] for n in range(4)]
    assert seqs == [1, 2, 3, 4]


def test_the_ref_is_the_boards_key_plus_the_number(logged_in_client):
    board = _board(logged_in_client, "Engine Room", "ENG")
    card = _card(logged_in_client, board["id"])
    assert card["ref"] == "ENG-1"
    # And the canonical ticket is still there, unchanged and unrelated.
    assert card["ticket_number"].startswith("KAN-")
    assert card["ticket_number"] != card["ref"]


def test_epics_number_on_their_own_sequence(logged_in_client):
    """SHAPING D4: a second, independent sequence rather than one shared with cards,
    mirroring the two-sequence split ADR 0009 made for ``ticket_number``. So
    ``ENG-1`` and ``ENG-E1`` coexist the way ``KAN-1`` and ``EPIC-1`` do."""
    board = _board(logged_in_client, "Engine Room", "ENG")
    for n in range(3):
        _card(logged_in_client, board["id"], f"s{n}")
    epic = logged_in_client.post(
        EPICS, json={"name": "Onboarding", "board_id": board["id"]}
    ).json()
    assert epic["board_seq"] == 1  # not 4 — the cards did not consume epic numbers
    assert epic["ref"] == "ENG-E1"
    second = logged_in_client.post(
        EPICS, json={"name": "Billing", "board_id": board["id"]}
    ).json()
    assert second["ref"] == "ENG-E2"


def test_numbering_is_per_board(logged_in_client):
    one = _board(logged_in_client, "Engine Room", "ENG")
    two = _board(logged_in_client, "Platform", "PLT")
    assert _card(logged_in_client, one["id"])["ref"] == "ENG-1"
    assert _card(logged_in_client, two["id"])["ref"] == "PLT-1"
    assert _card(logged_in_client, one["id"])["ref"] == "ENG-2"
    assert _card(logged_in_client, two["id"])["ref"] == "PLT-2"


def test_a_deleted_card_keeps_its_number_and_the_counter_does_not_rewind(
    logged_in_client,
):
    """SHAPING D7. The counter is never decremented, so the number of a trashed card
    is never handed out again — which is what makes a restore safe. The visible
    consequence is a gap in the *live* cards, and that is correct: the number
    describes every row that exists, not only the visible ones."""
    board = _board(logged_in_client, "Engine Room", "ENG")
    first = _card(logged_in_client, board["id"], "keep")
    second = _card(logged_in_client, board["id"], "trash me")
    assert [first["board_seq"], second["board_seq"]] == [1, 2]

    assert logged_in_client.delete(f"{CARDS}/{second['id']}").status_code == 204
    third = _card(logged_in_client, board["id"], "after")
    assert third["board_seq"] == 3  # not 2 — nothing is reused

    # The trashed card still reports its own number, and restoring it cannot collide.
    trashed = logged_in_client.get(f"{CARDS}/trash?board_id={board['id']}").json()
    assert [c["ref"] for c in trashed] == ["ENG-2"]
    restored = logged_in_client.post(f"{CARDS}/{second['id']}/restore").json()
    assert restored["board_seq"] == 2
    listed = logged_in_client.get(f"{CARDS}?board_id={board['id']}").json()
    assert sorted(c["ref"] for c in listed) == ["ENG-1", "ENG-2", "ENG-3"]


def test_a_rejected_create_does_not_consume_a_number(logged_in_client):
    """Gaplessness has to survive failed writes, so the number is taken **after**
    validation. A create that 422s must leave the counter where it was."""
    board = _board(logged_in_client, "Engine Room", "ENG")
    assert _card(logged_in_client, board["id"], "first")["board_seq"] == 1
    bad = logged_in_client.post(
        CARDS, json={"title": "bad epic", "board_id": board["id"], "epic_id": 999999}
    )
    assert bad.status_code == 422
    assert _card(logged_in_client, board["id"], "second")["board_seq"] == 2


def test_a_key_change_relabels_every_ref_at_once(logged_in_client):
    """The refs are rendered, not stored, which is what makes ``board.key`` editable
    (ADR 0020). Nothing about the cards is rewritten — including their tickets."""
    board = _board(logged_in_client, "Engine Room", "ENG")
    card = _card(logged_in_client, board["id"])
    logged_in_client.patch(f"{BOARDS}/{board['id']}", json={"key": "PLT"})
    after = logged_in_client.get(f"{CARDS}/{card['id']}").json()
    assert after["ref"] == "PLT-1"
    assert after["board_seq"] == card["board_seq"]
    assert after["ticket_number"] == card["ticket_number"]


# --- batch allocation -------------------------------------------------------


def test_a_template_apply_takes_a_contiguous_range(logged_in_client):
    """The only server-side batch create. One statement takes the whole range rather
    than locking the board row once per card, and the numbers stay contiguous."""
    board = _board(logged_in_client, "Engine Room", "ENG")
    _card(logged_in_client, board["id"], "pre-existing")
    template = logged_in_client.post(
        f"{BOARDS}/{board['id']}/templates",
        json={
            "name": "Release checklist",
            "cards": [{"title": "bump"}, {"title": "tag"}, {"title": "verify"}],
        },
    ).json()
    applied = logged_in_client.post(
        f"{BOARDS}/{board['id']}/templates/{template['id']}/apply"
    ).json()
    assert [c["board_seq"] for c in applied] == [2, 3, 4]
    assert [c["ref"] for c in applied] == ["ENG-2", "ENG-3", "ENG-4"]


def test_a_failed_template_apply_consumes_no_numbers(logged_in_client):
    """The apply is one transaction, so a bad entry rolls the range allocation back
    with everything else — which is the property that keeps the counter gapless."""
    board = _board(logged_in_client, "Engine Room", "ENG")
    template = logged_in_client.post(
        f"{BOARDS}/{board['id']}/templates",
        json={"name": "Broken", "cards": [{"title": "ok"}, {"title": "bad", "epic_id": 999999}]},
    ).json()
    failed = logged_in_client.post(
        f"{BOARDS}/{board['id']}/templates/{template['id']}/apply"
    )
    assert failed.status_code == 422
    assert _card(logged_in_client, board["id"], "after")["board_seq"] == 1


# --- every route carries a ref ---------------------------------------------


def test_every_card_route_carries_a_ref(logged_in_client):
    """``ref`` is optional on the schema so a missed route returns null instead of a
    500 — which means this test, not the type, is what holds the promise. Covers the
    routes that return a card by a path other than plain create/get."""
    board = _board(logged_in_client, "Engine Room", "ENG")
    card = _card(logged_in_client, board["id"])
    cid = card["id"]

    on_one = {
        "create": card,
        "get": logged_in_client.get(f"{CARDS}/{cid}").json(),
        "list": logged_in_client.get(f"{CARDS}?board_id={board['id']}").json()[0],
        "patch": logged_in_client.patch(f"{CARDS}/{cid}", json={"title": "t2"}).json(),
        "needs-human": logged_in_client.post(
            f"{CARDS}/{cid}/needs-human", json={"attention_note": "help"}
        ).json(),
        "resolve": logged_in_client.post(f"{CARDS}/{cid}/resolve").json(),
        "batch": logged_in_client.patch(
            f"{CARDS}/batch", json=[{"id": cid, "title": "t3"}]
        ).json()[0],
        "move": logged_in_client.post(
            f"{CARDS}/{cid}/move", json={"column": "in_progress"}
        ).json(),
    }
    for name, payload in on_one.items():
        assert payload["ref"] == "ENG-1", f"{name} returned ref={payload.get('ref')!r}"
        assert payload["board_seq"] == 1, name

    # ``next``/``dispatch`` need a card that is still ready, so they get their own —
    # the first one is in ``in_progress`` by now and would 204.
    second = _card(logged_in_client, board["id"], "ready")
    assert second["ref"] == "ENG-2"
    peeked = logged_in_client.get(f"{BOARDS}/{board['id']}/next").json()
    assert peeked["ref"] == "ENG-2", peeked.get("ref")
    dispatched = logged_in_client.post(
        f"{BOARDS}/{board['id']}/dispatch", json={"assignee": "agent:test"}
    ).json()
    assert dispatched["ref"] == "ENG-2", dispatched.get("ref")


def test_epic_routes_carry_a_ref(logged_in_client):
    board = _board(logged_in_client, "Engine Room", "ENG")
    created = logged_in_client.post(
        EPICS, json={"name": "Onboarding", "board_id": board["id"]}
    ).json()
    eid = created["id"]
    for name, payload in {
        "create": created,
        "get": logged_in_client.get(f"{EPICS}/{eid}").json(),
        "list": logged_in_client.get(f"{EPICS}?board_id={board['id']}").json()[0],
        "patch": logged_in_client.patch(f"{EPICS}/{eid}", json={"name": "n2"}).json(),
    }.items():
        assert payload["ref"] == "ENG-E1", f"{name} returned ref={payload.get('ref')!r}"


# --- the migration ----------------------------------------------------------


def test_the_backfill_numbers_every_row_including_trashed_and_keeps_tickets(
    logged_in_client,
):
    """Migration 0023's backfill, over rows that actually exist.

    Every other test here runs against a database migrated while empty, so the
    ``row_number()`` backfill never executes — the branch that runs exactly once in
    production. This downgrades past it, inserts cards and epics (including a
    soft-deleted card in the middle), and upgrades.

    Two assertions carry the shape's decisions: **soft-deleted rows are numbered**
    (D7 — skipping them would renumber the live ones around them and make a restore a
    collision), and **every ``ticket_number`` is byte-identical afterwards** (D1 /
    R1.2 — the canonical identifier is never touched).

    The downgrade target is a **named revision**, not ``-1``: ``-1`` is relative to
    head, so the next migration would silently change what this brackets.
    """
    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from app.db import engine

    board = _board(logged_in_client, "Engine Room", "ENG")
    bid = board["id"]
    kept = [_card(logged_in_client, bid, f"s{n}") for n in range(3)]
    logged_in_client.delete(f"{CARDS}/{kept[1]['id']}")  # trash the middle one
    epic = logged_in_client.post(EPICS, json={"name": "E", "board_id": bid}).json()

    with engine.connect() as conn:
        before_cards = conn.execute(
            text("SELECT id, ticket_number FROM card ORDER BY id")
        ).all()
        before_epics = conn.execute(
            text("SELECT id, ticket_number FROM epic ORDER BY id")
        ).all()

    cfg = Config("alembic.ini")
    command.downgrade(cfg, "0022_board_keys")
    try:
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            cards = conn.execute(
                text(
                    "SELECT id, ticket_number, board_seq, deleted_at IS NOT NULL "
                    "AS trashed FROM card WHERE board_id = :b ORDER BY id"
                ),
                {"b": bid},
            ).all()
            epics = conn.execute(
                text(
                    "SELECT id, ticket_number, board_seq FROM epic "
                    "WHERE board_id = :b ORDER BY id"
                ),
                {"b": bid},
            ).all()
            counters = conn.execute(
                text(
                    "SELECT next_card_seq, next_epic_seq FROM board WHERE id = :b"
                ),
                {"b": bid},
            ).one()

        # Contiguous 1..3 across ALL rows, so the trashed middle card holds 2 and the
        # live cards read 1 and 3 — a gap in the visible set, by design.
        assert [(c.board_seq, c.trashed) for c in cards] == [
            (1, False),
            (2, True),
            (3, False),
        ]
        assert [e.board_seq for e in epics] == [1]
        # Counters seeded to the highest number in use, so the next card gets 4.
        assert (counters.next_card_seq, counters.next_epic_seq) == (3, 1)
        assert _card(logged_in_client, bid, "after the migration")["board_seq"] == 4

        # R1.2: not one canonical ticket moved.
        with engine.connect() as conn:
            after_cards = conn.execute(
                text("SELECT id, ticket_number FROM card ORDER BY id")
            ).all()
            after_epics = conn.execute(
                text("SELECT id, ticket_number FROM epic ORDER BY id")
            ).all()
        assert [tuple(r) for r in after_cards][: len(before_cards)] == [
            tuple(r) for r in before_cards
        ]
        assert [tuple(r) for r in after_epics] == [tuple(r) for r in before_epics]
        assert epic["ticket_number"] == before_epics[-1].ticket_number
    finally:
        command.upgrade(cfg, "head")
