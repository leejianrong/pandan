"""per-board sequences for cards and epics (M8 V52, KAN-973)

Revision ID: 0023_board_seq
Revises: 0022_board_keys
Create Date: 2026-08-25

Additive with a backfill (M8 R4.2). ``card.board_seq`` / ``epic.board_seq`` are the
board-local numbers a ref renders from — the ``14`` in ``ENG-14``, the ``7`` in
``ENG-E7`` — and ``board.next_card_seq`` / ``next_epic_seq`` are the counters new rows
take them from.

**``ticket_number`` is not touched, here or ever** (SHAPING D1, M8 R1.2). This adds a
second, board-local numbering *beside* the canonical one; it does not renumber
anything. A test pins that every ticket value survives this migration unchanged.

**Soft-deleted rows are numbered too** (SHAPING D7). The ``row_number()`` partitions
over **all** rows, trashed included, and the counters are never decremented. Skipping
trashed cards would renumber the live ones around them, so restoring a card would
collide with a number already handed out — the numbering has to describe every row
that exists, not just the visible ones.

Ordering by ``id`` makes the backfill deterministic and gives the oldest row the
lowest number, which is the only ordering a reader would expect: ``id`` is a monotonic
BigInteger, so it agrees with creation order and with ``ticket_number``'s own ordering
within a board.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0023_board_seq'
down_revision: Union[str, None] = '0022_board_keys'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('card', sa.Column('board_seq', sa.Integer(), nullable=True))
    op.add_column('epic', sa.Column('board_seq', sa.Integer(), nullable=True))
    op.add_column(
        'board',
        sa.Column(
            'next_card_seq', sa.Integer(), server_default=sa.text('0'), nullable=False
        ),
    )
    op.add_column(
        'board',
        sa.Column(
            'next_epic_seq', sa.Integer(), server_default=sa.text('0'), nullable=False
        ),
    )

    bind = op.get_bind()
    for table in ('card', 'epic'):
        # One UPDATE ... FROM over a windowed subquery: the whole backfill is a
        # single statement per table regardless of row count.
        bind.execute(
            sa.text(
                f"""
                WITH numbered AS (
                    SELECT id, row_number() OVER (
                        PARTITION BY board_id ORDER BY id
                    ) AS rn
                    FROM {table}
                )
                UPDATE {table} SET board_seq = numbered.rn
                FROM numbered WHERE {table}.id = numbered.id
                """  # noqa: S608
            )
        )

    # Seed each counter to the highest number now in use on that board. These columns
    # hold the LAST issued value, not the next one: a create runs
    # ``SET next_card_seq = next_card_seq + 1 ... RETURNING next_card_seq``, so the
    # value it returns is the next. A board with no cards stays at 0 and its first
    # card gets 1.
    for table, column in (('card', 'next_card_seq'), ('epic', 'next_epic_seq')):
        bind.execute(
            sa.text(
                f"""
                UPDATE board SET {column} = COALESCE(
                    (SELECT max(board_seq) FROM {table}
                     WHERE {table}.board_id = board.id),
                    0
                )
                """  # noqa: S608
            )
        )

    op.alter_column('card', 'board_seq', existing_type=sa.Integer(), nullable=False)
    op.alter_column('epic', 'board_seq', existing_type=sa.Integer(), nullable=False)
    op.create_unique_constraint('uq_card_board_seq', 'card', ['board_id', 'board_seq'])
    op.create_unique_constraint('uq_epic_board_seq', 'epic', ['board_id', 'board_seq'])


def downgrade() -> None:
    op.drop_constraint('uq_epic_board_seq', 'epic', type_='unique')
    op.drop_constraint('uq_card_board_seq', 'card', type_='unique')
    op.drop_column('board', 'next_epic_seq')
    op.drop_column('board', 'next_card_seq')
    op.drop_column('epic', 'board_seq')
    op.drop_column('card', 'board_seq')
