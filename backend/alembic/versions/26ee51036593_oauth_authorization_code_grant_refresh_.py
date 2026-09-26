"""oauth authorization_code grant, refresh tokens (ADR 0026, KAN-1735)

Revision ID: 26ee51036593
Revises: 2f8745167d7d
Create Date: 2026-09-26 18:41:54.532567

Two pieces, both purely additive:

- Extends ``device_authorization`` (rather than a parallel table — ADR 0026's own
  instruction, since the state it holds is the same pending/approved/consumed
  shape) so it can also back the ``authorization_code``+PKCE grant: makes
  ``device_code_hash``/``user_code`` nullable (an authorization-code-flow row
  populates neither), adds the new columns that flow needs, and a CHECK
  constraint pinning a row to exactly one kind. See the model docstring in
  ``app/auth_models.py`` for the full field-by-field rationale.
- Adds ``oauth_refresh_token``, one row per live (rotating, single-use) refresh
  token for an OAuth-issued ``personal_access_token``.

An unrelated autogenerate artefact is deliberately **not** included here: alembic
also detected a "removed unique constraint" on ``oauth_client.client_id`` — a
pre-existing mismatch between the model's ``unique=True`` (a metadata-level
``UniqueConstraint`` SQLAlchemy expects) and the prior migration's
``op.create_index(..., unique=True)`` (a unique *index*, which already enforces
uniqueness at the DB level, just not as a constraint object alembic can see).
Nothing about that drift is caused by or relevant to this card, so it's left
alone rather than folded into an unrelated migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "26ee51036593"
down_revision: Union[str, None] = "2f8745167d7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_refresh_token",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("personal_access_token_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["personal_access_token_id"], ["personal_access_token.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_oauth_refresh_token_token_hash",
        "oauth_refresh_token",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_oauth_refresh_token_personal_access_token_id",
        "oauth_refresh_token",
        ["personal_access_token_id"],
    )

    op.add_column(
        "device_authorization", sa.Column("client_id", sa.String(length=200), nullable=True)
    )
    op.add_column("device_authorization", sa.Column("redirect_uri", sa.String(), nullable=True))
    op.add_column(
        "device_authorization", sa.Column("code_challenge", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "device_authorization",
        sa.Column("code_challenge_method", sa.String(length=16), nullable=True),
    )
    op.add_column("device_authorization", sa.Column("resource", sa.String(), nullable=True))
    op.add_column(
        "device_authorization", sa.Column("code_hash", sa.String(length=64), nullable=True)
    )
    op.alter_column(
        "device_authorization",
        "device_code_hash",
        existing_type=sa.VARCHAR(length=64),
        nullable=True,
    )
    op.alter_column(
        "device_authorization", "user_code", existing_type=sa.VARCHAR(length=16), nullable=True
    )
    op.create_index(
        "ix_device_authorization_code_hash",
        "device_authorization",
        ["code_hash"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_device_authorization_kind",
        "device_authorization",
        "(device_code_hash IS NOT NULL AND user_code IS NOT NULL AND client_id IS NULL)"
        " OR (device_code_hash IS NULL AND user_code IS NULL"
        " AND client_id IS NOT NULL AND code_hash IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_device_authorization_kind", "device_authorization", type_="check")
    op.drop_index("ix_device_authorization_code_hash", table_name="device_authorization")
    op.alter_column(
        "device_authorization", "user_code", existing_type=sa.VARCHAR(length=16), nullable=False
    )
    op.alter_column(
        "device_authorization",
        "device_code_hash",
        existing_type=sa.VARCHAR(length=64),
        nullable=False,
    )
    op.drop_column("device_authorization", "code_hash")
    op.drop_column("device_authorization", "resource")
    op.drop_column("device_authorization", "code_challenge_method")
    op.drop_column("device_authorization", "code_challenge")
    op.drop_column("device_authorization", "redirect_uri")
    op.drop_column("device_authorization", "client_id")

    op.drop_index(
        "ix_oauth_refresh_token_personal_access_token_id", table_name="oauth_refresh_token"
    )
    op.drop_index("ix_oauth_refresh_token_token_hash", table_name="oauth_refresh_token")
    op.drop_table("oauth_refresh_token")
