"""Card-template endpoints (M5 V19, KAN-252; owner/member-gated, ADR 0013).

A card template is a named, board-scoped, reusable plan of cards: its ``cards`` is a
JSON list of card payloads (``schemas.TemplateCardItem``). *Applying* a template
instantiates those payloads as real cards on the board in one transaction, so a whole
plan is seeded in a single call. Full CRUD-lite + apply, mirroring the flat structure
of the saved-views router (API-first, ADR 0005). Mounted by ``main.py`` under
``/api/v1``:

- GET    /boards/{board_id}/templates                 — list a board's templates (viewer+)
- POST   /boards/{board_id}/templates                 — create a template (editor+)
- GET    /boards/{board_id}/templates/{template_id}   — read one template (viewer+)
- DELETE /boards/{board_id}/templates/{template_id}   — delete a template (editor+)
- POST   /boards/{board_id}/templates/{template_id}/apply — instantiate its cards (editor+)

Every template is addressed under its board (``/boards/{id}/templates``); the board
gates access via ``authorize_board`` (READ to list/get, WRITE to create/delete/apply).
A template whose ``board_id`` doesn't match the path board **404s** — so a cross-board
id is never reachable through another board you happen to own. Apply reuses the cards
router's ``_create_card_row`` per card in one transaction, so it is atomic (any bad
epic/label fails the whole apply) and records a ``created`` activity row per card.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import Access, authorize_board, get_principal
from ..db import get_db
from ..models import Card, CardTemplate
from ..schemas import (
    MAX_TEMPLATE_CARDS,
    CardCreate,
    CardRead,
    CardTemplateCreate,
    CardTemplateRead,
)
from .cards import _attach_dependencies, _create_card_row

router = APIRouter(tags=["templates"])


def _get_template_or_404(
    db: Session, board_id: int, template_id: int
) -> CardTemplate:
    """Load template ``template_id`` **on ``board_id``**; 404 if it doesn't exist or
    belongs to a different board (so a cross-board id is never reachable)."""
    template = db.get(CardTemplate, template_id)
    if template is None or template.board_id != board_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    return template


@router.get("/boards/{board_id}/templates", response_model=list[CardTemplateRead])
def list_templates(
    board_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[CardTemplate]:
    """List a board's card templates, oldest-first (creation order). Viewer or above;
    a board you can't see is a ``403`` (unknown board ``404``)."""
    authorize_board(db, principal, board_id, Access.READ)
    return list(
        db.scalars(
            select(CardTemplate)
            .where(CardTemplate.board_id == board_id)
            .order_by(CardTemplate.id)
        ).all()
    )


@router.post(
    "/boards/{board_id}/templates",
    response_model=CardTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_template(
    board_id: int,
    payload: CardTemplateCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> CardTemplate:
    """Create a card template on a board (editor or above). ``name`` + ``cards`` come
    from the body; the board from the path. Each entry in ``cards`` is validated as a
    ``TemplateCardItem`` and stored as JSON (``mode="json"`` so enums/datetimes
    serialize) — a replayable recipe, not real cards yet."""
    authorize_board(db, principal, board_id, Access.WRITE)
    template = CardTemplate(
        board_id=board_id,
        name=payload.name,
        cards=[item.model_dump(mode="json") for item in payload.cards],
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.get(
    "/boards/{board_id}/templates/{template_id}", response_model=CardTemplateRead
)
def get_template(
    board_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> CardTemplate:
    """Read one card template (viewer or above). **404** if it doesn't exist or isn't
    on this board; **403** if the board isn't yours."""
    authorize_board(db, principal, board_id, Access.READ)
    return _get_template_or_404(db, board_id, template_id)


@router.delete(
    "/boards/{board_id}/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_template(
    board_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Delete a card template (editor or above on its board). **404** if no such
    template on this board; **403** if the board isn't yours."""
    authorize_board(db, principal, board_id, Access.WRITE)
    template = _get_template_or_404(db, board_id, template_id)
    db.delete(template)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/boards/{board_id}/templates/{template_id}/apply",
    response_model=list[CardRead],
    status_code=status.HTTP_201_CREATED,
)
def apply_template(
    board_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[Card]:
    """Seed a board's cards from a template in one call (editor or above). Instantiates
    every card in the template's ``cards`` on this board **in one transaction** — all
    created or none (a bad epic/label id in any entry fails the whole apply, **422**).
    Each stored entry is re-validated as a ``CardCreate`` (with ``board_id`` forced to
    the path board) and created via the cards router's ``_create_card_row``, so cards
    are appended to their columns and each records a ``created`` activity row. Returns
    the created cards in template order."""
    authorize_board(db, principal, board_id, Access.WRITE)
    template = _get_template_or_404(db, board_id, template_id)
    # Payload hardening (V28, KAN-292): guard apply too, so a template stored before
    # the create-time cap existed can't fan out into an unbounded transaction.
    if len(template.cards) > MAX_TEMPLATE_CARDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"template exceeds the {MAX_TEMPLATE_CARDS}-card apply limit",
        )
    created: list[Card] = []
    for item in template.cards:
        payload = CardCreate.model_validate({**item, "board_id": board_id})
        created.append(_create_card_row(db, principal, board_id, payload))
    db.commit()
    for card in created:
        db.refresh(card)
    _attach_dependencies(db, created)
    return created
