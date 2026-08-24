"""Board key derivation, shape and reservation (M8 V51, KAN-972; ADR 0020).

Pure functions, so this lives in ``tests/unit`` — no DB, no Docker. The API-level
questions (per-owner uniqueness, 422 vs 409, PATCH) are integration tests in
``tests/integration/test_boards.py``; what is pinned here is the *vocabulary* those
tests rely on.

Two of these assertions are load-bearing rather than illustrative and are marked as
such: the hyphen ban (SHAPING D5 — it is what makes a ticket ref splittable) and
the reserved prefixes (D3 — a board key that shadowed ``KAN`` would make a
reference ambiguous). Both would be easy to relax by accident while widening the
pattern for some other reason.
"""
from __future__ import annotations

import pytest

from app.board_keys import (
    MAX_BOARD_KEY_LEN,
    MIN_BOARD_KEY_LEN,
    RESERVED_BOARD_KEYS,
    allocate_board_key,
    derive_board_key,
    is_reserved_board_key,
    is_valid_board_key,
)

# --- the shape --------------------------------------------------------------


@pytest.mark.parametrize("key", ["EN", "ENG", "ENG2", "A1", "ABCDEFGHIJ", "K9"])
def test_valid_keys(key):
    assert is_valid_board_key(key)


@pytest.mark.parametrize(
    ("key", "why"),
    [
        ("E", "one character is below the minimum"),
        ("ABCDEFGHIJK", "eleven characters is over the maximum"),
        ("eng", "lowercase"),
        ("1NG", "must start with a letter"),
        ("EN G", "no spaces"),
        ("", "empty"),
        ("EN_G", "no underscores"),
    ],
)
def test_invalid_keys(key, why):
    assert not is_valid_board_key(key), why


def test_a_hyphen_is_never_a_valid_key_character():
    """Load-bearing (SHAPING D5), not stylistic. A hyphen-free key is what lets a
    ref split on its **first** hyphen — head is the key, an all-digit tail is a
    card, an ``E``+digits tail is an epic. Allow ``ENG-X`` as a key and
    ``ENG-X-14`` stops being decidable."""
    assert not is_valid_board_key("ENG-X")
    assert not is_valid_board_key("E-")
    assert not is_valid_board_key("A-1")


def test_bounds_agree_with_the_pattern():
    assert is_valid_board_key("A" * MIN_BOARD_KEY_LEN)
    assert is_valid_board_key("A" * MAX_BOARD_KEY_LEN)
    assert not is_valid_board_key("A" * (MIN_BOARD_KEY_LEN - 1))
    assert not is_valid_board_key("A" * (MAX_BOARD_KEY_LEN + 1))


# --- reservation ------------------------------------------------------------


def test_the_canonical_prefixes_are_reserved_case_insensitively():
    """Load-bearing (SHAPING D3): a board key that shadowed a canonical prefix
    would make ``KAN-14`` mean two things. Case-insensitive because the stored form
    is uppercase, so a lowercase ``kan`` must not sneak past on its way there."""
    assert RESERVED_BOARD_KEYS == {"KAN", "EPIC"}
    for spelling in ("KAN", "kan", "Kan", "EPIC", "epic", "EpIc"):
        assert is_reserved_board_key(spelling), spelling


def test_a_reserved_prefix_with_anything_appended_is_not_reserved():
    # Reservation is exact-match, not prefix-match: KAN2 cannot be confused with
    # KAN-2 (the hyphen ban is what guarantees that).
    assert not is_reserved_board_key("KAN2")
    assert not is_reserved_board_key("KANBAN")
    assert not is_reserved_board_key("EPICS")


# --- derivation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Engine Room", "ENG"),
        ("kopicode", "KOP"),
        ("kaya — Notes (MVP)", "KAY"),
        ("Pandan Roadmap", "PAN"),
        ("  spaced  out  ", "SPA"),
        ("2026 planning", "PLA"),  # leading digits dropped: a key starts with a letter
        ("v2", "V2"),             # a digit after the first character is legal
        ("Q", "QX"),              # one usable character, padded to the minimum
        ("曜日", "BRD"),           # nothing usable in ASCII → the fallback
        ("2026", "BRD"),          # digits only, and a key cannot start with one
        ("!!!", "BRD"),
    ],
)
def test_derivation_is_predictable(name, expected):
    assert derive_board_key(name) == expected


@pytest.mark.parametrize(
    "name",
    ["Engine Room", "曜日", "2026", "Q", "", "!!!", "x", "AAAAAAAAAAAAAAAAAAAA"],
)
def test_derivation_always_returns_a_valid_key(name):
    """The property that matters more than any single mapping above: derivation
    never raises and never produces something the column would reject."""
    assert is_valid_board_key(derive_board_key(name))


# --- allocation (derivation + collision) ------------------------------------


def test_allocation_returns_the_derived_key_when_free():
    assert allocate_board_key("Engine Room", set()) == "ENG"


def test_allocation_suffixes_on_collision_rather_than_failing():
    """R1.4: creating a board must never block on naming."""
    assert allocate_board_key("Engine Room", {"ENG"}) == "ENG2"
    assert allocate_board_key("Engine Room", {"ENG", "ENG2"}) == "ENG3"
    assert allocate_board_key("Engine Room", {"ENG", "ENG2", "ENG3"}) == "ENG4"


def test_a_reserved_derivation_walks_the_same_collision_path():
    """One mechanism for "cannot have this key", so there is no second rule to keep
    in sync. A board named "Kanban" derives KAN, finds it reserved, lands on KAN2."""
    assert allocate_board_key("Kanban", set()) == "KAN2"
    assert allocate_board_key("Kanban", {"KAN2"}) == "KAN3"
    assert allocate_board_key("Epic work", set()) == "EPI"  # EPI is not EPIC


def test_allocation_never_returns_a_reserved_or_taken_key():
    taken = {"ENG", "ENG2", "ENG3", "KAN2"}
    for name in ["Engine Room", "Kanban", "kopicode", "曜日", "Q"]:
        key = allocate_board_key(name, taken)
        assert is_valid_board_key(key)
        assert not is_reserved_board_key(key)
        assert key not in taken
