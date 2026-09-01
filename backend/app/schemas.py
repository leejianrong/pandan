"""Pydantic v2 schemas — the API's request/response contract (CONTEXT §4, ADR 0006 + 0009).

CardCreate / CardRead for create+read; CardUpdate for field edits; CardMove for move/reorder.
Epic{Create,Update,Read} are the contract for the separate epic entity (ADR 0009).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .board_keys import (
    MAX_BOARD_KEY_LEN,
    board_key_error,
    is_reserved_board_key,
    is_valid_board_key,
    reserved_board_key_error,
)
from .palette import is_valid_label_color, label_color_error


def _validate_board_key(v: str | None) -> str | None:
    """Shared board-key field validator for :class:`BoardCreate` /
    :class:`BoardUpdate` (V51, KAN-972).

    Two *different* rejections, kept apart because they need different messages:
    malformed (the shape) and reserved (it would shadow a canonical ticket prefix).
    Uniqueness is deliberately **not** checked here — it needs the database and the
    caller's identity, so it lives in the router as a ``409``, not a ``422``. A
    schema cannot answer "is this taken", and pretending otherwise is how a
    validation layer starts needing a session.
    """
    if v is None:
        return None
    if not is_valid_board_key(v):
        raise ValueError(board_key_error())
    if is_reserved_board_key(v):
        raise ValueError(reserved_board_key_error(v))
    return v

# --- Payload hardening caps (V28, KAN-292) ---------------------------------
# ``max_length`` bounds on the write contract so no single string field can carry an
# unbounded blob (defence-in-depth *behind* the body-size ceiling in ``app.main``).
# For fields backed by a ``varchar(N)`` column (models.py) the cap is aligned to N,
# so an over-long value is a clean **422** at validation rather than a 500 at INSERT
# (a latent gap before this slice); ``Text`` columns have no DB limit, so those caps
# are just a generous app-level ceiling. All additive — normal content is far below.
MAX_TITLE_LEN = 255  # card.title varchar(255)
MAX_NAME_LEN = 255  # epic/board/template/view/label/token name varchar(255)
MAX_ASSIGNEE_LEN = 255  # card.assignee varchar(255)
MAX_LEAD_LEN = 255  # epic.lead varchar(255)
MAX_LINK_LABEL_LEN = 255  # card_link.label varchar(255)
MAX_LABEL_COLOR_LEN = 32  # label.color varchar(32)
MAX_EMAIL_LEN = 320  # RFC 5321 upper bound (member lookup)
MAX_DESCRIPTION_LEN = 20_000  # Text column — long markdown
MAX_TEXT_LEN = 10_000  # Text columns — comment body, attention note
MAX_URL_LEN = 2_000  # card_link.url + board.outbound_webhook_url (Text columns)
MAX_WEBHOOK_SECRET_LEN = 255  # board.outbound_webhook_secret (Text column — app cap)
MAX_SEARCH_LEN = 500  # free-text search term (feeds the expensive full-text path)
MAX_LABEL_IDS = 100  # labels attachable to one card in one request


def _int_env(name: str, default: int) -> int:
    """Read a positive int from the env, falling back to ``default`` when unset or
    malformed (a bad value must never crash import — mirrors ``app.ratelimit``)."""
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value > 0 else default


# Array-length caps — env-tunable (generous defaults) since batch/template size is
# the real amplification lever. The body-size ceiling env var lives in ``app.main``.
MAX_BATCH_ITEMS = _int_env("MAX_BATCH_ITEMS", 500)  # cards per PATCH /cards/batch
MAX_TEMPLATE_CARDS = _int_env("MAX_TEMPLATE_CARDS", 200)  # cards per template
# Selectors per batch read (GET /cards?ids=/refs=, issue #254). Lower than the write
# batch on purpose: this one arrives in the URL, and the point of the endpoint is to
# replace an N-round-trip fan-out, not to become an alternative full-table read.
MAX_CARD_SELECTORS = _int_env("MAX_CARD_SELECTORS", 100)


class ColumnEnum(str, Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class PriorityEnum(str, Enum):
    """Card priority (M5 V11, KAN-244). Mirrors ``VALID_PRIORITIES`` /
    ``ck_card_priority`` (models) and the ``Priority`` type (api.ts) — the three
    places that must stay in sync. ``none`` is the default (an unranked card)."""

    none = "none"
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


STORY_POINTS = {1, 2, 3, 5, 8, 13}


class CardCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=MAX_TITLE_LEN)]
    description: Annotated[str | None, Field(max_length=MAX_DESCRIPTION_LEN)] = None
    column: ColumnEnum = ColumnEnum.todo
    story_points: int | None = None
    assignee: Annotated[str | None, Field(max_length=MAX_ASSIGNEE_LEN)] = None
    # Optional parent epic. That the id references an existing epic is checked in
    # the router (routers/cards.py), which returns 422 on violation.
    epic_id: int | None = None
    # Optional cycle/iteration (V33, KAN-297) — mirrors ``epic_id``: the id must
    # reference an existing cycle on the card's board (checked in the router, 422).
    cycle_id: int | None = None
    # The target board (M3 V7). Optional for back-compat: when omitted the router
    # falls back to the default board, so pre-board clients (the MCP server, older
    # tests) keep working. The referenced board must exist (422 otherwise).
    board_id: int | None = None
    # Card fields (M5 V11, KAN-244). ``priority`` defaults to ``none``; ``due_date``
    # is optional. ``label_ids`` attaches board-scoped labels — each id must belong
    # to the card's board (checked in the router, 422 otherwise). Omitted → no labels.
    priority: PriorityEnum = PriorityEnum.none
    due_date: datetime | None = None
    label_ids: Annotated[list[int] | None, Field(max_length=MAX_LABEL_IDS)] = None

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v

    @field_validator("story_points")
    @classmethod
    def story_points_in_set(cls, v: int | None) -> int | None:
        if v is not None and v not in STORY_POINTS:
            raise ValueError(f"story_points must be one of {sorted(STORY_POINTS)} or null")
        return v


class CardUpdate(BaseModel):
    """Field edits (BREADBOARD §3). All optional — only sent fields are applied.

    Column is intentionally absent: moving a card is done via /move, not PATCH
    (ADR 0006). ticket_number and position are not editable either. `title` may
    not be set empty/null; description/story_points/assignee accept null to clear.
    """

    title: Annotated[str | None, Field(max_length=MAX_TITLE_LEN)] = None
    description: Annotated[str | None, Field(max_length=MAX_DESCRIPTION_LEN)] = None
    story_points: int | None = None
    assignee: Annotated[str | None, Field(max_length=MAX_ASSIGNEE_LEN)] = None
    # Re-link the story to a different epic, or clear it with null. The referenced
    # epic must exist; enforced in the router.
    epic_id: int | None = None
    # Re-assign the story to a different cycle/iteration, or clear it with null
    # (V33, KAN-297). The referenced cycle must exist on the card's board; router.
    cycle_id: int | None = None
    # Card fields (M5 V11). All optional (only sent fields apply, like the rest):
    # ``priority`` re-ranks; ``due_date`` accepts null to clear; ``label_ids``
    # **replaces** the card's label set (``[]`` clears them). Each label id must
    # belong to the card's board (checked in the router, 422 otherwise).
    priority: PriorityEnum | None = None
    due_date: datetime | None = None
    label_ids: Annotated[list[int] | None, Field(max_length=MAX_LABEL_IDS)] = None

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("title must not be empty")
        return v

    @field_validator("story_points")
    @classmethod
    def story_points_in_set(cls, v: int | None) -> int | None:
        if v is not None and v not in STORY_POINTS:
            raise ValueError(f"story_points must be one of {sorted(STORY_POINTS)} or null")
        return v


class CardBatchUpdateItem(CardUpdate):
    """One entry in a batch update (M5 V19, KAN-252): the same optional field edits
    as :class:`CardUpdate`, plus the required ``id`` of the card to patch. Column /
    position stay out (the move-vs-edit split, ADR 0006) — same as ``CardUpdate``."""

    id: int


class CardMove(BaseModel):
    column: ColumnEnum
    position: int | None = Field(default=None, ge=0)


class NeedsHumanRequest(BaseModel):
    """Flag a card as needing a human (M5 V13, KAN-246): ``POST
    /cards/{id}/needs-human`` with an optional ``attention_note`` describing the
    ask (the decision to make, the access that's missing, why a PR is stuck). The
    note is optional and, when given, must not be blank; omit it (or send null) to
    flag the card without a note."""

    attention_note: Annotated[str | None, Field(max_length=MAX_TEXT_LEN)] = None

    @field_validator("attention_note")
    @classmethod
    def note_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("attention_note must not be empty")
        return v


class LinkCreate(BaseModel):
    """Attach a work-link to a card (KAN-32): ``POST /cards/{id}/links`` with a
    ``label`` (e.g. "PR", "branch", "CI") and a ``url`` (the PR URL, branch, CI run,
    …). Both are required and non-empty."""

    label: Annotated[str, Field(min_length=1, max_length=MAX_LINK_LABEL_LEN)]
    url: Annotated[str, Field(min_length=1, max_length=MAX_URL_LEN)]

    @field_validator("label", "url")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


class LinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    url: str
    created_at: datetime


class LabelCreate(BaseModel):
    """Create a board-scoped label (M5 V11, KAN-244): ``POST /boards/{id}/labels``
    with a non-empty ``name`` and a ``color`` (an arbitrary string, typically a hex
    like ``#0ea5e9``). The board comes from the path, not the body."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    color: Annotated[str, Field(min_length=1, max_length=MAX_LABEL_COLOR_LEN)]

    @field_validator("name", "color")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("color")
    @classmethod
    def known_color(cls, v: str) -> str:
        """A palette token or a well-formed hex (V62, KAN-983).

        Before this, ``"banana"`` was a valid colour that rendered as a blank dot.
        Runs after :meth:`non_empty` (validators fire in declaration order), so an
        all-whitespace colour still reports the more specific "must not be empty"."""
        if not is_valid_label_color(v):
            raise ValueError(label_color_error())
        return v


class LabelUpdate(BaseModel):
    """Field edits for a label (V61, KAN-982): ``PATCH /labels/{id}``. Both fields
    optional — only sent fields are applied, via ``exclude_unset`` in the router.

    Neither field is nullable: a label with no name or no colour cannot render, so
    ``null`` is rejected rather than treated as "clear". That is the difference from
    :class:`EpicUpdate`, whose ``target_date``/``lead`` are genuinely clearable."""

    name: Annotated[str | None, Field(min_length=1, max_length=MAX_NAME_LEN)] = None
    color: Annotated[
        str | None, Field(min_length=1, max_length=MAX_LABEL_COLOR_LEN)
    ] = None

    @field_validator("name", "color")
    @classmethod
    def not_null_and_not_blank(cls, v: str | None) -> str:
        """Reject an explicit ``null`` as well as whitespace.

        This leans on a Pydantic v2 behaviour worth naming, because the whole
        distinction rests on it: field validators do **not** run for a field left at
        its default (``validate_default`` is False), so this fires only when the key
        was actually sent. That is what lets one optional field mean "not sent" while
        still refusing ``{"name": null}``.

        Without the null branch, an explicit null validated cleanly, survived
        ``exclude_unset`` (it *was* set), and reached ``setattr`` — turning a bad
        request into a ``NOT NULL`` violation at COMMIT. A 500, not a 422."""
        if v is None:
            raise ValueError("must not be null; omit the field to leave it unchanged")
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("color")
    @classmethod
    def known_color(cls, v: str) -> str:
        """The same palette rule as :class:`LabelCreate` (V62, KAN-983).

        Recolouring is the operation this milestone is *for*, so validating create
        but not update would leave the wider hole open. It fires only when ``color``
        was actually sent, so a label still carrying a legacy free-string colour can
        be renamed without being forced onto the palette — which is what keeps this
        slice free of a value migration (SHAPING D11)."""
        if not is_valid_label_color(v):
            raise ValueError(label_color_error())
        return v


class LabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    name: str
    color: str
    created_at: datetime


class LabelReadWithUsage(LabelRead):
    """A label plus how many cards carry it (V61, KAN-982) — the management
    screen's list shape, and **only** that endpoint's.

    Deliberately a subclass rather than a field on :class:`LabelRead`, because
    ``LabelRead`` is embedded in :attr:`CardRead.labels`: putting the count there
    would add a redundant number to every label on every card in every card read —
    the per-call payload cost ADR 0019 is about — and would break card reads
    outright, since the ORM ``Label`` objects nested under a card carry no such
    attribute.

    ``usage_count`` exists to make deletion honest: deleting a label detaches it
    from every card via ``ON DELETE CASCADE``, and the confirm should say how many."""

    usage_count: int


class CommentCreate(BaseModel):
    """Post a note to a card (KAN-33): ``POST /cards/{id}/comments`` with a
    ``body``. Human/agent-authored intentional context — distinct from Epic 4's
    SYSTEM activity log. Required and non-empty; the author is taken from the
    request principal, never the body."""

    body: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LEN)]

    @field_validator("body")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body must not be empty")
        return v


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    body: str
    # The authoring user (UUID), or null once that user is deleted (SET NULL).
    author_id: uuid.UUID | None
    created_at: datetime


class CardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_number: str
    board_id: int
    # Board-local numbering (M8 V52, KAN-973). ``board_seq`` is a real column — the
    # ``14`` in ``ENG-14``, gapless within its board. ``ref`` is the rendered form,
    # populated by the router from the board's key (not an ORM column), mirroring
    # ``labels``/``links``; it needs the board row, which a card does not carry.
    #
    # ``ref`` is optional so a route that forgets to attach it returns null rather
    # than a 500 — and a test asserts every card-returning route fills it, which is
    # the half that actually keeps it honest.
    board_seq: int
    ref: str | None = None
    title: str
    description: str | None
    column: ColumnEnum
    position: int
    story_points: int | None
    assignee: str | None
    epic_id: int | None
    # The story's cycle/iteration (V33, KAN-297), or null when unassigned.
    cycle_id: int | None
    # Card fields (M5 V11, KAN-244). ``priority`` + ``due_date`` are real columns;
    # ``labels`` is populated by the router from the card_label join (not an ORM
    # column), mirroring ``links`` — empty when the card has none.
    priority: PriorityEnum
    due_date: datetime | None
    # Needs-human handoff flag (M5 V13, KAN-246). ``needs_human`` is the boolean
    # flag an agent raises when a card needs a human; ``attention_note`` is the
    # optional ask it left. Both are real columns, so from_attributes reads them
    # directly. A resolved card reads ``needs_human=false`` + ``attention_note=null``.
    needs_human: bool
    attention_note: str | None
    labels: list[LabelRead] = []
    # Card-to-card dependencies (KAN-28), populated by the router from the
    # card_dependency table (not ORM-mapped columns): ids of cards that block this
    # one, and ids of cards this one blocks. Empty when there are none.
    blocked_by: list[int] = []
    blocks: list[int] = []
    # Derived ready/blocked signal (KAN-29): True when this card has >=1 blocker
    # that is not yet in the ``done`` column — i.e. it is *not* actionable. A card
    # with no blockers, or whose every blocker is done, is ``blocked = False``
    # (ready). Computed by the router, not an ORM column; see ``GET /api/v1/cards``.
    blocked: bool = False
    # Work-links (KAN-32) — PR / branch / CI URLs pointing at the card's real work
    # state. Populated by the router from the card_link table (not ORM-mapped
    # columns). Empty when there are none.
    links: list[LinkRead] = []
    created_at: datetime
    updated_at: datetime


