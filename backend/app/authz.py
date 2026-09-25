"""Board authorization — the one authz layer (M3 V8, ADR 0013; V10, ADR 0015).

V8 made the whole ``/api/v1`` surface **auth-required and owner-scoped**: every
board-scoped read and write resolves a **principal** and checks it against the
target board's owner (R3.4).

**V10 (ADR 0015)** retires the transitional ``API_TOKENS`` SERVICE bypass V8 left
in place. Now there is exactly one kind of principal — a real ``User`` — reached
two ways (BREADBOARD S5 "principal resolver"):

- **Human** — a valid ``kanbanauth`` cookie session → a ``User`` (via
  fastapi-users' ``current_optional_user``, on the async engine).
- **Agent** — a valid **personal access token** bearer → its owning ``User``
  (V9, ADR 0014; sync lookup on our own table).

Either way the principal is owner-gated: it may only touch boards whose
``owner_id`` is its id. No principal → **401**; a principal that doesn't own the
target board → **403**. The board CRUD stays on the sync engine (ADR 0008): the
sync board routes depend on the async ``current_optional_user`` — FastAPI resolves
the async sub-dependency for a sync endpoint (proven in V7's ``create_board``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from .auth import bearer_scheme
from .auth_models import PersonalAccessToken, PersonalAccessTokenBoard, User
from .db import get_db
from .models import Board, BoardMember, Workspace, WorkspaceMember
from .tokens import ACCEPTED_TOKEN_PREFIXES, hash_token
from .users import current_optional_user


class Access(IntEnum):
    """The capability a board-scoped action requires (KAN-13).

    Ordered so a ``>=`` comparison *is* the authorization check: a principal's
    effective access must be **at least** the level the action demands.

    - ``READ`` — viewer or above: GET/list/read of a board's cards/epics/members.
    - ``WRITE`` — editor or above: create/update/move/delete cards + epics.
    - ``MANAGE`` — owner only: board rename/delete + member management.
    """

    READ = 1
    WRITE = 2
    MANAGE = 3


# A board_member role maps to the highest :class:`Access` level it grants. The
# board OWNER (``board.owner_id``) is always treated as ``MANAGE`` regardless of
# any membership row.
_ROLE_ACCESS: dict[str, Access] = {
    "viewer": Access.READ,
    "editor": Access.WRITE,
    "owner": Access.MANAGE,
}


# HTTP methods that only read state. A ``read``-scoped PAT (V18, KAN-251) is
# allowed exactly these; anything else is a write and is denied (403).
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _resolve_pat(db: Session, raw: str) -> User | None:
    """Resolve a bearer value to its owning ``User`` if it is a valid, unexpired
    personal access token (M3 V9, ADR 0014), else ``None``.

    Fully **sync** (ADR 0008): our own table, an indexed lookup by hash. Stamps
    ``last_used_at`` on success. Revocation is deletion, so a revoked token simply
    isn't found.

    Stashes the PAT's ``scope`` (V18, KAN-251) on the returned user as a transient
    ``_pat_scope`` attribute so :func:`get_principal` can enforce observer/operator
    access — a human cookie principal has no such attribute (→ full access).

    Also stashes the PAT's board allow-list (ADR 0024, KAN-1726/1728) as a transient
    ``_pat_board_ids`` attribute — a ``frozenset`` of board ids **only when the PAT
    has at least one** :class:`PersonalAccessTokenBoard` **row**. No rows is
    unrestricted (today's behaviour, and every PAT minted before this slice or via
    the existing Tokens UI), so the attribute is simply absent then, mirroring how
    ``_pat_scope`` is absent for a cookie principal — ``getattr(..., None)`` reads
    as "no restriction" in both cases.
    """
    # Fast-path skip: only strings minted by us can match, so a stray bearer never
    # triggers a DB round-trip. The tuple includes prefixes retired by a rebrand
    # (V40, KAN-423) — a PAT issued as ``kanban_pat_…`` must keep working, and this
    # guard is the *only* place a prefix change could have invalidated one. The
    # actual verification below is still a hash lookup over the whole raw token.
    if not raw.startswith(ACCEPTED_TOKEN_PREFIXES):
        return None
    pat = db.scalars(
        select(PersonalAccessToken).where(
            PersonalAccessToken.token_hash == hash_token(raw)
        )
    ).first()
    if pat is None:
        return None
    if pat.expires_at is not None and pat.expires_at <= datetime.now(timezone.utc):
        return None
    pat.last_used_at = func.now()  # server-clock stamp; committed below
    scope = pat.scope
    board_ids = set(
        db.scalars(
            select(PersonalAccessTokenBoard.board_id).where(
                PersonalAccessTokenBoard.personal_access_token_id == pat.id
            )
        ).all()
    )
    db.commit()
    user = db.get(User, pat.user_id)
    if user is not None:
        # Non-mapped transient attributes; never flushed, carried per-request only.
        user._pat_scope = scope
        if board_ids:
            user._pat_board_ids = frozenset(board_ids)
    return user


def get_principal(
    request: Request,
    user: User | None = Depends(current_optional_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the request principal (always a real ``User``), or 401 if none.

    Precedence: a human **cookie session** wins; else a valid **personal access
    token** bearer → its owning ``User`` (V9, owner-gated like a human). Anything
    else is unauthenticated.

    Stashes the resolved id on ``request.state.principal_id`` so the access-log
    middleware (KAN-172, :mod:`app.observability`) can attribute the request to a
    user — the id only, never the token or cookie.
    """
    principal: User | None = user
    if principal is None and credentials is not None:
        principal = _resolve_pat(db, credentials.credentials)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Scoped tokens (V18, KAN-251): a ``read`` (observer) PAT may make only safe
    # reads. This is the ONE chokepoint every ``/api/v1`` route flows through
    # (board routes via ``authorize_board``, per-user routes like ``/tokens``
    # directly), so enforcing here denies *every* write — a PATCH/POST/DELETE/move
    # to a card, epic, board, member, label, view, or token — with 403 (never 401:
    # the caller is authenticated, just not authorized). All writes are unsafe
    # methods and all reads are GET, so the method test *is* the ``Access.WRITE``+
    # test. Cookie (human) principals and ``write``/legacy PATs have no ``_pat_scope``
    # or a ``write`` one → unaffected. (The GitHub webhook is signature-authed and
    # never reaches here.)
    if (
        getattr(principal, "_pat_scope", None) == "read"
        and request.method not in _SAFE_METHODS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this token is read-only (observer scope); writes are not permitted",
        )
    request.state.principal_id = principal.id
    return principal


