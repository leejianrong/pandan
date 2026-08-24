"""Board-local sequence numbers and the refs rendered from them (M8 V52, KAN-973).

A board-local ref is ``<board.key>-<board_seq>`` for a card and
``<board.key>-E<board_seq>`` for an epic — ``ENG-14``, ``ENG-E7``. It is a *display*
form. The canonical, globally unique, immutable identifier is still
``ticket_number`` (``KAN-955`` / ``EPIC-7``), and nothing here touches it (SHAPING D1;
[ADR 0020](../../docs/adr/0020-board-keys.md)).

**Allocation is one statement, and the choice of mechanism inverts the usual advice.**

    UPDATE board SET next_card_seq = next_card_seq + :n WHERE id = :id
    RETURNING next_card_seq

A Postgres sequence never blocks and always leaves gaps on rollback; this counter
column briefly serialises concurrent writers to *one board* and is **gapless**.
Gapless is precisely what issue #280 asked for — "the numbers jump and are not
sequential (locally)" — so the property normally counted as a sequence's advantage is,
here, the defect being fixed (SHAPING D6). A sequence *object* per board was rejected
outright: that is DDL per board, and hundreds of them do not scale.

The row lock the ``UPDATE`` takes is held until the enclosing transaction ends, which
is the serialisation. Two consequences worth knowing rather than discovering:

* Allocate **as late as possible** in a create, so the lock is held briefly.
* Allocate a **range** for a batch (``:n`` > 1) rather than looping — one statement,
  one lock acquisition, and the numbers stay contiguous. ``apply_template`` is the
  only server-side batch create; the MCP's ``create_cards`` is a client-side loop over
  N HTTP posts, so it allocates one at a time by construction.

Nothing is ever decremented. A soft-deleted card keeps its number so that restoring it
cannot collide with a number since handed out (SHAPING D7).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from .board_keys import is_reserved_board_key

#: The epic marker inside a board-local ref: ``ENG-E7``. A single letter, and it sits
#: in the *tail* rather than the key, which is what keeps the split decidable — a key
#: has no hyphens (ADR 0020), so a ref splits on its first one and the tail is then
#: either all digits (a card) or ``E`` + digits (an epic).
EPIC_REF_MARKER = "E"


def _allocate(db: Session, board_id: int, column: str, count: int) -> list[int]:
    """Take ``count`` consecutive numbers from ``board.<column>``, in one statement.

    Returns them in ascending order. The column name is interpolated rather than
    bound because an identifier cannot be a bind parameter; it never comes from
    request data — only the two module-level callers below pass it.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    assert column in ("next_card_seq", "next_epic_seq"), column
    last = db.execute(
        text(
            f"UPDATE board SET {column} = {column} + :n "  # noqa: S608 - fixed identifiers
            "WHERE id = :board_id RETURNING " + column
        ),
        {"n": count, "board_id": board_id},
    ).scalar_one()
    return list(range(last - count + 1, last + 1))


def allocate_card_seqs(db: Session, board_id: int, count: int = 1) -> list[int]:
    """The next ``count`` board-local card numbers on ``board_id``, ascending."""
    return _allocate(db, board_id, "next_card_seq", count)


def allocate_epic_seqs(db: Session, board_id: int, count: int = 1) -> list[int]:
    """The next ``count`` board-local epic numbers on ``board_id``, ascending."""
    return _allocate(db, board_id, "next_epic_seq", count)


def card_ref(board_key: str, board_seq: int) -> str:
    """``ENG-14`` — a card's board-local ref."""
    return f"{board_key}-{board_seq}"


def epic_ref(board_key: str, board_seq: int) -> str:
    """``ENG-E7`` — an epic's board-local ref."""
    return f"{board_key}-{EPIC_REF_MARKER}{board_seq}"


# --- parsing and resolution (V53, KAN-974) ---------------------------------
# The inverse of the two renderers above, kept in the same module so the two halves
# of the contract cannot drift apart.


@dataclass(frozen=True)
class ParsedRef:
    """A reference, decomposed. ``canonical`` distinguishes the two scopes:

    * ``canonical=True`` — ``KAN-955`` / ``EPIC-7``. Globally unique, resolves from
      anywhere, no board context needed. ``board_key`` is ``None``.
    * ``canonical=False`` — ``ENG-14`` / ``ENG-E7``. Board-local, resolves **only
      within a known board** (SHAPING D3), because board keys are unique per owner
      and two users may each hold ``ENG``.

    ``owner`` carries the qualifier from ``alice/ENG-14``, which V54 prints when a
    viewer can see two boards with the same key. It is only meaningful on a
    board-local ref; ``alice/KAN-12`` does not parse, because the canonical form is
    already unambiguous and accepting a redundant qualifier would suggest it means
    something.
    """

    entity: str  # "card" | "epic"
    canonical: bool
    number: int
    board_key: str | None = None
    owner: str | None = None


# The grammar, as fragments, so the anchored parser and the free-text scanner below
# cannot drift into two different grammars.
_CANONICAL_PREFIXES = r"(KAN|EPIC)"
#: Mirrors ``board_keys.BOARD_KEY_PATTERN`` without its anchors.
_KEY = r"([A-Za-z][A-Za-z0-9]{1,9})"

