"""cycles (iterations)

Adds the ``cycle`` table (a board-scoped, time-boxed iteration) and a nullable
``card.cycle_id`` FK (``ON DELETE SET NULL``, mirroring ``card.epic_id``) linking a
story to zero-or-one cycle. Purely additive — no data backfill (V33, KAN-297).

Revision ID: f7b35130c1f4
Revises: 36af407aaa9c
Create Date: 2026-07-22 00:28:12.013492
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7b35130c1f4'
down_revision: Union[str, None] = '36af407aaa9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cycle',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('board_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('starts_on', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ends_on', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['board_id'], ['board.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cycle_board_id'), 'cycle', ['board_id'], unique=False)
    op.add_column('card', sa.Column('cycle_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_card_cycle_id_cycle',
        'card',
        'cycle',
        ['cycle_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_card_cycle_id_cycle', 'card', type_='foreignkey')
    op.drop_column('card', 'cycle_id')
    op.drop_index(op.f('ix_cycle_board_id'), table_name='cycle')
    op.drop_table('cycle')
