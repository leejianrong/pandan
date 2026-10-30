"""Activity summaries and notification bodies render board-local refs on read.

The stored text keeps the immutable canonical ticket; the read swaps in the board's
*current* ref, so editing ``board.key`` re-renders history. Per the suite convention,
app imports live inside the test bodies.
"""
from __future__ import annotations

BOARDS = "/api/v1/boards"
CARDS = "/api/v1/cards"


def _setup(client, key="ENG"):
    board = client.post(BOARDS, json={"name": "Engine Room", "key": key}).json()
    card = client.post(
        CARDS, json={"title": "Fix login", "board_id": board["id"]}
    ).json()
    return board, card


def _summaries(client, board_id):
    return [a["summary"] for a in client.get(f"{BOARDS}/{board_id}/activity").json()]


def test_activity_summary_shows_the_board_local_ref(logged_in_client):
    board, card = _setup(logged_in_client)
    assert "created ENG-1: Fix login" in _summaries(logged_in_client, board["id"])
    joined = " ".join(_summaries(logged_in_client, board["id"]))
    assert card["ticket_number"] not in joined


def test_editing_the_key_rerenders_history(logged_in_client):
    board, _ = _setup(logged_in_client)
    logged_in_client.patch(f"{BOARDS}/{board['id']}", json={"key": "OPS"})
    assert "created OPS-1: Fix login" in _summaries(logged_in_client, board["id"])


def test_a_ticket_inside_a_title_is_left_alone(logged_in_client):
    board, card = _setup(logged_in_client)
    logged_in_client.patch(
        f"{CARDS}/{card['id']}", json={"title": "dup of KAN-999"}
    )
    logged_in_client.delete(f"{CARDS}/{card['id']}")
    summaries = _summaries(logged_in_client, board["id"])
    assert "deleted ENG-1: dup of KAN-999" in summaries


def test_notification_body_shows_the_board_local_ref(logged_in_client):
    board, card = _setup(logged_in_client)
    logged_in_client.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:bot"})
    bodies = [n["body"] for n in logged_in_client.get("/api/v1/notifications").json()]
    assert any(b.startswith("ENG-1 assigned to") for b in bodies), bodies
    assert not any(card["ticket_number"] in b for b in bodies)


def test_stored_text_is_unchanged(logged_in_client):
    """Rendering is a read-side concern: the row keeps the canonical ticket."""
    board, card = _setup(logged_in_client)
    _summaries(logged_in_client, board["id"])
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Activity

    with SessionLocal() as db:
        stored = db.scalars(
            select(Activity.summary).where(Activity.board_id == board["id"])
        ).all()
    assert f"created {card['ticket_number']}: Fix login" in stored
