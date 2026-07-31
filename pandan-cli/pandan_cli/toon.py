"""A TOON encoder (V47, KAN-430) — the token-cheap serialization of ``--format toon``.

TOON (`Token-Oriented Object Notation <https://toonformat.dev/>`_) is JSON's data
model in a YAML-shaped, key-deduplicating syntax: an array of uniform objects prints
its field names **once** in a header and then one comma-separated row per element,
so a 55-row ``by_assignee`` block stops paying for 55 copies of
``{"assignee": …, "throughput": …, "wip": …}``. That is exactly the shape of this
CLI's *nested* payloads (``metrics``, ``activity``, ``epic list`` with rollups), which
is where the measured saving lives — see the module docstring of ``cli.py`` and the
V47 slice notes for the numbers.

**Encoder only, on purpose.** The CLI *writes* TOON for an agent to read; nothing in
the product reads it back. A decoder would be untested weight in the shipped binary,
so the round-trip contract is proven by a decoder that lives in the test suite
(``tests/toon_decode.py``) instead.

**Stdlib only**, like the rest of the CLI: no new dependency, and it survives the
PyInstaller freeze. This is a faithful port of the reference implementation
(``@toon-format/toon``) — the tabular/keyed/list-item classification, the quoting
rules and the header grammar all mirror it, and ``tests/test_toon.py`` pins the
behaviours that port could plausibly get wrong.

Two deliberate, documented deviations from the reference, both so ``--format toon``
and ``--format json`` describe the **same** data (the "one shared serializer" the
slice asks for — see ``cli._render_structured``):

1. A value that isn't part of JSON's data model is stringified (``str(value)``)
   rather than encoded as ``null``. That matches the CLI's
   ``json.dumps(…, default=str)``, so the two formats can't disagree about it.
2. Object keys are stringified. ``json.dumps`` does the same.

Neither can trigger on a real payload — the shared client hands us the output of
``response.json()``, which is already pure JSON — but a divergence here would be a
silent contract break, so both are pinned by tests.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

DEFAULT_DELIMITER = ","
DEFAULT_INDENT = 2

# A key may go unquoted when it looks like an identifier (dots allowed, so a
# flattened path stays readable).
_UNQUOTED_KEY_RE = re.compile(r"^[A-Za-z_][\w.]*$")
# A bare token that would decode as a number must be quoted when it's a string,
# or `"3"` and `3` would be indistinguishable.
_NUMERIC_LIKE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?$", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x1f]")
_BRACKET_RE = re.compile(r"[\[\]{}]")

# A field in a tabular header: its name plus, when the column holds uniform
# objects, the child fields it expands into (``progress{total,done,percent}``).
_Field = tuple[str, "list[_Field] | None"]


# --- normalization ----------------------------------------------------------


def _normalize(value: Any) -> Any:
    """Map a Python value onto TOON's (== JSON's) data model.

    ``bool`` is tested before ``int`` — in Python ``True`` *is* an ``int``, and
    encoding it as ``1`` would silently change the data."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Neither infinity nor NaN exists in JSON; the reference encoder writes
        # ``null``, and ``json.dumps`` would write the non-standard ``Infinity``.
        # Prefer the spec-legal ``null`` — a value no JSON parser will choke on.
        if math.isnan(value) or math.isinf(value):
            return None
        return 0.0 if value == 0 else value  # -0.0 → 0
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    # Deviation 1 (see the module docstring): mirror ``json.dumps(default=str)``.
    return str(value)


def _is_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool, int, float))


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


# --- primitives -------------------------------------------------------------


def _escape_string(value: str) -> str:
    out = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return _CONTROL_RE.sub(lambda m: f"\\u{ord(m.group(0)):04x}", out)


def _is_safe_unquoted(value: str, delimiter: str) -> bool:
    """Whether a string can be written bare. Anything that could be re-read as a
    different token — a literal, a number, a structural character, the active
    delimiter, a list marker or a comment — has to be quoted."""
    if not value:
        return False
    if value[0] in " \t" or value[-1] in " \t":
        return False
    if value in ("true", "false", "null"):
        return False
    if _NUMERIC_LIKE_RE.match(value):
        return False
    if ":" in value or '"' in value or "\\" in value:
        return False
    if _BRACKET_RE.search(value):
        return False
    if _CONTROL_RE.search(value):
        return False
    if delimiter in value:
        return False
    return not value.startswith(("-", "#"))


