"""API tests for card notes / comments — KAN-33.

Human/agent-authored notes on a card (distinct from Epic 4's SYSTEM activity log).
Covers posting / listing (creation order) / deleting-own comments, and the guards:
empty body (422), missing card (404), missing comment (404), deleting someone
else's comment (403), non-owner board access (403), unauthenticated (401), and
cascade-delete. Uses only the HTTP client — per the suite convention, any
app-module imports go inside test bodies, not at module top.
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


def _add_comment(client, card_id, body="a note"):
    return client.post(f"{CARDS}/{card_id}/comments", json={"body": body})


# --- add / list happy path ---------------------------------------------------


def test_add_comment_returns_created(client):
    card = _card(client, "with-notes")

    r = _add_comment(client, card["id"], "why this is blocked")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["body"] == "why this is blocked"
    assert "id" in body and "created_at" in body
    # author_id is set from the principal (never the request body).
    assert body["author_id"] is not None


def test_list_comments_ordered_by_creation(client):
    card = _card(client, "thread")
    _add_comment(client, card["id"], "first")
    _add_comment(client, card["id"], "second")
    _add_comment(client, card["id"], "third")

    r = client.get(f"{CARDS}/{card['id']}/comments")
    assert r.status_code == 200, r.text
    bodies = [c["body"] for c in r.json()]
    assert bodies == ["first", "second", "third"]  # oldest-first


def test_list_comments_empty_when_none(client):
    card = _card(client, "quiet")
    r = client.get(f"{CARDS}/{card['id']}/comments")
    assert r.status_code == 200
    assert r.json() == []


# --- delete own -------------------------------------------------------------


def test_delete_own_comment(client):
    card = _card(client, "deletable")
    comment_id = _add_comment(client, card["id"]).json()["id"]

    r = client.delete(f"{CARDS}/{card['id']}/comments/{comment_id}")
    assert r.status_code == 204, r.text
    assert client.get(f"{CARDS}/{card['id']}/comments").json() == []


def test_delete_missing_comment_404(client):
    card = _card(client, "no-comment")
    r = client.delete(f"{CARDS}/{card['id']}/comments/999999")
    assert r.status_code == 404


def test_delete_comment_belonging_to_other_card_404(client):
    a = _card(client, "A")
    b = _card(client, "B")
    comment_id = _add_comment(client, a["id"]).json()["id"]
    # The comment exists, but not on card B → 404 (not silently removed).
    r = client.delete(f"{CARDS}/{b['id']}/comments/{comment_id}")
    assert r.status_code == 404
    assert len(client.get(f"{CARDS}/{a['id']}/comments").json()) == 1


# --- edit own ----------------------------------------------------------------


def test_edit_own_comment(client):
    card = _card(client, "editable")
    created = _add_comment(client, card["id"], "first draft").json()

    r = client.patch(
        f"{CARDS}/{card['id']}/comments/{created['id']}", json={"body": "revised"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["body"] == "revised"
    # Identity and ordering are untouched by an edit.
    assert body["id"] == created["id"]
    assert body["author_id"] == created["author_id"]
    assert body["created_at"] == created["created_at"]
    listed = client.get(f"{CARDS}/{card['id']}/comments").json()
    assert [c["body"] for c in listed] == ["revised"]


def test_edit_comment_empty_body_422(client):
    card = _card(client, "edit-bad")
    cid = _add_comment(client, card["id"], "keep me").json()["id"]
    url = f"{CARDS}/{card['id']}/comments/{cid}"
    assert client.patch(url, json={"body": "   "}).status_code == 422
    assert client.patch(url, json={}).status_code == 422
    assert client.get(f"{CARDS}/{card['id']}/comments").json()[0]["body"] == "keep me"


def test_edit_missing_comment_404(client):
    card = _card(client, "no-comment")
    r = client.patch(f"{CARDS}/{card['id']}/comments/999999", json={"body": "x"})
    assert r.status_code == 404


def test_edit_comment_on_missing_card_404(client):
    r = client.patch(f"{CARDS}/999999/comments/1", json={"body": "x"})
    assert r.status_code == 404


def test_edit_comment_belonging_to_other_card_404(client):
    a = _card(client, "A")
    b = _card(client, "B")
    cid = _add_comment(client, a["id"], "orig").json()["id"]
    r = client.patch(f"{CARDS}/{b['id']}/comments/{cid}", json={"body": "hijack"})
    assert r.status_code == 404
    assert client.get(f"{CARDS}/{a['id']}/comments").json()[0]["body"] == "orig"


def test_edit_another_authors_comment_403(client):
    """Edit-own-only, mirroring delete: seed a foreign-authored comment directly
    (boards are single-owner, so no second principal can post via the API)."""
    from sqlalchemy import text

    from app.db import engine

    card = client.post(CARDS, json={"title": "shared-card"}).json()
    with engine.begin() as conn:
        other_id = conn.execute(
            text(
                'INSERT INTO "user" '
                "(id, email, hashed_password, is_active, is_superuser, is_verified) "
                "VALUES (gen_random_uuid(), 'editor-else@example.com', 'x', "
                "true, false, false) RETURNING id"
            )
        ).scalar_one()
        foreign_id = conn.execute(
            text(
                "INSERT INTO card_comment (card_id, author_id, body) "
                "VALUES (:cid, :aid, 'not yours') RETURNING id"
            ),
            {"cid": card["id"], "aid": other_id},
        ).scalar_one()

    r = client.patch(
        f"{CARDS}/{card['id']}/comments/{foreign_id}", json={"body": "mine now"}
    )
    assert r.status_code == 403, r.text
    listed = client.get(f"{CARDS}/{card['id']}/comments").json()
    assert [c["body"] for c in listed] == ["not yours"]


def test_non_owner_cannot_edit_comment_403(login_as):
    alice = login_as(*ALICE)
    a_board = alice.get(BOARDS).json()[0]["id"]
    card = alice.post(CARDS, json={"title": "owned", "board_id": a_board}).json()
    cid = _add_comment(alice, card["id"], "orig").json()["id"]

    bob = login_as(*BOB)
    r = bob.patch(f"{CARDS}/{card['id']}/comments/{cid}", json={"body": "x"})
    assert r.status_code == 403
    assert alice.get(f"{CARDS}/{card['id']}/comments").json()[0]["body"] == "orig"


def test_unauthenticated_cannot_edit_comment_401(client):
    from fastapi.testclient import TestClient

    from app.main import app

    card = _card(client, "owned")
    cid = _add_comment(client, card["id"]).json()["id"]
    with TestClient(app) as anon:
        r = anon.patch(f"{CARDS}/{card['id']}/comments/{cid}", json={"body": "x"})
        assert r.status_code == 401


# --- guards ------------------------------------------------------------------


def test_empty_body_rejected_422(client):
    card = _card(client, "bad-body")
    assert _add_comment(client, card["id"], "   ").status_code == 422


def test_add_comment_to_missing_card_404(client):
    r = _add_comment(client, 999999)
    assert r.status_code == 404


def test_list_comments_on_missing_card_404(client):
    r = client.get(f"{CARDS}/999999/comments")
    assert r.status_code == 404


# --- authorization: delete-own-only + board ownership ------------------------


def test_delete_another_authors_comment_403(client):
    """Delete-own-only (KAN-33): the board owner is **403** on a comment authored by
    someone else, even though they own the board.

    Boards are single-owner (V8), so via the HTTP API only the owner (and their
    PATs, which resolve to the owner) can ever reach a card — there is no second
    principal that can post through the API. To exercise the author check itself
    (not just the board gate) we seed a comment authored by a *different* user
    directly in the DB, then have the board owner try to delete it.
    """
    from sqlalchemy import text

    from app.db import engine

    card = client.post(CARDS, json={"title": "shared-card"}).json()

    with engine.begin() as conn:
        other_id = conn.execute(
            text(
                'INSERT INTO "user" '
                "(id, email, hashed_password, is_active, is_superuser, is_verified) "
                "VALUES (gen_random_uuid(), 'someone-else@example.com', 'x', "
                "true, false, false) RETURNING id"
            )
        ).scalar_one()
        foreign_comment_id = conn.execute(
            text(
                "INSERT INTO card_comment (card_id, author_id, body) "
                "VALUES (:cid, :aid, 'not yours') RETURNING id"
            ),
            {"cid": card["id"], "aid": other_id},
        ).scalar_one()

    # The owner can see it (list is board-scoped, not author-scoped)...
    listed = client.get(f"{CARDS}/{card['id']}/comments").json()
    assert any(c["id"] == foreign_comment_id for c in listed)
    # ...but cannot delete another author's comment.
    r = client.delete(f"{CARDS}/{card['id']}/comments/{foreign_comment_id}")
    assert r.status_code == 403, r.text
    # Still there.
    assert client.get(f"{CARDS}/{card['id']}/comments").json()


def test_non_owner_cannot_touch_comments_403(login_as):
    alice = login_as(*ALICE)  # claims default board
    a_board = alice.get(BOARDS).json()[0]["id"]
    card = alice.post(CARDS, json={"title": "owned", "board_id": a_board}).json()
    comment_id = _add_comment(alice, card["id"]).json()["id"]

    bob = login_as(*BOB)  # owns nothing
    assert bob.get(f"{CARDS}/{card['id']}/comments").status_code == 403
    assert _add_comment(bob, card["id"]).status_code == 403
    assert bob.delete(
        f"{CARDS}/{card['id']}/comments/{comment_id}"
    ).status_code == 403


def test_unauthenticated_cannot_add_comment_401(client):
    from fastapi.testclient import TestClient

    from app.main import app

    card = _card(client, "owned")
    with TestClient(app) as anon:
        r = anon.post(f"{CARDS}/{card['id']}/comments", json={"body": "hi"})
        assert r.status_code == 401


def test_cascade_delete_removes_comments(client):
    card = _card(client, "doomed")
    _add_comment(client, card["id"])
    # Deleting the card cascades its comments away (ON DELETE CASCADE).
    assert client.delete(f"{CARDS}/{card['id']}").status_code == 204
    assert client.get(f"{CARDS}/{card['id']}/comments").status_code == 404
