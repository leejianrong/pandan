"""Cycle (iteration) endpoints (V33, KAN-297; owner/member-gated, ADR 0013).

A cycle is a board-scoped, time-boxed iteration a story can belong to (via the
nullable ``card.cycle_id`` — set through ``PATCH /cards/{id}``). Full CRUD-lite,
mirroring the flat structure of the saved-views / card-templates routers
(API-first, ADR 0005). Mounted by ``main.py`` under ``/api/v1``:

- GET    /boards/{board_id}/cycles                    — list a board's cycles (viewer+)
- POST   /boards/{board_id}/cycles                    — create a cycle (editor+)
- POST   /boards/{board_id}/cycles/generate           — generate a run of cycles (editor+, M8 V58)
- GET    /boards/{board_id}/cycles/{cycle_id}         — read one cycle (viewer+)
- GET    /boards/{board_id}/cycles/{cycle_id}/metrics — burndown/velocity (viewer+, V34)
- PATCH  /boards/{board_id}/cycles/{cycle_id}         — edit a cycle (editor+, V55)
- DELETE /boards/{board_id}/cycles/{cycle_id}         — delete a cycle (editor+)
- POST   /boards/{board_id}/cycles/{cycle_id}/close   — close + rollover (editor+, M8 V59)

Every cycle is addressed under its board (``/boards/{id}/cycles``); the board
gates access via ``authorize_board`` (READ to list/get, WRITE to create/delete). A
cycle whose ``board_id`` doesn't match the path board **404s** — so a cross-board
id is never reachable through another board you happen to own. Deleting a cycle
detaches its stories (``card.cycle_id`` is ``ON DELETE SET NULL``), it never
cascades them away.

**PATCH arrived late (V55, KAN-976)**, exactly as it did for labels in V61: cycles
shipped in V33 with create/list/get/metrics/delete and no edit, so a mistyped date
or name could only be fixed by delete-and-recreate — which detaches every card in
the cycle. This is the non-destructive edit; membership is untouched by it.

**A cycle can belong to zero-or-one planning interval (M8 V57, KAN-978)** — the
grouping one level above the cycle, via the nullable ``Cycle.planning_interval_id``
(``CycleCreate``/``CycleUpdate``, validated against the same board by
``_validate_planning_interval``). ``list_cycles`` gains a plain
``planning_interval_id`` filter for browsing membership from the cycle side; the
rollup itself lives on the planning interval, at
``GET /boards/{id}/planning-intervals/{pi_id}/metrics``
(``routers/planning_intervals.py``), which reuses this module's
``cycle_metrics_dict`` per member cycle rather than duplicating the burndown
computation.

**``generate_cycles`` (M8 V58, KAN-979)** is pure convenience over
``create_cycle`` — "two weeks per sprint, six sprints" as one call instead of
six. It adds no new state and needs no migration: it builds ``count`` back-to-back
``[starts_on, ends_on)`` windows from ``start`` + ``length_days`` and inserts them
in one transaction, all-or-nothing (mirroring ``apply_template``'s batch
semantics) — any generated window overlapping an existing dated cycle on the
board rejects the whole batch with a ``422`` naming the collision. **CLI-only,
declined for MCP**: an agent that wants N cycles can already call ``create_cycle``
N times, so this doesn't spend against the frozen ADR 0019 surface.

**``close_cycle`` (M8 V59, KAN-980, SHAPING D9)** is the opposite of V58's
convenience-and-cheap: rollover is a deliberate verb, never something that fires
on the cycle's own ``ends_on`` date, because auto-rollover would silently rewrite
history ``cycle_metrics`` has already reported. Closing stamps ``closed_at`` and
**freezes** the committed/completed snapshot into ``frozen_committed`` /
``frozen_completed`` — captured from exactly the live query
``cycle_metrics_dict`` runs for an open cycle — so a card leaving the cycle on
rollover afterward cannot change numbers already reported (``cycle_metrics_dict``
branches on ``closed_at`` to serve them back with an empty ``burndown``, see
below). Every card still in the cycle and not ``done`` then moves to
``payload.rollover_to`` (another open cycle on the same board) or the backlog
(``null``) via the same ``_apply_card_update`` a `PATCH /cards/{id}` uses, so each
move is recorded as an ordinary ``updated`` activity row. Closing an
already-closed cycle is ``409``, not a silent no-op. **This is the one write op
added to the frozen MCP surface in this batch** (an ADR 0019 amendment,
56 → 57) — unlike ``update_cycle`` or planning-interval setup, ending a cycle and
rolling over unfinished work is exactly the loop a short, agent-paced cycle needs
to run on its own.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import Access, authorize_board, get_principal
from ..db import get_db
from ..metrics import compute_cycle_metrics, move_target
from ..models import Activity, Card, Cycle, PlanningInterval
from ..schemas import (
    CycleClose,
    CycleCloseRead,
    CycleCreate,
    CycleGenerate,
    CycleMetricsRead,
    CycleRead,
    CycleUpdate,
)
from .cards import _apply_card_update

router = APIRouter(tags=["cycles"])


def _get_cycle_or_404(db: Session, board_id: int, cycle_id: int) -> Cycle:
    """Load cycle ``cycle_id`` **on ``board_id``**; 404 if it doesn't exist or
    belongs to a different board (so a cross-board id is never reachable)."""
    cycle = db.get(Cycle, cycle_id)
    if cycle is None or cycle.board_id != board_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found"
        )
    return cycle


def _validate_planning_interval(
    db: Session, planning_interval_id: int | None, board_id: int
) -> None:
    """A cycle's ``planning_interval_id`` (if set) must reference an existing
    planning interval (M8 V57, KAN-978) **on the same board** as the cycle (no
    cross-board links); 422 otherwise. Mirrors ``_validate_epic``/
    ``_validate_cycle`` in ``routers/cards.py``."""
    if planning_interval_id is None:
        return
    pi = db.get(PlanningInterval, planning_interval_id)
    if pi is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="planning_interval_id must reference an existing planning interval",
        )
    if pi.board_id != board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="planning interval must belong to the same board as the cycle",
        )


@router.get("/boards/{board_id}/cycles", response_model=list[CycleRead])
def list_cycles(
    board_id: int,
    planning_interval_id: int | None = None,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[Cycle]:
    """List a board's cycles, oldest-first (creation order). Viewer or above; a
    board you can't see is a ``403`` (unknown board ``404``). Optional
    ``planning_interval_id`` narrows to the cycles that belong to one planning
    interval (M8 V57, KAN-978) — an ordinary equality filter, browsing membership
    from the cycle side."""
    authorize_board(db, principal, board_id, Access.READ)
    stmt = select(Cycle).where(Cycle.board_id == board_id)
    if planning_interval_id is not None:
        stmt = stmt.where(Cycle.planning_interval_id == planning_interval_id)
    return list(db.scalars(stmt.order_by(Cycle.id)).all())


@router.post(
    "/boards/{board_id}/cycles",
    response_model=CycleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_cycle(
    board_id: int,
    payload: CycleCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Cycle:
    """Create a cycle on a board (editor or above). ``name`` + optional
    ``starts_on`` / ``ends_on`` / ``planning_interval_id`` come from the body;
    the board from the path."""
    authorize_board(db, principal, board_id, Access.WRITE)
    _validate_planning_interval(db, payload.planning_interval_id, board_id)
    cycle = Cycle(
        board_id=board_id,
        name=payload.name,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        planning_interval_id=payload.planning_interval_id,
    )
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return cycle


@router.post(
    "/boards/{board_id}/cycles/generate",
    response_model=list[CycleRead],
    status_code=status.HTTP_201_CREATED,
)
def generate_cycles(
    board_id: int,
    payload: CycleGenerate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[Cycle]:
    """Generate ``count`` back-to-back cycles in one call (editor or above,
    M8 V58, KAN-979) — pure convenience over :func:`create_cycle`, no new state.

    Each cycle's ``[starts_on, ends_on)`` window is ``payload.start`` (midnight
    UTC) plus ``n * length_days`` for ``n`` in ``0..count-1``; ``name_template``
    interpolates 1-indexed ``{n}`` (``"Sprint {n}"`` → ``Sprint 1``, ``Sprint
    2``, ...). Generated windows are contiguous by construction and never overlap
    each other, but **every** window is checked against every existing (dated)
    cycle on the board; the first collision is a ``422`` naming the colliding
    cycle, and **the whole batch is rejected** — mirroring ``apply_template``'s
    all-or-nothing semantics — rather than partially created.
    """
    authorize_board(db, principal, board_id, Access.WRITE)
    _validate_planning_interval(db, payload.planning_interval_id, board_id)

    length = timedelta(days=payload.length_days)
    batch_start = datetime.combine(payload.start, time.min, tzinfo=timezone.utc)
    windows: list[tuple[datetime, datetime, str]] = []
    for n in range(1, payload.count + 1):
        try:
            name = payload.name_template.format(n=n)
        except (KeyError, IndexError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"invalid name_template: {exc}",
            ) from exc
        starts_on = batch_start + length * (n - 1)
        ends_on = starts_on + length
        windows.append((starts_on, ends_on, name))

    existing = list(
        db.scalars(
            select(Cycle).where(
                Cycle.board_id == board_id,
                Cycle.starts_on.is_not(None),
                Cycle.ends_on.is_not(None),
            )
        ).all()
    )
    for starts_on, ends_on, name in windows:
        for cycle in existing:
            if starts_on < cycle.ends_on and cycle.starts_on < ends_on:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"generated cycle {name!r} ({starts_on.date()}"
                        f"–{ends_on.date()}) overlaps existing cycle "
                        f"{cycle.id} {cycle.name!r} ({cycle.starts_on.date()}"
                        f"–{cycle.ends_on.date()})"
                    ),
                )

    created = [
        Cycle(
            board_id=board_id,
            name=name,
            starts_on=starts_on,
            ends_on=ends_on,
            planning_interval_id=payload.planning_interval_id,
        )
        for starts_on, ends_on, name in windows
    ]
    db.add_all(created)
    db.commit()
    for cycle in created:
        db.refresh(cycle)
    return created


@router.get("/boards/{board_id}/cycles/{cycle_id}", response_model=CycleRead)
def get_cycle(
    board_id: int,
    cycle_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Cycle:
    """Read one cycle (viewer or above). **404** if it doesn't exist or isn't on
    this board; **403** if the board isn't yours."""
    authorize_board(db, principal, board_id, Access.READ)
    return _get_cycle_or_404(db, board_id, cycle_id)


