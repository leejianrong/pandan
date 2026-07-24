"""Unit tests for the notification emit helper (V37, KAN-301, app.notifications).

No database: :func:`record_notification` only reads the board (``db.get``) and adds
a row (``db.add``), so a tiny fake session exercises every branch — the board-owner
recipient (a real ``User`` id), the ownerless skip, and the missing-board skip. The
same-transaction guarantee (it never commits) is covered here by construction (the
fake session has no ``commit``) and end-to-end in the integration suite.
"""
from __future__ import annotations

import uuid

from app.models import Board, Notification
from app.notifications import record_notification


class FakeSession:
    """Minimal stand-in for a SQLAlchemy ``Session`` — records ``add``, returns a
    preset board from ``get`` (or ``None`` for the missing-board case)."""

    def __init__(self, board: Board | None) -> None:
        self._board = board
        self.added: list[object] = []

    def get(self, model, pk):
        assert model is Board
        return self._board

    def add(self, obj) -> None:
        self.added.append(obj)


def test_emits_one_row_addressed_to_the_board_owner():
    owner = uuid.uuid4()
    db = FakeSession(Board(id=7, name="B", owner_id=owner))

    row = record_notification(
        db, board_id=7, kind="needs_human", body="KAN-1 needs a human", card_id=3
    )

    assert isinstance(row, Notification)
    assert db.added == [row]  # added to the caller's session, not committed
    assert row.user_id == owner  # recipient = board owner (a real User)
    assert row.board_id == 7
    assert row.card_id == 3
    assert row.kind == "needs_human"
    assert row.body == "KAN-1 needs a human"
    assert row.read_at is None  # born unread


def test_card_id_is_optional():
    db = FakeSession(Board(id=1, name="B", owner_id=uuid.uuid4()))
    row = record_notification(db, board_id=1, kind="ci_failed", body="CI failed")
    assert row is not None
    assert row.card_id is None


def test_skips_silently_when_board_is_ownerless():
    db = FakeSession(Board(id=7, name="B", owner_id=None))
    assert record_notification(db, board_id=7, kind="blocked", body="x") is None
    assert db.added == []  # no recipient → no row, no crash


def test_skips_silently_when_board_is_missing():
    db = FakeSession(None)
    assert record_notification(db, board_id=99, kind="assigned", body="x") is None
    assert db.added == []
