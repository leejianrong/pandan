"""card.done_at — when a card last entered the done column (PAN-237)

Revision ID: c3d91a7e5b20
Revises: 8930ac7b370f
Create Date: 2026-10-30 12:00:00.000000

Additive and nullable. ``updated_at`` can't order the Done column by completion
because any later edit bumps it; ``done_at`` is stamped only on a column
transition into ``done`` and cleared on a move out. Backfilled from the latest
``activity`` row whose ``to_column`` is ``done``, falling back to ``updated_at``
for done cards with no such row (pre-V17 history).
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c3d91a7e5b20"
down_revision: Union[str, None] = "8930ac7b370f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("card", sa.Column("done_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE card SET done_at = COALESCE(
            (SELECT MAX(a.ts) FROM activity a
              WHERE a.entity_type = 'card' AND a.entity_id = card.id
                AND a.to_column = 'done'),
            card.updated_at)
        WHERE card."column" = 'done'
        """
    )


def downgrade() -> None:
    op.drop_column("card", "done_at")