def cycle_metrics_dict(
    db: Session, board_id: int, cycle: Cycle, *, now: datetime
) -> dict[str, Any]:
    """Compute one cycle's committed/completed/velocity/unit/burndown dict (V34,
    KAN-298) — the shared body behind ``GET .../cycles/{id}/metrics`` **and** the
    planning-interval rollup (M8 V57, KAN-978's ``routers/planning_intervals.py``
    reuses this per member cycle rather than recomputing burndown logic itself).

    Reuses the V17 metrics engine's derivation style: everything is computed on
    the fly from the cycle's current card state (story points + column) plus the
    ``done`` transition times in the activity feed — no stored metric, no
    migration. Callers are responsible for authz + loading ``cycle``.

    **Closed cycles are the one exception (M8 V59, KAN-980)**: once
    ``cycle.closed_at`` is set, ``committed``/``completed``/``velocity`` come
    straight from the ``frozen_committed``/``frozen_completed`` snapshot captured
    at close time — no query — so a card rolling out of the cycle afterward can't
    change the numbers already reported. ``burndown`` is empty for a closed cycle:
    the day-by-day series is derived from the committed roster's done-times, and
    that roster no longer matches reality once rollover moves cards out; freezing
    an accurate historical burndown too is real scope (a full timeseries snapshot,
    not two numbers) and isn't asked for here, so it's declined rather than
    silently attempted (SLICES.md's V59 entry).
    """
    if cycle.closed_at is not None:
        committed = cycle.frozen_committed or {"count": 0, "points": 0}
        completed = cycle.frozen_completed or {"count": 0, "points": 0}
        return {
            "committed": committed,
            "completed": completed,
            "velocity": completed.get("points", 0),
            "unit": "points" if committed.get("points", 0) > 0 else "count",
            "burndown": [],
        }
    # The cycle's live stories (exclude soft-deleted — they're not committed work).
    card_rows = db.execute(
        select(Card.id, Card.story_points, Card.column).where(
            Card.cycle_id == cycle.id, Card.deleted_at.is_(None)
        )
    ).all()
    cards = [
        {"id": row.id, "story_points": row.story_points, "column": row.column}
        for row in card_rows
    ]

    # First ``done`` transition per card, recovered from the activity feed exactly
    # like the board metrics (structured columns, summary fallback for legacy rows).
    done_times: dict[int, datetime] = {}
    if cards:
        card_ids = [c["id"] for c in cards]
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
                Activity.entity_id.in_(card_ids),
            )
        ).all()
        for entity_id, from_column, to_column, summary, ts in move_rows:
            if move_target(from_column, to_column, summary) != "done":
                continue
            if entity_id not in done_times or ts < done_times[entity_id]:
                done_times[entity_id] = ts

    return compute_cycle_metrics(
        cards,
        done_times,
        starts_on=cycle.starts_on,
        ends_on=cycle.ends_on,
        now=now,
    )


