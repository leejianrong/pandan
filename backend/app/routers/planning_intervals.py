"""Planning interval endpoints (M8 V57, KAN-978; owner/member-gated, ADR 0013).

A planning interval is a board-scoped grouping one level above the cycle — e.g.
a quarter containing six two-week sprints — via the nullable
``Cycle.planning_interval_id`` (set through ``PATCH /boards/{id}/cycles/{cid}``,
``routers/cycles.py``). Full CRUD-lite, structurally identical to
``routers/cycles.py`` (API-first, ADR 0005). Mounted by ``main.py`` under
``/api/v1``:

- GET    /boards/{board_id}/planning-intervals                    — list (viewer+)
- POST   /boards/{board_id}/planning-intervals                    — create (editor+)
- GET    /boards/{board_id}/planning-intervals/{pi_id}             — read one (viewer+)
- GET    /boards/{board_id}/planning-intervals/{pi_id}/metrics     — rollup (viewer+)
- PATCH  /boards/{board_id}/planning-intervals/{pi_id}             — edit (editor+)
- DELETE /boards/{board_id}/planning-intervals/{pi_id}             — delete (editor+)

Every planning interval is addressed under its board (`/boards/{id}/planning-
intervals`); the board gates access via ``authorize_board`` (READ to list/get,
WRITE to create/edit/delete). A planning interval whose ``board_id`` doesn't
match the path board **404s** — so a cross-board id is never reachable through
another board you happen to own. Deleting a planning interval detaches its
member cycles (``Cycle.planning_interval_id`` is ``ON DELETE SET NULL``), it
never cascades them away.

**PATCH ships from day one** — unlike cycles, which shipped in V33 without an
edit route and only got one in V55 (KAN-976) after the gap was felt. Don't
repeat that: a mistyped name/date here would otherwise need delete-and-recreate,
which detaches every member cycle.

**The metrics endpoint is a dedicated rollup, not a filter on ``cycle_metrics``**
(SHAPING Q4, resolved 2026-09-02): a per-cycle day-by-day burndown series doesn't
compose across a planning interval's member cycles into anything meaningful. It
sums committed/completed/velocity across member cycles, reusing
``routers.cycles.cycle_metrics_dict`` per cycle rather than recomputing burndown
logic — and reports no ``burndown`` field, out of scope per the slice.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import Access, authorize_board, get_principal
from ..db import get_db
from ..metrics import compute_planning_interval_metrics
from ..models import Cycle, PlanningInterval
from ..schemas import (
    PlanningIntervalCreate,
    PlanningIntervalMetricsRead,
    PlanningIntervalRead,
    PlanningIntervalUpdate,
)
from .cycles import cycle_metrics_dict

router = APIRouter(tags=["planning-intervals"])


def _get_planning_interval_or_404(
    db: Session, board_id: int, pi_id: int
) -> PlanningInterval:
    """Load planning interval ``pi_id`` **on ``board_id``**; 404 if it doesn't
    exist or belongs to a different board (so a cross-board id is never
    reachable)."""
    pi = db.get(PlanningInterval, pi_id)
    if pi is None or pi.board_id != board_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Planning interval not found"
        )
    return pi


@router.get(
    "/boards/{board_id}/planning-intervals", response_model=list[PlanningIntervalRead]
)
def list_planning_intervals(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[PlanningInterval]:
    """List a board's planning intervals, oldest-first (creation order). Viewer
    or above; a board you can't see is a ``403`` (unknown board ``404``)."""
    authorize_board(db, principal, board_id, Access.READ)
    return list(
        db.scalars(
            select(PlanningInterval)
            .where(PlanningInterval.board_id == board_id)
            .order_by(PlanningInterval.id)
        ).all()
    )


