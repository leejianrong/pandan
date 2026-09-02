"""planning intervals (M8 V57, KAN-978)

Adds the ``planning_interval`` table (a board-scoped grouping one level above the
cycle — e.g. a quarter containing six two-week sprints) and a nullable
``cycle.planning_interval_id`` FK (``ON DELETE SET NULL``, mirroring
``card.epic_id``) linking a cycle to zero-or-one planning interval. Purely
additive — no data backfill, structurally identical to V33's ``cycle`` migration
(``f7b35130c1f4``).

Revision ID: a34847829681
Revises: 0025_card_parked
Create Date: 2026-09-02 15:05:46.729912
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a34847829681'
down_revision: Union[str, None] = '0025_card_parked'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'planning_interval',
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
    op.create_index(
        op.f('ix_planning_interval_board_id'), 'planning_interval', ['board_id'], unique=False
    )
    op.add_column('cycle', sa.Column('planning_interval_id', sa.BigInteger(), nullable=True))
    op.create_index(
        op.f('ix_cycle_planning_interval_id'), 'cycle', ['planning_interval_id'], unique=False
    )
    op.create_foreign_key(
        'fk_cycle_planning_interval_id_planning_interval',
        'cycle',
        'planning_interval',
        ['planning_interval_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_cycle_planning_interval_id_planning_interval', 'cycle', type_='foreignkey'
    )
    op.drop_index(op.f('ix_cycle_planning_interval_id'), table_name='cycle')
    op.drop_column('cycle', 'planning_interval_id')
    op.drop_index(op.f('ix_planning_interval_board_id'), table_name='planning_interval')
    op.drop_table('planning_interval')
