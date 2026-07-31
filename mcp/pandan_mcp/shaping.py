"""Shape what a read tool *returns* — field narrowing + text truncation (KAN-501).

Why this exists, in one number. V49 (ADR 0019) measured the whole 49-tool schema
surface at **7,388 `o200k_base` tokens resident** and a *single*
``mcp__pandan__list_cards`` against the live 121-card Roadmap board at
**~44,900 tokens in one tool result** — 5.1× the entire surface. Decomposing that
payload showed the cost is **field breadth, not pretty-printing**: 121 rows × 22
keys, with 1,111 null/empty values serialized. Narrowing to the handful of keys a
task actually needs recovers ~84% of it. So this module is where ADR 0019 said the
tokens really were.

Two knobs, both **opt-out-shaped so the default response is unchanged key-for-key**:

* ``fields`` — the keys to keep. Omitted (``None``) means "return exactly what the
  API returned", which is the invariant ``tests/test_shaping.py`` asserts *first*,
  before it asserts that narrowing works.
* ``full`` — the escape hatch for the truncation below, which unlike ``fields`` is
  **on by default**.

### This is not a port of the CLI's ``--fields``, and the difference is deliberate

The CLI's V42 projection applies to its **human** row only; ``pandan … --format
json`` deliberately carries the client's keys unprojected, "because the structured
formats carry the client's own keys, so a projection there would reshape a
documented machine contract for no gain" (``pandan-cli/pandan_cli/cli.py:427-429``).

That reasoning does not transfer. On the CLI a machine payload is one of several
renderings and the cheap human one is the default; over MCP the machine payload
**is** what enters the model's context, and there is no cheaper rendering to fall
back to. Narrowing it is therefore the only lever, which is why the arguments here
are shaped like the CLI's but the code is not shared with it: the MCP server has no
dependency on ``pandan-cli`` in either direction (``mcp/pyproject.toml:9`` declares
``pandan-client`` only) and importing across adapters would invert ADR 0005.

The truncation rule, by contrast, *is* a faithful re-statement of V45 (KAN-428):
same allow-list of free-text fields, same "the reported total is the true original
length" invariant, same character-not-byte slicing. It is re-stated rather than
imported for the same packaging reason.
"""
from __future__ import annotations

import os
from typing import Any

#: Default cap for a single free-text value, in characters. Matches the CLI's V45
#: default so an agent sees the same shape whichever adapter it drives.
DEFAULT_MAX_TEXT_CHARS = 500

#: Env override for that cap. ``0`` disables truncation globally (what ``full=True``
#: does per call).
ENV_MAX_TEXT_CHARS = "PANDAN_MAX_TEXT_CHARS"

#: The fields truncation may cut — an **allow-list**, not "any long string". Two
#: payload strings are load-bearing at any length and must survive verbatim: a
#: keyset ``next_cursor`` (cut it and pagination silently breaks) and a work-link
#: ``url``. So the rule is keyed on the field name, exactly as V45 does. These are
#: the API's unbounded ``Text`` columns that hold prose.
TEXT_FIELDS = frozenset(
    {
        "description",     # card + epic
        "body",            # comment
        "attention_note",  # the needs-human handoff note
        "summary",         # an activity row's human sentence
    }
)

#: Aliases accepted in ``fields``, mirroring the CLI's (``pandan_cli/cli.py``,
#: ``FIELD_ALIASES``) so one vocabulary works across both adapters. The *output* key
#: is always the canonical API name, never the alias — a consumer reading
#: ``.ticket_number`` keeps working.
#:
#: **Duplicated with the CLI's copy on purpose** (decided in KAN-502, which was the
#: natural place to move it because that slice touched ``pandan-client``). Hoisting
#: this into the shared ``pandan-client`` was rejected: it would put *presentation*
#: vocabulary into the shared *transport* layer, which today knows only endpoints and
#: payloads. Two frozen three-entry tables are cheaper duplicated than coupled — but
#: if you change one, change the other, and keep the canonical-key rule identical.
#: The same reasoning covers ``TEXT_FIELDS`` above vs. the CLI's ``_TEXT_FIELDS``.
FIELD_ALIASES = {
    "ticket": "ticket_number",
    "pts": "story_points",
    "points": "story_points",
}

