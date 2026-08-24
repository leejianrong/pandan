"""Board-local ref rendering (M8 V52, KAN-973).

The rendering half of :mod:`app.board_seq` is pure, so it is pinned here; allocation
needs a database and lives in ``tests/integration/test_board_local_refs.py``.

What these assertions are really about is **decidability**. A board key has no
hyphens (ADR 0020), so a ref splits on its *first* hyphen and the tail then says what
kind of thing it is: all digits → a card, ``E`` + digits → an epic. V53 will parse
these; this is the other end of that contract, written down where the strings are
produced.
"""
from __future__ import annotations

import re

import pytest

from app.board_keys import BOARD_KEY_PATTERN
from app.board_seq import EPIC_REF_MARKER, card_ref, epic_ref


def test_card_and_epic_refs_render_as_documented():
    assert card_ref("ENG", 14) == "ENG-14"
    assert epic_ref("ENG", 7) == "ENG-E7"
    assert card_ref("KOP", 1) == "KOP-1"
    assert epic_ref("A1", 1000) == "A1-E1000"


@pytest.mark.parametrize("seq", [1, 9, 10, 77, 1000])
def test_a_ref_splits_on_its_first_hyphen_into_key_and_tail(seq):
    """The property V53's resolver will depend on. A key cannot contain a hyphen, so
    ``split("-", 1)`` recovers the key exactly, and the tail distinguishes the two
    entity kinds without any further context."""
    for ref, expected_tail in ((card_ref("ENG", seq), str(seq)), (epic_ref("ENG", seq), f"E{seq}")):
        head, tail = ref.split("-", 1)
        assert head == "ENG"
        assert tail == expected_tail
        assert re.fullmatch(BOARD_KEY_PATTERN, head)

    assert card_ref("ENG", seq).split("-", 1)[1].isdigit()
    epic_tail = epic_ref("ENG", seq).split("-", 1)[1]
    assert epic_tail.startswith(EPIC_REF_MARKER) and epic_tail[1:].isdigit()


def test_a_card_ref_can_never_be_read_as_an_epic_ref():
    """The one collision that would matter: if a card's tail could start with ``E``
    the two forms would be ambiguous. It cannot — a card's tail is a decimal
    integer."""
    for seq in range(1, 50):
        assert not card_ref("ENG", seq).split("-", 1)[1].startswith(EPIC_REF_MARKER)
