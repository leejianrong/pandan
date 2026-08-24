"""Demo seed data for a fresh board (R0.4).

A handful of cards across the three columns so the very first load shows a lively
board instead of an empty one. Kept as plain data plus a guarded insert so both
the Alembic data migration and any future management command can reuse it. Uses
Core SQL against the ``card`` table (no ORM models), so it stays valid even if the
ORM layer later changes — important for a migration that must run years from now.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

# (title, description, column, position, story_points, assignee)
_FIELDS = ("title", "description", "column", "position", "story_points", "assignee")
_ROWS: list[tuple] = [
    ("Set up project repository", "Monorepo: backend + frontend.", "done", 0, 2, "Alex"),
    ("Design the card data model", None, "done", 1, 3, "Sam"),
    ("Build the REST API", "CRUD + move endpoints.", "in_progress", 0, 8, "Sam"),
    ("Wire up drag-and-drop", "svelte-dnd-action between columns.", "in_progress", 1, 5, "Jordan"),
    ("Add demo seed data", None, "todo", 0, 2, None),
    ("Write end-to-end tests", "Playwright smoke coverage.", "todo", 1, 3, "Alex"),
]

# List of demo cards as dicts; the source of truth for both insert and cleanup.
DEMO_CARDS: list[dict] = [dict(zip(_FIELDS, row)) for row in _ROWS]

# board_id is included since M3 V7 (card.board_id is NOT NULL). The historical
# seed migration (0002) predates the board table and carries its own board-less
# INSERT, so this module is free to target the current schema.
_INSERT = text(
    "INSERT INTO card "
    '(board_id, board_seq, title, description, "column", position, story_points, assignee) '
    "VALUES (:board_id, :board_seq, :title, :description, :column, :position, "
    ":story_points, :assignee)"
)

# Board-local numbering (M8 V52, KAN-973). ``board_seq`` is NOT NULL, so this seam
# has to take numbers from the board's counter like any other create. Written out
# here rather than imported from :mod:`app.board_seq`: that helper takes an ORM
# ``Session`` and this module deliberately speaks Core SQL over a ``Connection`` so
# it stays valid if the ORM layer changes (see the module docstring). One statement
# for the whole batch, so the numbers are contiguous.
_TAKE_SEQ_RANGE = text(
    "UPDATE board SET next_card_seq = next_card_seq + :n WHERE id = :board_id "
    "RETURNING next_card_seq"
)


def seed_demo_cards(connection: Connection, board_id: int | None = None) -> int:
    """Insert the demo cards into a board, but only when the board table is empty.

    Returns the number of cards inserted (0 if any card already exists, so running
    this on an existing/production database is a safe no-op). ``board_id`` defaults
    to the earliest board (the default board); ``id``, ``ticket_number``, and the
    timestamps are left to their DB defaults.
    """
    existing = connection.execute(text("SELECT COUNT(*) FROM card")).scalar_one()
    if existing:
        return 0
    if board_id is None:
        board_id = connection.execute(
            text("SELECT id FROM board ORDER BY id LIMIT 1")
        ).scalar_one()
    last_seq = connection.execute(
        _TAKE_SEQ_RANGE, {"n": len(DEMO_CARDS), "board_id": board_id}
    ).scalar_one()
    first_seq = last_seq - len(DEMO_CARDS) + 1
    for offset, card in enumerate(DEMO_CARDS):
        connection.execute(
            _INSERT,
            {**card, "board_id": board_id, "board_seq": first_seq + offset},
        )
    return len(DEMO_CARDS)
