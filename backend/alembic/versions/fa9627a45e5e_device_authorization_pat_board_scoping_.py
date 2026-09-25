"""device authorization + PAT board scoping (ADR 0024, KAN-1726)

Revision ID: fa9627a45e5e
Revises: 226484067569
Create Date: 2026-09-25 15:05:13.510167

Two new, purely additive tables backing the OAuth 2.1 authorization-server core
and RFC 8628 device flow (ADR 0024):

- ``device_authorization`` — one row per in-flight ``pandan auth login`` (or,
  later, ADR 0025's hosted-MCP OAuth flow), short-lived and single-use. See the
  model docstring in ``app/auth_models.py`` for the full field-by-field rationale.
- ``personal_access_token_board`` — the board-scoping allow-list a PAT minted
  through the device-flow consent screen may carry. **No rows for a given PAT
  means unrestricted** (today's behaviour, unchanged): every PAT minted before
  this migration, and every PAT minted via the existing Tokens UI after it, has
  zero rows here and keeps working exactly as it does today. Enforcement (one
  more rung in ``app.authz.authorize_board``) is KAN-1728, not this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa9627a45e5e"
down_revision: Union[str, None] = "226484067569"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_authorization",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("device_code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_code", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("user_id", GUID(), nullable=True),
        sa.Column(
            "requested_scope",
            sa.String(length=16),
            server_default="write",
            nullable=False,
        ),
        sa.Column(
            "requested_board_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True
        ),
        sa.Column("pat_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_device_authorization_status",
        ),
        sa.CheckConstraint(
            "requested_scope IN ('read', 'write')",
            name="ck_device_authorization_requested_scope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pat_id"], ["personal_access_token.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("user_code"),
    )
    op.create_index(
        "ix_device_authorization_device_code_hash",
        "device_authorization",
        ["device_code_hash"],
        unique=True,
    )

    op.create_table(
        "personal_access_token_board",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("personal_access_token_id", sa.BigInteger(), nullable=False),
        sa.Column("board_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["personal_access_token_id"],
            ["personal_access_token.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["board_id"], ["board.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "personal_access_token_id", "board_id", name="uq_personal_access_token_board"
        ),
    )
    op.create_index(
        "ix_personal_access_token_board_personal_access_token_id",
        "personal_access_token_board",
        ["personal_access_token_id"],
    )
    op.create_index(
        "ix_personal_access_token_board_board_id",
        "personal_access_token_board",
        ["board_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_personal_access_token_board_board_id",
        table_name="personal_access_token_board",
    )
    op.drop_index(
        "ix_personal_access_token_board_personal_access_token_id",
        table_name="personal_access_token_board",
    )
    op.drop_table("personal_access_token_board")

    op.drop_index(
        "ix_device_authorization_device_code_hash", table_name="device_authorization"
    )
    op.drop_table("device_authorization")