# Every principal is now a real user, so per-user routes (e.g. token management)
# use ``get_principal`` directly; ``require_user`` remains as a self-documenting
# alias for routes that are inherently about the acting user.
require_user = get_principal


def _effective_access(db: Session, principal: User, board: Board) -> Access | None:
    """The principal's effective :class:`Access` on ``board``, or ``None`` if it
    has no access at all.

    Checked in order (M9 V68, KAN-1057; ADR 0021 §"Interaction with the existing
    board-role model", SHAPING D2):

    1. The board **OWNER** always has ``MANAGE`` (full access), regardless of any
       membership row (KAN-13).
    2. An explicit ``board_member`` row, if any — **the override**. Checked before
       the workspace default so an explicit share always wins, per D2.
    3. The board's **workspace default** (new): if ``board.workspace_id`` is set and the
       principal is a ``workspace_member`` of it, that membership's role maps through
       the *same* ``_ROLE_ACCESS`` table — one vocabulary, two places it can be
       granted (ADR 0021 §Shape). Only consulted when step 2 found nothing, so an
       explicit ``viewer`` share on a board still beats an ``editor`` workspace default,
       and vice versa — "explicit" wins on *presence*, not on being the higher
       grant.
    4. None of the above → ``None`` (→ 403).

    **Then, a PAT board allow-list (ADR 0024, KAN-1728) narrows whatever the above
    computed.** If the resolved principal is a PAT carrying a non-empty allow-list
    (``_pat_board_ids``, stashed by :func:`_resolve_pat`) and ``board.id`` isn't in
    it, the result is forced to ``None`` regardless of steps 1-4 — a *scope*
    restriction on the credential, not a grant, so it can only take access away,
    never add it, and it applies even to a board the PAT's own user owns. A human
    cookie principal, and a PAT with zero allow-list rows (every PAT minted before
    this slice, and every one minted via the Tokens UI after it), have no such
    attribute and are completely unaffected.
    """
    access = _board_role_access(db, principal, board)
    board_ids = getattr(principal, "_pat_board_ids", None)
    if board_ids is not None and board.id not in board_ids:
        return None
    return access


