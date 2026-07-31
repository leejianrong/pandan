"""fastapi-users auth tables (Milestone 3 V6, ADR 0011).

fastapi-users ships its `User` / `OAuthAccount` / access-token tables as
SQLAlchemy **declarative mixins**. Mixing them into our existing ``app.db.Base``
(already a 2.0 ``DeclarativeBase``) puts them on **one shared metadata** with the
board `card`/`epic` tables — so a single Alembic pipeline autogenerates them all
(the models just need importing in ``alembic/env.py``). Spike-validated; see
`docs/milestone-3/spike-fastapi-users-sync.md`.

User ids are **UUID** (fastapi-users' ``*UUID`` mixins). These tables are read and
written **only** through the async engine (`get_async_session`); the sync engine
never touches them.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTableUUID,
    SQLAlchemyBaseUserTableUUID,
)
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """A linked OAuth identity (e.g. a GitHub account) for a ``User``."""


class User(SQLAlchemyBaseUserTableUUID, Base):
    """The human user identity (R1.4). GitHub is the only provider wired now, but
    the model is provider-agnostic — Google/email later is registration, not a
    schema change (A3)."""

    # Eager-loaded so the user's OAuth links are available without a lazy async
    # round-trip inside fastapi-users' sync-serialized responses.
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", lazy="joined"
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    """A server-side session record for the cookie ``DatabaseStrategy`` — logout
    deletes the row, making sessions revocable (D3). Distinct from the agent
    personal-access-tokens below."""

    # The mixin defaults to "accesstoken"; use the snake_case name the docs use.
    __tablename__ = "access_token"


class PersonalAccessToken(Base):
    """A self-serve **agent personal access token** (M3 V9, ADR 0014).

    A PAT lets a non-interactive agent authenticate as its **owning user** and
    inherit that user's board access (SHAPING D5) — the same principal + owner
    check humans use (ADR 0013), just a different front door. It **supersedes**
    V4's shared ``API_TOKENS`` env list (ADR 0010) with per-user, revocable,
    metadata-carrying tokens.

    **Unlike the other tables in this module, a PAT is read through the SYNC
    engine** (``get_db``): it is *our* table, looked up with a plain indexed
    ``SELECT`` on ``token_hash`` inside the sync board-auth path (ADR 0008), not
    fastapi-users' async store. Only the raw secret's **hash** is stored (R7.1):
    HMAC-SHA256 keyed with ``AUTH_SECRET`` (see ``app/tokens.py``) — a fast,
    *indexable* hash (the token is a 256-bit random secret, so slow password
    hashing buys nothing and would forbid a direct lookup)."""

    __tablename__ = "personal_access_token"

    # A read (observer) PAT may only make safe/READ calls; a write (operator) PAT
    # has the owning user's full board access. varchar + CHECK (not a native PG
    # enum) so a future scope needs no ``ALTER TYPE`` (mirrors ``card.column``).
    __table_args__ = (
        CheckConstraint(
            "scope IN ('read', 'write')", name="ck_personal_access_token_scope"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The owning user. CASCADE: deleting a user removes their tokens.
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # HMAC-SHA256 hex digest (64 chars); unique + indexed for O(1) auth lookup.
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    # A short, non-secret prefix of the raw token (e.g. ``pandan_pat_ab12``) shown
    # in the UI list so a user can tell their tokens apart. Never the full secret.
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    # ``read`` = observer (GET only), ``write`` = operator (full access). Default
    # ``write`` for back-compat: every PAT minted before V18 is a writer (R5.3).
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="write"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Stamped on each successful auth (a "last used" signal for the UI/audit).
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Optional expiry; NULL = never expires. Enforced at auth time.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
