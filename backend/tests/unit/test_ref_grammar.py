"""The reference grammar is duplicated across two packages — proven, not trusted
(M8 V53, KAN-974).

``backend/app/board_seq.py`` parses references server-side; ``pandan-cli`` parses them
client-side. The CLI **must not** import the backend (that would invert ADR 0005 and
make a PyInstaller build impossible), so the grammar exists twice.

This test reads the CLI's source as **text** and compares its regexes and reserved-key
set to the backend's. It is the same technique ``test_palette.py`` uses for the
palette's four copies, and the direction is the same too: the *backend* test reads the
other tree, never the reverse, so no dependency is created in the direction that
matters.

The file's absence is a **skip**, not a failure — a wheel or PyInstaller build of the
backend carries no ``pandan-cli/``.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.board_keys import RESERVED_BOARD_KEYS

CLI_SOURCE = (
    pathlib.Path(__file__).resolve().parents[3] / "pandan-cli" / "pandan_cli" / "cli.py"
)


def _cli_text() -> str:
    if not CLI_SOURCE.exists():
        pytest.skip(f"{CLI_SOURCE} not present (backend-only checkout)")
    return CLI_SOURCE.read_text(encoding="utf-8")


def _assignment(source: str, name: str) -> str:
    """The right-hand side of a single-line ``name = ...`` assignment."""
    match = re.search(rf"^{re.escape(name)} = (.+)$", source, re.MULTILINE)
    assert match, f"{name} not found in {CLI_SOURCE.name}"
    return match.group(1).strip()


def test_the_cli_canonical_pattern_matches_the_backends():
    """Both must accept exactly ``KAN-<n>`` / ``EPIC-<n>``, case-insensitively. If
    these drift, one adapter resolves a reference the other rejects — and the CLI's
    standing rule is that it accepts everything it prints."""
    from app.board_seq import _CANONICAL_RE

    cli_rhs = _assignment(_cli_text(), "_TICKET_RE")
    assert r"^(KAN|EPIC)-(\d+)$" in cli_rhs
    assert "re.IGNORECASE" in cli_rhs
    assert _CANONICAL_RE.pattern == r"^(KAN|EPIC)-(\d+)$"
    assert _CANONICAL_RE.flags & re.IGNORECASE


def test_the_cli_board_local_pattern_matches_the_backends():
    from app.board_seq import _BOARD_LOCAL_RE

    cli_rhs = _assignment(_cli_text(), "_BOARD_LOCAL_RE")
    expected = r"^([A-Za-z][A-Za-z0-9]{1,9})-(E?)(\d+)$"
    assert expected in cli_rhs
    assert "re.IGNORECASE" in cli_rhs
    assert _BOARD_LOCAL_RE.pattern == expected
    assert _BOARD_LOCAL_RE.flags & re.IGNORECASE


@pytest.mark.parametrize(
    "key",
    [
        "EN", "ENG", "ENG2", "A1", "ABCDEFGHIJ", "K9", "BRD",   # valid keys
        "E", "ABCDEFGHIJK", "1NG", "EN G", "", "EN_G", "ENG-X",  # invalid keys
    ],
)
def test_a_reference_names_exactly_the_keys_a_board_can_hold(key):
    """Behavioural, not textual, because the two patterns are deliberately *not* the
    same string: a stored key is uppercase (``^[A-Z][A-Z0-9]{1,9}$``) while a
    reference is parsed case-insensitively, so a literal comparison would fail on a
    difference that is intended.

    What must hold is the equivalence: a key a board can hold is a key a reference can
    name, and nothing else is. A key that could be stored but never referenced would
    be unreachable; one that could be referenced but never stored would be a parse
    that can only ever miss.
    """
    from app.board_keys import is_valid_board_key
    from app.board_seq import parse_ref

    parsed = parse_ref(f"{key}-1")
    referenceable = parsed is not None and parsed.board_key == key.upper()
    assert referenceable == is_valid_board_key(key), key


def test_the_cli_reserves_the_same_keys():
    """Reserving ``KAN``/``EPIC`` is what makes "try canonical first" a total rule. If
    only one side reserved them, ``KAN-E7`` would parse differently in each."""
    cli_rhs = _assignment(_cli_text(), "_RESERVED_KEYS")
    for key in RESERVED_BOARD_KEYS:
        assert f'"{key}"' in cli_rhs, key
    # And nothing extra: an unequal set is a drift in the other direction.
    assert len(re.findall(r'"[A-Z0-9]+"', cli_rhs)) == len(RESERVED_BOARD_KEYS)
