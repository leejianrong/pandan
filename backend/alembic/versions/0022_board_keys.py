"""board keys — board.key, unique per owner (M8 V51, KAN-972; ADR 0020)

Revision ID: 0022_board_keys
Revises: a4f5050820ce
Create Date: 2026-08-25

Additive with a backfill (M8 R4.2). Three steps in one transaction:

1. add ``board.key`` nullable, so existing rows survive the ALTER;
2. backfill every row — derived from the board's name, deduplicated **per owner**;
3. tighten to NOT NULL and add ``uq_board_owner_key`` + the shape CHECK.

**The derivation is deliberately duplicated here rather than imported from
``app.board_keys``.** A migration is a historical record: it must keep producing the
same result years from now, and importing application code makes it a function of
whatever that code has since become. The two copies are allowed to drift *after*
this revision — what the app derives for a board created tomorrow is not this
migration's business, and no invariant depends on them agreeing. What does matter is
that both produce something the CHECK accepts, and a test pins that for the rows
this migration writes.

Per-owner deduplication is the subtle part: two boards owned by the same user whose
names both derive ``ENG`` cannot both be ``ENG``, so the second becomes ``ENG2``.
Boards with **no owner** (``owner_id IS NULL`` — the migrated default board is
unclaimed until someone logs in) are exempt: Postgres treats NULLs as distinct in a
unique index, so they can never collide and are left with the plain derived key.
"""
import re
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0022_board_keys'
down_revision: Union[str, None] = 'a4f5050820ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RESERVED = frozenset({"KAN", "EPIC"})
_MAX_LEN = 10


def _derive(name: str) -> str:
    """A frozen copy of ``app.board_keys.derive_board_key`` as of this revision."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", name or "").upper()
    alnum = re.sub(r"^[0-9]+", "", alnum)
    if not alnum:
        return "BRD"
    candidate = alnum[:3]
    return candidate if len(candidate) >= 2 else candidate.ljust(2, "X")


def _allocate(name: str, taken: set) -> str:
    """A frozen copy of ``app.board_keys.allocate_board_key`` as of this revision."""
    base = _derive(name)
    if base not in _RESERVED and base not in taken:
        return base
    suffix = 2
    while True:
        digits = str(suffix)
        candidate = f"{base[: _MAX_LEN - len(digits)]}{digits}"
        if candidate not in _RESERVED and candidate not in taken:
            return candidate
        suffix += 1


def upgrade() -> None:
    op.add_column('board', sa.Column('key', sa.String(length=10), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, name, owner_id FROM board ORDER BY id")
    ).fetchall()
    # One set of taken keys per owner. ``None`` (unclaimed) gets its own bucket that
    # is never consulted, since NULL owner_ids cannot collide under the constraint.
    taken_by_owner: dict = {}
    for row in rows:
        owner = row.owner_id
        if owner is None:
            key = _derive(row.name)
        else:
            taken = taken_by_owner.setdefault(owner, set())
            key = _allocate(row.name, taken)
            taken.add(key)
        bind.execute(
            sa.text("UPDATE board SET key = :key WHERE id = :id"),
            {"key": key, "id": row.id},
        )

    op.alter_column('board', 'key', existing_type=sa.String(length=10), nullable=False)
    op.create_unique_constraint('uq_board_owner_key', 'board', ['owner_id', 'key'])
    op.create_check_constraint(
        'ck_board_key_shape', 'board', "key ~ '^[A-Z][A-Z0-9]{1,9}$'"
    )


def downgrade() -> None:
    op.drop_constraint('ck_board_key_shape', 'board', type_='check')
    op.drop_constraint('uq_board_owner_key', 'board', type_='unique')
    op.drop_column('board', 'key')
