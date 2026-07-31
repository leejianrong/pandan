"""Unit tests for the TOON encoder (V47, KAN-430 — ``pandan_cli/toon.py``).

These pin the *encoder*: the classification rules that decide whether an array
prints as a table, a keyed table or a list, the quoting rules, and the number
formatting. The higher-level promise — that ``--format toon`` and ``--format json``
describe the same data — lives in ``test_toon_format.py``.

Every expected string here was checked against the reference implementation
(``@toon-format/toon``) while the port was written; a full 36-case corpus,
including the real board payloads, came back byte-identical (see the V47 PR).
"""
from __future__ import annotations

import json

import pytest

from pandan_cli import toon

# --- scalars and quoting ----------------------------------------------------


def test_flat_object_is_one_line_per_key():
    assert toon.encode({"a": 1, "b": "two", "c": True, "d": None}) == (
        "a: 1\nb: two\nc: true\nd: null"
    )


def test_booleans_are_not_encoded_as_integers():
    # ``True`` is an ``int`` in Python; a bool check that came *after* the int check
    # would silently turn ``needs_human: true`` into ``needs_human: 1``.
    assert toon.encode({"needs_human": True, "count": 1}) == "needs_human: true\ncount: 1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", "plain"),
        ("", '""'),
        (" padded ", '" padded "'),
        ("has: colon", '"has: colon"'),
        ("has,comma", '"has,comma"'),
        ("has[bracket]", '"has[bracket]"'),
        ("has{brace}", '"has{brace}"'),
        ('has "quote"', '"has \\"quote\\""'),
        ("back\\slash", '"back\\\\slash"'),
        ("two\nlines", '"two\\nlines"'),
        ("tab\there", '"tab\\there"'),
        ("-leading-dash", '"-leading-dash"'),
        ("#comment-ish", '"#comment-ish"'),
        # A bare token that would decode as something other than a string.
        ("true", '"true"'),
        ("false", '"false"'),
        ("null", '"null"'),
        ("42", '"42"'),
        ("-3.5e10", '"-3.5e10"'),
        # Non-ASCII is emitted literally — TOON is UTF-8, not \u-escaped JSON.
        ("café ☕", "café ☕"),
        # A control character has no literal form and becomes a \u escape.
        ("bell\x07", '"bell\\u0007"'),
    ],
)
def test_string_quoting(value, expected):
    assert toon.encode({"k": value}) == f"k: {expected}"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("plain", "plain"),
        ("with.dot", "with.dot"),
        ("_leading", "_leading"),
        ("with-dash", '"with-dash"'),
        ("with space", '"with space"'),
        ("9lead", '"9lead"'),
    ],
)
def test_key_quoting(key, expected):
    assert toon.encode({key: 1}) == f"{expected}: 1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (7, "7"),
        (-7, "-7"),
        (3624.1043964444443, "3624.1043964444443"),
        # JS ``String`` drops the ``.0`` Python's ``repr`` keeps…
        (100.0, "100"),
        # …and stays in fixed notation down to 1e-6, where Python's repr would
        # already have gone exponential.
        (0.000001, "0.000001"),
        (0.00001, "0.00001"),
        (1e-7, "1e-7"),
        (1e21, "1e+21"),
        (-0.0, "0"),
    ],
)
def test_number_formatting_matches_the_reference(value, expected):
    assert toon.encode({"n": value}) == f"n: {expected}"


def test_non_finite_floats_become_null():
    # json.dumps would emit the non-standard `Infinity`; TOON has no such literal.
    assert toon.encode({"a": float("inf"), "b": float("nan")}) == "a: null\nb: null"


def test_a_non_json_value_is_stringified_like_json_dumps_default_str():
    """Deviation 1 in the module docstring. The reference encoder writes ``null``
    here; we stringify, because ``--format json`` uses ``default=str`` and the two
    formats must not describe different data."""

    class Thing:
        def __str__(self) -> str:
            return "a thing"

    value = {"k": Thing()}
    assert toon.encode(value) == "k: a thing"
    assert json.loads(json.dumps(value, default=str)) == {"k": "a thing"}


