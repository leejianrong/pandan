"""Notification write path (V37, KAN-301) — the emit-on-event helper.

The notification analogue of the activity logger (:mod:`app.activity`): a single
flat helper the write paths call to append one :class:`app.models.Notification`
row for an event a human shouldn't miss. Matches the deliberately flat backend
style (ADR 0008 — no service/repository layer): routers (and the autosync webhook
path) call :func:`record_notification` directly.

**Same-transaction, write path only.** The helper *adds* the row to the caller's
session but does **not** commit — the caller commits it in the **same transaction**
as the mutation that triggered it, so the notification and the change it describes
land (or roll back) atomically. The inbox read + mark-read API is
:mod:`app.routers.notifications`.

**Recipient = the board owner** (``board.owner_id``). It is always a real ``User``,
so owner-scoping the inbox is trivial (you only see your own rows), and it always
resolves to a real recipient — unlike a free-text ``card.assignee`` (e.g.
``agent:foo``), which is not a user. If the board has no owner (``owner_id`` is
``NULL``), emission is **skipped** (returns ``None``) — never a crash.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import outbound
from .models import Board, Notification


def record_notification(
    db: Session,
    *,
    board_id: int,
    kind: str,
    body: str,
    card_id: int | None = None,
) -> Notification | None:
    """Append one notification for ``board_id``'s owner (added, not committed).

    Resolves the recipient as ``board.owner_id``. When the board is missing or
    **ownerless** (``owner_id is None``) no row is written and ``None`` is returned
    — the emit call-sites can call this unconditionally without guarding.

    ``kind`` ∈ {``needs_human``, ``blocked``, ``ci_failed``, ``assigned``}
    (CHECK-constrained on the table); ``body`` is a short human-readable one-liner
    (e.g. ``"KAN-3 needs a human: pick an auth provider"``). ``card_id`` links the
    card the event is about (optional). The caller commits it in the same
    transaction as the mutation it describes.
    """
    board = db.get(Board, board_id)
    if board is None or board.owner_id is None:
        return None
    notification = Notification(
        user_id=board.owner_id,
        board_id=board_id,
        card_id=card_id,
        kind=kind,
        body=body,
    )
    db.add(notification)
    # Queue a best-effort signed outbound POST for this notification, dispatched only
    # AFTER the caller's transaction commits (V38, KAN-302). Never sent here — the row
    # is uncommitted and the transaction may still roll back. See :mod:`app.outbound`.
    outbound.queue_delivery(db, notification, board)
    return notification