@router.get(
    "/boards/{board_id}/cycles/{cycle_id}/metrics", response_model=CycleMetricsRead
)
def cycle_metrics(
    board_id: int,
    cycle_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> CycleMetricsRead:
    """Derived burndown / velocity metrics for one cycle (V34, KAN-298).

    ``Access.READ`` (viewer or above); **404** if the cycle doesn't exist or isn't
    on this board (a cross-board id is never reachable), **403** if the board
    isn't yours, **401** unauthenticated.

    Reports **committed** (stories + points assigned to the cycle), **completed**
    (the subset currently ``done``), **velocity** (completed points) and a per-day
    **burndown** over the cycle's ``starts_on``..``ends_on`` window. A cycle with
    no dates burns down to an empty series (the totals still compute); an empty
    cycle returns zeros.
    """
    authorize_board(db, principal, board_id, Access.READ)
    cycle = _get_cycle_or_404(db, board_id, cycle_id)
    now = datetime.now(timezone.utc)
    metrics = cycle_metrics_dict(db, board_id, cycle, now=now)
    return CycleMetricsRead(
        board_id=board_id,
        cycle_id=cycle_id,
        generated_at=now,
        starts_on=cycle.starts_on,
        ends_on=cycle.ends_on,
        **metrics,
    )


@router.patch("/boards/{board_id}/cycles/{cycle_id}", response_model=CycleRead)
def update_cycle(
    board_id: int,
    cycle_id: int,
    payload: CycleUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Cycle:
    """Rename a cycle and/or correct its bounds (editor or above on its board).

    Only the fields actually sent are applied (``exclude_unset``), so a PATCH
    carrying just ``ends_on`` leaves the name alone. An empty body is a no-op that
    returns the cycle unchanged rather than an error — a PATCH with nothing to
    change has already achieved it.

    ``starts_on``/``ends_on`` accept an explicit ``null`` to *unschedule* the cycle;
    ``name`` does not (see :class:`~app.schemas.CycleUpdate`). **404** if the cycle
    doesn't exist or isn't on this board — the same ``_get_cycle_or_404`` every other
    route here uses, so a cross-board id stays unreachable through a board you own;
    **403** if the board isn't yours.

    **The cycle keeps its cards.** That is the whole point of the endpoint: the only
    previous way to fix a cycle was to delete it, and deleting detaches every story
    assigned to it. Nothing here touches ``card.cycle_id``.
    """
    authorize_board(db, principal, board_id, Access.WRITE)
    cycle = _get_cycle_or_404(db, board_id, cycle_id)
    fields = payload.model_dump(exclude_unset=True)
    if "planning_interval_id" in fields:
        _validate_planning_interval(db, fields["planning_interval_id"], board_id)
    for field, value in fields.items():
        setattr(cycle, field, value)
    db.commit()
    db.refresh(cycle)
    return cycle


@router.delete(
    "/boards/{board_id}/cycles/{cycle_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_cycle(
    board_id: int,
    cycle_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Delete a cycle (editor or above on its board). **404** if no such cycle on
    this board; **403** if the board isn't yours. Any stories still assigned to it
    are detached (``card.cycle_id`` → NULL), not deleted."""
    authorize_board(db, principal, board_id, Access.WRITE)
    cycle = _get_cycle_or_404(db, board_id, cycle_id)
    db.delete(cycle)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/boards/{board_id}/cycles/{cycle_id}/close", response_model=CycleCloseRead
)
def close_cycle(
    board_id: int,
    cycle_id: int,
    payload: CycleClose,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> CycleCloseRead:
    """Close a cycle explicitly (editor or above, M8 V59, KAN-980, SHAPING D9) —
    rollover is a verb, never a date; nothing moves on the cycle's own ``ends_on``.

    Freezes the committed/completed snapshot ``cycle_metrics`` reports from now on
    (so a card leaving on rollover can't change numbers already reported), then
    moves every card still assigned to this cycle and **not** ``done`` to
    ``payload.rollover_to`` — another **open** cycle on the same board (``422`` if
    it's closed, cross-board, or doesn't exist; ``422`` if it names this same
    cycle) — or the backlog when ``rollover_to`` is ``null`` (``card.cycle_id =
    NULL``, M8 V56).

    **404** if the cycle doesn't exist or isn't on this board; **403** if the
    board isn't yours; **409** if the cycle is already closed (a second close with
    a different rollover target would otherwise be a silent-looking footgun, so
    it's a conflict rather than a no-op).
    """
    authorize_board(db, principal, board_id, Access.WRITE)
    cycle = _get_cycle_or_404(db, board_id, cycle_id)
    if cycle.closed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="cycle is already closed"
        )

    rollover_to = payload.rollover_to
    if rollover_to is not None:
        if rollover_to == cycle_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="rollover_to must be a different cycle",
            )
        target = db.get(Cycle, rollover_to)
        if target is None or target.board_id != board_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="rollover_to must reference another open cycle on the same board",
            )
        if target.closed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"rollover_to cycle {target.id} {target.name!r} is already closed",
            )

    now = datetime.now(timezone.utc)
    metrics = cycle_metrics_dict(db, board_id, cycle, now=now)
    cycle.frozen_committed = metrics["committed"]
    cycle.frozen_completed = metrics["completed"]
    cycle.closed_at = now

    unfinished = list(
        db.scalars(
            select(Card).where(
                Card.cycle_id == cycle_id,
                Card.deleted_at.is_(None),
                Card.column != "done",
            )
        ).all()
    )
    for card in unfinished:
        _apply_card_update(db, principal, card, {"cycle_id": rollover_to})

    db.commit()
    return CycleCloseRead(
        closed_at=now, rolled_over_count=len(unfinished), rollover_to=rollover_to
    )
