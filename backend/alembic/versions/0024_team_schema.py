"""team schema — team/team_member tables, board.team_id (M9 V65, KAN-1054; ADR 0021)

Revision ID: 0024_team_schema
Revises: 0023_board_seq
Create Date: 2026-09-01

Purely additive, **no backfill** (SHAPING R5, unlike M8's board-key migration):
every existing board simply gets ``team_id = NULL``, which is exactly today's
"personal board" meaning, unchanged — there is nothing to derive.

``team`` / ``team_member`` mirror ``board`` / ``board_member``'s own shape
(ADR 0021 §Shape) — a team has no ``owner_id`` (administered by whichever member
holds the ``owner`` role) and no ``key`` (no ticket-ref namespace of its own).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from fastapi_users_db_sqlalchemy.generics import GUID

from alembic import op

revision: str = "0024_team_schema"
down_revision: Union[str, None] = "0023_board_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "team_member",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "team_id",
            sa.BigInteger(),
            sa.ForeignKey("team.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor', 'owner')", name="ck_team_member_role"
        ),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )
    op.create_index("ix_team_member_team_id", "team_member", ["team_id"])

    op.add_column("board", sa.Column("team_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_board_team_id", "board", "team", ["team_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_board_team_id", "board", type_="foreignkey")
    op.drop_column("board", "team_id")
    op.drop_index("ix_team_member_team_id", table_name="team_member")
    op.drop_table("team_member")
    op.drop_table("team")
