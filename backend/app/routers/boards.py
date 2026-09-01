"""Boards endpoints (M3 V7, ADR 0012; **owner-gated in V8, ADR 0013**).

A board is a first-class entity owning a set of cards + epics. Full CRUD, mirroring
the flat structure of the cards/epics routers (API-first, ADR 0005). Mounted by
``main.py`` under ``/api/v1`` (e.g. ``/api/v1/boards``):

- GET    /boards       — list the caller's boards
- POST   /boards       — create a board (owner = the calling user)
- GET    /boards/{id}  — read one board (viewer or above)
- PATCH  /boards/{id}  — rename (owner only)
- DELETE /boards/{id}  — hard-delete; its cards + epics cascade away (owner only)
- GET    /boards/{id}/activity — the board's activity feed (viewer or above; KAN-18)

**Authorization (V8 + KAN-13, ADR 0013):** every route requires a principal (`401`
otherwise). Reads are ``Access.READ`` (viewer or above); rename/delete are
``Access.MANAGE`` (owner only). The list stays owner-scoped (member visibility is
KAN-15). See :mod:`app.authz`.

**Board keys (M8 V51, KAN-972; ADR 0020).** Every board carries a ``key`` — the
``ENG`` in a board-local ``ENG-14`` — unique **per owner**, not globally. Two status
codes, and which one you get depends on whether you named the key:

- **Omitted on create** → derived from the name, suffixed on collision, never an
  error (R1.4: creating a board must not block on naming).
- **Named** (on create or PATCH) → malformed or reserved is a ``422`` from the
  schema; already used by this owner is a ``409`` from here, because "taken" is a
  fact about the database and not about the request.

See :mod:`app.board_keys` for the shape, the reserved words and the derivation.

**Team linking (M9 V67, KAN-1056; ADR 0021).** ``team_id`` on create/update is
optional and 403s if the caller isn't a member of the named team (any role) —
:func:`_reject_non_member_team`. Omitted on create → ``NULL`` (a personal board,
today's unchanged default); a PATCH may set or explicitly clear it (``null``).
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..activity import record_activity
from ..auth_models import User
from ..authz import Access, authorize_board, get_principal, visible_board_ids
from ..board_keys import allocate_board_key
from ..db import get_db
from ..metrics import compute_metrics, move_target
from ..models import Activity, Board, BoardMember, Card, TeamMember
from ..ordering import next_position, renumber_column, select_next_ready_card
from ..pagination import NEXT_CURSOR_HEADER, decode_cursor, encode_cursor
from ..schemas import (
    ActivityRead,
    BoardCreate,
    BoardMetricsRead,
    BoardRead,
    BoardUpdate,
    CardRead,
    ColumnEnum,
    DispatchRequest,
    PriorityEnum,
)

router = APIRouter(prefix="/boards", tags=["boards"])

#: How many times ``create_board`` re-derives a key after losing the unique
#: constraint to a concurrent create. Three, because each retry reads the winning
#: key and suffixes past it, so the loop converges in one extra pass for any
#: realistic amount of contention — this is a bound on pathology, not a strategy.
_KEY_ALLOCATION_ATTEMPTS = 3


def resolve_board_id(db: Session, board_id: int | None) -> int:
    """Resolve the target board for a card/epic write.

    ``None`` → the default board (the earliest one), so pre-board clients keep
    working. A supplied id must reference an existing board (422). 409 if no board
    exists at all to default to. (Ownership of the resolved board is enforced
    separately by the caller via :func:`app.authz.authorize_board`.)
    """
    if board_id is None:
        default = db.scalars(select(Board.id).order_by(Board.id)).first()
        if default is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="no board exists; create one first",
            )
        return default
    if db.get(Board, board_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="board_id must reference an existing board",
        )
    return board_id


@router.get("", response_model=list[BoardRead])
def list_boards(
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[Board]:
    """List the boards the caller can see — owned **and** ones they're a member of
    (KAN-15). Each board carries the caller's effective ``role`` (owner → "owner",
    else the board_member role), attached transiently for the switcher's role
    badge (mirrors how ``MemberRead.email`` is attached in the members router)."""
    query = select(Board).order_by(Board.id).where(Board.id.in_(visible_board_ids(principal)))
    boards = list(db.scalars(query).all())
    # One lookup of the caller's member roles across all their boards.
    member_roles = dict(
        db.execute(
            select(BoardMember.board_id, BoardMember.role).where(
                BoardMember.user_id == principal.id
            )
        ).all()
    )
    for board in boards:
        board.role = (
            "owner" if board.owner_id == principal.id else member_roles.get(board.id)
        )
    _attach_owner_emails(db, boards)
    return boards


def _attach_owner_emails(db: Session, boards: Sequence[Board]) -> None:
    """Populate the transient ``owner_email`` on each board (V53, KAN-974).

    One query for the owners involved, so a list of N boards costs a single
    round-trip no matter how many distinct owners it spans (mirrors the card router's
    ``_attach_labels``). An unclaimed board (``owner_id`` NULL) gets ``None``.
    """
    owner_ids = {b.owner_id for b in boards if b.owner_id is not None}
    emails: dict = {}
    if owner_ids:
        emails = dict(
            db.execute(select(User.id, User.email).where(User.id.in_(owner_ids))).all()
        )
    for board in boards:
        board.owner_email = emails.get(board.owner_id)


def _owner_keys(
    db: Session, owner_id: uuid.UUID | None, *, excluding: int | None = None
) -> set[str]:
    """The board keys already used by one owner (V51, KAN-972).

    Scoped to the owner because that is the scope of the uniqueness constraint
    (SHAPING D2) — this must never be a global query, or two users could not each
    own an ``ENG``. ``excluding`` skips a board's own row so re-PATCHing a board to
    the key it already has is a no-op rather than a self-collision.
    """
    query = select(Board.key).where(Board.owner_id == owner_id)
    if excluding is not None:
        query = query.where(Board.id != excluding)
    return set(db.scalars(query).all())


def _reject_taken_key(
    db: Session,
    owner_id: uuid.UUID | None,
    key: str,
    *,
    excluding: int | None = None,
) -> None:
    """409 if ``key`` is already used by this owner. Only ever called for a key the
    caller *named*: a derived key resolves a collision by suffixing instead."""
    if key in _owner_keys(db, owner_id, excluding=excluding):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"board key {key!r} is already used by one of your boards",
        )


def _reject_non_member_team(db: Session, principal: User, team_id: int | None) -> None:
    """403 if ``team_id`` is set and the principal isn't a member of it — any role
    (M9 V67, KAN-1056; ADR 0021 §New surface). Uniform for an unknown team too (no
    row → no membership row → the same 403), so a create/update can't be used to
    probe which team ids exist — "you don't get to point a create at something you
    can't touch", the ``_validate_epic`` pattern, but 403 rather than 422 because
    the boundary here is membership, not shape."""
    if team_id is None:
        return
    is_member = db.scalar(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id, TeamMember.user_id == principal.id
        )
    )
    if is_member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you are not a member of that team",
        )


@router.post("", response_model=BoardRead, status_code=status.HTTP_201_CREATED)
def create_board(
    payload: BoardCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Board:
    # Owner comes from the calling user, never the request body.
    #
    # The key is the caller's if they named one (already checked for shape and
    # reservation by the schema; only "taken" is left to check), otherwise derived
    # from the name with a numeric suffix on collision. That asymmetry is the point:
    # asking for `ENG` and not getting it is worth an error, while not asking is
    # worth never failing.
    if payload.key is not None:
        _reject_taken_key(db, principal.id, payload.key)
    _reject_non_member_team(db, principal, payload.team_id)
    # Read-then-write is not atomic, so two concurrent creates can pick the same
    # derived key and one of them loses the unique constraint at COMMIT. Retry the
    # *derived* path — the second attempt reads the winner's key and suffixes past
    # it — and turn a lost race on a caller-named key into the 409 it would have
    # been a moment earlier, rather than a 500 from an IntegrityError.
    for attempt in range(_KEY_ALLOCATION_ATTEMPTS):
        key = payload.key or allocate_board_key(
            payload.name, _owner_keys(db, principal.id)
        )
        board = Board(
            name=payload.name, key=key, owner_id=principal.id, team_id=payload.team_id
        )
        db.add(board)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if payload.key is not None or attempt == _KEY_ALLOCATION_ATTEMPTS - 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"board key {key!r} is already used by one of your boards",
                ) from None
            continue
        break
    db.refresh(board)
    record_activity(
        db,
        principal,
        board_id=board.id,
        entity_type="board",
        entity_id=board.id,
        action="created",
        summary=f"created board {board.name}",
    )
    db.commit()
    _attach_owner_emails(db, [board])
    return board


@router.get("/{board_id}", response_model=BoardRead)
def get_board(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Board:
    board = authorize_board(db, principal, board_id, Access.READ)
    _attach_owner_emails(db, [board])
    return board


@router.patch("/{board_id}", response_model=BoardRead)
def update_board(
    board_id: int,
    payload: BoardUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Board:
    board = authorize_board(db, principal, board_id, Access.MANAGE)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and (data["name"] is None or not str(data["name"]).strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="name must not be empty",
        )
    if "key" in data:
        # Uniqueness is per owner, and the owner here is the board's — not
        # necessarily the caller's. `Access.MANAGE` means owner-only today, so the
        # two coincide; scoping to ``board.owner_id`` anyway keeps this correct if
        # MANAGE ever widens, rather than silently checking the wrong namespace.
        _reject_taken_key(db, board.owner_id, data["key"], excluding=board.id)
    if "team_id" in data:
        # The *caller's* membership gates a set (M9 V67) — an explicit ``null``
        # clears the link back to a personal board and needs no membership check.
        _reject_non_member_team(db, principal, data["team_id"])
    for field, value in data.items():
        setattr(board, field, value)
    record_activity(
        db,
        principal,
        board_id=board.id,
        entity_type="board",
        entity_id=board.id,
        action="updated",
        summary=f"updated board {board.name}",
    )
    db.commit()  # updated_at bumped server-side via onupdate
    db.refresh(board)
    _attach_owner_emails(db, [board])
    return board


@router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_board(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    board = authorize_board(db, principal, board_id, Access.MANAGE)
    # A board-deletion event is recorded for completeness, but it is keyed to the
    # board being deleted, whose ON DELETE CASCADE takes the whole audit trail —
    # including this row — with it. So the record is intentionally ephemeral: it is
    # written and then cascaded away in the same transaction (the board's history
    # dies with the board, by design).
    record_activity(
        db,
        principal,
        board_id=board.id,
        entity_type="board",
        entity_id=board.id,
        action="deleted",
        summary=f"deleted board {board.name}",
    )
    db.delete(board)
    db.commit()
    # Hard delete; the FK's ON DELETE CASCADE removes this board's cards + epics.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{board_id}/activity", response_model=list[ActivityRead])
def list_activity(
    board_id: int,
    response: Response,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    limit: int | None = Query(default=None, ge=1, le=200),
    cursor: str | None = None,
    actor: str | None = Query(
        default=None,
        description="filter to rows whose actor_label equals this (an email / agent handle)",
    ),
    action: str | None = Query(
        default=None,
        description="filter to rows with this action (created/updated/deleted/moved/restored/…)",
    ),
) -> list[Activity]:
    """The board's activity feed, **newest-first** (KAN-18, reading KAN-17's write
    path). One row per successful create / update / delete / move of a card, epic or
    board.

    **Member-scoped (``Access.READ`` — viewer or above):** the board owner and any
    member may read it; a non-member/non-owner gets ``403``, an unauthenticated
    caller ``401``, an unknown board ``404`` (via :func:`app.authz.authorize_board`).

    Optional filters (M5 V16, KAN-249), AND-ed with each other and with pagination:
    ``actor`` (exact match on ``actor_label`` — an actor's email / agent handle) and
    ``action`` (exact match on the action verb). Both narrow the feed so the
    awareness dashboard can slice it by *who* did *what*; the cursor still pages
    within the filtered result.

    Pagination mirrors ``GET /cards`` exactly: keyset over ``(ts, id)`` — but
    **descending**, since the feed is newest-first. Pass ``limit`` to cap the page;
    when a full page is returned the next page's opaque cursor rides the
    ``X-Next-Cursor`` response header (absent on the last page). Echo it back as
    ``cursor`` for the next request.
    """
    authorize_board(db, principal, board_id, Access.READ)
    query = (
        select(Activity)
        .where(Activity.board_id == board_id)
        .order_by(Activity.ts.desc(), Activity.id.desc())
    )
    if actor is not None:
        query = query.where(Activity.actor_label == actor)
    if action is not None:
        query = query.where(Activity.action == action)
    if cursor is not None:
        try:
            cursor_ts, cursor_id = decode_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid cursor",
            ) from exc
        # Descending keyset: the next page is everything ordered *before* the cursor.
        query = query.where(tuple_(Activity.ts, Activity.id) < (cursor_ts, cursor_id))
    if limit is not None:
        query = query.limit(limit)

    rows = list(db.scalars(query).all())

    # A full page implies there may be more — hand back the next cursor. A short
    # (or empty) page is the last one, so no header.
    if limit is not None and len(rows) == limit:
        last = rows[-1]
        response.headers[NEXT_CURSOR_HEADER] = encode_cursor(last.ts, last.id)
    return rows


# --- dispatch + fleet-safe claim (M5 V12, KAN-245) -------------------------
#
# Agent-operate core: pull the next ready-to-work card off a board. ``next``
# peeks; ``dispatch`` atomically claims. The selection (todo, not blocked, ordered
# priority DESC then position, one row) lives in :func:`app.ordering.select_next_ready_card`
# so both share exactly one definition of "ready" (reusing the ``blocked`` predicate
# from ``routers/cards.py``, not re-deriving it). ``dispatch`` uses ``FOR UPDATE SKIP
# LOCKED`` so a whole fleet can dispatch concurrently and never collide on a card.


@router.get(
    "/{board_id}/next",
    response_model=CardRead,
    responses={204: {"description": "no card is ready to dispatch"}},
)
def peek_next(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    label: int | None = None,
    priority: PriorityEnum | None = None,
):
    """**Peek** at the next ready-to-dispatch card on this board without claiming it
    (M5 V12, KAN-245) — the same selection as ``dispatch`` (next ``todo`` card not
    blocked by an open dependency, ordered ``priority DESC`` then ``position``) but
    read-only: no assignee change, no move, no lock. Returns the card, or **204 No
    Content** when nothing is ready.

    Optional filters (AND-ed): ``label`` (a label id) and ``priority`` (a *minimum*
    priority — only cards at that rank or above). ``Access.READ`` — a viewer may peek.
    """
    authorize_board(db, principal, board_id, Access.READ)
    card = select_next_ready_card(
        db,
        board_id,
        label=label,
        min_priority=priority.value if priority is not None else None,
        for_update=False,
    )
    if card is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # Attach dependency arrays / links / labels so the body is a full CardRead
    # (lazy import: routers/cards.py imports this module, so it can't be top-level).
    from .cards import _attach_one

    return _attach_one(db, card)


@router.post(
    "/{board_id}/dispatch",
    response_model=CardRead,
    responses={204: {"description": "no card is ready to dispatch"}},
)
def dispatch_card(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    payload: DispatchRequest | None = None,
):
    """**Dispatch** (atomically claim) the next ready-to-work card on this board in
    one transaction (M5 V12, KAN-245) — the agent-operate core.

    Selects the next ``todo`` card that is **not blocked** by an open dependency,
    ordered ``priority DESC`` (urgent first) then ``position ASC``, with ``FOR UPDATE
    SKIP LOCKED`` so concurrent dispatchers each lock-and-skip and never claim the
    same card (the fleet-safety mechanism — a DB row lock, not app locking; ADR
    0007). It then sets ``assignee`` (the body's ``assignee``, else the caller's
    identity), moves the card to ``in_progress`` (appended, with the source column
    renumbered), records a ``moved`` activity event, and returns the card. **204 No
    Content** when nothing is ready.

    Optional body filters (AND-ed with readiness): ``assignee`` (who to claim as),
    ``label`` (a label id), ``priority`` (a *minimum* priority). ``Access.WRITE`` —
    it mutates.
    """
    authorize_board(db, principal, board_id, Access.WRITE)
    req = payload or DispatchRequest()
    card = select_next_ready_card(
        db,
        board_id,
        label=req.label,
        min_priority=req.priority.value if req.priority is not None else None,
        for_update=True,
    )
    if card is None:
        # Nothing ready — release the (empty) FOR UPDATE scan and reply 204.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    assignee = req.assignee or principal.email
    source_column = card.column  # "todo"
    # Append to the end of in_progress. Computed before mutating card.column; with
    # autoflush off the count sees the DB (card still in todo), so it excludes this
    # very card and lands it cleanly at the end (mirrors move_card).
    new_position = next_position(db, board_id, ColumnEnum.in_progress.value)
    card.assignee = assignee
    card.column = ColumnEnum.in_progress.value
    card.position = new_position
    # Flush so the moved card's new column is visible to the source renumber query.
    db.flush()
    renumber_column(db, board_id, source_column)

    record_activity(
        db,
        principal,
        board_id=board_id,
        entity_type="card",
        entity_id=card.id,
        action="moved",
        summary=f"dispatched {card.ticket_number} to {assignee}",
        # Structured transition for metrics (KAN-260): a dispatch always claims a
        # todo card into in_progress.
        from_column=source_column,
        to_column=ColumnEnum.in_progress.value,
    )
    # One transaction: the SELECT ... FOR UPDATE SKIP LOCKED row lock is held right
    # through here and released on commit, so the claim is atomic + fleet-safe.
    db.commit()
    db.refresh(card)
    from .cards import _attach_one

    return _attach_one(db, card)


# --- fleet reporting / metrics (M5 V17, KAN-250) ---------------------------
#
# Derived flow metrics for a board — throughput, cycle time, aging WIP, and a
# per-assignee breakdown — computed entirely from the activity feed (KAN-17/18)
# plus current card state. **No new write path and no migration**: reporting
# rides data already recorded. The pure derivation (parse move summaries →
# compute the numbers) lives in :mod:`app.metrics` so it unit-tests without a DB.

_WINDOW_RE = re.compile(r"^(?P<n>\d+)(?P<unit>[dhm])$")
_WINDOW_UNITS = {"d": "days", "h": "hours", "m": "minutes"}


def _resolve_since(since: datetime | None, window: str | None, now: datetime) -> datetime | None:
    """Resolve the reporting period's lower bound.

    ``since`` (an explicit ISO-8601 timestamp) wins; else ``window`` (a relative
    span like ``7d`` / ``24h`` / ``30m``) is subtracted from ``now``; else ``None``
    (all time). A malformed ``window`` is a 422."""
    if since is not None:
        return since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    if window is not None:
        match = _WINDOW_RE.match(window)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="window must look like '7d', '24h' or '30m'",
            )
        delta = timedelta(**{_WINDOW_UNITS[match.group("unit")]: int(match.group("n"))})
        return now - delta
    return None


@router.get("/{board_id}/metrics", response_model=BoardMetricsRead)
def board_metrics(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    since: datetime | None = Query(
        default=None, description="ISO-8601 lower bound for the reporting period"
    ),
    window: str | None = Query(
        default=None,
        description="relative period, e.g. '7d' / '24h' / '30m' (ignored if 'since' is set)",
    ),
) -> BoardMetricsRead:
    """Derived fleet-reporting metrics for this board (M5 V17, KAN-250).

    Everything is computed on the fly from the activity feed + card timestamps —
    there is no stored metric and no migration. ``Access.READ`` (viewer or above);
    unknown board 404, no access 403, unauthenticated 401.

    The period is ``[since, now]``: pass ``since`` (an ISO-8601 timestamp) or the
    convenience ``window`` (``7d``/``24h``/``30m``); omit both for all time. Reports:

    - **throughput** — cards that reached ``done`` in the period;
    - **cycle_time** — first ``in_progress`` → ``done`` (avg/median/p90 seconds);
    - **aging_wip** — how long each currently-``in_progress`` card has sat there;
    - **by_assignee** — completed + open WIP per assignee.

    A quiet/empty board returns zeros and nulls (never an error).
    """
    authorize_board(db, principal, board_id, Access.READ)
    now = datetime.now(timezone.utc)
    period_since = _resolve_since(since, window, now)

    # Column transitions from the "moved" activity rows. Read the structured
    # from_column/to_column recorded at write time (KAN-260); move_target falls back
    # to parsing the summary for legacy rows predating that migration.
    move_rows = db.execute(
        select(
            Activity.entity_id,
            Activity.from_column,
            Activity.to_column,
            Activity.summary,
            Activity.ts,
        ).where(
            Activity.board_id == board_id,
            Activity.entity_type == "card",
            Activity.action == "moved",
        )
    ).all()
    transitions = [
        (entity_id, target, ts)
        for entity_id, from_column, to_column, summary, ts in move_rows
        if (target := move_target(from_column, to_column, summary)) is not None
    ]

    # Current card state (all rows, incl. soft-deleted, for assignee lookup; the
    # metrics themselves exclude deleted cards from live WIP).
    card_rows = db.execute(
        select(
            Card.id,
            Card.ticket_number,
            Card.column,
            Card.assignee,
            Card.created_at,
            Card.deleted_at,
        ).where(Card.board_id == board_id)
    ).all()
    cards = [
        {
            "id": row.id,
            "ticket_number": row.ticket_number,
            "column": row.column,
            "assignee": row.assignee,
            "created_at": row.created_at,
            "deleted": row.deleted_at is not None,
        }
        for row in card_rows
    ]

    metrics = compute_metrics(transitions, cards, now=now, since=period_since)
    return BoardMetricsRead(
        board_id=board_id,
        generated_at=now,
        since=period_since,
        until=now,
        **metrics,
    )