def _encode_number(value: int | float) -> str:
    """Render a number the way the reference (JavaScript ``String(n)``) does.

    Python's ``repr`` and JS's ``String`` both emit the shortest round-tripping
    decimal, but they disagree about *when* to go exponential, and Python keeps a
    ``.0`` tail JS drops. Both differences are cosmetic to a decoder and invisible
    on our real payloads, but matching JS keeps the output canonical TOON — which is
    what lets the conformance corpus be checked byte-for-byte against the reference.

    JS uses fixed notation for ``1e-6 <= |n| < 1e21`` and exponential (unpadded,
    ``1e-7`` not ``1e-07``) outside it; Python's repr turns exponential from
    ``1e-5`` down and from ``1e16`` up."""
    if isinstance(value, int):
        return str(value)
    if value.is_integer() and abs(value) < 1e21:
        return str(int(value))
    text = repr(value)
    if "e" not in text:
        return text
    if 1e-6 <= abs(value) < 1e21:
        return format(Decimal(text), "f")
    mantissa, _, exponent = text.partition("e")
    sign = "-" if exponent.startswith("-") else "+"
    return f"{mantissa}e{sign}{exponent.lstrip('+-').lstrip('0') or '0'}"


def _encode_primitive(value: Any, delimiter: str) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _encode_number(value)
    return value if _is_safe_unquoted(value, delimiter) else f'"{_escape_string(value)}"'


def _encode_key(key: str) -> str:
    return key if _UNQUOTED_KEY_RE.match(key) else f'"{_escape_string(key)}"'


def _join_primitives(values: list[Any], delimiter: str) -> str:
    return delimiter.join(_encode_primitive(v, delimiter) for v in values)


def _format_fields(fields: list[_Field], delimiter: str) -> str:
    return delimiter.join(
        _encode_key(name) + (f"{{{_format_fields(children, delimiter)}}}" if children else "")
        for name, children in fields
    )


def _format_header(
    length: int,
    *,
    key: str | None = None,
    fields: list[_Field] | None = None,
    delimiter: str = DEFAULT_DELIMITER,
    keyed: bool = False,
) -> str:
    """``key[N]{a,b}:`` — the array/tabular header. ``keyed`` marks the ``[N:]``
    form used when an *object's* entries are themselves uniform rows."""
    header = _encode_key(key) if key is not None else ""
    header += f"[{length}{':' if keyed else ''}"
    header += "" if delimiter == DEFAULT_DELIMITER else delimiter
    header += "]"
    if fields is not None:
        header += f"{{{_format_fields(fields, delimiter)}}}"
    return header + ":"


# --- tabular classification -------------------------------------------------


def _extract_tabular_fields(rows: list[Any]) -> list[_Field] | None:
    """The field list for a tabular array, or ``None`` when the rows aren't uniform.

    Uniform means: same key set, same size, and every column either all-primitive
    or all-uniform-objects (which expands into child fields)."""
    if not rows:
        return None
    first = rows[0]
    if not _is_object(first):
        return None
    keys = list(first.keys())
    if not keys:
        return None
    for row in rows:
        if not _is_object(row) or len(row) != len(keys):
            return None
        if any(key not in row for key in keys):
            return None
    fields: list[_Field] = []
    for key in keys:
        field = _classify_column(key, [row[key] for row in rows])
        if field is None:
            return None
        fields.append(field)
    return fields


def _classify_column(name: str, values: list[Any]) -> _Field | None:
    if all(_is_primitive(v) for v in values):
        return (name, None)
    if not all(_is_object(v) and v for v in values):
        return None
    children = _extract_tabular_fields(values)
    return None if children is None else (name, children)


