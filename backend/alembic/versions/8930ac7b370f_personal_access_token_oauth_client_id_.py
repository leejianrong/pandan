"""personal_access_token oauth_client_id (ADR 0026, KAN-1736)

Revision ID: 8930ac7b370f
Revises: 26ee51036593
Create Date: 2026-09-27 01:45:20.490151

Purely additive: a nullable ``oauth_client_id`` FK on ``personal_access_token``
naming which DCR-registered app minted it via the ``authorization_code``/
``refresh_token`` grants (ADR 0026) — ``NULL`` for every PAT minted before this
migration and for every self-serve Tokens-UI/device-flow PAT after it, per ADR
0026's own disposition. See the column's docstring in ``app/auth_models.py``.

The same unrelated autogenerate artefact noted in 26ee51036593 (a pre-existing
model/migration drift on `oauth_client`/`oauth_refresh_token`'s unique
constraints, already enforced at the DB level as unique indexes) showed up
again here and is again left alone rather than folded into this card.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8930ac7b370f"
down_revision: Union[str, None] = "26ee51036593"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personal_access_token", sa.Column("oauth_client_id", sa.BigInteger(), nullable=True)
    )
    op.create_index(
        "ix_personal_access_token_oauth_client_id",
        "personal_access_token",
        ["oauth_client_id"],
    )
    op.create_foreign_key(
        "fk_personal_access_token_oauth_client_id",
        "personal_access_token",
        "oauth_client",
        ["oauth_client_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_personal_access_token_oauth_client_id", "personal_access_token", type_="foreignkey"
    )
    op.drop_index(
        "ix_personal_access_token_oauth_client_id", table_name="personal_access_token"
    )
    op.drop_column("personal_access_token", "oauth_client_id")