# --- containers -------------------------------------------------------------


def test_empty_array_and_empty_object():
    assert toon.encode({"tags": [], "meta": {}}) == "tags: []\nmeta:"


def test_array_of_primitives_is_inline_with_a_length_header():
    assert toon.encode({"tags": ["a", "b", "c"]}) == "tags[3]: a,b,c"


def test_nested_objects_indent_by_two_spaces():
    assert toon.encode({"a": {"b": {"c": 1}}}) == "a:\n  b:\n    c: 1"


def test_uniform_object_array_is_tabular_and_names_its_fields_once():
    """The whole point of the format: 2 rows, 1 copy of the field names."""
    assert toon.encode({"rows": [{"id": 1, "n": "a"}, {"id": 2, "n": "b"}]}) == (
        "rows[2]{id,n}:\n  1,a\n  2,b"
    )


def test_a_uniform_object_column_expands_into_child_fields():
    # This is what makes `epic list` cheap: `progress{total,done,percent}` in the
    # header, three bare numbers per row.
    assert toon.encode(
        {"rows": [{"id": 1, "p": {"x": 1, "y": 2}}, {"id": 2, "p": {"x": 3, "y": 4}}]}
    ) == ("rows[2]{id,p{x,y}}:\n  1,1,2\n  2,3,4")


def test_a_non_uniform_object_array_falls_back_to_list_items():
    # Different key sets → no shared header is possible, so each element prints as
    # a `- ` item and pays for its own keys.
    assert toon.encode({"rows": [{"id": 1}, {"id": 2, "extra": 3}]}) == (
        "rows[2]:\n  - id: 1\n  - id: 2\n    extra: 3"
    )


def test_an_object_of_uniform_objects_is_a_keyed_table():
    assert toon.encode({"by": {"alice": {"n": 1, "w": 0}, "bob": {"n": 2, "w": 1}}}) == (
        "by[2:]{n,w}:\n  alice: 1,0\n  bob: 2,1"
    )


def test_a_single_entry_object_is_not_a_keyed_table():
    # The keyed form needs >= 2 entries to be worth (or even to be) a table.
    assert toon.encode({"by": {"alice": {"n": 1}}}) == "by:\n  alice:\n    n: 1"


def test_mixed_array_of_scalars_objects_and_arrays():
    assert toon.encode({"rows": [1, {"a": 2}, [3, 4]]}) == (
        "rows[3]:\n  - 1\n  - a: 2\n  - [2]: 3,4"
    )


def test_root_level_scalars_and_arrays():
    assert toon.encode(42) == "42"
    assert toon.encode("hello world") == "hello world"
    assert toon.encode(None) == "null"
    assert toon.encode([]) == "[]"
    assert toon.encode([1, 2, 3]) == "[3]: 1,2,3"
    assert toon.encode([{"a": 1}, {"a": 2}]) == "[2]{a}:\n  1\n  2"


def test_a_row_count_disagreeing_with_the_header_would_be_a_bug():
    """The header's ``[N]`` is what a decoder trusts; assert it tracks the rows."""
    rows = [{"id": i} for i in range(7)]
    encoded = toon.encode({"rows": rows})
    assert encoded.splitlines()[0] == "rows[7]{id}:"
    assert len(encoded.splitlines()) == 8


def test_an_unsupported_delimiter_is_rejected():
    with pytest.raises(ValueError, match="invalid TOON delimiter"):
        toon.encode({"a": 1}, delimiter=";")


def test_the_tab_delimiter_is_declared_in_the_header():
    # Only the non-default delimiters appear in the header, so a decoder can tell.
    assert toon.encode({"tags": ["a", "b"]}, delimiter="\t") == "tags[2\t]: a\tb"
