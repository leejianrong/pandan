"""workspace rename — team/team_member -> workspace/workspace_member, board.team_id -> workspace_id (M9, ADR 0023, KAN-1721)

Revision ID: 226484067569
Revises: 6a252bfbdd11
Create Date: 2026-09-25 13:48:54.760624

Pure rename (ADR 0023): the M9 Team tier becomes Workspace end to end, before its
SPA view (V70, already shipped as "Teams" — see KAN-1725) gets its own rename. No
new entity, no schema redesign, no backfill — every existing row and FK survives
untouched via ``ALTER TABLE ... RENAME`` (table/column) and
``ALTER TABLE ... RENAME CONSTRAINT`` / ``ALTER INDEX ... RENAME`` (the
auto-generated + explicitly-named constraints from 0024_team_schema), never a
drop-and-recreate. Constraint/index renames are cosmetic — a foreign key tracks
its target by OID, not name, so ``fk_board_team_id`` kept working across the table
rename even before this migration explicitly renames it — but leaving a
``team``-named constraint on a ``workspace`` table would be exactly the kind of
half-finished rename ADR 0018 (the pandan rebrand) warns against.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "226484067569"
down_revision: Union[str, None] = "6a252bfbdd11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("team", "workspace")
    op.rename_table("team_member", "workspace_member")
    op.alter_column("workspace_member", "team_id", new_column_name="workspace_id")
    op.alter_column("board", "team_id", new_column_name="workspace_id")

    op.execute("ALTER TABLE workspace RENAME CONSTRAINT team_pkey TO workspace_pkey")
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT team_member_pkey TO workspace_member_pkey"
    )
    op.execute(
        "ALTER INDEX ix_team_member_team_id RENAME TO ix_workspace_member_workspace_id"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT uq_team_member TO uq_workspace_member"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT ck_team_member_role TO ck_workspace_member_role"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT team_member_team_id_fkey "
        "TO workspace_member_workspace_id_fkey"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT team_member_user_id_fkey "
        "TO workspace_member_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE board RENAME CONSTRAINT fk_board_team_id TO fk_board_workspace_id"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE board RENAME CONSTRAINT fk_board_workspace_id TO fk_board_team_id"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT workspace_member_user_id_fkey "
        "TO team_member_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT workspace_member_workspace_id_fkey "
        "TO team_member_team_id_fkey"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT ck_workspace_member_role TO ck_team_member_role"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT uq_workspace_member TO uq_team_member"
    )
    op.execute(
        "ALTER INDEX ix_workspace_member_workspace_id RENAME TO ix_team_member_team_id"
    )
    op.execute(
        "ALTER TABLE workspace_member RENAME CONSTRAINT workspace_member_pkey TO team_member_pkey"
    )
    op.execute("ALTER TABLE workspace RENAME CONSTRAINT workspace_pkey TO team_pkey")

    op.alter_column("board", "workspace_id", new_column_name="team_id")
    op.alter_column("workspace_member", "workspace_id", new_column_name="team_id")
    op.rename_table("workspace_member", "team_member")
    op.rename_table("workspace", "team")
