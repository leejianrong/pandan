"""card.parked (M8 V56, KAN-977)

Additive: a NOT NULL boolean with a `false` server default, mirroring
`needs_human` exactly — every existing row stays valid, no backfill needed
beyond the default itself. Distinguishes a card someone deliberately parked
from one simply not yet scheduled (the backlog itself stays derived from
`cycle_id IS NULL`, SHAPING D8 — no new column for that).

Revision ID: 0025_card_parked
Revises: 0024_team_schema
Create Date: 2026-09-02 14:22:16.963590
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0025_card_parked'
down_revision: Union[str, None] = '0024_team_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('card', sa.Column('parked', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('card', 'parked')