def _extract_keyed_tabular_fields(value: dict[str, Any]) -> list[_Field] | None:
    """An object whose values are themselves 2+ uniform non-empty objects prints as
    a *keyed* table: the entry key leads each row."""
    entries = list(value.values())
    if len(entries) < 2:
        return None
    if not all(_is_object(v) and v for v in entries):
        return None
    return _extract_tabular_fields(entries)


def _row_leaves(row: dict[str, Any], fields: list[_Field]) -> list[Any]:
    leaves: list[Any] = []
    for name, children in fields:
        if children:
            leaves.extend(_row_leaves(row[name], children))
        else:
            leaves.append(row[name])
    return leaves


# --- line emission ----------------------------------------------------------


def _indent(depth: int, content: str, indent_size: int) -> str:
    return " " * (indent_size * depth) + content


def _item(depth: int, content: str, indent_size: int) -> str:
    return _indent(depth, "- " + content, indent_size)


def _value_lines(value: Any, depth: int, delim: str, size: int) -> Iterator[str]:
    if _is_primitive(value):
        encoded = _encode_primitive(value, delim)
        if encoded:
            yield encoded
        return
    if isinstance(value, list):
        yield from _array_lines(None, value, depth, delim, size)
    elif _is_object(value):
        keyed = _extract_keyed_tabular_fields(value)
        if keyed is not None:
            yield from _keyed_object_lines(None, value, keyed, depth, delim, size)
        else:
            yield from _object_lines(value, depth, delim, size)


def _object_lines(value: dict[str, Any], depth: int, delim: str, size: int) -> Iterator[str]:
    for key, val in value.items():
        yield from _pair_lines(key, val, depth, delim, size)


def _pair_lines(key: str, value: Any, depth: int, delim: str, size: int) -> Iterator[str]:
    if _is_primitive(value):
        yield _indent(depth, f"{_encode_key(key)}: {_encode_primitive(value, delim)}", size)
    elif isinstance(value, list):
        yield from _array_lines(key, value, depth, delim, size)
    elif _is_object(value):
        keyed = _extract_keyed_tabular_fields(value)
        if keyed is not None:
            yield from _keyed_object_lines(key, value, keyed, depth, delim, size)
            return
        yield _indent(depth, f"{_encode_key(key)}:", size)
        if value:
            yield from _object_lines(value, depth + 1, delim, size)


def _keyed_object_lines(
    key: str | None, value: dict[str, Any], fields: list[_Field], depth: int, delim: str, size: int
) -> Iterator[str]:
    yield _indent(
        depth,
        _format_header(len(value), key=key, fields=fields, delimiter=delim, keyed=True),
        size,
    )
    yield from _keyed_rows(list(value.items()), fields, depth + 1, delim, size)


def _keyed_rows(
    entries: list[tuple[str, Any]], fields: list[_Field], depth: int, delim: str, size: int
) -> Iterator[str]:
    for entry_key, entry_value in entries:
        leaves = _row_leaves(entry_value, fields)
        yield _indent(depth, f"{_encode_key(entry_key)}: {_join_primitives(leaves, delim)}", size)


def _array_lines(
    key: str | None, value: list[Any], depth: int, delim: str, size: int
) -> Iterator[str]:
    if not value:
        yield _indent(depth, f"{_encode_key(key)}: []" if key is not None else "[]", size)
        return
    if all(_is_primitive(v) for v in value):
        yield _indent(depth, _inline_array(value, delim, key), size)
        return
    if all(isinstance(v, list) for v in value) and all(
        all(_is_primitive(x) for x in v) for v in value
    ):
        yield _indent(depth, _format_header(len(value), key=key, delimiter=delim), size)
        for arr in value:
            yield _item(depth + 1, _inline_array(arr, delim, None), size)
        return
    if all(_is_object(v) for v in value):
        fields = _extract_tabular_fields(value)
        if fields is not None:
            yield _indent(
                depth,
                _format_header(len(value), key=key, fields=fields, delimiter=delim),
                size,
            )
            yield from _tabular_rows(value, fields, depth + 1, delim, size)
            return
    yield from _mixed_array_lines(key, value, depth, delim, size)


def _inline_array(values: list[Any], delim: str, key: str | None) -> str:
    header = _format_header(len(values), key=key, delimiter=delim)
    if not values:
        return header
    return f"{header} {_join_primitives(values, delim)}"


