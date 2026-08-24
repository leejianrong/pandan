"""Cards endpoints (BREADBOARD §6, P4; **owner-gated in V8, ADR 0013**).

Mounted by ``main.py`` under ``/api/v1`` (e.g. ``/api/v1/cards``):

- GET    /cards         — list/query cards (filter + keyset pagination; also the
                          batch read by ``ids=``/``refs=``, issue #254; see list_cards)
- POST   /cards         — create a card (appended to the end of its column)
- GET    /cards/{id}    — read one card
- PATCH  /cards/{id}    — edit fields (title/description/story_points/assignee)
- DELETE /cards/{id}    — soft-delete (tombstone; excluded from default reads, KAN-19)
- POST   /cards/{id}/move — move/reorder a card (column change + reorder within column)
- GET    /cards/trash   — list this board's soft-deleted cards (KAN-20)
- POST   /cards/{id}/restore — un-tombstone a soft-deleted card, re-appending it (KAN-20)
- DELETE /cards/{id}/purge — permanently hard-delete a soft-deleted card (KAN-20)

**Authorization (V8):** every route requires a principal (`401` otherwise) and
that the principal own the card's board (`403`); the list is scoped to the caller's
boards. See :mod:`app.authz`.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session, aliased

from ..activity import record_activity
from ..auth_models import User
from ..authz import Access, authorize_board, get_principal, visible_board_ids
from ..board_seq import allocate_card_seqs, card_ref, parse_ref
from ..card_query import sort_order_by
from ..db import get_db
from ..models import (
    Board,
    Card,
    CardComment,
    CardDependency,
    CardLabel,
    CardLink,
    Cycle,
    Epic,
    Label,
)
from ..notifications import record_notification
from ..ordering import next_position, renumber_column
from ..pagination import NEXT_CURSOR_HEADER, decode_cursor, encode_cursor
from ..schemas import (
    MAX_BATCH_ITEMS,
    MAX_CARD_SELECTORS,
    CardBatchUpdateItem,
    CardCreate,
    CardMove,
    CardRead,
    CardTrashRead,
    CardUpdate,
    ColumnEnum,
    CommentCreate,
    CommentRead,
    DependencyCreate,
    LinkCreate,
    NeedsHumanRequest,
    PriorityEnum,
)
from .boards import resolve_board_id

router = APIRouter(prefix="/cards", tags=["cards"])

# --- batch read by id / ticket ref (issue #254) -------------------------------
# The header a batch read uses to name the selectors that came back with nothing.
# A header, not a body field, because the response body is a bare ``CardRead[]``
# and the SPA depends on that shape; ``X-Next-Cursor`` set the same precedent.
UNRESOLVED_HEADER = "X-Unresolved-Selectors"

# A reference as the CLI displays it. Three forms parse (V53, KAN-974):
#
#   KAN-12   canonical, global      → resolves from anywhere
#   EPIC-3   canonical, global      → a real ticket that is not a card
#   ENG-14   board-local            → needs ``board_id`` (SHAPING D3)
#   ENG-E7   board-local, an epic   → parses, is not a card
#
# The two canonical prefixes and the epic forms all parse rather than 422, because a
# well-formed reference to something that is not a card is an *unresolved* selector
# (reported in the header), not malformed input (rejected). Anything that is not a
# reference at all is a client bug and 422s.
#
# Parsing lives in :mod:`app.board_seq` so the one grammar serves every call site.


def _split_selectors(raw: str, *, param: str) -> list[str]:
    """Split a comma-separated selector list, preserving order and dropping repeats.

    Order is preserved so the unresolved report reads back in the caller's own terms;
    duplicates are dropped so ``ids=7,7`` cannot be reported as one hit and one miss.
    """
    seen: set[str] = set()
    out: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        key = token.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    if not out:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{param} was given but contained no selectors",
        )
    return out


def _parse_card_selectors(
    ids: str | None, refs: str | None, board_id: int | None
) -> tuple[list[str], list[int], list[str], list[int]]:
    """Parse ``ids``/``refs`` into (original tokens, numeric ids, canonical tickets,
    board-local card numbers).

    Malformed input 422s rather than silently resolving to nothing: ``ids=abc`` is a
    client bug, and reporting it as "unresolved" would let a broken caller look like
    one asking about a deleted card.

    **A board-local ref requires ``board_id``** (V53, KAN-974). That is not a
    limitation of this endpoint, it is what "board-local" means: keys are unique per
    *owner* (ADR 0020), so ``ENG-14`` can name a different card for two different
    people and is only decidable inside a known board (SHAPING D3). The alternatives
    were worse — resolving across every visible board would silently return two cards
    for one selector, and failing the whole request on one ambiguous selector would
    contradict this endpoint's own design, where a selector that misses is *reported*
    rather than fatal. Requiring the board is the only answer that is neither. A
    caller with no board in mind has the canonical ``KAN-955``, which is exactly what
    it is for.

    An owner-qualified ``alice/ENG-14`` also 422s here: with ``board_id`` given the
    owner is already determined, so the qualifier can only agree redundantly or
    contradict, and neither is worth a code path.
    """
    tokens: list[str] = []
    numeric: list[int] = []
    tickets: list[str] = []
    local_seqs: list[int] = []

    if ids is not None:
        for token in _split_selectors(ids, param="ids"):
            if not token.isdigit():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"ids must be numeric card ids, got {token!r}",
                )
            tokens.append(token)
            numeric.append(int(token))

    if refs is not None:
        for token in _split_selectors(refs, param="refs"):
            parsed = parse_ref(token)
            if parsed is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"refs must be references like 'KAN-12' or 'ENG-14', "
                        f"got {token!r}"
                    ),
                )
            if parsed.owner is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"an owner-qualified ref is not accepted here, got {token!r} "
                        "— board_id already determines the owner"
                    ),
                )
            if not parsed.canonical and board_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"{token!r} is a board-local ref, which resolves only within "
                        "a known board — pass board_id, or use the canonical "
                        "'KAN-<n>' form"
                    ),
                )
            tokens.append(token)
            if parsed.canonical:
                tickets.append(token.upper())
            elif parsed.entity == "card":
                local_seqs.append(parsed.number)
            # A board-local *epic* ref (``ENG-E7``) parses and matches no card, so it
            # falls through to the unresolved report — exactly like ``EPIC-3``.

    # Capped, and a documented 422 rather than a silent truncation — a caller that
    # asked for 150 refs and got 100 cards has no way to tell that from 50 misses.
    if len(tokens) > MAX_CARD_SELECTORS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"too many selectors: {len(tokens)} (max {MAX_CARD_SELECTORS}). "
                "Split the read into batches."
            ),
        )
    return tokens, numeric, tickets, local_seqs


def _unresolved_selectors(tokens: Sequence[str], cards: Sequence[Card]) -> list[str]:
    """The requested selectors that no returned card answers to.

    Computed from what actually came back, so it covers every reason a selector can
    miss with one rule: the card never existed, it is soft-deleted, or it sits on a
    board the caller cannot see. Deliberately *not* distinguished — telling an
    outsider "that id exists but is not yours" would leak the row's existence, which
    is exactly what the owner-scoping in the query is there to prevent.

    A board-local selector is matched against the card's rendered ``ref`` (V53), which
    is why the caller attaches refs **before** calling this. Doing it the other way —
    re-deriving the expected ref here — would put a second copy of the rendering rule
    one function away from the first.
    """
    found_ids = {str(card.id) for card in cards}
    found = {card.ticket_number.upper() for card in cards}
    found |= {card.ref.upper() for card in cards if getattr(card, "ref", None)}
    return [token for token in tokens if token not in found_ids and token.upper() not in found]


def _get_or_404(db: Session, card_id: int) -> Card:
    # Soft-deleted cards are invisible to every default read (KAN-19, R5.2): a
    # ``deleted_at``-set row 404s here, so GET/PATCH/move/DELETE on it all 404.
    card = db.scalars(
        select(Card).where(Card.id == card_id, Card.deleted_at.is_(None))
    ).first()
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    return card


def _get_trashed_or_404(db: Session, card_id: int) -> Card:
    """Load a **soft-deleted** card (the mirror of :func:`_get_or_404`) — the trash
    lifecycle (restore/purge, KAN-20) operates only on tombstoned rows, so a live
    (or non-existent) card 404s here."""
    card = db.scalars(
        select(Card).where(Card.id == card_id, Card.deleted_at.is_not(None))
    ).first()
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    return card


def _blocked_predicate():
    """A correlated-``EXISTS`` SQL predicate that is true for a ``Card`` (the outer
    row) iff it is **blocked** (KAN-29): it has ≥1 blocker whose ``column`` is not
    ``done``. Expressed in SQL so the ``blocked`` list filter composes cleanly with
    the other ``WHERE`` clauses and keyset pagination (``limit``/``cursor`` stay
    accurate). This is the exact SQL twin of the Python computation in
    ``_attach_dependencies`` — keep the two definitions in step.
    """
    blocker = aliased(Card)
    return (
        select(1)
        .select_from(CardDependency)
        .join(blocker, blocker.id == CardDependency.blocker_id)
        .where(
            CardDependency.blocked_id == Card.id,
            blocker.column != ColumnEnum.done.value,
            # A soft-deleted blocker (KAN-19) no longer blocks — no phantom.
            blocker.deleted_at.is_(None),
        )
        .exists()
    )


def _attach_dependencies(db: Session, cards: Sequence[Card]) -> Sequence[Card]:
    """Populate the transient ``blocked_by`` / ``blocks`` lists **and the derived
    ``blocked`` flag** on each card from the ``card_dependency`` table (KAN-28 +
    KAN-29), then return the same cards.

    One query fetches every edge touching the given cards (joined to the blocker's
    ``column``) and the grouping happens in Python, so a list of N cards costs a
    single round-trip — no per-card N+1. ``blocked_by`` = ids of cards that block
    this one (edges where it is the *blocked*); ``blocks`` = ids it blocks (edges
    where it is the *blocker*). ``blocked`` is True when ≥1 of its blockers is not
    yet ``done`` — the same rule as ``_blocked_predicate``.
    """
    ids = [c.id for c in cards]
    if not ids:
        return cards
    blocker = aliased(Card)
    blocked = aliased(Card)
    # Only edges between two **live** cards count — an edge touching a soft-deleted
    # card (KAN-19) is dropped so it never leaves a phantom in ``blocked_by`` /
    # ``blocks`` / the ``blocked`` flag (the outer cards here are already live).
    rows = db.execute(
        select(
            CardDependency.blocker_id,
            CardDependency.blocked_id,
            blocker.column,
        )
        .join(blocker, blocker.id == CardDependency.blocker_id)
        .join(blocked, blocked.id == CardDependency.blocked_id)
        .where(
            or_(
                CardDependency.blocker_id.in_(ids),
                CardDependency.blocked_id.in_(ids),
            ),
            blocker.deleted_at.is_(None),
            blocked.deleted_at.is_(None),
        )
    ).all()
    blocked_by: dict[int, list[int]] = defaultdict(list)
    blocks: dict[int, list[int]] = defaultdict(list)
    # blocked_id -> number of its blockers not yet in ``done``.
    active_blockers: dict[int, int] = defaultdict(int)
    for blocker_id, blocked_id, blocker_column in rows:
        blocked_by[blocked_id].append(blocker_id)
        blocks[blocker_id].append(blocked_id)
        if blocker_column != ColumnEnum.done.value:
            active_blockers[blocked_id] += 1
    for card in cards:
        card.blocked_by = sorted(blocked_by.get(card.id, []))
        card.blocks = sorted(blocks.get(card.id, []))
        card.blocked = active_blockers.get(card.id, 0) > 0
    _attach_links(db, cards)
    _attach_labels(db, cards)
    _attach_refs(db, cards)
    return cards


def _attach_links(db: Session, cards: Sequence[Card]) -> None:
    """Populate the transient ``links`` list on each card from the ``card_link``
    table (KAN-32), ordered by id (creation order). One grouped query over all the
    given cards, so a list of N cards costs a single round-trip — no per-card N+1
    (mirrors ``_attach_dependencies``). Called from ``_attach_dependencies`` so every
    card-returning route carries its work-links.
    """
    ids = [c.id for c in cards]
    if not ids:
        return
    rows = db.scalars(
        select(CardLink).where(CardLink.card_id.in_(ids)).order_by(CardLink.id)
    ).all()
    by_card: dict[int, list[CardLink]] = defaultdict(list)
    for link in rows:
        by_card[link.card_id].append(link)
    for card in cards:
        card.links = by_card.get(card.id, [])


def _attach_labels(db: Session, cards: Sequence[Card]) -> None:
    """Populate the transient ``labels`` list on each card from the ``card_label``
    join (M5 V11, KAN-244), ordered by label id. One grouped query over all the
    given cards — a single round-trip, no per-card N+1 (mirrors ``_attach_links``).
    Called from ``_attach_dependencies`` so every card-returning route carries its
    labels.
    """
    ids = [c.id for c in cards]
    if not ids:
        return
    rows = db.execute(
        select(CardLabel.card_id, Label)
        .join(Label, Label.id == CardLabel.label_id)
        .where(CardLabel.card_id.in_(ids))
        .order_by(Label.id)
    ).all()
    by_card: dict[int, list[Label]] = defaultdict(list)
    for card_id, label in rows:
        by_card[card_id].append(label)
    for card in cards:
        card.labels = by_card.get(card.id, [])


def _attach_refs(db: Session, cards: Sequence[Card]) -> None:
    """Populate the transient ``ref`` on each card — its board-local form, ``ENG-14``
    (M8 V52, KAN-973).

    One query for the boards involved, keyed by ``board_id``, so a list of N cards
    costs a single round-trip no matter how many boards it spans (mirrors
    ``_attach_labels``). A card carries ``board_seq`` but not its board's ``key``,
    which is the only reason this needs a query at all.

    Called from ``_attach_dependencies`` so every card-returning route carries a ref;
    ``test_every_card_route_carries_a_ref`` is what actually holds that promise.
    """
    if not cards:
        return
    board_ids = {c.board_id for c in cards}
    keys = dict(
        db.execute(select(Board.id, Board.key).where(Board.id.in_(board_ids))).all()
    )
    for card in cards:
        key = keys.get(card.board_id)
        card.ref = card_ref(key, card.board_seq) if key else None


def _attach_one(db: Session, card: Card) -> Card:
    """Attach dependency arrays + work-links + labels to a single card (thin
    wrapper on the batch helper)."""
    _attach_dependencies(db, [card])
    return card


def _validate_labels(
    db: Session, label_ids: list[int] | None, board_id: int
) -> list[int]:
    """Every id in ``label_ids`` (if given) must reference an existing label **on
    the same board** as the card (M5 V11 — a label is board-scoped, mirroring
    ``_validate_epic``); 422 otherwise. Returns the de-duplicated list of ids
    (order preserved). ``None`` → ``[]`` (no labels)."""
    if not label_ids:
        return []
    # De-dupe while preserving order so a caller repeating an id is harmless.
    unique = list(dict.fromkeys(label_ids))
    found = set(
        db.scalars(
            select(Label.id).where(Label.id.in_(unique), Label.board_id == board_id)
        ).all()
    )
    missing = [lid for lid in unique if lid not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="every label_id must reference a label on the card's board",
        )
    return unique


def _set_labels(db: Session, card: Card, label_ids: list[int]) -> None:
    """Replace a card's label set with exactly ``label_ids`` (already validated).
    Deletes the existing ``card_label`` rows for the card and inserts the new ones —
    a full replace so ``label_ids=[]`` clears them. Does not commit (the caller
    commits in the same transaction as the rest of the mutation)."""
    db.execute(CardLabel.__table__.delete().where(CardLabel.card_id == card.id))
    for lid in label_ids:
        db.add(CardLabel(card_id=card.id, label_id=lid))


def _validate_epic(db: Session, epic_id: int | None, board_id: int) -> None:
    """A story's ``epic_id`` (if set) must reference an existing epic (ADR 0009)
    **on the same board** as the story (M3 V8 — one board owns its epics + stories;
    no cross-board links); 422 otherwise."""
    if epic_id is None:
        return
    # A soft-deleted epic (KAN-19) is invisible, so it can't be linked to either.
    epic = db.scalars(
        select(Epic).where(Epic.id == epic_id, Epic.deleted_at.is_(None))
    ).first()
    if epic is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="epic_id must reference an existing epic",
        )
    if epic.board_id != board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="epic must belong to the same board as the story",
        )


def _validate_cycle(db: Session, cycle_id: int | None, board_id: int) -> None:
    """A story's ``cycle_id`` (if set) must reference an existing cycle (V33,
    KAN-297) **on the same board** as the story (no cross-board links); 422
    otherwise. Mirrors :func:`_validate_epic`."""
    if cycle_id is None:
        return
    cycle = db.get(Cycle, cycle_id)
    if cycle is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="cycle_id must reference an existing cycle",
        )
    if cycle.board_id != board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="cycle must belong to the same board as the story",
        )


@router.get("", response_model=list[CardRead])
def list_cards(
    response: Response,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    board_id: int | None = None,
    ids: str | None = None,
    refs: str | None = None,
    column: ColumnEnum | None = None,
    epic_id: int | None = None,
    cycle_id: int | None = None,
    updated_since: datetime | None = None,
    blocked: bool | None = None,
    priority: PriorityEnum | None = None,
    label: int | None = None,
    due_before: datetime | None = None,
    overdue: bool | None = None,
    needs_human: bool | None = None,
    assignee: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=200),
    cursor: str | None = None,
) -> list[Card]:
    """List cards, optionally filtered and keyset-paginated (P4).

    **Owner-scoped (V8):** results are limited to boards the caller owns. A
    ``board_id`` naming a board you don't own is a ``403`` (not a silently-empty
    list).

    **Batch read by id / ticket ref (issue #254):** ``ids=12,45,67`` and/or
    ``refs=KAN-12,KAN-45`` fetch a known set of cards in **one** request, replacing an
    N-round-trip fan-out (the motivating case is kaya rendering ``[[KAN-12]]``
    wikilinks — a spec note with forty refs was forty reads per render). Both are
    comma-separated, order-preserving and de-duplicated; they OR with each other and
    AND with every filter below, so ``refs=…&column=done`` is "which of these are
    done". Combined they are capped at ``MAX_CARD_SELECTORS`` (default 100) — over it
    is a ``422``, never a silent truncation.

    A selector that resolves to nothing is **omitted from the body and named in the
    ``X-Unresolved-Selectors`` response header** (comma-separated, in the order given).
    That is the deliberate choice between the two defensible answers: a renderer must
    not have one bad ref blank the whole note, but a miss must not be silent either.
    The header is present only when something missed, so its absence means a complete
    answer. Unknown, soft-deleted and not-yours all report identically — distinguishing
    them would leak whether a row exists on a board you cannot see. Malformed input is
    a different thing and 422s: ``ids=abc``, or a ``refs`` token that is not a
    ``KAN-``/``EPIC-`` ticket. (A well-formed ``EPIC-3`` parses and then resolves to
    nothing, because it is a real ticket that is not a card.)

    Because the unresolved report is computed from what came back, ``ids``/``refs``
    **cannot be combined with ``limit`` or ``cursor``** (``422``): a truncated page
    would report visible cards as misses. The selector cap already bounds the result.

    Filters (all optional, AND-ed): ``board_id`` (cards on that board — the SPA
    always sends it to scope the view; omitted → all *your* boards); ``column``;
    ``epic_id`` (stories linked to that epic); ``cycle_id`` (stories in that
    cycle/iteration, V33); ``updated_since`` (an ISO-8601
    timestamp — cards whose ``updated_at`` is at or after it, **inclusive**, the
    "changed since" feed for polling agents); ``blocked`` (KAN-29 ready/blocked
    signal — ``blocked=true`` returns only cards with ≥1 blocker not yet ``done``;
    ``blocked=false`` returns the **actionable/ready** cards, i.e. no blockers or
    all blockers done). The ``blocked`` field is on every card in the response
    regardless of this filter. It is a SQL ``EXISTS`` predicate, so it AND-s with
    the other filters and keyset pagination stays exact.

    Card-field filters (M5 V11, KAN-244): ``priority`` (exact match on the enum);
    ``label`` (a label id — cards carrying that label); ``due_before`` (an ISO-8601
    timestamp — cards with a ``due_date`` strictly before it; null due dates are
    excluded); ``overdue`` (``true`` → cards past their ``due_date`` and not yet
    ``done``; ``false`` → the null-safe complement).

    Handoff filter (M5 V13, KAN-246): ``needs_human`` (``true`` → cards an agent
    flagged for a human via ``POST /cards/{id}/needs-human``; ``false`` → the rest).

    Query grammar (M5 V14, KAN-247): ``assignee`` (exact match) joins the filter
    set above, and ``sort`` re-orders the result — a comma-separated list of keys
    with an optional ``-`` prefix for descending (e.g. ``sort=priority``,
    ``sort=-due_date``, ``sort=-priority,position``). ``priority`` sorts by rank
    (none→urgent), NULLs sink either way, and ``id`` is the stable tiebreaker. Valid
    sort fields: ``position``, ``priority``, ``due_date``, ``created_at``,
    ``updated_at``, ``story_points``, ``assignee``, ``title``, ``column``, ``id``
    (an unknown one is a ``422``). These same keys are the structured JSON grammar a
    **saved view** stores (``/boards/{id}/views``), so a view's query replays here.

    Full-text search (M5 V15, KAN-248): ``q`` (a free-text query) narrows the result
    to cards whose ``title``/``description`` match ``websearch_to_tsquery('english',
    q)`` (so ``foo bar`` = both terms, ``"foo bar"`` = the phrase, ``foo -bar`` =
    exclude). It AND-s with every filter above and honours board access exactly like
    the rest. **Ordering precedence:** an explicit ``sort`` always wins; otherwise a
    non-empty ``q`` ranks by relevance (``ts_rank`` best-first, a **title** hit above
    a description-only hit via the vector's A/B weighting), with ``id`` the stable
    tiebreaker. An empty/whitespace-only (or absent) ``q`` is a no-op — the ordering
    and result set are unchanged.

    Pagination is keyset over ``(updated_at, id)`` — the **default** ordering: pass
    ``limit`` to cap the page; when a full page is returned the next page's opaque
    cursor rides the ``X-Next-Cursor`` response header (absent on the last page).
    Echo it back as ``cursor`` for the next request. A custom ``sort`` — or relevance
    ranking from a non-empty ``q`` — overrides that order, so it is **incompatible
    with ``cursor``** (``422`` if combined) and emits no cursor; ``limit`` then just
    caps a top-N by that order. The body stays a bare ``CardRead[]`` so the SPA is
    unaffected; it re-sorts by ``position`` per column client-side.
    """
    # Batch read by id / ticket ref (issue #254). Parsed before anything else so a
    # malformed selector fails before any query work.
    selector_tokens: list[str] = []
    selector_ids: list[int] = []
    selector_refs: list[str] = []
    selector_local_seqs: list[int] = []
    batch_read = ids is not None or refs is not None
    if batch_read:
        (
            selector_tokens,
            selector_ids,
            selector_refs,
            selector_local_seqs,
        ) = _parse_card_selectors(ids, refs, board_id)
        # Pagination would corrupt the unresolved report: a page cut short leaves
        # real, visible cards looking like misses, and the caller cannot tell the
        # difference. The selector list is already capped, so paging it is
        # meaningless anyway — say so instead of silently returning a wrong report.
        if cursor is not None or limit is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "ids/refs cannot be combined with limit or cursor — a batch read "
                    f"is already bounded by the {MAX_CARD_SELECTORS}-selector cap, and "
                    "truncating it would misreport the unresolved selectors"
                ),
            )

    # Treat an empty/whitespace-only ``q`` as absent (a true no-op, R5 back-compat).
    q_text = q.strip() if q is not None else None
    q_active = bool(q_text)
    # A custom sort — or relevance ranking from ``q`` — replaces the keyset ordering,
    # so it can't co-exist with a keyset cursor (the cursor predicate assumes the
    # (updated_at, id) order).
    if cursor is not None and (sort is not None or q_active):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="sort/q cannot be combined with cursor pagination",
        )
    # Soft-deleted cards (KAN-19, R5.2) are excluded from every list read. Ordering
    # is applied below (default keyset order, or the custom ``sort``).
    query = select(Card).where(Card.deleted_at.is_(None))

    if board_id is not None:
        # Naming a board authorizes against it directly (403 if no read access).
        authorize_board(db, principal, board_id, Access.READ)
        query = query.where(Card.board_id == board_id)
    else:
        # No board named → scope to every board the caller owns.
        query = query.where(Card.board_id.in_(visible_board_ids(principal)))
    if batch_read:
        # OR across the two selector kinds (a card matches by id *or* by ticket), but
        # AND-ed with every other filter and with the owner-scoping above — so a
        # selector for a board you cannot see resolves to nothing and is reported as
        # unresolved, never as a 403 that would confirm the row exists.
        # OR across the selector kinds (a card matches by id, canonical ticket *or*
        # board-local number), AND-ed with every other filter and with the
        # owner-scoping above. A board-local number is only reachable here when
        # ``board_id`` was given (the parser enforces that), and the ``board_id``
        # filter above has already narrowed to that board — so ``board_seq`` needs no
        # further qualification, and a number belonging to some other board can never
        # leak in.
        selector_predicates = [
            Card.id.in_(selector_ids),
            Card.ticket_number.in_(selector_refs),
        ]
        if selector_local_seqs:
            selector_predicates.append(Card.board_seq.in_(selector_local_seqs))
        query = query.where(or_(*selector_predicates))
    if column is not None:
        query = query.where(Card.column == column.value)
    if epic_id is not None:
        query = query.where(Card.epic_id == epic_id)
    if cycle_id is not None:
        # Cards in a cycle/iteration (V33, KAN-297); mirrors the epic_id filter.
        query = query.where(Card.cycle_id == cycle_id)
    if updated_since is not None:
        query = query.where(Card.updated_at >= updated_since)
    if blocked is not None:
        predicate = _blocked_predicate()
        query = query.where(predicate if blocked else ~predicate)
    if priority is not None:
        query = query.where(Card.priority == priority.value)
    if label is not None:
        # Cards carrying the given label (M5 V11). A subquery over the join keeps it
        # composing cleanly with the other filters + keyset pagination.
        query = query.where(
            Card.id.in_(
                select(CardLabel.card_id).where(CardLabel.label_id == label)
            )
        )
    if due_before is not None:
        # A NULL due_date is naturally excluded by ``<`` (no due date = not due).
        query = query.where(Card.due_date < due_before)
    if overdue is not None:
        # Overdue = has a due date in the past AND not yet done (M5 V11, R4.3).
        overdue_pred = and_(
            Card.due_date.is_not(None),
            Card.due_date < func.now(),
            Card.column != ColumnEnum.done.value,
        )
        if overdue:
            query = query.where(overdue_pred)
        else:
            # Null-safe negation: no due date, not yet due, or already done.
            query = query.where(
                or_(
                    Card.due_date.is_(None),
                    Card.due_date >= func.now(),
                    Card.column == ColumnEnum.done.value,
                )
            )
    if needs_human is not None:
        # The human↔agent handoff filter (M5 V13): needs_human=true surfaces the
        # cards an agent flagged for a human; false is their complement.
        query = query.where(Card.needs_human.is_(needs_human))
    if assignee is not None:
        # Exact-match assignee filter (M5 V14): the "cards assigned to X" slice.
        query = query.where(Card.assignee == assignee)
    tsquery = None
    if q_active:
        # Full-text search (M5 V15): match the generated ``search_vector`` against a
        # websearch-style query. ``websearch_to_tsquery`` is the forgiving, user-input
        # grammar (bare terms AND-ed, quotes = phrase, ``-`` = exclude). AND-s with
        # every filter above via the ``@@`` predicate, so keyset/limit stay exact.
        tsquery = func.websearch_to_tsquery("english", q_text)
        query = query.where(Card.search_vector.op("@@")(tsquery))

    # Ordering precedence: an explicit ``sort`` (M5 V14) always wins; else a non-empty
    # ``q`` ranks by relevance (M5 V15); else the default keyset order.
    if sort is not None:
        try:
            query = query.order_by(*sort_order_by(sort))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    elif q_active:
        # Best match first (ts_rank honours the A/B field weighting baked into the
        # vector, so a title hit outranks a description-only hit); ``id`` is the
        # stable tiebreaker for equal ranks.
        query = query.order_by(
            func.ts_rank(Card.search_vector, tsquery).desc(), Card.id
        )
    else:
        query = query.order_by(Card.updated_at, Card.id)

    if cursor is not None:
        try:
            cursor_updated_at, cursor_id = decode_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid cursor",
            ) from exc
        query = query.where(
            tuple_(Card.updated_at, Card.id) > (cursor_updated_at, cursor_id)
        )
    if limit is not None:
        query = query.limit(limit)

    cards = list(db.scalars(query).all())

    # A full page implies there may be more — hand back the next cursor. A short
    # (or empty) page is the last one, so no header. Keyset paging is defined only
    # for the default order, so a custom ``sort`` or ``q`` ranking never emits a
    # cursor (see above).
    if sort is None and not q_active and limit is not None and len(cards) == limit:
        last = cards[-1]
        response.headers[NEXT_CURSOR_HEADER] = encode_cursor(last.updated_at, last.id)

    # Name the selectors that came back with nothing (issue #254). Emitted only when
    # something actually missed, so its presence is the signal — a caller can treat
    # "header absent" as "you got everything you asked for" without parsing it.
    _attach_dependencies(db, cards)

    if batch_read:
        # After the attach, so a board-local selector can be matched against the
        # card's own rendered ``ref`` rather than a second copy of the rule.
        missing = _unresolved_selectors(selector_tokens, cards)
        if missing:
            response.headers[UNRESOLVED_HEADER] = ",".join(missing)

    return cards


@router.get("/trash", response_model=list[CardTrashRead])
def list_trashed_cards(
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
    board_id: int | None = None,
) -> list[Card]:
    """List **soft-deleted** cards (KAN-20 Trash view) — the mirror of
    :func:`list_cards`, returning only tombstoned rows, newest-deleted first.

    Owner/member-gated identically (``authorize_board`` READ when a ``board_id`` is
    named, else scoped to :func:`visible_board_ids`). Declared **before** the
    ``/{card_id}`` routes so ``/cards/trash`` matches this and not the id path.
    ``deleted_at`` is exposed on this path only (:class:`CardTrashRead`); the normal
    reads stay unchanged.
    """
    query = (
        select(Card)
        .where(Card.deleted_at.is_not(None))
        .order_by(Card.deleted_at.desc(), Card.id.desc())
    )
    if board_id is not None:
        authorize_board(db, principal, board_id, Access.READ)
        query = query.where(Card.board_id == board_id)
    else:
        query = query.where(Card.board_id.in_(visible_board_ids(principal)))
    rows = list(db.scalars(query).all())
    # Refs, but deliberately not the rest. This path has always skipped
    # ``_attach_dependencies``, so labels/links/blocked_by read empty on the trash
    # listing — a pre-existing simplification left alone here. ``ref`` is different:
    # it is one query and the slice's promise is that every card carries one, so a
    # trashed card that rendered no ref would be the only hole in it.
    _attach_refs(db, rows)
    return rows


def _create_card_row(
    db: Session,
    principal: User,
    board_id: int,
    payload: CardCreate,
    board_seq: int | None = None,
) -> Card:
    """Build + persist one card on ``board_id`` from a ``CardCreate``-shaped payload,
    validating its epic + labels and recording a ``created`` activity row. Flushes
    (so ``id``/``ticket_number`` are assigned and the next card's ``position`` counts
    it) but does **not** commit — the caller owns the transaction, so a single create
    and a batch/template apply can share this and stay atomic (M5 V19, KAN-252).

    ``board_seq`` (M8 V52, KAN-973) is the card's board-local number. Passing one lets
    a batch take its whole range in a single statement instead of locking the board
    row once per card; omitting it allocates one here, which is what every
    single-card create does. Allocation happens **after** validation on purpose — a
    payload that is going to 422 should not have consumed a number first, since the
    counter is deliberately gapless and nothing gives a number back.
    """
    _validate_epic(db, payload.epic_id, board_id)
    _validate_cycle(db, payload.cycle_id, board_id)
    label_ids = _validate_labels(db, payload.label_ids, board_id)
    if board_seq is None:
        board_seq = allocate_card_seqs(db, board_id)[0]
    card = Card(
        board_id=board_id,
        board_seq=board_seq,
        title=payload.title,
        description=payload.description,
        column=payload.column.value,
        position=next_position(db, board_id, payload.column.value),
        story_points=payload.story_points,
        assignee=payload.assignee,
        epic_id=payload.epic_id,
        cycle_id=payload.cycle_id,
        priority=payload.priority.value,
        due_date=payload.due_date,
    )
    db.add(card)
    db.flush()
    # Load server-assigned fields (id, ticket_number, timestamps) within the txn.
    db.refresh(card)
    if label_ids:
        _set_labels(db, card, label_ids)
    record_activity(
        db,
        principal,
        board_id=board_id,
        entity_type="card",
        entity_id=card.id,
        action="created",
        summary=f"created {card.ticket_number}: {card.title}",
    )
    return card


@router.post("", response_model=CardRead, status_code=status.HTTP_201_CREATED)
def create_card(
    payload: CardCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    board_id = resolve_board_id(db, payload.board_id)
    authorize_board(db, principal, board_id, Access.WRITE)
    card = _create_card_row(db, principal, board_id, payload)
    db.commit()
    return _attach_one(db, card)


@router.get("/{card_id}", response_model=CardRead)
def get_card(
    card_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.READ)
    return _attach_one(db, card)


def _apply_card_update(db: Session, principal: User, card: Card, data: dict) -> None:
    """Apply the sent field edits in ``data`` (a ``CardUpdate.model_dump(
    exclude_unset=True)``, ``id`` already removed) to ``card``, validating title /
    epic / labels exactly like a single PATCH and recording an ``updated`` activity
    row. Does **not** commit — the caller owns the transaction, so a single PATCH and
    a batch update share this and a batch stays atomic (M5 V19, KAN-252)."""
    if "title" in data and (data["title"] is None or not str(data["title"]).strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="title must not be empty",
        )
    if "epic_id" in data:
        _validate_epic(db, data["epic_id"], card.board_id)
    if "cycle_id" in data:
        _validate_cycle(db, data["cycle_id"], card.board_id)
    # ``label_ids`` isn't a card column — it replaces the card_label join, so pull
    # it out of the field-edit loop and apply it separately (M5 V11).
    label_ids_sent = "label_ids" in data
    label_ids = _validate_labels(db, data.pop("label_ids", None), card.board_id)
    # ``priority`` is an enum on the schema but a varchar column — store its value.
    if data.get("priority") is not None:
        data["priority"] = PriorityEnum(data["priority"]).value
    # Capture the assignee before the edit so we notify only on the *transition* into
    # a new assignee (V37, KAN-301) — one row per assignment, not per unrelated edit.
    assignee_before = card.assignee
    for field, value in data.items():
        setattr(card, field, value)
    if label_ids_sent:
        _set_labels(db, card, label_ids)
    record_activity(
        db,
        principal,
        board_id=card.board_id,
        entity_type="card",
        entity_id=card.id,
        action="updated",
        summary=f"updated {card.ticket_number}",
    )
    # Notify the board owner when a card is (re)assigned to someone (V37, KAN-301):
    # ``assignee`` was sent, is truthy (empty string = un-assign → no notification),
    # and actually changed. Same transaction as the edit (record_notification adds,
    # never commits) — so a single PATCH and a batch item both emit exactly once.
    if data.get("assignee") and data["assignee"] != assignee_before:
        record_notification(
            db,
            board_id=card.board_id,
            card_id=card.id,
            kind="assigned",
            body=f"{card.ticket_number} assigned to {data['assignee']}",
        )


@router.patch("/batch", response_model=list[CardRead])
def batch_update_cards(
    payload: list[CardBatchUpdateItem],
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[Card]:
    """Atomically PATCH several cards in one call (M5 V19, KAN-252).

    Body: a non-empty list of ``{id, ...fields}`` objects — each takes the same field
    edits as a single ``PATCH /cards/{id}`` (title/description/story_points/assignee/
    epic_id/priority/due_date/label_ids). **Column/position are deliberately absent** —
    moving a card stays on ``POST /cards/{id}/move`` (the move-vs-edit split, ADR 0006).

    **All-or-nothing (atomic):** the whole batch commits or nothing does. Any missing
    or soft-deleted id → **404**; a duplicate id in the body → **422**; a card on a
    board you can't write → **403** (each distinct board is WRITE-authorized once); a
    per-card validation failure (bad title/epic/label/story_points) → **422/404**. On
    any of these the transaction is rolled back and no card changes. Records one
    ``updated`` activity row per card. Returns the updated cards in request order.

    Declared **before** ``/{card_id}`` so ``/cards/batch`` matches this, not the id
    path (mirrors ``/cards/trash``)."""
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="batch must contain at least one card update",
        )
    # Payload hardening (V28, KAN-292): cap the batch so a single call can't fan out
    # into an unbounded transaction. Configurable via MAX_BATCH_ITEMS (generous default).
    if len(payload) > MAX_BATCH_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"batch must not exceed {MAX_BATCH_ITEMS} card updates",
        )
    ids = [item.id for item in payload]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="batch must not repeat a card id",
        )
    # Authorize each distinct board once (WRITE); a board you can't write → 403.
    cards: list[Card] = []
    authorized: set[int] = set()
    for item in payload:
        card = _get_or_404(db, item.id)  # 404 fails the whole batch (nothing committed)
        if card.board_id not in authorized:
            authorize_board(db, principal, card.board_id, Access.WRITE)
            authorized.add(card.board_id)
        cards.append(card)
    for item, card in zip(payload, cards):
        data = item.model_dump(exclude_unset=True)
        data.pop("id", None)
        _apply_card_update(db, principal, card, data)
    db.commit()  # single transaction → atomic; updated_at bumped via onupdate
    for card in cards:
        db.refresh(card)
    _attach_dependencies(db, cards)
    return cards


@router.patch("/{card_id}", response_model=CardRead)
def update_card(
    card_id: int,
    payload: CardUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    # Only fields the client actually sent; distinguishes "omitted" from "set null".
    data = payload.model_dump(exclude_unset=True)
    _apply_card_update(db, principal, card, data)
    db.commit()  # updated_at is bumped server-side via onupdate
    db.refresh(card)
    return _attach_one(db, card)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    # Record before the delete (same transaction) — the audit row survives on the
    # still-present board; ``entity_id`` is a plain int, not an FK to the gone card.
    record_activity(
        db,
        principal,
        board_id=card.board_id,
        entity_type="card",
        entity_id=card.id,
        action="deleted",
        summary=f"deleted {card.ticket_number}: {card.title}",
    )
    # Soft delete (KAN-19, R5.2): tombstone the row rather than removing it, so it
    # can be restored later (KAN-20). The row keeps its position — the vacated slot
    # still reads as an intentional gap (ADR 0006) because default reads and the
    # ordering helpers filter ``deleted_at`` out.
    card.deleted_at = func.now()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{card_id}/move", response_model=CardRead)
def move_card(
    card_id: int,
    payload: CardMove,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)

    source_column = card.column
    target_column = payload.column.value

    # The target column's other cards **on the same board**, in order (the moved
    # card excluded). A move only reorders within a board (M3 V7).
    siblings = list(
        db.scalars(
            select(Card)
            .where(
                Card.board_id == card.board_id,
                Card.column == target_column,
                Card.id != card.id,
                Card.deleted_at.is_(None),
            )
            .order_by(Card.position, Card.id)
        ).all()
    )

    # Insert at the requested index (clamped); None => append to the end.
    index = payload.position if payload.position is not None else len(siblings)
    index = max(0, min(index, len(siblings)))
    siblings.insert(index, card)
    card.column = target_column
    for pos, sibling in enumerate(siblings):
        sibling.position = pos

    # Flush so the moved card's new column is visible to the source renumber query
    # (the session has autoflush disabled).
    db.flush()
    if source_column != target_column:
        renumber_column(db, card.board_id, source_column)

    record_activity(
        db,
        principal,
        board_id=card.board_id,
        entity_type="card",
        entity_id=card.id,
        action="moved",
        summary=(
            f"moved {card.ticket_number} to {target_column}"
            if source_column == target_column
            else f"moved {card.ticket_number} from {source_column} to {target_column}"
        ),
        # Structured transition for metrics (KAN-260); a same-column reorder records
        # from == to and is not counted as a transition.
        from_column=source_column,
        to_column=target_column,
    )
    db.commit()
    db.refresh(card)
    return _attach_one(db, card)


# --- needs-human handoff (M5 V13, KAN-246) ---------------------------------
#
# The human↔agent handoff primitive: an agent flags a card ``needs-human`` (with an
# optional note describing the ask) when it hits something only a human can settle;
# a human clears the flag once handled. The *resolution channel* is the existing
# comments feature (KAN-33) — the agent discovers resolution via the cleared flag +
# a human's comment; we deliberately do not add a new messaging path here. Both
# events land in the activity feed as first-class ``attention`` / ``resolved`` rows.


@router.post("/{card_id}/needs-human", response_model=CardRead)
def flag_needs_human(
    card_id: int,
    payload: NeedsHumanRequest,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    """Flag card ``{card_id}`` as needing a human (M5 V13): set ``needs_human=true``
    and store the optional ``attention_note`` from the body. Records an ``attention``
    activity event. **404** unless the card is live; owner/member-gated (WRITE)."""
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    # Notify only on the transition into needs-human (V37, KAN-301): re-flagging an
    # already-flagged card emits nothing (exactly one row per event).
    was_flagged = card.needs_human
    card.needs_human = True
    card.attention_note = payload.attention_note
    record_activity(
        db,
        principal,
        board_id=card.board_id,
        entity_type="card",
        entity_id=card.id,
        action="attention",
        summary=(
            f"flagged {card.ticket_number} for a human: {payload.attention_note}"
            if payload.attention_note
            else f"flagged {card.ticket_number} for a human"
        ),
    )
    if not was_flagged:
        record_notification(
            db,
            board_id=card.board_id,
            card_id=card.id,
            kind="needs_human",
            body=(
                f"{card.ticket_number} needs a human: {payload.attention_note}"
                if payload.attention_note
                else f"{card.ticket_number} needs a human"
            ),
        )
    db.commit()
    db.refresh(card)
    return _attach_one(db, card)


@router.post("/{card_id}/resolve", response_model=CardRead)
def resolve_needs_human(
    card_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    """Clear the needs-human flag on card ``{card_id}`` (M5 V13): set
    ``needs_human=false`` and clear the ``attention_note`` (the ask is no longer
    outstanding, keeping the invariant that a note only rides a flagged card — the
    handoff context lives on in the activity feed + the card's comments). Records a
    ``resolved`` activity event. **404** unless the card is live; WRITE-gated.

    Resolving an unflagged card is a harmless no-op (idempotent): it still records a
    ``resolved`` event and returns the card."""
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    card.needs_human = False
    card.attention_note = None
    record_activity(
        db,
        principal,
        board_id=card.board_id,
        entity_type="card",
        entity_id=card.id,
        action="resolved",
        summary=f"resolved the human handoff on {card.ticket_number}",
    )
    db.commit()
    db.refresh(card)
    return _attach_one(db, card)


@router.post("/{card_id}/restore", response_model=CardRead)
def restore_card(
    card_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    """Bring a soft-deleted card back to life (KAN-20): clear its ``deleted_at`` so it
    reappears in every default read. **404** unless it is currently soft-deleted.

    Its stale position (from before deletion) may now collide with a live card, so we
    **re-append** it to the end of its (board, column) via ``next_position``. That
    count runs while the row is still tombstoned in the DB (the session has autoflush
    off), so it counts the live siblings only and the restored card lands cleanly at
    the end. Records a ``restored`` activity event. Owner/member-gated (WRITE).
    """
    card = _get_trashed_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    # Compute the append index while the card is still deleted_at-set in the DB, so
    # next_position() (which filters ``deleted_at IS NULL``) excludes this very row.
    card.position = next_position(db, card.board_id, card.column)
    card.deleted_at = None
    record_activity(
        db,
        principal,
        board_id=card.board_id,
        entity_type="card",
        entity_id=card.id,
        action="restored",
        summary=f"restored {card.ticket_number}: {card.title}",
    )
    db.commit()
    db.refresh(card)
    return _attach_one(db, card)


@router.delete("/{card_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_card(
    card_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Permanently remove a card from the trash (KAN-20) — a real ``DELETE``, so its
    FK-cascaded rows (dependencies, links, comments) go with it. Operates **only** on
    an already-soft-deleted card (**404** otherwise), keeping the destructive path
    distinct from the soft ``DELETE /cards/{id}``. Records a ``purged`` activity
    event (KAN-239) — a first-class audit of permanent destruction, distinct from
    the ``deleted`` row the soft-delete already logged. The ``entity_id`` is a plain
    int (not an FK), so the audit row survives the card it names.
    Owner/member-gated (WRITE)."""
    card = _get_trashed_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    record_activity(
        db,
        principal,
        board_id=card.board_id,
        entity_type="card",
        entity_id=card.id,
        action="purged",
        summary=f"purged {card.ticket_number}: {card.title}",
    )
    db.delete(card)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- card-to-card dependencies (KAN-28) ------------------------------------


def _blocks_reaches(db: Session, start_id: int, target_id: int) -> bool:
    """True if ``start_id`` can reach ``target_id`` by following blocks-edges
    (blocker→blocked). Iterative DFS with a visited set, so it terminates even on
    an (already-persisted) cycle.

    Used for cycle prevention: adding the edge ``blocker→blocked`` would close a
    loop iff ``blocked`` already reaches ``blocker``.
    """
    seen: set[int] = set()
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current == target_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(
            db.scalars(
                select(CardDependency.blocked_id).where(
                    CardDependency.blocker_id == current
                )
            ).all()
        )
    return False


@router.post(
    "/{card_id}/dependencies",
    response_model=CardRead,
    status_code=status.HTTP_201_CREATED,
)
def add_dependency(
    card_id: int,
    payload: DependencyCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    """Record that card ``{card_id}`` is **blocked-by** card ``blocker_id`` — i.e.
    insert the edge ``(blocker_id → card_id)``. Returns the (now-blocked) card with
    refreshed ``blocked_by`` / ``blocks`` arrays.

    Guards (all 422 unless noted), mirroring ``_validate_epic``:
    - both cards must exist (**404** otherwise);
    - **same board** — the blocker must live on the blocked card's board;
    - **no self-link** — a card cannot block itself;
    - **no duplicate** — the edge must not already exist;
    - **no cycle** — the edge must not make the blocks-graph cyclic.

    Owner-gated on ``{card_id}``'s board; the same-board rule means that also covers
    the blocker.
    """
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)

    blocker_id = payload.blocker_id
    if blocker_id == card.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="a card cannot block itself",
        )
    blocker = db.scalars(
        select(Card).where(Card.id == blocker_id, Card.deleted_at.is_(None))
    ).first()
    if blocker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="blocker card not found"
        )
    if blocker.board_id != card.board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="blocker must be on the same board",
        )
    existing = db.scalars(
        select(CardDependency).where(
            CardDependency.blocker_id == blocker_id,
            CardDependency.blocked_id == card.id,
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="dependency already exists",
        )
    # Adding blocker→card would create a cycle iff card already reaches blocker.
    if _blocks_reaches(db, card.id, blocker_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="dependency would create a cycle",
        )

    # Notify the board owner when THIS edge transitions the card into "blocked"
    # (V37, KAN-301): it had no active (non-``done``, live) blocker before and the
    # new blocker isn't ``done`` yet — so it flips from ready → blocked. Emit only on
    # that transition (a card that was already blocked stays blocked → no new row).
    blocker_alias = aliased(Card)
    active_blockers_before = db.scalar(
        select(func.count())
        .select_from(CardDependency)
        .join(blocker_alias, blocker_alias.id == CardDependency.blocker_id)
        .where(
            CardDependency.blocked_id == card.id,
            blocker_alias.column != ColumnEnum.done.value,
            blocker_alias.deleted_at.is_(None),
        )
    )
    newly_blocked = (
        active_blockers_before == 0 and blocker.column != ColumnEnum.done.value
    )

    db.add(CardDependency(blocker_id=blocker_id, blocked_id=card.id))
    if newly_blocked:
        record_notification(
            db,
            board_id=card.board_id,
            card_id=card.id,
            kind="blocked",
            body=f"{card.ticket_number} is now blocked by {blocker.ticket_number}",
        )
    db.commit()
    return _attach_one(db, card)


@router.delete("/{card_id}/dependencies/{blocker_id}", response_model=CardRead)
def remove_dependency(
    card_id: int,
    blocker_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    """Remove the ``(blocker_id → card_id)`` edge (card ``{card_id}`` is no longer
    blocked-by ``blocker_id``). **404** if that edge doesn't exist. Returns the card
    with refreshed dependency arrays."""
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    edge = db.scalars(
        select(CardDependency).where(
            CardDependency.blocker_id == blocker_id,
            CardDependency.blocked_id == card.id,
        )
    ).first()
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dependency not found"
        )
    db.delete(edge)
    db.commit()
    return _attach_one(db, card)


# --- card work-links (PR / branch / CI) (KAN-32) ---------------------------


@router.post(
    "/{card_id}/links",
    response_model=CardRead,
    status_code=status.HTTP_201_CREATED,
)
def add_link(
    card_id: int,
    payload: LinkCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    """Attach a work-link (``label`` + ``url`` — e.g. a PR URL, branch, or CI run) to
    card ``{card_id}``, closing the board↔git gap (KAN-32). Returns the card with its
    refreshed ``links`` array. **404** if the card doesn't exist; owner-gated on the
    card's board.
    """
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    db.add(CardLink(card_id=card.id, label=payload.label, url=payload.url))
    db.commit()
    return _attach_one(db, card)


@router.delete("/{card_id}/links/{link_id}", response_model=CardRead)
def remove_link(
    card_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Card:
    """Detach work-link ``{link_id}`` from card ``{card_id}`` (KAN-32). **404** if no
    such link belongs to the card. Returns the card with its refreshed ``links``.
    Owner-gated on the card's board.
    """
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    link = db.scalars(
        select(CardLink).where(
            CardLink.id == link_id,
            CardLink.card_id == card.id,
        )
    ).first()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Link not found"
        )
    db.delete(link)
    db.commit()
    return _attach_one(db, card)


# --- card notes / comments (KAN-33) ----------------------------------------
#
# Human/agent-authored intentional notes (a decision, a handoff, "why this is
# blocked") — **distinct from Epic 4's SYSTEM activity log** (KAN-17..20, not yet
# built), which will record machine-generated audit events. No activity-log
# machinery here. Comments are a thread, so — unlike KAN-32's small ``links`` array
# which is inlined on every card read — they get a dedicated list endpoint rather
# than being serialized onto CardRead (a card could accumulate many).


@router.get("/{card_id}/comments", response_model=list[CommentRead])
def list_comments(
    card_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Sequence[CardComment]:
    """List a card's notes (KAN-33), oldest-first (creation order). **404** if the
    card doesn't exist; owner-gated on the card's board."""
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.READ)
    return list(
        db.scalars(
            select(CardComment)
            .where(CardComment.card_id == card.id)
            .order_by(CardComment.created_at, CardComment.id)
        ).all()
    )


@router.post(
    "/{card_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_comment(
    card_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> CardComment:
    """Post a note to a card (KAN-33). ``author_id`` is the acting principal (never
    the request body). Returns the created comment. **404** if the card doesn't
    exist; owner-gated on the card's board."""
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    comment = CardComment(card_id=card.id, author_id=principal.id, body=payload.body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.delete(
    "/{card_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_comment(
    card_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Delete **your own** note (KAN-33). **404** if no such comment belongs to the
    card; **403** if the comment was authored by someone else (delete-own-only).
    Owner-gated on the card's board."""
    card = _get_or_404(db, card_id)
    authorize_board(db, principal, card.board_id, Access.WRITE)
    comment = db.scalars(
        select(CardComment).where(
            CardComment.id == comment_id,
            CardComment.card_id == card.id,
        )
    ).first()
    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found"
        )
    if comment.author_id != principal.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you can only delete your own comments",
        )
    db.delete(comment)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
