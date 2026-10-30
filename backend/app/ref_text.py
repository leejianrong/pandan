"""Render canonical tickets in stored prose as board-local refs, on read (M8 follow-up).

Activity ``summary`` and notification ``body`` are written once, at the mutation, as
free text that names the canonical ticket (``"created KAN-12: Fix login"``). Baking the
board-local ref in at write time would be wrong: ``board.key`` is editable, so a stored
``ENG-14`` goes stale the day the key changes. Instead the stored text keeps the
immutable canonical ticket and this module rewrites it per read from the board's
*current* key — the same reason ``card.ref`` is attached per read rather than stored.

Only the text before the first ``": "`` is rewritten. Every writer puts the ticket(s)
there and a user-typed title after it, and a title that happens to say ``KAN-5`` must
not be silently renamed. A ticket with no row left (a purged card) stays canonical.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .board_seq import card_ref, epic_ref
from .models import Board, Card, Epic

_TICKET = re.compile(r"\b(KAN|EPIC)-(\d+)\b")


def _head_and_tail(text: str) -> tuple[str, str]:
    head, sep, tail = text.partition(": ")
    return head, sep + tail


def render_refs(db: Session, items: Sequence[tuple[int, str]]) -> list[str]:
    """Rewrite each ``(board_id, text)``'s canonical tickets to board-local refs.

    Two lookups total (cards, epics) however many rows and boards are involved.
    """
    wanted: dict[str, set[int]] = {"KAN": set(), "EPIC": set()}
    board_ids: set[int] = set()
    for board_id, text in items:
        head, _ = _head_and_tail(text)
        for prefix, num in _TICKET.findall(head):
            wanted[prefix].add(int(num))
            board_ids.add(board_id)
    if not board_ids:
        return [text for _, text in items]

    keys = dict(
        db.execute(select(Board.id, Board.key).where(Board.id.in_(board_ids))).all()
    )
    refs: dict[tuple[int, str], str] = {}
    for model, prefix, make in ((Card, "KAN", card_ref), (Epic, "EPIC", epic_ref)):
        if not wanted[prefix]:
            continue
        tickets = [f"{prefix}-{n}" for n in wanted[prefix]]
        rows = db.execute(
            select(model.ticket_number, model.board_id, model.board_seq).where(
                model.ticket_number.in_(tickets), model.board_id.in_(board_ids)
            )
        ).all()
        for ticket, bid, seq in rows:
            if keys.get(bid):
                refs[(bid, ticket)] = make(keys[bid], seq)

    out: list[str] = []
    for board_id, text in items:
        head, tail = _head_and_tail(text)
        head = _TICKET.sub(
            lambda m: refs.get((board_id, m.group(0)), m.group(0)), head
        )
        out.append(head + tail)
    return out