@router.post(
    "/boards/{board_id}/planning-intervals",
    response_model=PlanningIntervalRead,
    status_code=status.HTTP_201_CREATED,
)
def create_planning_interval(
    board_id: int,
    payload: PlanningIntervalCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> PlanningInterval:
    """Create a planning interval on a board (editor or above). ``name`` +
    optional ``starts_on`` / ``ends_on`` come from the body; the board from the
    path."""
    authorize_board(db, principal, board_id, Access.WRITE)
    pi = PlanningInterval(
        board_id=board_id,
        name=payload.name,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
    )
    db.add(pi)
    db.commit()
    db.refresh(pi)
    return pi


@router.get(
    "/boards/{board_id}/planning-intervals/{pi_id}",
    response_model=PlanningIntervalRead,
)
def get_planning_interval(
    board_id: int,
    pi_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> PlanningInterval:
    """Read one planning interval (viewer or above). **404** if it doesn't exist
    or isn't on this board; **403** if the board isn't yours."""
    authorize_board(db, principal, board_id, Access.READ)
    return _get_planning_interval_or_404(db, board_id, pi_id)


@router.get(
    "/boards/{board_id}/planning-intervals/{pi_id}/metrics",
    response_model=PlanningIntervalMetricsRead,
)
def planning_interval_metrics(
    board_id: int,
    pi_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> PlanningIntervalMetricsRead:
    """Rolled-up committed/completed/velocity across a planning interval's member
    cycles (M8 V57, KAN-978).

    For each cycle whose ``planning_interval_id`` is ``pi_id``, computes the same
    per-cycle metrics dict ``GET .../cycles/{id}/metrics`` does
    (``cycle_metrics_dict``, shared with ``routers/cycles.py``), then sums them
    (``compute_planning_interval_metrics``) into one committed-vs-completed
    number. ``Access.READ`` (viewer or above); **404** if the planning interval
    doesn't exist or isn't on this board, **403** if the board isn't yours. A
    planning interval with no member cycles reports all zeros. Deliberately no
    ``burndown`` field — a per-cycle day-by-day series doesn't compose across
    member cycles into anything meaningful (SHAPING Q4).
    """
    authorize_board(db, principal, board_id, Access.READ)
    _get_planning_interval_or_404(db, board_id, pi_id)  # 404 if unknown / cross-board
    now = datetime.now(timezone.utc)

    member_cycles = list(
        db.scalars(
            select(Cycle).where(Cycle.planning_interval_id == pi_id)
        ).all()
    )
    member_metrics = [
        cycle_metrics_dict(db, board_id, cycle, now=now) for cycle in member_cycles
    ]
    rollup = compute_planning_interval_metrics(member_metrics)

    return PlanningIntervalMetricsRead(
        board_id=board_id,
        planning_interval_id=pi_id,
        generated_at=now,
        cycle_count=len(member_cycles),
        **rollup,
    )


@router.patch(
    "/boards/{board_id}/planning-intervals/{pi_id}", response_model=PlanningIntervalRead
)
def update_planning_interval(
    board_id: int,
    pi_id: int,
    payload: PlanningIntervalUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> PlanningInterval:
    """Rename a planning interval and/or correct its bounds (editor or above on
    its board).

    Only the fields actually sent are applied (``exclude_unset``), so a PATCH
    carrying just ``ends_on`` leaves the name alone. An empty body is a no-op
    that returns the planning interval unchanged rather than an error.

    ``starts_on``/``ends_on`` accept an explicit ``null`` to *unschedule* the
    planning interval; ``name`` does not (see
    :class:`~app.schemas.PlanningIntervalUpdate`). **404** if it doesn't exist
    or isn't on this board — the same ``_get_planning_interval_or_404`` every
    other route here uses; **403** if the board isn't yours.

    **The planning interval keeps its member cycles.** Nothing here touches
    ``Cycle.planning_interval_id``.
    """
    authorize_board(db, principal, board_id, Access.WRITE)
    pi = _get_planning_interval_or_404(db, board_id, pi_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(pi, field, value)
    db.commit()
    db.refresh(pi)
    return pi


@router.delete(
    "/boards/{board_id}/planning-intervals/{pi_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_planning_interval(
    board_id: int,
    pi_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Delete a planning interval (editor or above on its board). **404** if no
    such planning interval is on this board; **403** if the board isn't yours.
    Any cycles still assigned to it are detached
    (``Cycle.planning_interval_id`` → NULL), not deleted."""
    authorize_board(db, principal, board_id, Access.WRITE)
    pi = _get_planning_interval_or_404(db, board_id, pi_id)
    db.delete(pi)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
