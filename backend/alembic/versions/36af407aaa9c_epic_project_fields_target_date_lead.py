"""epic project fields (target_date, lead)

Additive, back-compatible (V31, KAN-295): add two nullable columns to ``epic`` —
``target_date`` (an optional timestamptz target/ship date) and ``lead`` (an
optional free-text owner, varchar(255)). Both nullable with no server default, so
every existing epic reads NULL after the upgrade — no data backfill, no rewrite.
``downgrade`` drops them.

Revision ID: 36af407aaa9c
Revises: 0021_card_templates
Create Date: 2026-07-22 00:11:04.451130
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36af407aaa9c'
down_revision: Union[str, None] = '0021_card_templates'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('epic', sa.Column('target_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('epic', sa.Column('lead', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('epic', 'lead')
    op.drop_column('epic', 'target_date')