class CardTrashRead(CardRead):
    """A soft-deleted card on the trash listing path (KAN-20). Identical to
    :class:`CardRead` plus the ``deleted_at`` tombstone — exposed **only** here (the
    normal card reads stay unchanged), so the Trash view can show when each item was
    deleted and order by it."""

    deleted_at: datetime


class DependencyCreate(BaseModel):
    """Add a blocker to a card (KAN-28): ``POST /cards/{id}/dependencies`` with
    ``{"blocker_id": N}`` records that card ``{id}`` is *blocked-by* card ``N``."""

    blocker_id: int


class EpicCreate(BaseModel):
    """Create an epic (ADR 0009). Epics carry only a name + optional description —
    no column/position/assignee/story_points."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    description: Annotated[str | None, Field(max_length=MAX_DESCRIPTION_LEN)] = None
    # Target board (M3 V7); optional → default board when omitted (see CardCreate).
    board_id: int | None = None
    # Lightweight project fields (V31, KAN-295). ``target_date`` is an optional
    # target/ship date; ``lead`` an optional free-text owner. Both optional → NULL.
    target_date: datetime | None = None
    lead: Annotated[str | None, Field(max_length=MAX_LEAD_LEN)] = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class EpicUpdate(BaseModel):
    """Field edits for an epic. All optional — only sent fields are applied.

    ``target_date`` / ``lead`` (V31, KAN-295) accept a value to set, or ``null`` to
    clear (the router applies only the fields actually sent, via ``exclude_unset``)."""

    name: Annotated[str | None, Field(max_length=MAX_NAME_LEN)] = None
    description: Annotated[str | None, Field(max_length=MAX_DESCRIPTION_LEN)] = None
    target_date: datetime | None = None
    lead: Annotated[str | None, Field(max_length=MAX_LEAD_LEN)] = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("name must not be empty")
        return v


class EpicHealth(str, Enum):
    """Derived health signal for an epic (V32, KAN-296). ``on_track`` / ``at_risk``
    / ``overdue`` — computed from ``target_date`` vs. remaining child work; ``null``
    (absent) when the epic has no ``target_date``. See ``app.epic_rollup``."""

    on_track = "on_track"
    at_risk = "at_risk"
    overdue = "overdue"


class EpicProgress(BaseModel):
    """Derived rollup over an epic's **non-deleted** child cards (V32, KAN-296):
    ``done`` of ``total``, and ``percent`` = round(done/total*100) (``0`` when the
    epic has no children). Computed on read — no stored column, no migration."""

    total: int
    done: int
    percent: int


class EpicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_number: str
    board_id: int
    # Board-local numbering (M8 V52, KAN-973), on the epic's **own** per-board
    # sequence rather than the cards' (SHAPING D4). ``board_seq`` is a real column;
    # ``ref`` renders as ``ENG-E7`` and is attached by the router. Same optionality
    # rationale as :class:`CardRead`.
    board_seq: int
    ref: str | None = None
    name: str
    description: str | None
    # Lightweight project fields (V31, KAN-295) — real columns, read directly.
    target_date: datetime | None
    lead: str | None
    # Derived progress rollup + health signal (V32, KAN-296) — NOT stored columns;
    # the epics router attaches them per read from a grouped child-card COUNT +
    # ``app.epic_rollup.compute_rollup``. ``health`` is null when target_date is unset.
    progress: EpicProgress
    health: EpicHealth | None = None
    created_at: datetime
    updated_at: datetime


class EpicTrashRead(EpicRead):
    """A soft-deleted epic on the trash listing path (KAN-20). :class:`EpicRead` plus
    the ``deleted_at`` tombstone, exposed only here (normal epic reads unchanged)."""

    deleted_at: datetime


class BoardCreate(BaseModel):
    """Create a board (M3 V7, ADR 0012). The owner is set from the session, not the
    request body.

    ``key`` (M8 V51, KAN-972) is the short prefix a board-local ticket ref is built
    from — the ``ENG`` in ``ENG-14``. **Optional, and omitting it is the normal
    case**: the router derives one from the name and suffixes on collision, because
    creating a board must never block on naming (R1.4). Supplying one asks for that
    exact key, so it is the only path that can fail — a malformed or reserved key is
    a ``422`` here, and a key already used by this owner is a ``409`` in the router.

    ``team_id`` (M9 V67, KAN-1056; ADR 0021) optionally links the new board to a
    team. Omitted → ``team_id = NULL``, i.e. today's behavior, byte-for-byte. The
    router 403s if the creating principal isn't a member of the named team (any
    role) — "you don't get to point a create at something you can't touch",
    mirroring ``_validate_epic``'s pattern but at 403 since the boundary here is
    membership, not shape.
    """

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    key: Annotated[str | None, Field(max_length=MAX_BOARD_KEY_LEN)] = None
    team_id: int | None = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v

    @field_validator("key")
    @classmethod
    def key_well_formed(cls, v: str | None) -> str | None:
        return _validate_board_key(v)


class BoardUpdate(BaseModel):
    """Rename a board and/or toggle its auto-sync opt-ins (KAN-43). ``name`` is the
    only renamable field; ownership isn't reassignable here. ``autosync_enabled``
    turns the GitHub-webhook card auto-sync on for this board (default OFF);
    ``autosync_advance_to_done`` separately allows PR-merge to move a card to
    ``done``. All optional — only the fields sent are applied.

    Outbound signed webhook (V38, KAN-302) — mirrors the autosync opt-in:
    ``outbound_webhook_enabled`` turns on a signed ``POST`` on every notification-create;
    ``outbound_webhook_url`` is the target; ``outbound_webhook_secret`` keys the
    HMAC-SHA256 signature and is **write-only** (accepted here, never echoed back in
    ``BoardRead``). Send ``null`` for the url/secret to clear it.

    ``team_id`` (M9 V67, KAN-1056; ADR 0021) sets or clears the board's team link —
    unlike ``key``, ``null`` here is meaningful (clears the link back to a personal
    board) rather than rejected, mirroring the webhook fields above. Setting it to
    a non-null value 403s if the caller isn't a member of that team (any role),
    same as on create."""

    name: Annotated[str | None, Field(max_length=MAX_NAME_LEN)] = None
    key: Annotated[str | None, Field(max_length=MAX_BOARD_KEY_LEN)] = None
    autosync_enabled: bool | None = None
    autosync_advance_to_done: bool | None = None
    outbound_webhook_url: Annotated[str | None, Field(max_length=MAX_URL_LEN)] = None
    outbound_webhook_secret: Annotated[
        str | None, Field(max_length=MAX_WEBHOOK_SECRET_LEN)
    ] = None
    outbound_webhook_enabled: bool | None = None
    team_id: int | None = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("name must not be empty")
        return v

    @field_validator("outbound_webhook_url", "outbound_webhook_secret")
    @classmethod
    def webhook_field_non_blank(cls, v: str | None) -> str | None:
        # Allow ``null`` (clear), but a provided value must not be blank whitespace.
        if v is not None and not v.strip():
            raise ValueError("must not be empty (send null to clear)")
        return v

    @field_validator("key")
    @classmethod
    def key_well_formed(cls, v: str | None) -> str | None:
        """A board key is **not clearable** — unlike the webhook fields above.

        Every board has a key (the column is NOT NULL, because V52's board-local
        refs cannot render without one), so ``null`` here can only mean "not sent".
        Relying on the same Pydantic behaviour :class:`LabelUpdate` documents: a
        field validator does not run for a field left at its default, so this fires
        only when the key was really sent, which is what lets one optional field
        mean "unchanged" while still refusing an explicit ``null``."""
        if v is None:
            raise ValueError(
                "key must not be null; omit the field to leave it unchanged"
            )
        return _validate_board_key(v)


class RoleEnum(str, Enum):
    viewer = "viewer"
    editor = "editor"
    owner = "owner"


class BoardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    # The board's short ref prefix (V51) — the ``ENG`` in ``ENG-14``. Unique per
    # owner, not globally (ADR 0020), so this value alone does not identify a board
    # across users; the canonical ``KAN-…`` ticket remains the cross-board address.
    key: str
    # The owning user (UUID), or null for an unclaimed board (e.g. the migrated
    # default board). Server-enforced ownership checks arrive in V8.
    owner_id: uuid.UUID | None
    # The linked team (M9 V67, KAN-1056; ADR 0021), or null for a personal board —
    # every board's meaning before this slice, and still the default. A real ORM
    # column (unlike ``role``/``owner_email`` below), so this reads straight off
    # the model with no router-side attachment.
    team_id: int | None
    # Auto-sync opt-ins (KAN-43); both default false.
    autosync_enabled: bool
    autosync_advance_to_done: bool
    # Outbound signed webhook (V38, KAN-302): the opt-in flag + the target URL are
    # readable (a settings UI needs them), but ``outbound_webhook_secret`` is
    # **deliberately absent** — it is write-only (set via BoardUpdate, never returned),
    # exactly like a password.
    outbound_webhook_url: str | None
    outbound_webhook_enabled: bool
    # The *caller's* effective role on this board (KAN-15): "owner" if they own it,
    # else their board_member role (viewer/editor). Attached transiently by the
    # list router (not an ORM column), mirroring MemberRead.email; the switcher
    # uses it to badge shared boards. Null when the router doesn't compute it.
    role: RoleEnum | None = None
    # The board owner's email (V53, KAN-974), attached transiently like ``role``.
    # Null for an unclaimed board, and null when the router doesn't compute it.
    #
    # It exists because a board key is unique per *owner*, so a viewer who can see
    # two `ENG` boards needs the owner to tell them apart — that is the
    # ``alice/ENG-14`` qualifier V53 resolves and V54 prints, and neither is possible
    # from ``owner_id`` alone (a UUID is not a handle a human types).
    #
    # **The privacy question, answered rather than assumed:** every board a caller can
    # read is one they own or are a member of, and ``MemberRead.email`` already shows
    # a board's members their addresses. So this exposes nothing that co-membership
    # did not already expose. It is not on any unauthenticated or cross-board path.
    owner_email: str | None = None
    created_at: datetime
    updated_at: datetime


class MemberCreate(BaseModel):
    """Add a member to a board (KAN-12): identify the user by **either** ``user_id``
    or ``email`` (exactly one), with a ``role`` (defaults to ``viewer``). The user
    must already exist; the router resolves the identity and returns 404 otherwise."""

    user_id: uuid.UUID | None = None
    email: Annotated[str | None, Field(max_length=MAX_EMAIL_LEN)] = None
    role: RoleEnum = RoleEnum.viewer

    @field_validator("email")
    @classmethod
    def email_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("email must not be empty")
        return v

    @model_validator(mode="after")
    def exactly_one_identity(self) -> MemberCreate:
        if (self.user_id is None) == (self.email is None):
            raise ValueError("provide exactly one of user_id or email")
        return self


class MemberUpdate(BaseModel):
    """Change a member's role (KAN-12)."""

    role: RoleEnum


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    user_id: uuid.UUID
    # The member's email, populated by the router from the user table (not an ORM
    # column on board_member) so the list is human-readable for the coming UI.
    email: str | None = None
    role: RoleEnum
    created_at: datetime
    updated_at: datetime


