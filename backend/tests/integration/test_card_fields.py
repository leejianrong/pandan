"""API tests for card fields — priority, due date, labels (M5 V11, KAN-244).

Covers: setting/reading ``priority`` + ``due_date`` + ``labels`` on create and
update; the priority CHECK (bad value → 422 at the API, and the DB constraint
itself); board-scoped labels (attaching another board's label → 422); the list
filters (priority / label / due_before / overdue); label CRUD + authorization; and
the cascade that detaches a label from its cards when the label is deleted.

Per the suite convention, any app-module imports go inside test bodies, not at
module top (the PR #17 trap).
"""
from __future__ import annotations

import pytest

CARDS = "/api/v1/cards"
BOARDS = "/api/v1/boards"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these tests run as the
    board-owning session user (claim-on-login gives them the default board)."""
    return logged_in_client


def _card(client, title="T", **fields):
    r = client.post(CARDS, json={"title": title, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _label(client, board_id, name="bug", color="#ef4444"):
    r = client.post(f"{BOARDS}/{board_id}/labels", json={"name": name, "color": color})
    assert r.status_code == 201, r.text
    return r.json()


def _default_board(client) -> int:
    return client.get(BOARDS).json()[0]["id"]


# --- priority ---------------------------------------------------------------


def test_priority_defaults_to_none(client):
    card = _card(client, "no-priority")
    assert card["priority"] == "none"


def test_set_and_read_priority(client):
    card = _card(client, "urgent", priority="urgent")
    assert card["priority"] == "urgent"
    assert client.get(f"{CARDS}/{card['id']}").json()["priority"] == "urgent"


def test_update_priority(client):
    card = _card(client, "rerank")
    r = client.patch(f"{CARDS}/{card['id']}", json={"priority": "high"})
    assert r.status_code == 200, r.text
    assert r.json()["priority"] == "high"


def test_bad_priority_rejected_422(client):
    r = client.post(CARDS, json={"title": "bad", "priority": "critical"})
    assert r.status_code == 422


def test_priority_check_constraint_in_db():
    # The DB CHECK (ck_card_priority) is the last line of defence behind the schema.
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.db import engine

    # ``board_seq`` is supplied (V52, KAN-973) even though this row is meant to fail:
    # without it the insert violates that column's NOT NULL instead, and the test
    # would pass while proving nothing about the priority CHECK.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO card (board_id, board_seq, title, "column", position, '
                    "priority) VALUES (1, 9999, 't', 'todo', 0, 'bogus')"
                )
            )


# --- due_date ---------------------------------------------------------------


def test_set_and_clear_due_date(client):
    card = _card(client, "due", due_date="2026-08-01T00:00:00Z")
    assert card["due_date"] is not None
    # Clear it with null.
    r = client.patch(f"{CARDS}/{card['id']}", json={"due_date": None})
    assert r.status_code == 200, r.text
    assert r.json()["due_date"] is None


# --- labels: attach on create/update ----------------------------------------


def test_create_with_labels(client):
    board = _default_board(client)
    la = _label(client, board, "bug", "#ef4444")
    lb = _label(client, board, "feat", "#0ea5e9")
    card = _card(client, "tagged", label_ids=[la["id"], lb["id"]])
    names = {label["name"] for label in card["labels"]}
    assert names == {"bug", "feat"}
    # Present on a fresh read too.
    assert len(client.get(f"{CARDS}/{card['id']}").json()["labels"]) == 2


def test_update_replaces_labels(client):
    board = _default_board(client)
    la = _label(client, board, "one", "#111111")
    lb = _label(client, board, "two", "#222222")
    card = _card(client, "swap", label_ids=[la["id"]])
    r = client.patch(f"{CARDS}/{card['id']}", json={"label_ids": [lb["id"]]})
    assert r.status_code == 200, r.text
    assert [label["name"] for label in r.json()["labels"]] == ["two"]
    # Empty list clears them.
    r = client.patch(f"{CARDS}/{card['id']}", json={"label_ids": []})
    assert r.json()["labels"] == []


def test_labels_empty_when_none(client):
    card = _card(client, "plain")
    assert card["labels"] == []


def test_label_from_another_board_rejected_422(login_as):
    alice = login_as(*ALICE)  # claims the default board
    a_board = alice.get(BOARDS).json()[0]["id"]
    # A second board Alice owns, with its own label.
    other = alice.post(BOARDS, json={"name": "Other"}).json()
    other_label = alice.post(
        f"{BOARDS}/{other['id']}/labels", json={"name": "x", "color": "#000"}
    ).json()
    # Attaching the other board's label to a card on a_board is a 422.
    r = alice.post(
        CARDS, json={"title": "cross", "board_id": a_board, "label_ids": [other_label["id"]]}
    )
    assert r.status_code == 422


# --- list filters -----------------------------------------------------------


def test_filter_by_priority(client):
    _card(client, "hi", priority="high")
    _card(client, "lo", priority="low")
    r = client.get(CARDS, params={"priority": "high"})
    assert {c["title"] for c in r.json()} == {"hi"}


def test_filter_by_label(client):
    board = _default_board(client)
    la = _label(client, board, "target", "#123456")
    _card(client, "has", label_ids=[la["id"]])
    _card(client, "hasnt")
    r = client.get(CARDS, params={"label": la["id"]})
    assert {c["title"] for c in r.json()} == {"has"}


def test_filter_due_before(client):
    _card(client, "early", due_date="2026-01-01T00:00:00Z")
    _card(client, "late", due_date="2027-01-01T00:00:00Z")
    _card(client, "undated")
    r = client.get(CARDS, params={"due_before": "2026-06-01T00:00:00Z"})
    assert {c["title"] for c in r.json()} == {"early"}


def test_filter_overdue(client):
    # Past-due + not done → overdue; past-due but done → not; future → not.
    _card(client, "overdue", due_date="2020-01-01T00:00:00Z")
    _card(client, "done-past", column="done", due_date="2020-01-01T00:00:00Z")
    _card(client, "future", due_date="2099-01-01T00:00:00Z")
    r = client.get(CARDS, params={"overdue": "true"})
    assert {c["title"] for c in r.json()} == {"overdue"}


# --- label CRUD + authorization ---------------------------------------------


def test_list_labels(client):
    board = _default_board(client)
    # "#1"/"#2" until V62 (KAN-983): colour was unvalidated, so a one-digit stand-in
    # was fine. It is a 422 now, which is the point of the slice.
    _label(client, board, "a", "#111111")
    _label(client, board, "b", "#222222")
    r = client.get(f"{BOARDS}/{board}/labels")
    assert r.status_code == 200
    assert [label["name"] for label in r.json()] == ["a", "b"]


def test_create_label_empty_name_422(client):
    board = _default_board(client)
    assert client.post(
        f"{BOARDS}/{board}/labels", json={"name": "  ", "color": "#000"}
    ).status_code == 422


def test_delete_label_detaches_from_cards(client):
    board = _default_board(client)
    la = _label(client, board, "doomed", "#999")
    card = _card(client, "labelled", label_ids=[la["id"]])
    assert len(card["labels"]) == 1
    # Deleting the label cascades its card_label rows away → detached from the card.
    assert client.delete(f"/api/v1/labels/{la['id']}").status_code == 204
    assert client.get(f"{CARDS}/{card['id']}").json()["labels"] == []
    # And it's gone from the board's label list.
    assert client.get(f"{BOARDS}/{board}/labels").json() == []


# --- PATCH /labels/{id} + usage_count (V61, KAN-982) ------------------------
# Labels shipped in M5 V11 with create/list/delete only, so the only way to fix a
# typo was to delete the label — which detaches it from every card it was on. These
# pin the non-destructive edit and the count the delete confirm needs.


def test_update_label_renames_and_recolours(client):
    board = _default_board(client)
    la = _label(client, board, "buge", "#111")
    r = client.patch(f"/api/v1/labels/{la['id']}", json={"name": "bug", "color": "#222"})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["color"]) == ("bug", "#222")
    # Server-authoritative: the board list agrees, not just the response body.
    listed = client.get(f"{BOARDS}/{board}/labels").json()
    assert [(x["name"], x["color"]) for x in listed] == [("bug", "#222")]


def test_update_label_applies_only_sent_fields(client):
    """A PATCH carrying just ``color`` must not blank the name. ``exclude_unset`` is
    what makes that true, so this fails if the router ever switches to a plain dump —
    the bug would be silent otherwise, since ``name`` defaults to None."""
    board = _default_board(client)
    la = _label(client, board, "keepme", "#111")
    r = client.patch(f"/api/v1/labels/{la['id']}", json={"color": "#333"})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["color"]) == ("keepme", "#333")


def test_update_label_keeps_its_card_attachments(client):
    """The whole point of PATCH over delete-and-recreate: a rename must not detach."""
    board = _default_board(client)
    la = _label(client, board, "old", "#111")
    card = _card(client, "labelled", label_ids=[la["id"]])
    client.patch(f"/api/v1/labels/{la['id']}", json={"name": "new"})
    labels = client.get(f"{CARDS}/{card['id']}").json()["labels"]
    assert [x["name"] for x in labels] == ["new"]


def test_update_label_empty_body_is_a_noop_not_an_error(client):
    board = _default_board(client)
    la = _label(client, board, "same", "#111")
    r = client.patch(f"/api/v1/labels/{la['id']}", json={})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["color"]) == ("same", "#111")


@pytest.mark.parametrize(
    "payload",
    [{"name": "  "}, {"color": " "}, {"name": None}, {"color": None}],
)
def test_update_label_rejects_blank_and_null_422(client, payload):
    """Neither field is clearable: a label with no name or no colour cannot render,
    so ``null`` is a 422 rather than "set it to nothing". That is the deliberate
    difference from EpicUpdate, whose target_date/lead ARE clearable."""
    board = _default_board(client)
    la = _label(client, board, "ok", "#111")
    assert client.patch(f"/api/v1/labels/{la['id']}", json=payload).status_code == 422


def test_update_missing_label_404(client):
    assert client.patch("/api/v1/labels/999999", json={"name": "x"}).status_code == 404

# --- V62 (KAN-983): colour is validated at the schema layer ------------------
# Before this, `color` was any non-empty string <= 32 chars, so "banana" was a valid
# label colour that rendered as a blank dot (issue #278). It is now a palette token or
# a well-formed hex, checked on BOTH create and update.


@pytest.mark.parametrize("color", ["sky", "ink", "mulberry", "#0ea5e9", "#abc", "#ABCDEF"])
def test_create_label_accepts_palette_tokens_and_hex(client, color):
    board = _default_board(client)
    r = client.post(f"{BOARDS}/{board}/labels", json={"name": "ok", "color": color})
    assert r.status_code == 201
    # Stored verbatim: the token is the value, not a hex the server resolves. The SPA
    # maps it to var(--label-<token>) so it follows the theme, which a stored hex
    # could not do.
    assert r.json()["color"] == color


@pytest.mark.parametrize(
    "color",
    [
        "banana",  # the value issue #278 named
        "red",  # a CSS keyword is not a palette token
        "Sky",  # tokens are identifiers; one spelling only
        "#0ea5e",  # five digits
        "#0ea5e9ff",  # #rrggbbaa would composite against whatever surface it lands on
        "var(--danger)",  # would smuggle a status colour back in
    ],
)
def test_create_label_rejects_unrenderable_colour_422(client, color):
    board = _default_board(client)
    assert client.post(
        f"{BOARDS}/{board}/labels", json={"name": "bad", "color": color}
    ).status_code == 422


def test_update_label_rejects_unrenderable_colour_422(client):
    """Recolouring is what this milestone is FOR, so validating create alone would
    leave the wider hole open — the CLI's `label update --color` is the likeliest way
    a bad value gets in."""
    board = _default_board(client)
    la = _label(client, board, "ok", "sky")
    assert client.patch(
        f"/api/v1/labels/{la['id']}", json={"color": "banana"}
    ).status_code == 422
    # And the label is untouched, not half-written.
    r = client.get(f"{BOARDS}/{board}/labels")
    assert [x["color"] for x in r.json() if x["id"] == la["id"]] == ["sky"]


def test_the_422_names_the_palette(client):
    """The error detail is the palette's only discovery path for an API or CLI caller
    — there is no "list the palette" endpoint, and the MCP surface is frozen at 49
    tools (ADR 0019) — so it must carry the tokens, not just say "invalid"."""
    board = _default_board(client)
    r = client.post(f"{BOARDS}/{board}/labels", json={"name": "x", "color": "banana"})
    assert r.status_code == 422
    detail = str(r.json()["detail"])
    assert "sky" in detail and "ink" in detail


def test_a_legacy_colour_survives_a_rename(client):
    """No value migration (SHAPING D11). A label already carrying a free-string colour
    can still be renamed: `color` is only validated when it is actually SENT, which is
    what lets the rule tighten without rewriting stored data.

    Set up through the model rather than the API, because the API is exactly what can
    no longer create such a row."""
    from app.db import SessionLocal
    from app.models import Label

    board = _default_board(client)
    with SessionLocal() as db:
        legacy = Label(board_id=board, name="old", color="banana")
        db.add(legacy)
        db.commit()
        label_id = legacy.id

    r = client.patch(f"/api/v1/labels/{label_id}", json={"name": "renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["color"] == "banana"  # untouched, still rendering as it always did


def test_label_list_reports_usage_count(client):
    board = _default_board(client)
    used = _label(client, board, "used", "#111")
    _label(client, board, "unused", "#222")
    _card(client, "one", label_ids=[used["id"]])
    _card(client, "two", label_ids=[used["id"]])
    counts = {x["name"]: x["usage_count"] for x in client.get(f"{BOARDS}/{board}/labels").json()}
    assert counts == {"used": 2, "unused": 0}


def test_usage_count_is_absent_from_labels_nested_under_a_card(client):
    """``usage_count`` lives on LabelReadWithUsage, which is the LIST endpoint's shape
    only. If it leaked onto LabelRead it would ride along on every label of every card
    in every card read — the per-call payload cost ADR 0019 is about — so this pins the
    asymmetry that the subclass exists to create."""
    board = _default_board(client)
    la = _label(client, board, "nested", "#111")
    card = _card(client, "labelled", label_ids=[la["id"]])
    assert "usage_count" not in client.get(f"{CARDS}/{card['id']}").json()["labels"][0]
    # ...and it IS on the list endpoint, so the test can't pass by the field being gone.
    assert "usage_count" in client.get(f"{BOARDS}/{board}/labels").json()[0]


def test_non_owner_cannot_patch_a_label_403(login_as):
    alice = login_as(*ALICE)
    a_board = alice.get(BOARDS).json()[0]["id"]
    label = alice.post(
        f"{BOARDS}/{a_board}/labels", json={"name": "priv", "color": "#000"}
    ).json()
    bob = login_as(*BOB)
    assert bob.patch(f"/api/v1/labels/{label['id']}", json={"name": "x"}).status_code == 403


def test_non_owner_cannot_touch_labels_403(login_as):
    alice = login_as(*ALICE)
    a_board = alice.get(BOARDS).json()[0]["id"]
    label = alice.post(
        f"{BOARDS}/{a_board}/labels", json={"name": "priv", "color": "#000"}
    ).json()

    bob = login_as(*BOB)  # owns nothing
    assert bob.get(f"{BOARDS}/{a_board}/labels").status_code == 403
    assert bob.post(
        f"{BOARDS}/{a_board}/labels", json={"name": "x", "color": "#000"}
    ).status_code == 403
    assert bob.delete(f"/api/v1/labels/{label['id']}").status_code == 403


def test_unauthenticated_cannot_list_labels_401(client):
    from fastapi.testclient import TestClient

    from app.main import app

    board = _default_board(client)
    with TestClient(app) as anon:
        assert anon.get(f"{BOARDS}/{board}/labels").status_code == 401