def _board_role_access(db: Session, principal: User, board: Board) -> Access | None:
    """Steps 1-4 of :func:`_effective_access`, unaffected by PAT scoping — the
    plain owner/board_member/workspace-default resolution."""
    if board.owner_id == principal.id:
        return Access.MANAGE
    role = db.scalar(
        select(BoardMember.role).where(
            BoardMember.board_id == board.id,
            BoardMember.user_id == principal.id,
        )
    )
    if role is not None:
        # An unknown role (should never happen — CHECK-constrained) grants nothing.
        return _ROLE_ACCESS.get(role)
    if board.workspace_id is not None:
        role = db.scalar(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == board.workspace_id,
                WorkspaceMember.user_id == principal.id,
            )
        )
        if role is not None:
            return _ROLE_ACCESS.get(role)
    return None


def authorize_board(
    db: Session, principal: User, board_id: int, require: Access = Access.READ
) -> Board:
    """Load ``board_id`` and assert the principal has at least ``require`` access,
    else raise. Returns the loaded board so callers can reuse it.

    Role-aware (KAN-13, ADR 0013 — the *one* authz layer, no ad-hoc checks): the
    board owner has full (``MANAGE``) access; other principals get the access their
    ``board_member`` role grants (viewer→READ, editor→WRITE, owner→MANAGE).

    - **404** if the board doesn't exist.
    - **403** if the principal has no access to it, or less than ``require``.
    """
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    access = _effective_access(db, principal, board)
    if access is None or access < require:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this board",
        )
    return board


def visible_board_ids(principal: User) -> Select:
    """A scalar subquery of the board ids this principal may see. Used to scope
    list endpoints so a caller only ever sees boards they have access to.

    A board is visible if the principal **owns** it, *or* is a ``board_member`` of
    it (KAN-15), *or* is a ``workspace_member`` of the workspace it belongs to (M9 V68,
    KAN-1057; ADR 0021 — the matching ``OR`` clause for :func:`_effective_access`'s
    new workspace-default rung) — the same set of boards :func:`authorize_board` grants
    at least ``READ`` on. Kept as a ``Select`` so callers can use it as an ``IN``
    subquery unchanged.

    **Then narrowed by a PAT board allow-list**, exactly like :func:`_effective_access`
    (ADR 0024, KAN-1728) — a scoped PAT's ``list_boards`` must not name a board a
    direct ``GET`` on it would 403 for. No-op for a human cookie principal or a PAT
    with zero allow-list rows.
    """
    base = or_(
        Board.owner_id == principal.id,
        Board.id.in_(
            select(BoardMember.board_id).where(BoardMember.user_id == principal.id)
        ),
        Board.id.in_(
            select(Board.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Board.workspace_id)
            .where(WorkspaceMember.user_id == principal.id)
        ),
    )
    board_ids = getattr(principal, "_pat_board_ids", None)
    if board_ids is not None:
        return select(Board.id).where(base, Board.id.in_(board_ids))
    return select(Board.id).where(base)


# --- workspaces (M9 V65-V66, KAN-1054/1055; ADR 0021) ----------------------------
#
# A workspace has no owner_id (ADR 0021 §Shape — administered by whichever member holds
# the `owner` role, not by one person by default), so unlike a board there is no
# owner-always-MANAGE rung: membership itself is the whole visibility rule, and
# holding the `owner` role (not "being *the* owner" — a workspace may have several) is
# the whole management rule. (The workspace-default-board-*access* rung — a workspace role
# granting access to a *board* — is `_effective_access` step 3 / `visible_board_ids`
# above, V68; what follows here gates the workspace's own membership, V66.)


def visible_workspace_ids(principal: User) -> Select:
    """A scalar subquery of the workspace ids this principal is a member of. Mirrors
    :func:`visible_board_ids`, but simpler: a workspace has no owner analogue, so
    membership is the entire rule."""
    return select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == principal.id)


def authorize_workspace(
    db: Session, principal: User, workspace_id: int, *, require_owner: bool = False
) -> Workspace:
    """Load ``workspace_id`` and assert the principal is a member of it, else raise.
    Returns the loaded workspace with the principal's role attached transiently as
    ``workspace.role`` (mirrors ``BoardRead.role``'s attachment pattern), so callers
    don't need a second query to answer "what's my role here".

    - **404** if the workspace doesn't exist.
    - **403** if the principal is not a member of it (any role).
    - **403** if ``require_owner`` and the principal's role isn't ``owner`` (V66,
      KAN-1055) — workspace-member management + rename/delete are owner-role gated,
      mirroring ``Access.MANAGE`` for a board, but checked against the
      ``workspace_member`` role directly since a workspace has no ``owner_id`` to compare.
    """
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    role = db.scalar(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == principal.id
        )
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this workspace",
        )
    if require_owner and role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only a workspace owner can do this",
        )
    workspace.role = role
    return workspace