#: The canonical form (ADR 0006/0009). Tried **first**, which is the whole reason
#: ``KAN``/``EPIC`` are reserved board keys (ADR 0020): with them reserved, no
#: board-local ref can ever shadow this pattern, so "canonical first" is a total
#: rule rather than a precedence hack.
_CANONICAL_RE = re.compile(rf"^{_CANONICAL_PREFIXES}-(\d+)$", re.IGNORECASE)

#: The board-local form. A key has no hyphens, so the split on the first hyphen is
#: unambiguous and the tail then decides the entity: all digits → a card, ``E`` +
#: digits → an epic (SHAPING D5).
_BOARD_LOCAL_RE = re.compile(rf"^{_KEY}-(E?)(\d+)$", re.IGNORECASE)

# The same two grammars, unanchored, for finding a reference *inside* free text — a
# git branch name, a PR title. The boundaries matter more here than in the anchored
# case: without the lookbehind, ``feature-eng-42`` would yield the key ``FEATURE``
# from ``e-42``… and without the trailing ``(?!\d)``, ``eng-4200`` would be read as
# ``ENG-42``. Both would attach a webhook to the wrong card.
_BOUNDARY = r"(?<![A-Za-z0-9])"
_CANONICAL_SCAN_RE = re.compile(
    rf"{_BOUNDARY}{_CANONICAL_PREFIXES}-(\d+)(?!\d)", re.IGNORECASE
)
_BOARD_LOCAL_SCAN_RE = re.compile(
    rf"{_BOUNDARY}{_KEY}-(E?)(\d+)(?!\d)", re.IGNORECASE
)

_CANONICAL_ENTITY = {"KAN": "card", "EPIC": "epic"}


def parse_ref(token: str) -> ParsedRef | None:
    """Parse one reference in any of the three accepted forms, or ``None``.

    ``None`` means "not a reference" — the caller decides whether that is a 422, a
    fall-through to a numeric id, or an unresolved selector. Parsing never touches
    the database and never decides whether the thing exists.
    """
    token = token.strip()
    if not token:
        return None

    owner: str | None = None
    if "/" in token:
        owner, _, token = token.partition("/")
        owner = owner.strip()
        token = token.strip()
        if not owner or not token:
            return None

    canonical = _CANONICAL_RE.match(token)
    if canonical:
        # An owner qualifier on a globally unique ref is meaningless, so it does not
        # parse rather than being silently ignored.
        if owner is not None:
            return None
        prefix, number = canonical.groups()
        return ParsedRef(
            entity=_CANONICAL_ENTITY[prefix.upper()],
            canonical=True,
            number=int(number),
        )

    local = _BOARD_LOCAL_RE.match(token)
    if local:
        key, marker, number = local.groups()
        if is_reserved_board_key(key):
            # Unreachable through a real board (the key is reserved) and already
            # handled above in its canonical spelling. Refuse rather than invent a
            # board-local reading of ``KAN-E7``.
            return None
        return ParsedRef(
            entity="epic" if marker else "card",
            canonical=False,
            number=int(number),
            board_key=key.upper(),
            owner=owner,
        )

    return None


def find_ref(*candidates: str | None) -> ParsedRef | None:
    """The first reference appearing anywhere in ``candidates`` — a branch name, a PR
    title (V53, KAN-974).

    Canonical is searched across **every** candidate before board-local is searched
    across any, so ``feat/kan-12-on-the-eng-9-board`` resolves to ``KAN-12`` and not
    to whichever form happens to appear first in the string. That ordering matters
    because the canonical form is the one that cannot be wrong: it needs no board
    context, so it can never attach a webhook to a coincidence.

    Board-local scanning is genuinely loose — ``release-2024`` parses as key
    ``RELEASE``, number 2024 — and it is meant to be. Nothing here decides that a
    board exists; the caller resolves the key against boards it is willing to touch,
    which for autosync means boards that opted in. A key nobody owns simply finds
    nothing.
    """
    for pattern, canonical in ((_CANONICAL_SCAN_RE, True), (_BOARD_LOCAL_SCAN_RE, False)):
        for text_value in candidates:
            if not text_value:
                continue
            match = pattern.search(text_value)
            if not match:
                continue
            if canonical:
                prefix, number = match.groups()
                return ParsedRef(
                    entity=_CANONICAL_ENTITY[prefix.upper()],
                    canonical=True,
                    number=int(number),
                )
            key, marker, number = match.groups()
            if is_reserved_board_key(key):
                continue
            return ParsedRef(
                entity="epic" if marker else "card",
                canonical=False,
                number=int(number),
                board_key=key.upper(),
            )
    return None


# **Resolution is deliberately not shared.** There is no ``resolve_ref(db, ref)``
# here, and an earlier draft of this slice had one before it was deleted unused. Each
# call site resolves against a *different* scope, and the scope is the whole of the
# problem:
#
# * the batch read scopes to the caller's visible boards, and resolves up to 100
#   selectors in ONE query — a per-ref helper would have made it 100;
# * auto-sync scopes to boards that opted into auto-sync, which is what supplies the
#   board context a webhook does not otherwise have;
# * the CLI scopes to the configured board, or to every visible board when there is
#   none, and turns "more than one" into a menu rather than an error.
#
# A shared resolver would take that scope as a parameter, which is to say it would be
# a thin wrapper around the two lines each caller already writes. The *grammar* is
# what must not be duplicated, and that is what lives here.