class TeamCreate(BaseModel):
    """Create a team (M9 V65, KAN-1054; ADR 0021). The creator is auto-added as an
    owner-role team_member by the router — the same bootstrap
    ``app.authz.authorize_board`` already gives a board's creator."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    # The caller's effective role on this team (viewer/editor/owner), attached
    # transiently by the router (not an ORM column) — mirrors BoardRead.role.
    # Unlike a board a team has no owner analogue: every team a caller can see is
    # one they're a member of (visible_team_ids IS membership), so this is never
    # null on a list/get response reached through the router.
    role: RoleEnum | None = None
    created_at: datetime
    updated_at: datetime


class TeamUpdate(BaseModel):
    """Rename a team (M9 V66, KAN-1055). Owner-role members only. Renaming does not
    touch any board's ``team_id`` — a team's boards are a separate pointer
    (``board.team_id``) that this schema has no field for."""

    name: Annotated[str | None, Field(max_length=MAX_NAME_LEN)] = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("name must not be empty")
        return v


class TeamMemberCreate(BaseModel):
    """Add a member to a team (M9 V66, KAN-1055): identify the user by **either**
    ``user_id`` or ``email`` (exactly one), with a ``role`` (defaults to
    ``viewer``). Mirrors ``MemberCreate`` (board membership) exactly."""

    user_id: uuid.UUID | None = None
    email: Annotated[str | None, Field(max_length=MAX_EMAIL_LEN)] = None
    role: RoleEnum = RoleEnum.viewer

    @field_validator("email")
    @classmethod
    def email_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("email must not be empty")
        return v

    @model_validator(mode="after")
    def exactly_one_identity(self) -> TeamMemberCreate:
        if (self.user_id is None) == (self.email is None):
            raise ValueError("provide exactly one of user_id or email")
        return self


class TeamMemberUpdate(BaseModel):
    """Change a team member's role (M9 V66, KAN-1055)."""

    role: RoleEnum


class TeamMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_id: int
    user_id: uuid.UUID
    # The member's email, populated by the router from the user table (not an ORM
    # column on team_member) — mirrors MemberRead.email.
    email: str | None = None
    role: RoleEnum
    created_at: datetime
    updated_at: datetime


class ActivityRead(BaseModel):
    """One append-only audit record of a board-domain mutation (KAN-17 write path,
    KAN-18 read side). Mirrors the ``Activity`` model's real columns; there is no
    ``ticket_number`` on an activity row (``entity_id`` is a plain int, the entity
    may already be deleted) — the human ticket, when there is one, is embedded in
    ``summary`` (e.g. ``"created KAN-3: Fix login"``)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    # The acting user (UUID), or null once that user is deleted (SET NULL).
    actor_user_id: uuid.UUID | None
    # Denormalised human handle for the actor (email / assignee), survives deletion.
    actor_label: str | None
    entity_type: str
    entity_id: int
    action: str
    summary: str
    ts: datetime


class NotificationRead(BaseModel):
    """One inbox notification for a board owner (V37, KAN-301). Mirrors the
    ``Notification`` model's real columns. ``kind`` ∈ {needs_human, blocked,
    ci_failed, assigned}; ``read_at`` is null while unread. Poll/pull only (ADR
    0007) — there is no push channel; a client polls ``GET /notifications``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    # The recipient (UUID) — always the current caller on the owner-scoped list.
    user_id: uuid.UUID
    board_id: int
    card_id: int | None
    kind: str
    body: str
    read_at: datetime | None
    created_at: datetime


