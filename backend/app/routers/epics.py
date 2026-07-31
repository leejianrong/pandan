"""Epics endpoints (ADR 0009; **owner-gated in V8, ADR 0013**).

Epics are a per-board grouping a story can belong to — one board owns many epics,
one epic groups many stories (all on that board). Created and read in a separate UI
surface, not on the kanban board. Full CRUD, mirroring the flat structure of the
cards router (API-first, ADR 0005). Mounted by ``main.py`` under ``/api/v1``:

- GET    /epics       — list the caller's epics (optionally scoped to one board)
- POST   /epics       — create an epic (EPIC-<n> assigned by the DB)
- GET    /epics/{id}  — read one epic
- PATCH  /epics/{id}  — edit fields (name/description)
- DELETE /epics/{id}  — soft-delete (tombstone, KAN-19); child stories keep epic_id
- GET    /epics/trash — list this board's soft-deleted epics (KAN-20)
- POST   /epics/{id}/restore — un-tombstone a soft-deleted epic; its stories re-link (KAN-20)
- DELETE /epics/{id}/purge — permanently hard-delete a soft-deleted epic (KAN-20)

**Authorization (V8):** every route requires a principal (`401` otherwise) and
that the principal own the epic's board (`403`); the list is scoped to the caller's
boards. See :mod:`app.authz`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..activity import record_activity
from ..auth_models import User
from ..authz import Access, authorize_board, get_principal, visible_board_ids
from ..db import get_db
from ..epic_rollup import compute_rollup
from ..models import Card, Epic
from ..schemas import EpicCreate, EpicProgress, EpicRead, EpicTrashRead, EpicUpdate
from .boards import resolve_board_id

router = APIRouter(prefix="/epics", tags=["epics"])


def _attach_rollups(db: Session, epics: list[Epic]) -> list[Epic]:
    """Attach the derived progress + health (V32, KAN-296) onto each epic in place so
    :class:`EpicRead` (``from_attributes``) serialises them — no stored column, no
    migration. One grouped ``COUNT`` over the epics' **non-deleted** child cards
    (``done`` = the ``done`` column); the math lives in :mod:`app.epic_rollup`.
    Returns the same list for call-site convenience."""
    now = datetime.now(timezone.utc)
    counts: dict[int, tuple[int, int]] = {}
    epic_ids = [e.id for e in epics]
    if epic_ids:
        rows = db.execute(
            select(
                Card.epic_id,
                func.count().label("total"),
                func.count().filter(Card.column == "done").label("done"),
            )
            .where(Card.epic_id.in_(epic_ids), Card.deleted_at.is_(None))
            .group_by(Card.epic_id)
        ).all()
        counts = {row.epic_id: (row.total, row.done) for row in rows}
    for epic in epics:
        total, done = counts.get(epic.id, (0, 0))
        rollup = compute_rollup(total, done, epic.target_date, now=now)
        # Transient (unmapped) attributes read by EpicRead's from_attributes.
        epic.progress = EpicProgress(**rollup["progress"])  # type: ignore[attr-defined]
        epic.health = rollup["health"]  # type: ignore[attr-defined]
    return epics


def _get_or_404(db: Session, epic_id: int) -> Epic:
    # Soft-deleted epics are invisible to every default read (KAN-19, R5.2): a
    # ``deleted_at``-set row 404s here, so GET/PATCH/DELETE on it all 404.
    epic = db.scalars(
        select(Epic).where(Epic.id == epic_id, Epic.deleted_at.is_(None))
    ).first()
    if epic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Epic not found")
    return epic


def _get_trashed_or_404(db: Session, epic_id: int) -> Epic:
    """Load a **soft-deleted** epic — the trash lifecycle (restore/purge, KAN-20)
    operates only on tombstoned rows, so a live (or missing) epic 404s here."""
    epic = db.scalars(
        select(Epic).where(Epic.id == epic_id, Epic.deleted_at.is_not(None))
    ).first()
    if epic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Epic not found")
    return epic


@router.get("", response_model=list[EpicRead])
def list_epics(
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    board_id: int | None = None,
) -> list[Epic]:
    """List epics, owner-scoped (V8) and optionally scoped to one board. A
    ``board_id`` you don't own is a ``403``; omitted → all *your* boards' epics
    (the SPA always sends it to scope the Epics view)."""
    # Soft-deleted epics (KAN-19, R5.2) are excluded from every list read.
    query = select(Epic).where(Epic.deleted_at.is_(None)).order_by(Epic.id)
    if board_id is not None:
        authorize_board(db, principal, board_id, Access.READ)
        query = query.where(Epic.board_id == board_id)
    else:
        query = query.where(Epic.board_id.in_(visible_board_ids(principal)))
    return _attach_rollups(db, list(db.scalars(query).all()))


@router.get("/trash", response_model=list[EpicTrashRead])
def list_trashed_epics(
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    board_id: int | None = None,
) -> list[Epic]:
    """List **soft-deleted** epics (KAN-20 Trash view), newest-deleted first —
    the mirror of :func:`list_epics`. Owner/member-gated identically; declared
    **before** the ``/{epic_id}`` routes so ``/epics/trash`` matches this.
    ``deleted_at`` is exposed on this path only (:class:`EpicTrashRead`)."""
    query = (
        select(Epic)
        .where(Epic.deleted_at.is_not(None))
        .order_by(Epic.deleted_at.desc(), Epic.id.desc())
    )
    if board_id is not None:
        authorize_board(db, principal, board_id, Access.READ)
        query = query.where(Epic.board_id == board_id)
    else:
        query = query.where(Epic.board_id.in_(visible_board_ids(principal)))
    return _attach_rollups(db, list(db.scalars(query).all()))


@router.post("", response_model=EpicRead, status_code=status.HTTP_201_CREATED)
def create_epic(
    payload: EpicCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Epic:
    board_id = resolve_board_id(db, payload.board_id)
    authorize_board(db, principal, board_id, Access.WRITE)
    epic = Epic(
        board_id=board_id,
        name=payload.name,
        description=payload.description,
        target_date=payload.target_date,
        lead=payload.lead,
    )
    db.add(epic)
    db.commit()
    # Refresh so server-assigned fields (id, ticket_number, timestamps) are populated.
    db.refresh(epic)
    record_activity(
        db,
        principal,
        board_id=board_id,
        entity_type="epic",
        entity_id=epic.id,
        action="created",
        summary=f"created {epic.ticket_number}: {epic.name}",
    )
    db.commit()
    return _attach_rollups(db, [epic])[0]


@router.get("/{epic_id}", response_model=EpicRead)
def get_epic(
    epic_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Epic:
    epic = _get_or_404(db, epic_id)
    authorize_board(db, principal, epic.board_id, Access.READ)
    return _attach_rollups(db, [epic])[0]


@router.patch("/{epic_id}", response_model=EpicRead)
def update_epic(
    epic_id: int,
    payload: EpicUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Epic:
    epic = _get_or_404(db, epic_id)
    authorize_board(db, principal, epic.board_id, Access.WRITE)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and (data["name"] is None or not str(data["name"]).strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="name must not be empty",
        )
    for field, value in data.items():
        setattr(epic, field, value)
    record_activity(
        db,
        principal,
        board_id=epic.board_id,
        entity_type="epic",
        entity_id=epic.id,
        action="updated",
        summary=f"updated {epic.ticket_number}",
    )
    db.commit()  # updated_at is bumped server-side via onupdate
    db.refresh(epic)
    return _attach_rollups(db, [epic])[0]


@router.delete("/{epic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_epic(
    epic_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    epic = _get_or_404(db, epic_id)
    authorize_board(db, principal, epic.board_id, Access.WRITE)
    # Record before the delete (same transaction): the board survives, so the audit
    # row does too; ``entity_id`` is a plain int, not an FK to the gone epic.
    record_activity(
        db,
        principal,
        board_id=epic.board_id,
        entity_type="epic",
        entity_id=epic.id,
        action="deleted",
        summary=f"deleted {epic.ticket_number}: {epic.name}",
    )
    # Soft delete (KAN-19, R5.2): tombstone the row rather than removing it, so it
    # can be restored later (KAN-20). Child stories keep their ``epic_id`` intact —
    # the FK's ON DELETE SET NULL never fires because the row isn't deleted; a
    # story just won't resolve its (now-invisible) epic in default reads. This
    # deliberate non-detach is what lets KAN-20 restore an epic with its stories.
    epic.deleted_at = func.now()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{epic_id}/restore", response_model=EpicRead)
def restore_epic(
    epic_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Epic:
    """Bring a soft-deleted epic back to life (KAN-20): clear its ``deleted_at`` so it
    reappears in default reads. **404** unless it is currently soft-deleted.

    KAN-19 left child stories' ``epic_id`` intact on soft-delete (no detach), so a
    restored epic automatically **re-associates** its still-linked stories — nothing
    else to do. Records a ``restored`` activity event. Owner/member-gated (WRITE)."""
    epic = _get_trashed_or_404(db, epic_id)
    authorize_board(db, principal, epic.board_id, Access.WRITE)
    epic.deleted_at = None
    record_activity(
        db,
        principal,
        board_id=epic.board_id,
        entity_type="epic",
        entity_id=epic.id,
        action="restored",
        summary=f"restored {epic.ticket_number}: {epic.name}",
    )
    db.commit()
    db.refresh(epic)
    return _attach_rollups(db, [epic])[0]


@router.delete("/{epic_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_epic(
    epic_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Permanently remove an epic from the trash (KAN-20) — a real ``DELETE``. The
    ``card.epic_id`` FK is ``ON DELETE SET NULL``, so any stories still linked to it
    are detached (not deleted). Operates **only** on an already-soft-deleted epic
    (**404** otherwise). Records a ``purged`` activity event (KAN-239) — a first-class
    audit of permanent destruction, distinct from the ``deleted`` row the soft-delete
    already logged. The ``entity_id`` is a plain int (not an FK), so the audit row
    survives the epic it names. Owner/member-gated (WRITE)."""
    epic = _get_trashed_or_404(db, epic_id)
    authorize_board(db, principal, epic.board_id, Access.WRITE)
    record_activity(
        db,
        principal,
        board_id=epic.board_id,
        entity_type="epic",
        entity_id=epic.id,
        action="purged",
        summary=f"purged {epic.ticket_number}: {epic.name}",
    )
    db.delete(epic)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