#: List-envelope keys the shaped read tools can return (``PandanClient`` wraps a
#: bare API array in exactly one of these). Detection is *shape*-checked as well as
#: name-checked — see :func:`_envelope`, and the card-carrying-``labels`` trap it
#: exists to avoid.
#:
#: **This set is not "every list the API returns" — it is exactly the envelopes a
#: tool passes to** :func:`shape`. A name in here that no shaped tool produces is a
#: name that can only ever *mis*-classify some other payload, so KAN-517 added
#: exactly two — ``notifications`` (a 127-row unpaginated inbox: ~14.3k tokens) and
#: ``boards`` (1,157 → 181) — and stopped there: ``labels``/``views``/``templates``/
#: ``cycles`` measured 7–68 tokens against the real account, which no amount of
#: resident schema is worth.
_ROW_ENVELOPES = frozenset(
    {"cards", "epics", "activity", "comments", "notifications", "boards"}
)

#: Keys that may sit beside an envelope's row list without it stopping being an
#: envelope. Preserved verbatim through a projection: ``next_cursor`` is how the
#: caller pages, so narrowing must never eat it.
_ENVELOPE_SIBLINGS = frozenset({"next_cursor"})


# --- truncation (V45's rule, re-stated) --------------------------------------


def max_text_chars() -> int:
    """The configured character cap. Read from the environment on each call so a
    test (or a session) can change it without re-importing the server.

    A non-integer or negative value falls back to the default rather than raising:
    this is an output-shaping preference, and failing a board read over a typo in an
    optional env var would be a worse outcome than ignoring it.
    """
    raw = os.environ.get(ENV_MAX_TEXT_CHARS, "").strip()
    if not raw:
        return DEFAULT_MAX_TEXT_CHARS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_TEXT_CHARS
    return value if value >= 0 else DEFAULT_MAX_TEXT_CHARS


def text_limit(*, full: bool) -> int:
    """The effective limit for one call: ``full=True`` collapses to ``0`` (= off),
    which is the same value ``PANDAN_MAX_TEXT_CHARS=0`` produces. One concept
    downstream, so nothing below has to know about the flag."""
    return 0 if full else max_text_chars()


def truncation_hint(total: int) -> str:
    """The hint appended to a cut value. ``total`` is the **original** length in
    characters, measured before the cut — a hint claiming a wrong size is worse than
    no hint, so this number is never an estimate."""
    return f"(truncated, {total} chars total — pass full=true for the complete text)"


def _truncate_inline(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters and append the ellipsis + size hint.

    Deliberately still a **string**: a consumer's ``.description`` keeps its type and
    only gets shorter, which is the smallest change that bounds the payload.
    Promoting it to ``{"text": …, "truncated": true}`` would break every caller that
    reads the field. ``str`` slicing is by code point, so this can never split a
    multi-byte character — the output is always valid UTF-8, and the reported total
    is a character count too.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}… {truncation_hint(len(text))}"