def _tabular_rows(
    rows: list[Any], fields: list[_Field], depth: int, delim: str, size: int
) -> Iterator[str]:
    for row in rows:
        yield _indent(depth, _join_primitives(_row_leaves(row, fields), delim), size)


def _mixed_array_lines(
    key: str | None, items: list[Any], depth: int, delim: str, size: int
) -> Iterator[str]:
    yield _indent(depth, _format_header(len(items), key=key, delimiter=delim), size)
    for item in items:
        yield from _list_item_lines(item, depth + 1, delim, size)


def _list_item_lines(value: Any, depth: int, delim: str, size: int) -> Iterator[str]:
    if _is_primitive(value):
        yield _item(depth, _encode_primitive(value, delim), size)
    elif isinstance(value, list):
        if all(_is_primitive(v) for v in value):
            yield _item(depth, _inline_array(value, delim, None), size)
        else:
            yield _item(depth, _format_header(len(value), delimiter=delim), size)
            for item in value:
                yield from _list_item_lines(item, depth + 1, delim, size)
    elif _is_object(value):
        yield from _object_as_list_item(value, depth, delim, size)


def _object_as_list_item(obj: dict[str, Any], depth: int, delim: str, size: int) -> Iterator[str]:
    """An object inside a non-uniform array: its **first** entry rides the ``- ``
    marker (so the row isn't wasted on a bare dash) and the rest indent under it."""
    if not obj:
        yield _indent(depth, "-", size)
        return
    entries = list(obj.items())
    first_key, first_value = entries[0]
    rest = dict(entries[1:])

    if isinstance(first_value, list) and first_value and all(_is_object(v) for v in first_value):
        fields = _extract_tabular_fields(first_value)
        if fields is not None:
            yield _item(
                depth,
                _format_header(len(first_value), key=first_key, fields=fields, delimiter=delim),
                size,
            )
            yield from _tabular_rows(first_value, fields, depth + 2, delim, size)
            if rest:
                yield from _object_lines(rest, depth + 1, delim, size)
            return

    if _is_object(first_value):
        keyed = _extract_keyed_tabular_fields(first_value)
        if keyed is not None:
            keyed_entries = list(first_value.items())
            yield _item(
                depth,
                _format_header(
                    len(keyed_entries),
                    key=first_key,
                    fields=keyed,
                    delimiter=delim,
                    keyed=True,
                ),
                size,
            )
            yield from _keyed_rows(keyed_entries, keyed, depth + 2, delim, size)
            if rest:
                yield from _object_lines(rest, depth + 1, delim, size)
            return

    encoded_key = _encode_key(first_key)
    if _is_primitive(first_value):
        yield _item(depth, f"{encoded_key}: {_encode_primitive(first_value, delim)}", size)
    elif isinstance(first_value, list):
        if not first_value:
            yield _item(depth, f"{encoded_key}: []", size)
        elif all(_is_primitive(v) for v in first_value):
            yield _item(depth, f"{encoded_key}{_inline_array(first_value, delim, None)}", size)
        else:
            yield _item(
                depth,
                f"{encoded_key}{_format_header(len(first_value), delimiter=delim)}",
                size,
            )
            for item in first_value:
                yield from _list_item_lines(item, depth + 2, delim, size)
    elif _is_object(first_value):
        yield _item(depth, f"{encoded_key}:", size)
        if first_value:
            yield from _object_lines(first_value, depth + 2, delim, size)

    if rest:
        yield from _object_lines(rest, depth + 1, delim, size)


# --- public API -------------------------------------------------------------


def encode(
    value: Any, *, indent_size: int = DEFAULT_INDENT, delimiter: str = DEFAULT_DELIMITER
) -> str:
    """Encode ``value`` as TOON. No trailing newline (``print`` adds one)."""
    if delimiter not in (",", "\t", "|"):
        raise ValueError(f"invalid TOON delimiter {delimiter!r}; use ',', '\\t' or '|'")
    return "\n".join(_value_lines(_normalize(value), 0, delimiter, indent_size))