# --- the acting principal (KAN-530) ----------------------------------------


class PrincipalRead(BaseModel):
    """Who the caller is — the response of ``GET /api/v1/me`` (KAN-530).

    Deliberately the **minimum** a consumer needs to key a local record off a
    pandan identity: the user's UUID and their email. Every extra field here
    becomes a cross-app contract that is awkward to withdraw, so add one only with
    a consumer that needs it (the resolved principal is a full ``User``, so more is
    always available if that day comes).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str


class TokenScope(str, Enum):
    """A PAT's capability (M5 V18, KAN-251). ``read`` = observer (GET only);
    ``write`` = operator (the owning user's full board access, the default)."""

    read = "read"
    write = "write"


class TokenCreate(BaseModel):
    """Create a personal access token (M3 V9, ADR 0014). Only a name, an optional
    scope (default ``write`` for back-compat), and an optional expiry; the secret is
    server-generated, never client-supplied."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    scope: TokenScope = TokenScope.write
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class TokenRead(BaseModel):
    """Token metadata — never includes the secret (only shown once, on create)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    scope: TokenScope
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


class TokenCreated(TokenRead):
    """The create-only response: metadata **plus** the raw secret, returned
    exactly once. The client must copy it now — it is not stored and cannot be
    retrieved again (R7.1)."""

    token: str


class DispatchRequest(BaseModel):
    """Optional body for ``POST /boards/{id}/dispatch`` (M5 V12, KAN-245). All
    fields optional: ``assignee`` is who to claim the selected card as (defaults to
    the caller's own identity); ``label`` (a label id) and ``priority`` (a
    **minimum** priority — cards at that rank or above) narrow which ready card is
    chosen. An empty/absent body dispatches the next ready card to the caller."""

    assignee: Annotated[str | None, Field(max_length=MAX_ASSIGNEE_LEN)] = None
    label: int | None = None
    priority: PriorityEnum | None = None


# --- board metrics (M5 V17, KAN-250) ---------------------------------------
# All derived from the activity feed + card timestamps (no new writes). See
# ``app.metrics.compute_metrics`` for how each number is computed, and
# ``GET /api/v1/boards/{id}/metrics`` (routers/boards.py) for the endpoint.


class CycleTimeMetrics(BaseModel):
    """Cycle-time distribution (seconds) for cards completed in the period —
    time from a card's first ``in_progress`` to its ``done``. All-null when no
    completed card in the period had a recorded ``in_progress`` (``count`` 0)."""

    count: int
    avg_seconds: float | None = None
    median_seconds: float | None = None
    p90_seconds: float | None = None


class AgingWipItem(BaseModel):
    """One card currently ``in_progress`` and how long it has sat there."""

    card_id: int
    ticket_number: str
    # The board-local ref (V54, KAN-975) so the dashboard's aging bars label cards the
    # same way every other surface does. Optional for the same reason ``CardRead.ref``
    # is: it is rendered, not stored.
    ref: str | None = None
    assignee: str | None = None
    age_seconds: float


class AgingWipMetrics(BaseModel):
    """Age of the current work-in-progress: how long each in-flight card has been
    ``in_progress`` (from its last move there). Zeros/nulls + empty ``items`` when
    nothing is in progress."""

    count: int
    avg_seconds: float | None = None
    max_seconds: float | None = None
    items: list[AgingWipItem] = []


class AssigneeMetrics(BaseModel):
    """Per-assignee breakdown — the "which agent did what" view. ``throughput`` is
    cards this assignee completed in the period; ``wip`` is cards it currently holds
    ``in_progress``. ``assignee`` is null for unassigned cards."""

    assignee: str | None = None
    throughput: int
    wip: int


class BoardMetricsRead(BaseModel):
    """Derived fleet-reporting metrics for a board over a period (M5 V17, KAN-250).

    Entirely computed from the activity feed + card timestamps — no stored metric,
    no migration. ``since``/``until`` bound the reporting period (``since`` null →
    all time); ``generated_at`` is the server clock at computation (also the aging
    reference). ``throughput`` is the count of cards that reached ``done`` in the
    period."""

    board_id: int
    generated_at: datetime
    since: datetime | None = None
    until: datetime
    throughput: int
    cycle_time: CycleTimeMetrics
    aging_wip: AgingWipMetrics
    by_assignee: list[AssigneeMetrics] = []


# --- query grammar + saved views (M5 V14, KAN-247) --------------------------
#
# The "JQL-lite" filter+sort grammar shared by GET /cards and saved views. Kept
# here (plain strings, no SQL) so both the ``CardQuery`` validator below and the
# SQL sort builder (``app/card_query.py``) share one definition of the sortable
# fields — no drift between "what's a valid sort" and "how it's ordered".

# Allowlisted card sort fields. A leading ``-`` in a sort spec means descending;
# ``priority`` sorts by *rank* (none→urgent), not alphabetically (see card_query).
CARD_SORT_FIELDS = (
    "position",
    "priority",
    "due_date",
    "created_at",
    "updated_at",
    "story_points",
    "assignee",
    "title",
    "column",
    "id",
)


def parse_sort_spec(sort: str) -> list[tuple[str, bool]]:
    """Parse a comma-separated ``sort`` spec into ``(field, descending)`` pairs.

    ``"priority"`` → ascending; ``"-due_date"`` → descending;
    ``"-priority,position"`` → two keys. Raises ``ValueError`` on an empty or
    unknown field so both the schema validator (422) and the SQL builder reject
    the same bad input identically."""
    keys: list[tuple[str, bool]] = []
    for raw in sort.split(","):
        token = raw.strip()
        if not token or token == "-":
            raise ValueError("empty sort key")
        descending = token.startswith("-")
        field = token[1:] if descending else token
        if field not in CARD_SORT_FIELDS:
            raise ValueError(
                f"unknown sort field {field!r}; valid fields: {', '.join(CARD_SORT_FIELDS)}"
            )
        keys.append((field, descending))
    return keys


class CardQuery(BaseModel):
    """The structured filter+sort grammar (M5 V14, KAN-247) shared by ``GET
    /cards`` and saved views.

    Every field is optional and its name matches the ``GET /cards`` query param
    exactly, so a saved view's stored ``query`` replays verbatim as query params —
    that's what makes "a view's query reproduces its result set" hold by
    construction. Stored as JSON on ``saved_view.query``. ``extra='forbid'`` so a
    stored query can't smuggle an unknown key past validation."""

    model_config = ConfigDict(extra="forbid")

    column: ColumnEnum | None = None
    epic_id: int | None = None
    # Filter to stories in one cycle/iteration (V33, KAN-297); mirrors ``epic_id``.
    cycle_id: int | None = None
    priority: PriorityEnum | None = None
    label: int | None = None
    due_before: datetime | None = None
    overdue: bool | None = None
    needs_human: bool | None = None
    assignee: Annotated[str | None, Field(max_length=MAX_ASSIGNEE_LEN)] = None
    # Free-text search over title+description (M5 V15, KAN-248). A plain string —
    # ``GET /cards`` treats empty/whitespace as absent, so a saved view can carry a
    # search term and replay verbatim.
    q: Annotated[str | None, Field(max_length=MAX_SEARCH_LEN)] = None
    sort: str | None = None

    @field_validator("sort")
    @classmethod
    def sort_is_valid(cls, v: str | None) -> str | None:
        if v is not None:
            parse_sort_spec(v)  # raises ValueError (→ 422) on a bad field
        return v


class SavedViewCreate(BaseModel):
    """Create a saved view (M5 V14, KAN-247): a named, persisted card query on a
    board. ``name`` is required non-empty; ``query`` is the structured filter+sort
    grammar (``CardQuery``), stored as JSON and replayable against ``GET /cards``.
    Omit ``query`` for an unfiltered "all cards" view."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    query: CardQuery = Field(default_factory=CardQuery)

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class SavedViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    name: str
    # The stored filter+sort grammar as JSON (``{}`` = no filters). A plain dict
    # so it round-trips exactly what was stored, ready to replay as query params.
    query: dict[str, Any]
    created_at: datetime


class TemplateCardItem(BaseModel):
    """One card in a card template (M5 V19, KAN-252) — the creatable card fields,
    minus ``board_id`` (the board comes from the template's path on apply). Mirrors
    :class:`CardCreate`'s field set + validation; ``title`` is required non-empty."""

    title: Annotated[str, Field(min_length=1, max_length=MAX_TITLE_LEN)]
    description: Annotated[str | None, Field(max_length=MAX_DESCRIPTION_LEN)] = None
    column: ColumnEnum = ColumnEnum.todo
    story_points: int | None = None
    assignee: Annotated[str | None, Field(max_length=MAX_ASSIGNEE_LEN)] = None
    epic_id: int | None = None
    priority: PriorityEnum = PriorityEnum.none
    due_date: datetime | None = None
    label_ids: Annotated[list[int] | None, Field(max_length=MAX_LABEL_IDS)] = None

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v

    @field_validator("story_points")
    @classmethod
    def story_points_in_set(cls, v: int | None) -> int | None:
        if v is not None and v not in STORY_POINTS:
            raise ValueError(f"story_points must be one of {sorted(STORY_POINTS)} or null")
        return v


class CardTemplateCreate(BaseModel):
    """Create a card template (M5 V19, KAN-252): a named, reusable plan of cards on a
    board. ``name`` is required non-empty; ``cards`` is a non-empty list of
    :class:`TemplateCardItem`, capped at ``MAX_TEMPLATE_CARDS`` (V28, KAN-292).
    Applying the template instantiates those cards on the board in one transaction."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    cards: Annotated[
        list[TemplateCardItem], Field(min_length=1, max_length=MAX_TEMPLATE_CARDS)
    ]

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class CardTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    name: str
    # The stored list of card payloads as JSON — round-trips exactly what was stored.
    cards: list[dict[str, Any]]
    created_at: datetime


# --- cycles / iterations (V33, KAN-297) ------------------------------------


class CycleCreate(BaseModel):
    """Create a cycle (a board-scoped, time-boxed iteration). ``name`` is required
    non-empty; ``starts_on`` / ``ends_on`` are optional ISO-8601 iteration bounds.
    The board comes from the path (``/boards/{id}/cycles``), not the body."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    starts_on: datetime | None = None
    ends_on: datetime | None = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class CycleUpdate(BaseModel):
    """Field edits for a cycle (V55, KAN-976): ``PATCH /boards/{id}/cycles/{cid}``.

    All three fields are optional — only the keys actually sent are applied, via
    ``exclude_unset`` in the router.

    **The three fields are deliberately not tri-state in the same way**, and the
    split mirrors :class:`LabelUpdate` vs :class:`EpicUpdate`:

    * ``name`` is **not nullable**. A cycle with no name cannot be listed or
      referred to, so an explicit ``null`` is a ``422`` rather than "clear it".
      Same Pydantic subtlety :class:`LabelUpdate` documents at length: a field
      validator does not run for a field left at its default, so this fires only
      when the key was really sent — which is what lets one optional field mean
      "not sent" while still refusing ``{"name": null}``.
    * ``starts_on`` / ``ends_on`` **are** nullable, because a cycle with no bounds
      is already a valid cycle (:class:`CycleCreate` makes both optional, and
      ``cycle metrics`` burns down to an empty series when they are absent). So
      ``null`` here genuinely means *unschedule*, and is not an error.

    Cycle **bounds are not order-checked** (``ends_on`` before ``starts_on`` is
    accepted). ``CycleCreate`` does not check it either, and adding the rule on the
    edit path alone would make the one operation that exists to *fix* a mistyped
    date the only one that can be refused by an already-stored value.
    """

    name: Annotated[str | None, Field(min_length=1, max_length=MAX_NAME_LEN)] = None
    starts_on: datetime | None = None
    ends_on: datetime | None = None

    @field_validator("name")
    @classmethod
    def name_not_null_and_not_blank(cls, v: str | None) -> str:
        if v is None:
            raise ValueError("must not be null; omit the field to leave it unchanged")
        if not v.strip():
            raise ValueError("name must not be empty")
        return v


class CycleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    name: str
    starts_on: datetime | None
    ends_on: datetime | None
    created_at: datetime


# --- cycle metrics: burndown / velocity (V34, KAN-298) ---------------------
# Derived from the cycle's card state (story points + column) + the ``done``
# transition times in the activity feed — no stored metric, no migration. See
# ``app.metrics.compute_cycle_metrics`` and
# ``GET /api/v1/boards/{id}/cycles/{cid}/metrics`` (routers/cycles.py).


class WorkTotals(BaseModel):
    """A count of stories and their summed story points (``points`` treats an
    unestimated story as 0)."""

    count: int
    points: int


class BurndownPoint(BaseModel):
    """One calendar day of the cycle window: work still ``remaining``, work
    ``completed`` cumulatively by that day, and the linear ``ideal`` reference
    line. All in the cycle's chosen unit (points, or card count when unestimated)."""

    date: str  # ISO-8601 calendar day (YYYY-MM-DD, UTC)
    remaining: float
    completed: float
    ideal: float


class CycleMetricsRead(BaseModel):
    """Derived burndown / velocity metrics for one cycle (V34, KAN-298).

    Entirely computed from the cycle's current card state + the activity feed —
    no stored metric, no migration. ``committed`` is the work assigned to the
    cycle; ``completed`` the subset currently ``done``; ``velocity`` the completed
    story points. ``unit`` is ``"points"`` when the cycle has any estimated work,
    else ``"count"`` — the unit ``burndown`` is expressed in. ``burndown`` is empty
    when the cycle has no dated ``starts_on`` / ``ends_on`` window."""

    board_id: int
    cycle_id: int
    generated_at: datetime
    starts_on: datetime | None = None
    ends_on: datetime | None = None
    committed: WorkTotals
    completed: WorkTotals
    velocity: int
    unit: str
    burndown: list[BurndownPoint] = []
