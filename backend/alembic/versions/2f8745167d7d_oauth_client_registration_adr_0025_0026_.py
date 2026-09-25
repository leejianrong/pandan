"""oauth client registration (ADR 0025/0026, KAN-1734)

Revision ID: 2f8745167d7d
Revises: fa9627a45e5e
Create Date: 2026-09-25 18:52:04.599182

One new, purely additive table backing RFC 7591 Dynamic Client Registration
(``POST /auth/register``): ``oauth_client``, one row per DCR-registered client.
A client identifying itself via a Client ID Metadata Document (the other
mechanism this card adds) never gets a row here — its "registration" is just a
URL it already hosts, fetched fresh each time (``app/oauth_client.py``). See
the model docstring in ``app/auth_models.py`` for the full field-by-field
rationale, including why there is no secret-hash column (public clients only).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f8745167d7d"
down_revision: Union[str, None] = "fa9627a45e5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_client",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=True),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("client_id"),
    )
    op.create_index(
        "ix_oauth_client_client_id", "oauth_client", ["client_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_client_client_id", table_name="oauth_client")
    op.drop_table("oauth_client")
