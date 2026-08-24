"""Board keys — the short, per-owner prefix a board-local ticket ref is built from
(M8 V51, KAN-972; ADR 0020).

A board key is the ``ENG`` in ``ENG-14``. It is **unique per owner, not globally**
(SHAPING D2): at a hundred users a global namespace would have people fighting over
``ENG``, and every good short key would be gone within the first dozen signups. The
consequence is the important part — a board-local ref only ever resolves *inside a
known board* (SHAPING D3), which is exactly why the canonical, globally unique
``KAN-955`` is kept beside it rather than replaced by it (D1).

This module is the single source of truth for three things:

1. **The shape.** ``^[A-Z][A-Z0-9]{1,9}$``. No hyphens, and that is load-bearing
   rather than tidy: it means a ref splits unambiguously on its **first** hyphen —
   head is the key, an all-digit tail is a card, an ``E``+digits tail is an epic
   (SHAPING D5). The leading letter keeps a key from ever looking like a number.
2. **The reserved words.** ``KAN`` and ``EPIC``, case-insensitively, so a board key
   can never shadow the canonical form and D3's two-row table stays decidable by
   inspection.
3. **Derivation**, because creating a board must never block on naming (R1.4). A
   board created with no key gets one from its name, and a collision inside that
   owner's namespace takes a numeric suffix rather than an error.

Derivation is deliberately dumb and therefore predictable — a user who does not
like the result renames the key, which is a one-call fix:

    "Engine Room"        → ENG
    "kopicode"           → KOP
    "kaya — Notes (MVP)" → KAY
    "2026 planning"      → PLA   (leading digits dropped; a key starts with a letter)
    "Q"                  → QX    (padded to the two-character minimum)
    "曜日"                → BRD   (nothing usable in ASCII; the fallback)

Note the reserved words go through the *same* collision path as a taken key: a
board named "Kanban" derives ``KAN``, finds it reserved, and lands on ``KAN2``. One
mechanism, so there is no second rule to keep in sync.
"""
from __future__ import annotations

import re

#: The wire shape of a board key. Enforced by :func:`is_valid_board_key`, by the
#: Pydantic schemas, and by a CHECK constraint in the migration — three places on
#: purpose, matching how ``card.column`` is guarded (ADR 0008).
BOARD_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,9}$"
_BOARD_KEY_RE = re.compile(BOARD_KEY_PATTERN)

#: Key length bounds, mirroring the pattern so callers need not parse the regex.
MIN_BOARD_KEY_LEN = 2
MAX_BOARD_KEY_LEN = 10

#: The canonical ticket prefixes (ADR 0006/0009). Reserved case-insensitively so a
#: board key can never shadow the global addressing mode (SHAPING D3/D5).
RESERVED_BOARD_KEYS = frozenset({"KAN", "EPIC"})

#: How many leading characters of a name become the derived key.
_DERIVED_LEN = 3

#: Used when a name yields nothing usable — no ASCII letter anywhere. "BRD" is a
#: legal key that reads as "board" and is not reserved.
_FALLBACK_KEY = "BRD"

#: Filler for a name that yields exactly one usable letter, since the pattern's
#: minimum is two. Padding beats falling back to ``BRD``: the user's own letter
#: survives, and they can rename it.
_PAD_CHAR = "X"


def is_valid_board_key(key: str) -> bool:
    """Whether ``key`` matches the wire shape. Does **not** check reservation or
    uniqueness — those are separate questions with separate answers (a reserved key
    is well-formed, and a taken key is both well-formed and unreserved)."""
    return bool(_BOARD_KEY_RE.fullmatch(key))


def is_reserved_board_key(key: str) -> bool:
    """Whether ``key`` collides with a canonical ticket prefix, case-insensitively."""
    return key.upper() in RESERVED_BOARD_KEYS


def board_key_error() -> str:
    """The 422 message for a malformed key. One sentence, and it states the rule
    rather than echoing the regex — a caller who sent ``eng-1`` needs to know that
    keys are uppercase and hyphen-free, not to read a character class."""
    return (
        f"key must be {MIN_BOARD_KEY_LEN}-{MAX_BOARD_KEY_LEN} characters, start with "
        "an uppercase letter and contain only uppercase letters and digits "
        "(no hyphens, so a ticket ref splits on its first one)"
    )


def reserved_board_key_error(key: str) -> str:
    """The 422 message for a reserved key, naming what it would shadow."""
    return (
        f"key {key.upper()!r} is reserved: it is a canonical ticket prefix, and a "
        "board key that shadowed one would make a ticket reference ambiguous"
    )


def derive_board_key(name: str) -> str:
    """The key a board called ``name`` gets when the caller supplies none.

    Never raises and never returns an invalid key: every branch ends in something
    :func:`is_valid_board_key` accepts. It may return a *reserved* or *taken* key —
    resolving that is :func:`allocate_board_key`'s job, so this stays a pure
    function of the name and is trivial to test.
    """
    # ASCII alphanumerics only, uppercased. Everything else — spaces, em dashes,
    # brackets, non-Latin scripts — is dropped rather than transliterated: a
    # transliteration table is a dependency and a source of surprise, and the user
    # can always rename the key.
    alnum = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    # A key must start with a letter, so drop any leading digit run ("2026 planning"
    # → "PLA", not "202"). Digits are still legal after the first character.
    alnum = re.sub(r"^[0-9]+", "", alnum)
    if not alnum:
        return _FALLBACK_KEY
    candidate = alnum[:_DERIVED_LEN]
    if len(candidate) < MIN_BOARD_KEY_LEN:
        candidate = candidate.ljust(MIN_BOARD_KEY_LEN, _PAD_CHAR)
    return candidate


def allocate_board_key(name: str, taken: set[str] | frozenset[str]) -> str:
    """Derive a key for ``name`` that is neither reserved nor in ``taken``.

    ``taken`` is the keys already used **by this board's owner** — per-owner, never
    global (SHAPING D2). On collision the key takes a numeric suffix (``ENG`` →
    ``ENG2`` → ``ENG3``), because R1.4 says creating a board must never block on
    naming. Reserved keys walk the same path.

    Terminates: ``taken`` is finite, and the suffix grows without bound inside the
    10-character budget (a 3-character stem leaves room for millions).
    """
    base = derive_board_key(name)
    if not is_reserved_board_key(base) and base not in taken:
        return base
    suffix = 2
    while True:
        # Trim the stem, not the suffix, when the two together would overflow —
        # the suffix is what makes the key unique, so it is the half that must
        # survive intact.
        digits = str(suffix)
        stem = base[: MAX_BOARD_KEY_LEN - len(digits)]
        candidate = f"{stem}{digits}"
        if not is_valid_board_key(candidate):
            # Only reachable once the suffix has eaten the whole stem, which needs
            # ~10^8 boards under one owner sharing one stem. Raise rather than
            # return: writing a key that fails the CHECK constraint would surface
            # as an opaque IntegrityError far from the cause.
            raise RuntimeError(f"exhausted board keys for stem {base!r}")
        if not is_reserved_board_key(candidate) and candidate not in taken:
            return candidate
        suffix += 1
