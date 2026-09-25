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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
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


class DeviceAuthorization(Base):
    """RFC 8628 Device Authorization Grant state (ADR 0024, KAN-1726) — the CLI's
    ``pandan auth login`` and, later, ADR 0025's hosted MCP clients.

    A row is created by ``POST /auth/device/code`` (the CLI, no auth) and polled
    by ``POST /auth/device/token`` (also the CLI, no auth — the device code itself
    is the secret) until it resolves. A **human**, authenticated by the existing
    GitHub cookie session, visits ``verification_uri_complete``, sees the consent
    screen (requested scope + board/workspace picker, pre-filled from
    ``requested_scope``/``requested_board_ids`` but editable), and approves or
    denies — that request stamps ``user_id`` + flips ``status``, and approval also
    mints the real ``personal_access_token`` row this table points at via
    ``pat_id``.

    **Short-lived and single-use** (ADR 0024): ``expires_at`` is set at creation
    (~10-15 min out, pinned by the endpoint that creates rows, not here) and
    ``redeemed_at`` is stamped the one time ``POST /auth/device/token`` returns a
    successful raw PAT — a second poll after that must not hand out the secret
    again, mirroring why a PAT itself is never re-displayed after minting.

    ``device_code`` is stored **hashed**, exactly like a PAT (HMAC-SHA256 keyed
    with ``AUTH_SECRET`` — the same :func:`app.tokens.hash_token`), since it is a
    bearer secret a network observer could otherwise replay. ``user_code`` is the
    short, human-typed fallback (``gh auth login``'s shape) and is stored as-is —
    it is not a secret on its own (the consent screen requires an authenticated
    human session to act on it), only a lookup key.
    """

    __tablename__ = "device_authorization"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_device_authorization_status",
        ),
        CheckConstraint(
            "requested_scope IN ('read', 'write')",
            name="ck_device_authorization_requested_scope",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # HMAC-SHA256 hex digest (64 chars), like PersonalAccessToken.token_hash —
    # unique + indexed for the polling endpoint's O(1) lookup.
    device_code_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    # The short code shown to the human as a fallback/confirmation (e.g.
    # "WDJB-MJHT"). Unique so the consent-screen lookup by code alone is
    # unambiguous; a human never has two live codes collide in practice given the
    # short (~10-15 min) lifetime, but uniqueness is enforced rather than assumed.
    user_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    # Set by the consent-screen approval; NULL until then. CASCADE: deleting the
    # approving user removes their completed device-authorization rows too,
    # mirroring PersonalAccessToken.user_id's own CASCADE.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    # The scope/board selection the CLI asked for when it created this row — the
    # consent screen pre-fills from these but the human may change either before
    # approving. NULL board_ids (not an empty array) means "no request made",
    # distinct from an empty array meaning "explicitly requested unrestricted" —
    # both pre-fill the same "no boards selected" consent-screen state, but the
    # distinction is preserved at rest since a future consumer may care.
    requested_scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="write"
    )
    requested_board_ids: Mapped[list[int] | None] = mapped_column(
        ARRAY(BigInteger), nullable=True
    )
    # The minted PAT, set only on approval. SET NULL (not CASCADE): revoking the
    # resulting PAT later should not silently rewrite this row's own history of
    # what was approved and when.
    pat_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("personal_access_token.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Stamped the one time `POST /auth/device/token` hands back a successful raw
    # PAT — makes the code single-use per ADR 0024, independent of `expires_at`.
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PersonalAccessTokenBoard(Base):
    """A board a :class:`PersonalAccessToken` is allowed to touch (ADR 0024,
    KAN-1726) — the board-scoping half of the device-flow consent screen.

    **No rows for a given PAT = unrestricted** (that PAT's owning user's full
    board access, exactly today's behaviour) — this table is purely additive, so
    every PAT minted before this slice, and every PAT minted via the existing
    Tokens UI after it, keeps working unchanged. Only a PAT minted through the
    device-flow consent screen with an explicit board selection gets rows here.
    ``app.authz.authorize_board`` checks this allow-list as one more rung, after
    the existing owner/board_member/workspace-default checks (KAN-1728).

    Mirrors :class:`app.models.BoardMember`'s shape (``UNIQUE`` pair, both FKs
    ``ON DELETE CASCADE``): revoking the PAT or deleting the board both cleanly
    remove the grant, and a board can appear in more than one PAT's allow-list.
    """

    __tablename__ = "personal_access_token_board"
    __table_args__ = (
        UniqueConstraint(
            "personal_access_token_id", "board_id", name="uq_personal_access_token_board"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    personal_access_token_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("personal_access_token.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OAuthClient(Base):
    """An OAuth client registered via RFC 7591 Dynamic Client Registration
    (ADR 0025/0026, KAN-1734) — ``POST /auth/register``.

    **DCR-registered clients only.** A client identifying itself via a Client ID
    Metadata Document (CIMD, the other mechanism KAN-1734 adds) is never a row
    here: its "registration" is just a URL it already hosts, fetched fresh (with
    a short in-memory cache) each time a request needs it — see
    ``app.oauth_client.resolve_client``, the one function both mechanisms funnel
    through so KAN-1735's authorize/token endpoints don't care which produced the
    client they're looking at. Storing a row per DCR registration is also
    *why* CIMD matters for a hosted, publicly-connectable MCP endpoint: DCR
    mints a fresh, permanent row for every distinct connecting app+deployment
    (Claude's own docs warn this can accumulate "very large numbers of
    registered clients" for a high-traffic connector), while CIMD needs none at
    all.

    **Public clients only, on purpose.** ``token_endpoint_auth_method`` is
    always ``"none"`` — this table has no secret-hash column — matching ADR
    0026's model of MCP/CLI clients as PKCE public clients, exactly like the
    existing device-flow PAT issuance. A confidential-client registration
    (``client_secret_post``/``basic``) is out of scope until a real use case
    asks for one.

    ``client_id`` is the opaque, DCR-minted identifier a client presents on
    every subsequent ``/auth/authorize``/``/auth/device/token`` call — random,
    not guessable, but **not itself a secret** (public clients have none): the
    security boundary is PKCE + exact ``redirect_uri`` matching, not the
    client_id's obscurity.
    """

    __tablename__ = "oauth_client"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # RFC 7591 requires at least one; MCP spec requires each be either localhost
    # or HTTPS (app.oauth_client.validate_redirect_uris enforces this at
    # registration time, not here — a CHECK can't express "every array element").
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
