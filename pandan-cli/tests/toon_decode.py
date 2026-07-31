"""A TOON **decoder**, for tests only (V47, KAN-430).

The shipped CLI only ever *writes* TOON (``pandan_cli/toon.py``), so a decoder has no
place in the binary. But the slice's contract is round-trip equality — "the TOON
output parses back to data **equal** to the ``--json`` output", deliberately not a
golden string — and that needs something that reads TOON back. This is it.

It is written against the TOON grammar rather than against ``pandan_cli/toon.py``'s
internals, so a bug that made both agree would have to be made twice, in opposite
directions. The encoder is separately checked byte-for-byte against the reference
implementation (``@toon-format/toon``) — see the V47 PR — which is the other half of
the argument that what we emit is really TOON and not a private dialect.

Not a general-purpose parser: it assumes well-formed input (the encoder's output),
2-space indentation and the comma delimiter, and it validates nothing it doesn't
have to. Don't promote it out of ``tests/``.
"""
from __future__ import annotations

import re
from typing import Any

INDENT = 2
DELIMITER = ","

_BARE_KEY_RE = re.compile(r"[A-Za-z_][\w.]*")
_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?$", re.IGNORECASE)
_INTEGER_RE = re.compile(r"^[+-]?\d+$")

# A parsed header field: (name, child fields or None).
_Field = tuple[str, "list[_Field] | None"]
# A parsed header: (key, length, keyed, fields, delimiter, rest-of-line).
_Header = tuple["str | None", int, bool, "list[_Field] | None", str, str]


# --- string scanning --------------------------------------------------------


def _closing_quote(text: str, start: int) -> int:
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i
        i += 1
    raise ValueError(f"unterminated string in {text!r}")


def _find_unquoted(text: str, char: str, start: int = 0) -> int:
    i = start
    while i < len(text):
        if text[i] == '"':
            i = _closing_quote(text, i) + 1
            continue
        if text[i] == char:
            return i
        i += 1
    return -1


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '"':
            i = _closing_quote(text, i) + 1
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced braces in {text!r}")


def _split_cells(text: str, delimiter: str, *, braces: bool = False) -> list[str]:
    """Split on the delimiter, ignoring ones inside a quoted string — and, when
    ``braces`` is set, ones inside a ``{…}`` group. Row cells never contain a brace
    (the encoder quotes any value that does), but a *field list* nests them:
    ``id,progress{total,done,percent},health`` is three fields, not five."""
    cells: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            i = _closing_quote(text, i) + 1
            continue
        if braces and char == "{":
            depth += 1
        elif braces and char == "}":
            depth -= 1
        elif char == delimiter and depth == 0:
            cells.append(text[start:i])
            start = i + 1
        i += 1
    cells.append(text[start:])
    return cells


def _unescape(text: str) -> str:
    out: list[str] = []
    i = 0
    simple = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}
    while i < len(text):
        if text[i] != "\\":
            out.append(text[i])
            i += 1
            continue
        nxt = text[i + 1]
        if nxt in simple:
            out.append(simple[nxt])
            i += 2
        elif nxt == "u":
            out.append(chr(int(text[i + 2 : i + 6], 16)))
            i += 6
        else:
            raise ValueError(f"bad escape \\{nxt} in {text!r}")
    return "".join(out)


# --- tokens -----------------------------------------------------------------


def _parse_key(token: str) -> str:
    token = token.strip()
    if token.startswith('"'):
        return _unescape(token[1:-1])
    return token


def _parse_scalar(token: str) -> Any:
    token = token.strip(" ")
    if token.startswith('"') and token.endswith('"') and len(token) >= 2:
        return _unescape(token[1:-1])
    if token == "true":
        return True
    if token == "false":
        return False
    if token == "null":
        return None
    if _NUMERIC_RE.match(token):
        return int(token) if _INTEGER_RE.match(token) else float(token)
    return token


def _parse_fields(text: str, delimiter: str) -> list[_Field]:
    fields: list[_Field] = []
    for part in _split_cells(text, delimiter, braces=True):
        if part.startswith('"'):
            end = _closing_quote(part, 0)
            name = _unescape(part[1:end])
            tail = part[end + 1 :]
        else:
            brace = part.find("{")
            name = part if brace == -1 else part[:brace]
            tail = "" if brace == -1 else part[brace:]
        if tail.startswith("{"):
            fields.append((name, _parse_fields(tail[1:-1], delimiter)))
        else:
            fields.append((name, None))
    return fields


