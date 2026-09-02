"""Cycle (iteration) endpoints (V33, KAN-297; owner/member-gated, ADR 0013).

A cycle is a board-scoped, time-boxed iteration a story can belong to (via the
nullable ``card.cycle_id`` — set through ``PATCH /cards/{id}``). Full CRUD-lite,
mirroring the flat structure of the saved-views / card-templates routers
(API-first, ADR 0005). Mounted by ``main.py`` under ``/api/v1``:

- GET    /boards/{board_id}/cycles                    — list a board's cycles (viewer+)
- POST   /boards/{board_id}/cycles                    — create a cycle (editor+)
- GET    /boards/{board_id}/cycles/{cycle_id}         — read one cycle (viewer+)
- GET    /boards/{board_id}/cycles/{cycle_id}/metrics — burndown/velocity (viewer+, V34)
- PATCH  /boards/{board_id}/cycles/{cycle_id}         — edit a cycle (editor+, V55)
- DELETE /boards/{board_id}/cycles/{cycle_id}         — delete a cycle (editor+)

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
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import Access, authorize_board, get_principal
from ..db import get_db
from ..metrics import compute_cycle_metrics, move_target
from ..models import Activity, Card, Cycle, PlanningInterval
from ..schemas import CycleCreate, CycleMetricsRead, CycleRead, CycleUpdate

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
    """
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
