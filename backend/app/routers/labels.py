"""Label endpoints (M5 V11, KAN-244; owner/member-gated, ADR 0013).

Labels are board-scoped, colored tags a card can carry (R4.2). Full CRUD-lite,
mirroring the flat structure of the cards/epics routers (API-first, ADR 0005).
Mounted by ``main.py`` under ``/api/v1``:

- GET    /boards/{board_id}/labels — list a board's labels (viewer or above)
- POST   /boards/{board_id}/labels — create a label on a board (editor or above)
- PATCH  /labels/{label_id}        — rename / recolour a label (editor or above)
- DELETE /labels/{label_id}        — delete a label (editor or above); it detaches
                                     from every card via ON DELETE CASCADE

Create/list are addressed by board (``/boards/{id}/labels``); patch and delete are
addressed by the label's own id (``/labels/{id}``) and authorized via the label's
board — the cleanest shape for the two access patterns. No activity log rows: the
audit feed's CHECK vocabulary covers card/epic/board entities only, and a label is
neither.

**PATCH arrived late (V61, KAN-982).** Labels shipped in M5 V11 as create/list/delete
only, which meant a typo'd name or an unrenderable colour could only be fixed by
deleting the label — and deleting detaches it from every card it was on. There was no
non-destructive edit until the label management UI needed one.

**The list endpoint returns a different shape from the rest.** ``GET`` responds with
:class:`~app.schemas.LabelReadWithUsage`, which adds ``usage_count``; create and patch
return a plain :class:`~app.schemas.LabelRead`. That asymmetry is deliberate — see the
schema's own note on why the count must not live on ``LabelRead`` itself.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import Access, authorize_board, get_principal
from ..db import get_db
from ..models import CardLabel, Label
from ..schemas import LabelCreate, LabelRead, LabelReadWithUsage, LabelUpdate

router = APIRouter(tags=["labels"])


def _get_label_or_404(db: Session, label_id: int) -> Label:
    label = db.get(Label, label_id)
    if label is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Label not found"
        )
    return label


@router.get("/boards/{board_id}/labels", response_model=list[LabelReadWithUsage])
def list_labels(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[LabelReadWithUsage]:
    """List a board's labels, oldest-first (creation order), each with the number of
    cards carrying it. Viewer or above; a board you can't see is a ``403`` (unknown
    board ``404``).

    One LEFT JOIN + GROUP BY rather than a count per label, so the response cost is
    flat in the number of labels — a board with 30 labels is still one query."""
    authorize_board(db, principal, board_id, Access.READ)
    rows = db.execute(
        select(Label, func.count(CardLabel.card_id))
        .outerjoin(CardLabel, CardLabel.label_id == Label.id)
        .where(Label.board_id == board_id)
        .group_by(Label.id)
        .order_by(Label.id)
    ).all()
    return [
        LabelReadWithUsage(
            **LabelRead.model_validate(label).model_dump(), usage_count=count
        )
        for label, count in rows
    ]


@router.post(
    "/boards/{board_id}/labels",
    response_model=LabelRead,
    status_code=status.HTTP_201_CREATED,
)
def create_label(
    board_id: int,
    payload: LabelCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Label:
    """Create a label on a board (editor or above). ``name`` + ``color`` come from
    the body; the board from the path."""
    authorize_board(db, principal, board_id, Access.WRITE)
    label = Label(
        board_id=board_id, name=payload.name, color=payload.color, emoji=payload.emoji
    )
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@router.patch("/labels/{label_id}", response_model=LabelRead)
def update_label(
    label_id: int,
    payload: LabelUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Label:
    """Rename and/or recolour a label by id (editor or above on its board).

    Only the fields actually sent are applied (``exclude_unset``), so a PATCH
    carrying just ``color`` leaves the name alone. An empty body is a no-op that
    returns the label unchanged rather than an error — a PATCH with nothing to
    change has already achieved it.

    **404** if no such label; **403** if the label's board isn't yours. The label
    keeps its card attachments: unlike delete, this is the non-destructive edit."""
    label = _get_label_or_404(db, label_id)
    authorize_board(db, principal, label.board_id, Access.WRITE)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(label, field, value)
    db.commit()
    db.refresh(label)
    return label


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(
    label_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Delete a label by id (editor or above on its board). Its ``card_label`` join
    rows cascade away, so it detaches from every card that carried it. **404** if no
    such label; **403** if the label's board isn't yours."""
    label = _get_label_or_404(db, label_id)
    authorize_board(db, principal, label.board_id, Access.WRITE)
    db.delete(label)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
