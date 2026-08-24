"""Board-local sequence numbers and the refs rendered from them (M8 V52, KAN-973).

A board-local ref is ``<board.key>-<board_seq>`` for a card and
``<board.key>-E<board_seq>`` for an epic — ``ENG-14``, ``ENG-E7``. It is a *display*
form. The canonical, globally unique, immutable identifier is still
``ticket_number`` (``KAN-955`` / ``EPIC-7``), and nothing here touches it (SHAPING D1;
[ADR 0020](../../docs/adr/0020-board-keys.md)).

**Allocation is one statement, and the choice of mechanism inverts the usual advice.**

    UPDATE board SET next_card_seq = next_card_seq + :n WHERE id = :id
    RETURNING next_card_seq

A Postgres sequence never blocks and always leaves gaps on rollback; this counter
column briefly serialises concurrent writers to *one board* and is **gapless**.
Gapless is precisely what issue #280 asked for — "the numbers jump and are not
sequential (locally)" — so the property normally counted as a sequence's advantage is,
here, the defect being fixed (SHAPING D6). A sequence *object* per board was rejected
outright: that is DDL per board, and hundreds of them do not scale.

The row lock the ``UPDATE`` takes is held until the enclosing transaction ends, which
is the serialisation. Two consequences worth knowing rather than discovering:

* Allocate **as late as possible** in a create, so the lock is held briefly.
* Allocate a **range** for a batch (``:n`` > 1) rather than looping — one statement,
  one lock acquisition, and the numbers stay contiguous. ``apply_template`` is the
  only server-side batch create; the MCP's ``create_cards`` is a client-side loop over
  N HTTP posts, so it allocates one at a time by construction.

Nothing is ever decremented. A soft-deleted card keeps its number so that restoring it
cannot collide with a number since handed out (SHAPING D7).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

#: The epic marker inside a board-local ref: ``ENG-E7``. A single letter, and it sits
#: in the *tail* rather than the key, which is what keeps the split decidable — a key
#: has no hyphens (ADR 0020), so a ref splits on its first one and the tail is then
#: either all digits (a card) or ``E`` + digits (an epic).
EPIC_REF_MARKER = "E"


def _allocate(db: Session, board_id: int, column: str, count: int) -> list[int]:
    """Take ``count`` consecutive numbers from ``board.<column>``, in one statement.

    Returns them in ascending order. The column name is interpolated rather than
    bound because an identifier cannot be a bind parameter; it never comes from
    request data — only the two module-level callers below pass it.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    assert column in ("next_card_seq", "next_epic_seq"), column
    last = db.execute(
        text(
            f"UPDATE board SET {column} = {column} + :n "  # noqa: S608 - fixed identifiers
            "WHERE id = :board_id RETURNING " + column
        ),
        {"n": count, "board_id": board_id},
    ).scalar_one()
    return list(range(last - count + 1, last + 1))


def allocate_card_seqs(db: Session, board_id: int, count: int = 1) -> list[int]:
    """The next ``count`` board-local card numbers on ``board_id``, ascending."""
    return _allocate(db, board_id, "next_card_seq", count)


def allocate_epic_seqs(db: Session, board_id: int, count: int = 1) -> list[int]:
    """The next ``count`` board-local epic numbers on ``board_id``, ascending."""
    return _allocate(db, board_id, "next_epic_seq", count)


def card_ref(board_key: str, board_seq: int) -> str:
    """``ENG-14`` — a card's board-local ref."""
    return f"{board_key}-{board_seq}"


def epic_ref(board_key: str, board_seq: int) -> str:
    """``ENG-E7`` — an epic's board-local ref."""
    return f"{board_key}-{EPIC_REF_MARKER}{board_seq}"
