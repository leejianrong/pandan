"""API tests for the label emoji field (M8 V64, KAN-985, issue #278).

Additive, back-compatible field on the label entity: an optional ``emoji``, any
single Unicode grapheme cluster, validated via ``app.emoji.is_single_grapheme``
(see ``test_emoji.py`` for that module's own grapheme-cluster coverage — not
repeated here). Covers set/read/clear, back-compat (a label created without one
reads NULL), and that validation rejects more than one grapheme. Uses only the
HTTP client — per the suite convention any app-module imports go inside test
bodies.
"""
from __future__ import annotations

import pytest

BOARDS = "/api/v1/boards"


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these run as the board-owning
    session user (claim-on-login owns the reset fixture's default board)."""
    return logged_in_client


def _default_board(client) -> int:
    return client.get(BOARDS).json()[0]["id"]


def _label(client, board_id, name="bug", color="#ef4444", **fields):
    r = client.post(f"{BOARDS}/{board_id}/labels", json={"name": name, "color": color, **fields})
    assert r.status_code == 201, r.text
    return r.json()


# --- back-compat: existing labels read NULL ---------------------------------


def test_label_without_emoji_reads_null(client):
    board = _default_board(client)
    label = _label(client, board, "legacy")
    assert label["emoji"] is None
    listed = client.get(f"{BOARDS}/{board}/labels").json()
    assert [x["emoji"] for x in listed if x["id"] == label["id"]] == [None]


# --- set on create -----------------------------------------------------------


def test_create_label_with_emoji(client):
    board = _default_board(client)
    label = _label(client, board, "bug", emoji="🐛")
    assert label["emoji"] == "🐛"


def test_create_label_with_multi_codepoint_single_grapheme_emoji(client):
    """A ZWJ sequence is several codepoints but ONE grapheme — the whole reason
    app.emoji exists rather than a bare len(value) == 1 check."""
    board = _default_board(client)
    label = _label(client, board, "team", emoji="👨‍👩‍👧‍👦")
    assert label["emoji"] == "👨‍👩‍👧‍👦"


def test_create_label_rejects_more_than_one_grapheme(client):
    board = _default_board(client)
    r = client.post(
        f"{BOARDS}/{board}/labels", json={"name": "bad", "color": "#000", "emoji": "ab"}
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("one character" in str(e.get("msg", e)) for e in detail)


# --- set / clear via update ---------------------------------------------------


def test_patch_sets_emoji(client):
    board = _default_board(client)
    label = _label(client, board, "before")
    assert label["emoji"] is None
    r = client.patch(f"/api/v1/labels/{label['id']}", json={"emoji": "🔥"})
    assert r.status_code == 200
    assert r.json()["emoji"] == "🔥"


def test_patch_clears_emoji(client):
    """Unlike name/color (LabelUpdate rejects an explicit null), a label's emoji
    is genuinely optional — null is a real, permanent value here."""
    board = _default_board(client)
    label = _label(client, board, "coloured", emoji="⭐")
    assert label["emoji"] == "⭐"
    r = client.patch(f"/api/v1/labels/{label['id']}", json={"emoji": None})
    assert r.status_code == 200
    assert r.json()["emoji"] is None


def test_patch_emoji_independently_of_other_fields(client):
    """Only the fields actually sent are applied (exclude_unset): setting emoji
    alone leaves the name/colour untouched, and vice versa."""
    board = _default_board(client)
    label = _label(client, board, "partial", color="sky", emoji="🚀")
    r = client.patch(f"/api/v1/labels/{label['id']}", json={"name": "renamed"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "renamed"
    assert body["color"] == "sky"
    assert body["emoji"] == "🚀"  # not sent, so left as-is


def test_patch_rejects_more_than_one_grapheme(client):
    board = _default_board(client)
    label = _label(client, board, "e")
    r = client.patch(f"/api/v1/labels/{label['id']}", json={"emoji": "xy"})
    assert r.status_code == 422
    # And the rejected PATCH must not have applied any part of itself.
    listed = client.get(f"{BOARDS}/{board}/labels").json()
    assert [x["emoji"] for x in listed if x["id"] == label["id"]] == [None]