def _split_header(content: str) -> _Header | None:
    """Split ``key[N:]{a,b}: rest`` into its parts, or ``None`` when the line isn't
    a header (an ordinary ``key: value`` pair, a list item, a bare scalar)."""
    pos = 0
    key: str | None = None
    if content.startswith('"'):
        end = _closing_quote(content, 0)
        key = _unescape(content[1:end])
        pos = end + 1
    else:
        match = _BARE_KEY_RE.match(content)
        if match:
            key = match.group(0)
            pos = match.end()
    if pos >= len(content) or content[pos] != "[":
        return None
    close = content.find("]", pos)
    if close == -1:
        return None
    inner = content[pos + 1 : close]
    keyed = inner.endswith(":")
    if keyed:
        inner = inner[:-1]
    delimiter = DELIMITER
    if inner and not inner[-1].isdigit():
        delimiter = inner[-1]
        inner = inner[:-1]
    if not inner.isdigit():
        return None
    length = int(inner)
    pos = close + 1
    fields: list[_Field] | None = None
    if pos < len(content) and content[pos] == "{":
        end = _matching_brace(content, pos)
        fields = _parse_fields(content[pos + 1 : end], delimiter)
        pos = end + 1
    if pos >= len(content) or content[pos] != ":":
        return None
    return key, length, keyed, fields, delimiter, content[pos + 1 :]


def _build_row(fields: list[_Field], cells: list[str]) -> dict[str, Any]:
    row, _ = _build_row_from(fields, cells, 0)
    return row


def _build_row_from(
    fields: list[_Field], cells: list[str], index: int
) -> tuple[dict[str, Any], int]:
    row: dict[str, Any] = {}
    for name, children in fields:
        if children:
            row[name], index = _build_row_from(children, cells, index)
        else:
            row[name] = _parse_scalar(cells[index])
            index += 1
    return row, index


# --- structure --------------------------------------------------------------


def _parse_header_value(
    header: _Header, lines: list[tuple[int, str]], i: int, child_indent: int
) -> tuple[Any, int]:
    _, length, keyed, fields, delimiter, rest = header
    if rest.startswith(" "):
        rest = rest[1:]

    if keyed:
        assert fields is not None
        obj: dict[str, Any] = {}
        for _ in range(length):
            content = lines[i][1]
            i += 1
            colon = _find_unquoted(content, ":")
            obj[_parse_key(content[:colon])] = _build_row(
                fields, _split_cells(content[colon + 1 :].lstrip(" "), delimiter)
            )
        return obj, i

    if fields is not None:
        rows: list[Any] = []
        for _ in range(length):
            content = lines[i][1]
            i += 1
            rows.append(_build_row(fields, _split_cells(content, delimiter)))
        return rows, i

    if rest:
        return [_parse_scalar(cell) for cell in _split_cells(rest, delimiter)], i
    if length == 0:
        return [], i

    items: list[Any] = []
    for _ in range(length):
        item, i = _parse_list_item(lines, i, child_indent)
        items.append(item)
    return items, i


def _parse_entry(
    content: str, lines: list[tuple[int, str]], i: int, child_indent: int
) -> tuple[str, Any, int]:
    """One object entry whose line has already been consumed; ``i`` is the next line."""
    header = _split_header(content)
    if header is not None:
        key = header[0]
        assert key is not None
        value, i = _parse_header_value(header, lines, i, child_indent)
        return key, value, i

    colon = _find_unquoted(content, ":")
    if colon == -1:
        raise ValueError(f"not an object entry: {content!r}")
    key = _parse_key(content[:colon])
    rest = content[colon + 1 :]
    if rest.startswith(" "):
        rest = rest[1:]
    if rest == "":
        if i < len(lines) and lines[i][0] == child_indent:
            value, i = _parse_object(lines, i, child_indent)
        else:
            value = {}
        return key, value, i
    if rest == "[]":
        return key, [], i
    return key, _parse_scalar(rest), i


def _parse_object(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict[str, Any], int]:
    obj: dict[str, Any] = {}
    while i < len(lines) and lines[i][0] == indent:
        content = lines[i][1]
        if content == "-" or content.startswith("- "):
            break
        i += 1
        key, value, i = _parse_entry(content, lines, i, indent + INDENT)
        obj[key] = value
    return obj, i


def _parse_list_item(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    """A ``- …`` element. Its first entry rides the dash, so that entry's children sit
    two levels in while the element's remaining entries sit one level in."""
    line_indent, content = lines[i]
    if content == "-":
        return {}, i + 1
    body = content[2:]
    i += 1

    header = _split_header(body)
    if header is not None and header[0] is None:
        return _parse_header_value(header, lines, i, line_indent + INDENT)

    if header is None and _find_unquoted(body, ":") == -1:
        return _parse_scalar(body), i

    key, value, i = _parse_entry(body, lines, i, line_indent + 2 * INDENT)
    obj: dict[str, Any] = {key: value}
    rest, i = _parse_object(lines, i, line_indent + INDENT)
    obj.update(rest)
    return obj, i


def decode(text: str) -> Any:
    """Parse TOON back into Python data."""
    lines: list[tuple[int, str]] = []
    for raw in text.split("\n"):
        stripped = raw.rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped[indent:]))
    if not lines:
        return None

    first = lines[0][1]
    if first == "[]":
        return []
    header = _split_header(first)
    if header is not None and header[0] is None:
        value, i = _parse_header_value(header, lines, 1, INDENT)
    elif header is None and _find_unquoted(first, ":") == -1:
        return _parse_scalar(first)
    else:
        value, i = _parse_object(lines, 0, 0)
    if i != len(lines):
        raise ValueError(f"unconsumed input at line {i + 1}: {lines[i][1]!r}")
    return value