def truncate(value: Any, limit: int) -> Any:
    """Recursively copy ``value`` with its :data:`TEXT_FIELDS` strings cut to
    ``limit``. Everything else — numbers, booleans, other strings, every key — is
    returned untouched, and ``limit <= 0`` returns the input unchanged.

    Only values reached *through a* :data:`TEXT_FIELDS` *key* are cut, so a long
    string under some other key (``next_cursor``, ``url``, ``title``) is safe by
    construction rather than by luck.
    """
    if limit <= 0:
        return value
    if isinstance(value, dict):
        return {
            key: (
                _truncate_inline(item, limit)
                if key in TEXT_FIELDS and isinstance(item, str)
                else truncate(item, limit)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [truncate(item, limit) for item in value]
    return value


# --- field narrowing --------------------------------------------------------


def parse_fields(fields: list[str] | None) -> list[str] | None:
    """Normalise the ``fields`` argument: lower-cased, de-blanked, de-duplicated in
    order, with comma-joined elements split.

    ``None`` (and an all-blank list) means **no narrowing**, and is returned as
    ``None`` so the caller's identity path is a single ``is None`` check. The comma
    split is defensive: the CLI spells this ``--fields ticket,title``, so an agent
    porting that habit will hand over ``["ticket,title"]``, and silently doing the
    right thing beats an error about a field named ``ticket,title``.
    """
    if fields is None:
        return None
    names: list[str] = []
    for raw in fields:
        for part in str(raw).split(","):
            name = part.strip().lower()
            if name and name not in names:
                names.append(name)
    return names or None


def _resolve(name: str) -> str:
    return FIELD_ALIASES.get(name, name)


def _envelope(payload: dict[str, Any]) -> str | None:
    """The list-envelope key of ``payload``, or ``None`` if it isn't one.

    Both the name **and** the shape are checked, because a name check alone
    misfires: a single card carries a ``labels`` list, so "has a key that could be an
    envelope" would treat ``get_card``'s result as a label list. An envelope is
    exactly one row list plus, optionally, :data:`_ENVELOPE_SIBLINGS` — nothing else.
    """
    candidates = _ROW_ENVELOPES & set(payload)
    if len(candidates) != 1:
        return None
    key = next(iter(candidates))
    if not isinstance(payload[key], list):
        return None
    if set(payload) - {key} - _ENVELOPE_SIBLINGS:
        return None
    return key


def _available(rows: list[Any]) -> list[str]:
    """Every field name valid for ``rows``: the union of the keys they carry, plus
    the aliases that resolve onto one of those."""
    known: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            known |= {str(key) for key in row}
    return sorted(known | {a for a, target in FIELD_ALIASES.items() if target in known})


def _validate(names: list[str], rows: list[Any], noun: str) -> None:
    """Reject an unknown field name, naming the offender and listing what is valid.

    Raised as a plain ``ValueError``, which FastMCP surfaces to the model as a tool
    error — so a wrong guess costs one cheap round trip and teaches the vocabulary,
    instead of silently returning rows full of nulls.
    """
    available = _available(rows)
    known = set(available)
    for name in names:
        if _resolve(name) not in known:
            raise ValueError(
                f"unknown field {name!r} for {noun}; available: {', '.join(available)}"
            )


def _project_row(row: Any, names: list[str]) -> Any:
    """One row narrowed to ``names``, in the order asked for, under the **canonical**
    key (so ``ticket`` returns ``ticket_number``).

    A name the row happens to lack still appears, as ``null``: the projection is
    rectangular, so a caller can index every row the same way and a test can assert
    the key set exactly. Validation has already established the name exists on at
    least one row.
    """
    if not isinstance(row, dict):
        return row
    return {_resolve(name): row.get(_resolve(name)) for name in names}


def project(payload: Any, fields: list[str] | None) -> Any:
    """Narrow ``payload`` to ``fields``; ``None``/empty returns it **unchanged**.

    Two shapes, because the read tools return two:

    * a **list envelope** (``{"cards": [...], "next_cursor"?: str}``) — each row is
      narrowed and the envelope's own keys are preserved verbatim, so paging still
      works;
    * a **single object** (``get_card``, ``metrics``, ``cycle_metrics``) — its
      top-level keys are narrowed. For an aggregate like ``metrics`` that means
      picking whole sections (``fields=["throughput"]``), which is the useful unit
      there.
    """
    names = parse_fields(fields)
    if names is None or not isinstance(payload, dict):
        return payload
    key = _envelope(payload)
    if key is not None:
        rows = payload[key]
        _validate(names, rows, noun=f"{key} rows")
        # Rebuilt in the payload's own key order, so a narrowed response reads the
        # same way as an un-narrowed one.
        return {
            k: ([_project_row(row, names) for row in v] if k == key else v)
            for k, v in payload.items()
        }
    _validate(names, [payload], noun="this result")
    return _project_row(payload, names)


# --- the one entry point the tools call -------------------------------------


def shape(payload: Any, *, fields: list[str] | None = None, full: bool = False) -> Any:
    """Apply both knobs to a read result: narrow to ``fields``, then truncate long
    free text unless ``full``.

    Narrowing runs first — a field the caller dropped needs no truncating — and the
    two are independent: truncation is keyed on the field *name*, which a projection
    preserves, and the size hint is computed from the value being cut, which a
    projection copies verbatim.

    With ``fields=None`` and truncation off (``full=True`` or
    ``PANDAN_MAX_TEXT_CHARS=0``) this returns the client's payload untouched.
    """
    return truncate(project(payload, fields), text_limit(full=full))
