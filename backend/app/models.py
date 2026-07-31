"""SQLAlchemy ORM models: Board, Card (a story on a board) and Epic (CONTEXT §3,
ADR 0006 + ADR 0009 + ADR 0012).

Three tables. A **board** owns a set of cards + epics (M3 V7, ADR 0012); a
**card** is a story on a board; an **epic** is a separate grouping a story can
belong to (ADR 0009). Key mechanisms:
- Each table's ``ticket_number`` is assigned atomically at INSERT from its own
  Postgres SEQUENCE via a server_default — ``'KAN-' || nextval('card_ticket_seq')``
  for cards, ``'EPIC-' || nextval('epic_ticket_seq')`` for epics — immutable, never
  reused, and independent (KAN-1 and EPIC-1 can coexist). Ticket sequences stay
  **global** across boards (D4) — no per-board prefixes. The ``KAN-``/``EPIC-``
  prefixes survived the ``simple-kanban`` → ``pandan`` rebrand **on purpose**
  (V40, KAN-423, ADR 0018 §"What is deliberately NOT renamed"): because the numbers
  are immutable and never reused there is no correct way to renumber history, so
  renaming the prefix would leave ``KAN-1…N`` beside ``PAN-N+1…`` on the board that
  *is* this project's record. A legacy prefix beats a split one — ``KAN`` is simply
  retconned as "kanban". Please don't "finish" the rename here.
- ``column`` is a plain ``varchar`` guarded by a CHECK constraint (not a native PG
  enum) so new column values need no ``ALTER TYPE`` migration (ADR 0008).
- Every card + epic belongs to exactly one board via a NOT NULL ``board_id`` FK
  (R2.3). ``ON DELETE CASCADE`` — deleting a board removes its cards + epics.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

VALID_COLUMNS = ("todo", "in_progress", "done")
# Card priority (M5 V11, KAN-244). A plain varchar guarded by a CHECK constraint
# (the same pattern as ``card.column`` — ADR 0008) so adding a priority value later
# needs no ``ALTER TYPE`` migration. ``none`` is the default (an unranked card).
# These values live in **three** places that must stay in sync: ``VALID_PRIORITIES``
# + the CHECK here, ``PriorityEnum`` (schemas), and the ``Priority`` type (api.ts).
VALID_PRIORITIES = ("none", "low", "medium", "high", "urgent")
# Board-membership roles (KAN-12), aligned with ADR 0013's ownership language.
# A plain varchar guarded by a CHECK constraint (the same pattern as ``card.column``)
# so adding a role later needs no ``ALTER TYPE`` migration.
VALID_ROLES = ("viewer", "editor", "owner")
# Activity-log vocabulary (KAN-17, M4 audit trail). Both are plain varchars guarded
# by CHECK constraints (the ``card.column`` pattern) so a new entity type or action
# needs no ``ALTER TYPE`` migration.
VALID_ACTIVITY_ENTITY_TYPES = ("card", "epic", "board")
# ``restored`` (KAN-20) is a distinct lifecycle event from ``deleted`` — a trashed
# card/epic brought back to life — so the audit feed can badge it on its own (rather
# than muddying it as an "updated"). Added to the CHECK via migration 0013.
# ``attention``/``resolved`` (M5 V13, KAN-246) are the human↔agent handoff events:
# an agent flags a card ``needs-human`` (attention) and a human clears it (resolved).
# Added to the CHECK via migration 0015.
# ``purged`` (KAN-239) is permanent destruction of a soft-deleted card/epic — a
# first-class audit event distinct from the ``deleted`` row the soft-delete already
# logged. Added to the CHECK via migration 0018.
VALID_ACTIVITY_ACTIONS = (
    "created",
    "updated",
    "deleted",
    "moved",
    "restored",
    "attention",
    "resolved",
    "purged",
)
# Notification kinds (V37, KAN-301) — the four events a human shouldn't miss. A
# plain varchar guarded by a CHECK constraint (the ``card.column`` pattern) so a
# new kind needs no ``ALTER TYPE`` migration. Kept in sync with the emit call-sites
# (``app.notifications`` callers) and ``NotificationKind`` (schemas).
VALID_NOTIFICATION_KINDS = ("needs_human", "blocked", "ci_failed", "assigned")


class Board(Base):
    """A board owns a set of cards + epics (M3 V7, ADR 0012). ``owner_id`` is the
    human who owns it (nullable — the migrated default board is unclaimed until a
    user takes it; board authorization on ownership arrives in V8)."""

    __tablename__ = "board"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # FK → user.id (a UUID). ON DELETE SET NULL: deleting a user unclaims their
    # boards rather than cascading away the boards + all their cards.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    # Auto-sync opt-in (KAN-43): the GitHub webhook only touches a board's cards
    # when ``autosync_enabled`` is true — per-board opt-in, default OFF, so the
    # webhook is a no-op for any board that hasn't turned it on. ``advance_to_done``
    # is a SEPARATE opt-in gating only the "move card to done on PR merge" action,
    # keeping the human in the loop for 'done' even with auto-sync otherwise on.
    autosync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    autosync_advance_to_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Outbound signed webhook opt-in (V38, KAN-302) — mirrors the autosync per-board
    # opt-in above. When ``outbound_webhook_enabled`` is true AND
    # ``outbound_webhook_url`` is set, creating a notification fires one HMAC-SHA256
    # signed ``POST`` to the URL — the *same* ``X-Hub-Signature-256: sha256=<hex>``
    # scheme this app *verifies* on the inbound GitHub webhook (symmetric; see
    # :mod:`app.webhook_signing`). The delivery is best-effort and fired **after** the
    # mutation's transaction commits (:mod:`app.outbound`), so a slow/failed POST never
    # rolls back or blocks the mutation. Default OFF, so it is a no-op until a board
    # owner turns it on. ``outbound_webhook_secret`` keys the signature and is
    # **write-only** — accepted on ``PATCH`` but never returned in a board read (like a
    # password); see ``BoardRead`` (which omits it) vs. ``BoardUpdate`` (which accepts it).
    outbound_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    outbound_webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    outbound_webhook_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BoardMember(Base):
    """A user's membership of a board with a role (KAN-12).

    Grants a user (other than the board owner) some access to a board. Roles are
    ``viewer`` / ``editor`` / ``owner`` (``VALID_ROLES``), guarded by a CHECK
    constraint in the ``card.column`` varchar style. A ``UNIQUE(board_id, user_id)``
    keeps a user's membership of a board singular.

    Both FKs ``ON DELETE CASCADE`` — deleting a board or a user removes the
    membership row (consistent with the app's hard-delete model). Role-based
    enforcement is live (KAN-13): ``app.authz.authorize_board`` maps a member's role
    to an :class:`app.authz.Access` level (viewer→READ, editor→WRITE, owner→MANAGE)
    and gates each route accordingly. List-visibility scoping (KAN-15) is separate.
    """

    __tablename__ = "board_member"
    __table_args__ = (
        UniqueConstraint("board_id", "user_id", name="uq_board_member"),
        CheckConstraint(
            "role IN ('viewer', 'editor', 'owner')",
            name="ck_board_member_role",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The member user (a UUID). CASCADE: deleting a user removes their memberships.
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Epic(Base):
    """A board-less grouping of stories (ADR 0009). No column/position/assignee/
    story_points — an epic is not a board card and is too large to estimate or
    own individually."""

    __tablename__ = "epic"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        # Assigned by the DB at INSERT; the sequence is created in the migration.
        # ``EPIC-`` is deliberately NOT rebranded — see the module docstring.
        server_default=text("'EPIC-' || nextval('epic_ticket_seq')"),
    )
    # The board this epic belongs to (M3 V7). NOT NULL; cascade on board delete.
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lightweight project fields (V31, KAN-295). ``target_date`` is an optional
    # target/ship date for the epic; ``lead`` is an optional free-text owner (a
    # person/agent handle, not an FK to ``user`` — an epic lead can be anyone). Both
    # nullable + additive: existing epics read NULL. ``lead`` is a plain varchar(255),
    # capped in the schema (``MAX_LEAD_LEN``) so an over-long value is a clean 422.
    target_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lead: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Soft-delete tombstone (KAN-19, R5.2). NULL = live; a timestamp = deleted.
    # DELETE sets this instead of removing the row; default reads filter it out
    # (``deleted_at IS NULL``). The FK from ``card.epic_id`` is intentionally left
    # intact on soft-delete (no detach) so a future restore (KAN-20) can re-link.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Cycle(Base):
    """A board-scoped, time-boxed iteration a story can belong to (V33, KAN-297).

    A cycle groups the stories worked in one iteration (a sprint / week). Unlike an
    epic it is **not** a first-class ticketed entity — it mirrors the flat,
    board-owned shape of :class:`SavedView` / :class:`CardTemplate` (no
    ``ticket_number``, no soft-delete): full CRUD-lite addressed under its board.

    ``board_id`` FK → ``board`` (``ON DELETE CASCADE``): a cycle belongs to a board
    and is hard-deleted with it (consistent with the app's hard-delete model).
    ``starts_on`` / ``ends_on`` are optional (nullable) iteration bounds. A story
    links to zero-or-one cycle via the nullable ``card.cycle_id`` FK, exactly
    mirroring ``card.epic_id`` (``ON DELETE SET NULL`` — deleting a cycle detaches
    its stories rather than blocking or cascading). The non-empty ``name`` rule is
    enforced by the Pydantic schema (:class:`app.schemas.CycleCreate`), not the table.
    """

    __tablename__ = "cycle"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional iteration bounds (nullable + additive). Timestamptz to match the rest
    # of the schema's date columns (e.g. epic.target_date, card.due_date).
    starts_on: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_on: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CardDependency(Base):
    """A directed blocker→blocked edge between two cards on the same board
    (KAN-28, the foundation for the dependency line).

    ``blocker_id`` blocks ``blocked_id`` — i.e. the blocked card is *blocked-by*
    the blocker. Both FKs ``ON DELETE CASCADE`` so deleting a card removes any edge
    it participates in (consistent with the app's hard-delete model). A
    ``UNIQUE(blocker_id, blocked_id)`` constraint keeps an edge singular. The
    same-board rule, self-link ban and cycle prevention are enforced in the router
    (``routers/cards.py``), not the schema — they can't be a table constraint.
    """

    __tablename__ = "card_dependency"
    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_card_dependency_edge"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    blocker_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("card.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blocked_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("card.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CardLink(Base):
    """A work-link on a card (KAN-32): a ``label`` (e.g. "PR", "branch", "CI") and
    a ``url`` pointing at the card's real work state, so the board reflects git
    reality without manual reconciliation.

    ``card_id`` FK ``ON DELETE CASCADE`` — deleting a card removes its links
    (consistent with the app's hard-delete model). The non-empty ``label``/``url``
    rule is enforced by the Pydantic schema (``schemas.LinkCreate``), not the table.
    """

    __tablename__ = "card_link"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("card.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CardComment(Base):
    """A human/agent-authored note on a card (KAN-33): intentional context — a
    decision, a handoff, "why this is blocked". **Distinct from Epic 4's SYSTEM
    activity log** (KAN-17..20, not yet built): those are machine-generated audit
    events; a ``CardComment`` is a deliberate note written by a real principal.

    ``card_id`` FK ``ON DELETE CASCADE`` — deleting a card removes its comments
    (consistent with the app's hard-delete model). ``author_id`` FK → ``user`` is
    nullable with ``ON DELETE SET NULL``, so deleting the author keeps the note
    (mirrors ``Board.owner_id``). The non-empty ``body`` rule is enforced by the
    Pydantic schema (``schemas.CommentCreate``), not the table.
    """

    __tablename__ = "card_comment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("card.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The authoring user (a UUID). Nullable + SET NULL so a deleted author leaves
    # the note in place, unattributed (mirrors Board.owner_id).
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Label(Base):
    """A board-scoped, colored tag a card can carry (M5 V11, KAN-244).

    Labels belong to a board (``board_id`` FK ``ON DELETE CASCADE`` — deleting a
    board removes its labels, consistent with the app's hard-delete model) and are
    attached to cards through the :class:`CardLabel` M:N join. ``name`` +
    ``color`` (an arbitrary string, typically a hex like ``#0ea5e9``) are the
    display fields; the non-empty ``name`` rule is enforced by the Pydantic schema
    (:class:`app.schemas.LabelCreate`), not the table.
    """

    __tablename__ = "label"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CardLabel(Base):
    """The M:N join between a card and a label (M5 V11, KAN-244).

    A composite primary key ``(card_id, label_id)`` keeps each (card, label) pair
    singular. Both FKs ``ON DELETE CASCADE`` so deleting a card **or** a label
    detaches the pairing (deleting a label removes it from every card that had it —
    the tested cascade). That a label belongs to the card's board is enforced in
    ``routers/cards.py`` (``_validate_labels``, 422), mirroring ``_validate_epic`` —
    it can't be a table constraint.
    """

    __tablename__ = "card_label"

    card_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("card.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("label.id", ondelete="CASCADE"), primary_key=True
    )


class Card(Base):
    __tablename__ = "card"
    __table_args__ = (
        CheckConstraint(
            "\"column\" IN ('todo', 'in_progress', 'done')",
            name="ck_card_column",
        ),
        # Priority (M5 V11) — varchar + CHECK, the ``column`` pattern (ADR 0008).
        CheckConstraint(
            "priority IN ('none', 'low', 'medium', 'high', 'urgent')",
            name="ck_card_priority",
        ),
        # GIN index over the full-text ``search_vector`` (M5 V15, KAN-248). The DDL
        # lives in ``0017_card_search_vector``; this declaration must mirror it
        # (name + ``postgresql_using='gin'``) so autogenerate sees no drift (KAN-307).
        Index("ix_card_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        # Assigned by the DB at INSERT; the sequence is created in the migration.
        # ``KAN-`` is deliberately NOT rebranded — see the module docstring.
        server_default=text("'KAN-' || nextval('card_ticket_seq')"),
    )
    # The board this story lives on (M3 V7). NOT NULL; cascade on board delete.
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    column: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional link to the story's parent epic. ON DELETE SET NULL so deleting an
    # epic detaches (rather than blocks or cascades) its stories — consistent with
    # the app's hard-delete model.
    epic_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("epic.id", ondelete="SET NULL"), nullable=True
    )
    # Optional link to the story's iteration/cycle (V33, KAN-297). Mirrors ``epic_id``
    # exactly: ON DELETE SET NULL so deleting a cycle detaches (rather than blocks or
    # cascades) its stories. Validated on POST/PATCH (same board, ``_validate_cycle``).
    cycle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cycle.id", ondelete="SET NULL"), nullable=True
    )
    story_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Priority (M5 V11, KAN-244). A varchar guarded by ``ck_card_priority`` (the
    # ``column`` pattern, ADR 0008). NOT NULL with a ``'none'`` server default so
    # every existing row stays valid after the additive migration (R5.3).
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'none'")
    )
    # Optional due date (M5 V11). NULL = no due date. The *overdue* signal
    # (due_date < now AND not done) is derived in the query API, not stored.
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Needs-human handoff flag (M5 V13, KAN-246). An agent sets ``needs_human`` when
    # it hits something only a human can settle (a decision, missing access, a stuck
    # PR) and leaves an optional ``attention_note`` describing the ask; a human then
    # clears the flag (``POST /cards/{id}/resolve``) once handled. NOT NULL with a
    # ``false`` server default so every existing row stays valid after the additive
    # migration (R5.3). The resolution *channel* is the existing comments feature
    # (KAN-33) — the agent discovers resolution via the cleared flag + a human note.
    needs_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    attention_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full-text search vector over title + description (M5 V15, KAN-248). A Postgres
    # ``GENERATED ALWAYS AS (...) STORED`` column (the migration owns the DDL) with a
    # GIN index, so it is maintained by the DB on every INSERT/UPDATE — no trigger,
    # no app-side upkeep, always consistent with the row. The title is weighted ``A``
    # and the description ``B`` via ``setweight`` so ``ts_rank`` scores a title hit
    # above a description-only hit (Postgres' default weights are A=1.0 > B=0.4).
    # ``deferred`` so it is never loaded into a normal card read (it isn't a CardRead
    # field) and only the ``q=`` search path references it (``@@
    # websearch_to_tsquery`` + ``ts_rank``). ``Computed`` marks it read-only, so
    # SQLAlchemy omits it from INSERT/UPDATE. Keep the expression here in step with
    # the migration DDL (``0017_card_search_vector``).
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        nullable=True,
        deferred=True,
    )
    # Soft-delete tombstone (KAN-19, R5.2). NULL = live; a timestamp = deleted.
    # DELETE sets this instead of removing the row; default reads (list/get, the
    # ordering helpers, autosync) filter it out (``deleted_at IS NULL``) so a
    # deleted card leaves no phantom in a column.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Activity(Base):
    """An append-only audit record of a board-domain mutation (KAN-17, M4 R5.1).

    One row per successful create / update / delete / move of a card, epic or
    board — the seed of the activity feed KAN-18 will read (this card is the model
    + write path only; there is no read API or UI here yet).

    Design notes:
    - ``board_id`` FK → ``board`` (``ON DELETE CASCADE``): an activity always
      belongs to a board, and a board's whole audit trail is hard-deleted with it
      (consistent with the app's hard-delete model). A **board deletion** event is
      therefore intentionally ephemeral — recorded, then cascaded away with the
      board it describes.
    - ``entity_id`` is a plain integer, **not** an FK — the referenced card/epic may
      already be deleted (that's precisely a ``deleted`` event), so the audit row
      must outlive it.
    - ``actor_user_id`` FK → ``user`` (``ON DELETE SET NULL``, nullable, mirroring
      ``Board.owner_id`` / ``CardComment.author_id``) records the acting principal —
      always a real ``User`` today (``app.authz.get_principal``), but kept nullable so
      deleting the user leaves the history in place, unattributed. ``actor_label`` is
      a denormalised human handle (the principal's email / an assignee string) so the
      feed reads without a user join even after the user is gone.
    - ``entity_type`` / ``action`` are varchars guarded by CHECK constraints (the
      ``card.column`` pattern) rather than native PG enums.
    """

    __tablename__ = "activity"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('card', 'epic', 'board')",
            name="ck_activity_entity_type",
        ),
        CheckConstraint(
            "action IN ('created', 'updated', 'deleted', 'moved', 'restored', "
            "'attention', 'resolved', 'purged')",
            name="ck_activity_action",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("board.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The acting principal (a UUID). Nullable + SET NULL so a deleted user leaves the
    # audit row in place (mirrors Board.owner_id / CardComment.author_id).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalised human handle for the actor (email / assignee string), so the feed
    # reads without a user join and survives the user's deletion.
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # The affected card/epic/board id. NOT an FK — the entity may already be deleted.
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured column transition for a "moved" activity (M5 V17, KAN-260). Recorded
    # at write time by the move/dispatch handlers so metrics.py reads the transition
    # from these fields instead of regexing ``summary``. Nullable + no CHECK: only
    # moves set them, and rows written before this migration are NULL (metrics.py
    # falls back to parsing the human ``summary`` for those). Values come from
    # ``VALID_COLUMNS`` at write time; a CHECK rejecting NULL would break back-compat.
    from_column: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_column: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SavedView(Base):
    """A named, persisted card query on a board (M5 V14, KAN-247).

    ``query`` is the structured filter+sort grammar (``schemas.CardQuery``) stored
    as JSON; replaying it as ``GET /cards`` query params reproduces the view's
    result set — the field names match the query params exactly, so a saved view is
    a saved query, not a snapshot of rows (they stay live).

    ``board_id`` FK → ``board`` (``ON DELETE CASCADE``): a saved view belongs to a
    board and is hard-deleted with it (consistent with the app's hard-delete model).
    The non-empty ``name`` + the grammar's validity are enforced by the Pydantic
    schema (``schemas.SavedViewCreate``), not the table.
    """

    __tablename__ = "saved_view"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The filter+sort grammar as JSON (``{}`` = no filters, all cards). Portable
    # ``JSON`` type (maps to Postgres ``json``); always written by the router from a
    # validated ``CardQuery``, so no server_default is needed.
    query: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CardTemplate(Base):
    """A named, reusable plan of cards on a board (M5 V19, KAN-252).

    ``cards`` is a JSON **list** of card payloads (each ``schemas.TemplateCardItem``:
    ``title`` + optional ``description``/``column``/``story_points``/``assignee``/
    ``epic_id``/``priority``/``due_date``/``label_ids``). Applying the template
    (``POST /boards/{id}/templates/{tid}/apply``) instantiates those payloads as real
    cards on the board in one transaction — the template holds a *recipe*, not the
    cards themselves (they are independent once created).

    ``board_id`` FK → ``board`` (``ON DELETE CASCADE``): a template belongs to a board
    and is hard-deleted with it (consistent with ``SavedView`` and the app's
    hard-delete model). The non-empty ``name`` + the item shapes are enforced by the
    Pydantic schema (``schemas.CardTemplateCreate``), not the table.
    """

    __tablename__ = "card_template"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The list of card payloads as JSON. Portable ``JSON`` type (maps to Postgres
    # ``json``); always written by the router from a validated ``CardTemplateCreate``.
    cards: Mapped[list] = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Notification(Base):
    """A poll/pull inbox item for a board owner (V37, KAN-301) — an event a human
    shouldn't miss: a card flagged ``needs_human``, a card newly ``blocked`` by a
    dependency, a linked PR's CI failing, or a card being assigned.

    Poll/pull only (ADR 0007 — no websockets, no real-time): rows are written at the
    board write path (:mod:`app.notifications`, the notification analogue of the
    activity logger) in the SAME sync transaction as the mutation, and read back via
    ``GET /api/v1/notifications``.

    Design notes:
    - ``user_id`` FK → ``user`` (``ON DELETE CASCADE``, NOT NULL): the **recipient**.
      The MVP recipient is always the **board owner** (``board.owner_id``) — a real
      ``User``, which makes owner-scoping trivial (you only ever see your own rows).
      A board with no owner never produces a notification (the emit helper skips it).
      Cascade: a deleted user's inbox goes with them (unlike ``Activity``, this is
      not history — it is a personal inbox).
    - ``board_id`` FK → ``board`` (``ON DELETE CASCADE``): the notification belongs to
      a board and is hard-deleted with it.
    - ``card_id`` FK → ``card`` (``ON DELETE SET NULL``, nullable): the card the event
      is about (all four kinds are card events today, but kept nullable + SET NULL so
      a purged card leaves the human-readable ``body`` — which names the ticket —
      standing rather than cascading the inbox item away).
    - ``kind`` is a varchar guarded by a CHECK constraint (the ``card.column``
      pattern) rather than a native PG enum.
    - ``read_at`` NULL = unread; a mark-read (``PATCH``) stamps it once (idempotent).
    """

    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('needs_human', 'blocked', 'ci_failed', 'assigned')",
            name="ck_notification_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The recipient (a UUID). NOT NULL — every notification has a real owner.
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The card the event is about. Nullable + SET NULL: a purged card leaves the row
    # (its ``body`` names the ticket) rather than cascading the inbox item away.
    card_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("card.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL = unread; stamped once when the owner marks it read.
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
