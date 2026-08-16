"""``pandan`` — card / board / epic CRUD over the Pandan API (KAN-22, KAN-23).

Framework choice: **stdlib ``argparse``** with subparsers. No new dependency —
consistent with the repo's thin ethos (the MCP server likewise leans on the SDK +
httpx and nothing else). ``typer``/``click`` would buy nicer help/colour but add a
dependency for a handful of subcommands; not worth it here.

Card verbs are top-level (``pandan list``/``create``/…); boards and epics are nested
groups (``pandan board list``, ``pandan epic create``) so their verbs don't collide with
the card verbs — parity with the board/epic surface of ``/api/v1`` (KAN-23).

The CLI is a thin adapter over the shared ``PandanClient``: parse args → env
config → one client call → print. ``--format`` picks the rendering (V47, KAN-430):

* ``human`` (the default) — a concise ``ticket  column  title  pts=N`` line
  (``pts=-`` when unestimated, reading the API's ``story_points``). List verbs take
  ``--fields a,b,c`` to widen that minimal default row on demand (V42, KAN-425); it
  shapes the **human** row only. This tab-separated form is already key-free, so it
  is both the default and the cheapest list output — V47 did not touch it.
* ``json`` — the client's raw dict, indented (``pandan list --format json | jq …``).
  **``--json`` is a supported alias for ``--format json``** and is going nowhere.
* ``toon`` — the same object in `TOON <https://toonformat.dev/>`_, which prints a
  uniform array's field names once in a header instead of per row. On our *nested*
  payloads that is a large saving over ``--format json``: ``metrics`` −56%,
  ``activity`` −43%, ``epic list`` −37% measured in ``o200k_base`` tokens. On a
  single ``get`` it is a wash, and on the cards list it is worse than the TSV
  default — which is exactly why the default stayed put.

``json`` and ``toon`` render the **same** object through one shaping function
(``_structured_payload``) and differ only in the serializer, so the two can't drift.

**Every list verb ends with a pre-computed aggregate** (V44, KAN-427 — AXI 4), so an
agent never pays a second round trip for counts: ``42 cards · 12 todo · 5 in_progress
· 25 done`` as the last human line, or the same numbers as a ``summary`` object beside
the rows under ``--format json``/``toon``. It always describes **the rows actually
returned** — under ``--limit``, a filter, or one keyset page — never the whole board.

**Long free-text fields are truncated with a size hint** (V45, KAN-428 — AXI 3), so
one ``get`` can't blow an agent's context: a card/epic ``description``, a
comment/notification ``body`` and an ``attention_note`` are cut at
``PANDAN_MAX_TEXT_CHARS`` characters (default 500; ``0`` disables) and marked
``(truncated, 3431 chars total — use --full to see complete body)``. The count is the
**true original** length in characters. This applies to the human rows *and* to
``--format json``/``toon`` — the payload's shape is unchanged (a truncated string is
still a string) and ``--full`` restores every body everywhere. A **single** ``get``
also now prints that description at all, which it never did before: it used to be a
one-line summary, so the body was invisible without ``--json``.

**A bare ``pandan`` shows state, not usage** (V46, KAN-429 — AXI 8). With no verb at
all it prints its own identity (version + build provenance + the exact executable to
re-invoke), a one-sentence description, and then the **default board's open cards**
with V44's aggregate — exit **0**. No default board configured → the board list (the
content you need to pick one). No token → V43's structured config error, same as any
other verb. ``--help`` still prints the usage text, and the bare branch cannot have
disturbed it, because it is an argv **allow-list** (``_is_bare_invocation``): anything
that isn't "no verb, at most the global output flags" reaches argparse untouched.
``overview`` is a **listed** verb in ``--help`` (KAN-492); it shipped unlisted in V46
only to keep that slice's byte-freeze green, which was a one-slice regression guard,
not a permanent contract.

**Results carry ``help[]`` next-step hints** (V46, KAN-429 — AXI 9): a ``help: pandan
move <id> in_progress`` line per plausible next step, printed after the result.
They are **templates** — a fixed flag is carried forward (``--board 7``), every
runtime value stays parameterised (``<id>``, ``"…"``, ``N``) — and they are
suppressed under ``--format json``/``toon``. Hints are printed **before** V44's
aggregate (KAN-492), so a hinted list verb still ends with its aggregate: the
``tail -1`` contract is preserved by *ordering* rather than by withholding the hint
(see ``_HINTS``). A result that names **no** entity — an empty list, ``next``'s
``(no card ready)`` — drops the hints whose ``<id>`` slot would have had nothing to
refer to, and keeps the rest (KAN-526).

Failures are **structured and on stdout** (V43, KAN-426 — AXI 6): one tab-separated
row ``error<TAB><code><TAB><message><TAB><arg>`` (``-`` when no single argument is at
fault), or the same object serialized under ``--format json``/``toon``. stdout is the
machine channel, so an agent parses one stream; stderr keeps only human extras
(argparse's usage block, the ``KANBAN_*`` deprecation notice). No verb ever prompts
when stdin isn't a tty.

Exit codes (for scripting) — **stable, never renumbered**:
    0  success
    1  general / config / non-mapped API error
    2  usage error (argparse's own convention)
    3  401 unauthorized (bad/missing token)
    4  403 forbidden (board exists but isn't yours)
    5  404 not found — including a KAN-/EPIC- ticket that resolves to nothing, so
       the code doesn't depend on whether you addressed the card by id or by ticket
    6  409 conflict — the resource state contradicts the request

``6`` is an **addition**, not a renumbering (V51-era, KAN-831): it is the pandan half of
a suite-wide decision taken on kaya's side (kaya KAN-724 / kaya ADR 0009), where a 409 is
a designed, *retryable* outcome (a stale ``--if-updated-at`` precondition comes back with
the attempted and stored notes so the caller can merge and retry). kaya adopted this exit
table verbatim from pandan so an operator scripting both never has to remember which is
which, so letting the same status exit ``6`` there and ``1`` here would reintroduce
exactly the cost the shared table removes. **Be honest about what pandan gains**: its own
two 409s — a duplicate board member, and a card write with no board to default to — are
*terminal*, not retryable, so pandan gains the sameness rather than retry semantics. That
is still worth having on its own: a caller can tell "already a member" from "the API is
unreachable" without parsing stdout. Not ``2`` — ``2`` means the caller's *input* was
rejected, and a 409 is well-formed input meeting an inconvenient world.

The rule that decides 1 vs 2: **argparse rejected argv → 2; the CLI rejected a value
at runtime → 1.** ``ERROR_CODES`` below is the whole vocabulary, and each machine
``code`` maps to exactly one exit code.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Sequence
from typing import Any

import httpx
from pandan_client import PandanApiError, PandanClient, split_card_selectors

from . import build_info, context, toon
from .config import (
    _CONFIG_KEYS,
    DEFAULT_API_URL,
    DEFAULT_MAX_TEXT_CHARS,
    Config,
    ConfigError,
    config_file_path,
    find_mcp_json,
    load_config,
    parse_require_board,
    resolve_values,
    unset_config_keys,
    write_config_file,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2  # argparse's own convention; documented here for completeness.
EXIT_AUTH = 3
EXIT_FORBIDDEN = 4
EXIT_NOT_FOUND = 5
EXIT_CONFLICT = 6  # 409 — added in KAN-831; see the docstring's exit-code table.

# --- the error contract (V43, KAN-426 — AXI 6) -------------------------------
# Every machine `code` maps to exactly one exit code. **Both are a published
# contract**: scripts branch on the exit code and agents branch on the code string,
# so entries may be ADDED but never renumbered or renamed. A test pins this table.
ERROR_CODES: dict[str, int] = {
    # argparse rejected argv itself (unknown flag, bad --column value, missing arg).
    "usage": EXIT_USAGE,
    # The CLI rejected a value at runtime → 1 (see the module docstring's 1-vs-2 rule).
    "config": EXIT_ERROR,                 # no token, or unreadable config
    "board_required": EXIT_ERROR,         # verb needs a board; none given or configured
    "confirmation_required": EXIT_ERROR,  # destructive verb without --yes
    "invalid_input": EXIT_ERROR,          # parsed but unusable (bad JSON, wrong shape)
    "invalid_ref": EXIT_ERROR,            # an EPIC- ticket where a card is wanted, etc.
    "unknown_field": EXIT_ERROR,          # --fields named a field the row doesn't have
    "no_token": EXIT_ERROR,               # login/config set got no token to save
    # API-mapped.
    "unauthorized": EXIT_AUTH,            # 401
    "forbidden": EXIT_FORBIDDEN,          # 403
    "not_found": EXIT_NOT_FOUND,          # 404, or a ticket that resolves to nothing
    "conflict": EXIT_CONFLICT,            # 409 — the stored state contradicts the request
    "api_error": EXIT_ERROR,              # any other non-2xx
    # The request never got an answer, or the CLI itself broke.
    "transport": EXIT_ERROR,
    "unexpected": EXIT_ERROR,
}

# HTTP status → machine code. Anything else is "api_error" (exit 1).
_STATUS_CODE = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict"}
# Kept as a derived view (one source of truth) — status → exit code.
_STATUS_EXIT = {status: ERROR_CODES[code] for status, code in _STATUS_CODE.items()}


class CliError(Exception):
    """A failure with a **stable machine code**, the human message, and optionally the
    offending argument / HTTP status. The code decides the exit code (``ERROR_CODES``),
    so a raise site picks the *meaning* and never a number."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        arg: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.arg = arg
        self.status = status
        # KeyError here is a programming error: every code must be in the table.
        self.exit_code = ERROR_CODES[code]


# --- output formats (V47, KAN-430 — AXI 1) -----------------------------------
# One vocabulary for "how does this render", replacing V4-era's `--json` boolean.
# `human` is the default and is the tab-separated form every earlier slice built;
# `json` and `toon` are the two *structured* renderings of one shared payload.
FORMAT_HUMAN = "human"
FORMAT_JSON = "json"
FORMAT_TOON = "toon"
OUTPUT_FORMATS = (FORMAT_HUMAN, FORMAT_JSON, FORMAT_TOON)
# The machine-readable ones. Anything V44/V46 wants to add for humans only (a
# trailing summary line, `help[]` hints) is suppressed when the format is in here.
STRUCTURED_FORMATS = (FORMAT_JSON, FORMAT_TOON)

# How errors render. Set from argv at the top of ``run()`` because an argparse
# failure *is* an error and happens before the parsed namespace exists.
_ERROR_FORMAT = FORMAT_HUMAN


def _set_error_format(fmt: str) -> None:
    global _ERROR_FORMAT
    _ERROR_FORMAT = fmt


def _as_cli_error(exc: BaseException) -> CliError:
    """Classify any exception into the error contract."""
    if isinstance(exc, CliError):
        return exc
    if isinstance(exc, PandanApiError):
        code = _STATUS_CODE.get(exc.status_code, "api_error")
        return CliError(str(exc), code=code, status=exc.status_code)
    if isinstance(exc, ConfigError):
        return CliError(str(exc), code="config")
    if isinstance(exc, context.ContextError):
        # `pandan context …` raises its own exception so it needn't import `cli`
        # (which imports it). It already carries a code from ERROR_CODES.
        return CliError(exc.message, code=exc.code, arg=exc.arg)
    if isinstance(exc, httpx.HTTPError):
        # No answer from the API: connect/read timeout, DNS, refused connection.
        return CliError(f"{type(exc).__name__}: {exc}", code="transport")
    return CliError(f"{type(exc).__name__}: {exc}", code="unexpected")


def _error_payload(err: CliError) -> dict[str, Any]:
    """The structured (``json``/``toon``) error object. Every key is always present
    (``null`` when it doesn't apply) so a consumer never has to test for absence."""
    return {
        "error": {
            "code": err.code,
            "message": err.message,
            "arg": err.arg,
            "status": err.status,
            "exit_code": err.exit_code,
        }
    }


def _error_row(err: CliError) -> str:
    """The human/greppable form: four tab-separated columns, so `cut -f2` is the code
    and `cut -f3` the message. Newlines/tabs inside the message are flattened — via
    the shared ``_flatten`` (KAN-485), which is where this rule now lives for every
    row the CLI prints; it was open-coded here and in ``_field_value``, and the two
    copies each missed ``\\r``."""
    return "\t".join(("error", err.code, _flatten(err.message), err.arg or "-"))


def _print_error(err: CliError, *, fmt: str | None = None) -> int:
    """Print the structured error to **stdout** and return its exit code.

    The error object goes through the same ``_render_structured`` the results do, so
    ``--format toon`` gets a TOON error and not a surprise JSON one."""
    if fmt is None:
        fmt = _ERROR_FORMAT
    if fmt in STRUCTURED_FORMATS:
        print(_render_structured(_error_payload(err), fmt))
    else:
        print(_error_row(err))
    return err.exit_code


COLUMNS = ("todo", "in_progress", "done")
PRIORITIES = ("none", "low", "medium", "high", "urgent")

# Fallback color for `label create` when neither the positional nor --color is
# given (KAN-288). A neutral slate so an unspecified label still renders sensibly;
# the API requires a non-empty color string.
DEFAULT_LABEL_COLOR = "#64748b"


# --- content truncation (V45, KAN-428 — AXI 3) ------------------------------
# A card description on this project's own board runs to ~3.4k characters, so a
# single `get` was the most expensive call an agent could make, and `comment list`
# could return several of them at once. Every output path now caps a long
# free-text field at ``config.max_text_chars`` and says so, in a hint carrying the
# **true total** so the caller can decide whether the rest is worth a second call:
#
#     … (truncated, 3431 chars total — use --full to see complete body)
#
# `--full` opts out everywhere, including the structured formats — the escape hatch
# is what makes truncating a machine payload safe.
#
# Two invariants, both pinned by tests:
#
# * **Characters, never bytes.** Truncation slices a ``str``, which Python indexes
#   by code point, so a multi-byte character (the board's own text is full of
#   ``·``/``—``/``→``) can never be split in half and the output is always valid
#   UTF-8. The reported total is likewise a character count — `len(text)`, not
#   `len(text.encode())`. (Combining marks / ZWJ emoji sequences are *grapheme*
#   clusters, which the stdlib cannot segment; splitting one is cosmetic, produces
#   valid UTF-8, and is out of scope.)
# * **The total is true.** The hint's number is the length of the *original* text,
#   measured before the cut. A hint claiming a wrong size is worse than no hint.
#
# Which fields: an explicit allow-list, not "any long string". Two payload strings
# are load-bearing and must survive verbatim at any length — a keyset
# ``next_cursor`` (truncate it and pagination silently breaks) and a link ``url`` —
# so a blanket rule would be a correctness bug waiting for a long value. The
# allow-list is exactly the API's unbounded ``Text`` columns that hold prose.
_TEXT_FIELDS = frozenset(
    {
        "description",     # card + epic
        "body",            # comment + notification
        "attention_note",  # the needs-human handoff note
        "summary",         # an activity row's human sentence
    }
)


def _truncation_hint(total: int) -> str:
    """The size hint appended to a cut field. ``total`` is the **original** length in
    characters, so the caller can size the follow-up call it might make."""
    return f"(truncated, {total} chars total — use --full to see complete body)"


def _truncate_text(text: str, limit: int) -> tuple[str, int | None]:
    """``(rendered, original_length)`` — with ``original_length`` **None when nothing
    was cut**, which is how every caller decides whether to show a hint.

    ``limit <= 0`` disables truncation (that is what ``--full`` and
    ``PANDAN_MAX_TEXT_CHARS=0`` resolve to), and an under-limit string is returned
    unchanged — identical object, no ellipsis, no hint."""
    if limit <= 0 or len(text) <= limit:
        return text, None
    # `str` slicing is by code point: this cannot split a multi-byte character.
    return text[:limit], len(text)


def _flatten(text: str) -> str:
    """Collapse the three characters that would break a tab-separated row — ``\\t``,
    ``\\n``, ``\\r`` — to single spaces. **The one flattening rule** (KAN-485): every
    row helper that prints free text goes through it, and so does the ``--fields``
    projection (``_field_value``), so the default row and the projection cannot drift
    into disagreeing about what "one line" is — which is exactly what had happened:
    ``comment list --fields body`` was safe while ``comment list`` was not.

    It applies to a *row cell* only. A single-entity ``description:`` block
    (``_description_block``) is deliberately left alone: that output is prose on its
    own lines by design, and flattening it would destroy the paragraphs the caller
    asked for.

    Length-preserving — one character in, one out — which is what lets it run
    **before** ``_truncate_inline`` without changing how much real text survives or
    what the size hint's total says."""
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _truncate_inline(text: str, limit: int) -> str:
    """Truncate for a context that has to stay a single string — a TSV cell or a
    JSON/TOON string value — by appending the ellipsis + hint to the kept prefix.

    Deliberately still a **string**: a structured consumer's ``.description`` keeps
    its type and only gets shorter, which is the smallest change that bounds the
    payload. Promoting it to ``{"text": …, "truncated": true}`` would break every
    caller that reads the field."""
    kept, total = _truncate_text(text, limit)
    if total is None:
        return kept
    return f"{kept}… {_truncation_hint(total)}"


def _truncate_payload(value: Any, limit: int) -> Any:
    """Recursively copy a structured payload with its ``_TEXT_FIELDS`` strings cut to
    ``limit``. Anything else — numbers, booleans, other strings, keys — is returned
    untouched, and an unchanged payload is returned as the same object.

    Only *values reached through a ``_TEXT_FIELDS`` key* are cut, so a long string
    living under some other key (``next_cursor``, ``url``, ``title``) is safe by
    construction rather than by luck."""
    if limit <= 0:
        return value
    if isinstance(value, dict):
        return {
            key: (
                _truncate_inline(item, limit)
                if key in _TEXT_FIELDS and isinstance(item, str)
                else _truncate_payload(item, limit)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_truncate_payload(item, limit) for item in value]
    return value


def _text_limit(*, full: bool, limit: int) -> int:
    """The effective character limit: ``--full`` collapses to ``0`` (= off), which is
    the same value ``PANDAN_MAX_TEXT_CHARS=0`` produces. One concept downstream, so
    no helper below has to know about the flag."""
    return 0 if full else limit


# --- output helpers ---------------------------------------------------------


def _structured_payload(
    result: Any,
    *,
    full: bool = False,
    limit: int = DEFAULT_MAX_TEXT_CHARS,
) -> Any:
    """The object both structured formats serialize — **the one shared serializer**
    V47 (KAN-430) exists to establish. ``json`` and ``toon`` differ only in how this
    return value is written out, so they cannot describe different data.

    It is the client's result **plus** a ``summary`` object beside the rows on a list
    response (V44, KAN-427 — see ``_summary_for``), with its long free-text fields
    cut to ``limit`` characters (V45, KAN-428 — see ``_truncate_payload``). Rows are
    otherwise verbatim: no key is added, removed or retyped, and ``--full``
    (``full=True``) restores every body in full. Every other shape (a single entity,
    metrics, a delete receipt) grows no ``summary``, because there is nothing to
    total. The human counterpart of that ``summary`` is the trailing line in
    ``_emit`` below, rendered from the *same* dict.

    **The aggregate is attached after truncation, never before** — so the counts in
    ``summary`` are structurally out of the truncator's reach, and an activity row's
    own ``summary`` *string* (a ``_TEXT_FIELDS`` member) can still be cut without
    the two ever being confused for each other.
    """
    payload = _truncate_payload(result, _text_limit(full=full, limit=limit))
    # Computed from the untruncated ``result``: the numbers describe the rows the API
    # returned, and cannot be perturbed by how much of a body we chose to print.
    found = _summary_for(result)
    if found is None:
        return payload
    _, summary = found
    # ``summary`` last, so the rows an agent cares about stay at the top of the
    # payload; a list envelope never has a key of that name of its own.
    return {**payload, "summary": summary}


def _render_structured(payload: Any, fmt: str) -> str:
    """Serialize a payload in one of the ``STRUCTURED_FORMATS``.

    ``json.dumps(default=str)`` and ``toon.encode`` agree on how a non-JSON value is
    written (both stringify it), so the two renderings of one payload always carry
    the same data — that equality is the V47 round-trip contract, pinned in
    ``tests/test_toon_format.py``."""
    if fmt == FORMAT_TOON:
        return toon.encode(payload)
    return json.dumps(payload, indent=2, default=str)


def _emit(
    result: Any,
    *,
    fmt: str = FORMAT_HUMAN,
    noun: str = "card",
    fields: list[str] | None = None,
    full: bool = False,
    limit: int = DEFAULT_MAX_TEXT_CHARS,
    hints: list[str] | None = None,
) -> None:
    """Print a command result in ``fmt`` — the CLI's single output chokepoint.

    ``noun`` (``card``/``epic``/``board``) only disambiguates the delete summary,
    whose result dict (``{"deleted": id}``) is otherwise shape-identical across
    entities; everything else is detected from the result's shape.

    ``fields`` is the ``--fields`` projection (V42, KAN-425) and applies to the
    **human** row only: the structured formats carry the client's own keys, so a
    projection there would reshape a documented machine contract for no gain.

    ``full`` / ``limit`` are V45's content truncation (KAN-428): a long free-text
    field is cut to ``limit`` characters with a size hint in **both** branches —
    human and structured — and ``--full`` (``full=True``) turns that off everywhere.
    Truncation is a *content* concern, not a formatting one, so unlike the summary
    line it deliberately is **not** suppressed for structured consumers; the flag is
    their escape hatch instead.

    ``hints`` are V46's ``help[]`` next-step templates (KAN-429), printed here and
    **only** on the human branch — after the ``_humanize`` line and *inside* the
    ``fmt``-guard's fall-through, which is what "suppressed under ``--json``/``--format
    toon``" means mechanically. They print **before** the V44 summary line (KAN-492):
    the aggregate is a published ``tail -1`` contract, so putting the hints above it
    lets any verb carry hints — including a list verb — without breaking it. V46 got
    this order the other way round and paid for it by withholding hints from every
    list verb; ordering is the cheaper of the two prices. They arrive **finished** —
    built by ``_hint_lines`` from the parsed namespace *and* the result, including
    KAN-526's drop of the ``<id>`` templates on a result that names no entity — so
    this function stays a printer that never has to know which verb ran or inspect a
    payload to decide what to print.
    """
    if fmt in STRUCTURED_FORMATS:
        print(_render_structured(_structured_payload(result, full=full, limit=limit), fmt))
        return
    print(_humanize(result, noun=noun, fields=fields, limit=_text_limit(full=full, limit=limit)))
    for line in hints or ():
        print(line)
    # V44 (KAN-427): a list verb's pre-computed aggregate, always its last line, so
    # an agent reads counts off `tail -1` instead of paying a second round trip.
    # Non-list results get none (nothing to total); the structured formats carry the
    # same numbers as a `summary` object instead (see ``_structured_payload``).
    found = _summary_for(result)
    if found is not None:
        print(_summary_line(*found))


def _with_unresolved(text: str, result: Any) -> str:
    """Append the ``(unresolved: …)`` line to a rendered list, if there is one.

    A batch read (issue #254) reports the selectors that matched nothing, and the
    whole reason that report exists is that omitting a miss silently was the one
    option the issue ruled out. So the rule has to hold on **every** human path,
    not just the default one.

    It is a shared helper rather than a line repeated in each branch because the
    first version was exactly that repetition, and it shipped a bug: ``--fields``
    returns early from ``_humanize`` via ``_project_rows``, so the projected
    rendering silently dropped the report — in the combination an agent is most
    likely to use, since ``--refs --fields`` is the cheap read. Funnelling both
    exits through one function is what makes a third exit fail loudly instead.
    """
    unresolved = result.get("unresolved") if isinstance(result, dict) else None
    if not unresolved:
        return text
    return f"{text}\n(unresolved: {', '.join(unresolved)})"


def _humanize(
    result: Any,
    *,
    noun: str = "card",
    fields: list[str] | None = None,
    limit: int = DEFAULT_MAX_TEXT_CHARS,
) -> str:
    """Render a client result as concise human text (one entity per line).

    With ``fields`` set, a list result's rows are projected onto exactly those
    field names instead of the entity's default row; every other shape (and every
    single-entity result) renders as usual.

    ``limit`` is V45's already-resolved character cap (``0`` = don't truncate — what
    ``--full`` collapses to). It reaches three places: a **single** card/epic render,
    which since V45 also shows that entity's ``description`` (the under-disclosure
    the slice's audit found — a one-line summary was hiding the body entirely); a
    comment/notification line's ``body``; and a ``--fields`` projection of a
    free-text column. List *rows* never grow a description block — a hundred-card
    `list` must stay a hundred lines."""
    # The content-first overview (V46, KAN-429). Matched FIRST so it can't be
    # pre-empted by the `cards`/`boards` branch below, then delegated straight back
    # here for the inner payload — the banner is the only thing this branch renders,
    # so open cards and the no-board board list both print exactly as their own verb
    # would. `tool` is the CLI's own key; no API payload has one.
    if isinstance(result, dict) and "tool" in result:
        inner = {key: value for key, value in result.items() if key != "tool"}
        return "\n".join(
            (
                _tool_banner(result["tool"]),
                _humanize(inner, noun=noun, fields=fields, limit=limit),
            )
        )
    if fields:
        projected = _project_rows(result, fields, limit=limit)
        if projected is not None:
            # `--fields` returns early, so it has to append the unresolved line
            # itself — and this is the combination that matters most, since
            # `--refs --fields` is the cheap read an agent actually makes.
            return _with_unresolved(projected, result)
    # Whether a result IS a list is decided in exactly one place — ``_list_envelope``
    # — and this chain dispatches on its answer (KAN-478). Before that, the two
    # functions each carried their own idea of list-ness and disagreed: V44's
    # aggregate correctly declined to summarise a ``template create`` result while
    # this renderer printed the template's unsaved card *definitions* as rows with
    # ``?`` where a ticket number would be. The shared guard excludes both known
    # single-entity payloads that merely *carry* an envelope key — a ``CardRead``'s
    # ``labels`` (KAN-277) and a single template's ``cards`` — and any future one,
    # because it keys off the entity's own ``id``/``ticket_number`` rather than
    # naming the offenders. Each falls through to its single-entity branch below.
    envelope, rows = _list_envelope(result) or (None, [])
    # list_cards; create_cards'/apply_template's `created` (KAN-502); update_cards'
    # `updated` (KAN-519 — the audit finding, see ``_CARD_ENVELOPES``).
    if envelope in _CARD_ENVELOPES:
        # `(no cards)` stays the empty rendering, but it is now a *line* rather than
        # an early return: a batch read (issue #254) where every selector missed has
        # no rows and yet is precisely the case that must not render as silence.
        lines = [_card_line(c) for c in rows] if rows else [f"(no {envelope})"]
        if result.get("next_cursor"):
            lines.append(f"(more — next cursor: {result['next_cursor']})")
        return _with_unresolved("\n".join(lines), result)
    if envelope == "boards":  # list_boards
        return "\n".join(_board_line(b) for b in rows) if rows else "(no boards)"
    if envelope == "epics":  # list_epics
        return "\n".join(_epic_line(e) for e in rows) if rows else "(no epics)"
    if envelope == "labels":  # list_labels
        return "\n".join(_label_line(la) for la in rows) if rows else "(no labels)"
    if envelope == "views":  # list_views
        return "\n".join(_view_line(v) for v in rows) if rows else "(no views)"
    if envelope == "templates":  # list_templates
        return (
            "\n".join(_template_line(t) for t in rows)
            if rows
            else "(no templates)"
        )
    if envelope == "cycles":  # list_cycles
        return "\n".join(_cycle_line(c) for c in rows) if rows else "(no cycles)"
    if envelope == "notifications":  # list_notifications
        return (
            "\n".join(_notification_line(n, limit=limit) for n in rows)
            if rows
            else "(no notifications)"
        )
    if envelope == "activity":  # list_activity
        if not rows:
            return "(no activity)"
        lines = [_activity_line(r) for r in rows]
        if result.get("next_cursor"):
            lines.append(f"(more — next cursor: {result['next_cursor']})")
        return "\n".join(lines)
    if envelope == "comments":  # list_comments
        return (
            "\n".join(_comment_line(c, limit=limit) for c in rows)
            if rows
            else "(no comments)"
        )
    # list_dependencies returns {"card_id", "blocked_by", "blocks"} — ``card_id``
    # is distinctive (a card carries ``id``, not ``card_id``).
    if isinstance(result, dict) and "card_id" in result and "blocked_by" in result:
        return _dep_block(result)
    # link add/rm reshape to {"card_id", "links"} (``card_id`` distinguishes it from
    # a full card, which also carries ``links`` but keys it under ``id``).
    if isinstance(result, dict) and "card_id" in result and "links" in result:
        return _link_block(result)
    # A single comment (add_comment) carries ``body`` + ``author_id`` (no ticket) —
    # matched before the generic card/epic/board branches below.
    if isinstance(result, dict) and "body" in result and "author_id" in result:
        return _comment_line(result, limit=limit)
    # A single notification (mark_read) carries ``kind`` (distinctive — nothing else
    # does) + ``body``; matched before the generic branches below.
    if isinstance(result, dict) and "kind" in result and "body" in result:
        return _notification_line(result, limit=limit)
    # The `me` principal (KAN-614): `{id, email}` and nothing else. `email` is the
    # distinctive key — no other payload this CLI renders carries one — and it is
    # matched here rather than at the end because the generic single-entity branches
    # below key off `name`/`ticket_number`, neither of which a principal has, so it
    # would otherwise fall through to the `json.dumps` catch-all (the KAN-287/478/519
    # family).
    if isinstance(result, dict) and "email" in result and "id" in result:
        return _me_line(result)
    if isinstance(result, dict) and "card" in result:  # dispatch / next (peek/claim)
        card = result["card"]
        return _card_block(card, limit=limit) if card else "(no card ready)"
    if isinstance(result, dict) and "deleted" in result:  # delete_{card,epic,label,view}
        return f"deleted {noun} {result['deleted']}"
    if isinstance(result, dict) and "status" in result:  # warmup
        return _warmup_line(result)
    if isinstance(result, dict) and "velocity" in result and "burndown" in result:
        return _cycle_metrics_block(result)  # cycle metrics (V34)
    if isinstance(result, dict) and "throughput" in result and "cycle_time" in result:
        return _metrics_block(result)  # board metrics (V17)
    # A single saved view carries ``query`` (distinctive) — matched before the
    # generic name-without-title branch below (a view also has ``name``).
    if isinstance(result, dict) and "query" in result and "name" in result:
        return _view_line(result)
    # A single cycle carries ``starts_on`` (distinctive) — matched before the
    # generic name-without-title branch below.
    if isinstance(result, dict) and "starts_on" in result and "name" in result:
        return _cycle_line(result)
    # A single label carries ``color`` (distinctive) — matched before the generic
    # name-without-title branch below.
    if isinstance(result, dict) and "color" in result and "name" in result:
        return _label_line(result)
    # A single card template (``template create``) carries a ``cards`` array of card
    # *definitions* + ``name``. Render it as the template it is — the same line
    # ``template list`` prints for the same entity (KAN-478). Matched before the
    # generic name-without-title branch below, which would print it as a board line.
    if isinstance(result, dict) and "name" in result and isinstance(result.get("cards"), list):
        return _template_line(result)
    # A single entity: epics/boards carry ``name`` (no ``title``); cards carry
    # ``title``. Epics additionally have a ``ticket_number`` (``EPIC-…``).
    if isinstance(result, dict) and "name" in result and "title" not in result:
        return (
            _epic_block(result, limit=limit)
            if "ticket_number" in result
            else _board_line(result)
        )
    if isinstance(result, dict) and "ticket_number" in result:  # a single card
        return _card_block(result, limit=limit)
    return json.dumps(result, default=str)


def _fmt_points(points: int | None) -> str:
    """Render a card's ``story_points`` for human output: ``pts=3`` when set, ``pts=-``
    when null/absent (never the literal string ``None``). The field name mirrors the
    API's ``story_points`` (which ``--json`` shows) so the read value is unambiguous."""
    return f"pts={points if points is not None else '-'}"


def _card_line(card: dict[str, Any]) -> str:
    """One concise line for a card: ticket, column, title, story points (tab-separated).

    Story points read the API's ``story_points`` field (what ``--points`` writes and
    ``--json`` shows), rendered ``pts=<n>``/``pts=-`` so they're never invisible in
    human output (KAN-269). The ticket/column/title prefix is unchanged.

    ``title`` is free text (a ``varchar`` the API does not screen for control
    characters), so it goes through ``_flatten`` — one card, one line (KAN-485)."""
    return "\t".join(
        (
            str(card.get("ticket_number", card.get("id", "?"))),
            str(card.get("column", "")),
            _flatten(str(card.get("title", ""))),
            _fmt_points(card.get("story_points")),
        )
    )


def _description_block(
    head: str, description: Any, *, limit: int = DEFAULT_MAX_TEXT_CHARS
) -> str:
    """``head`` plus a ``description:`` block for a **single**-entity human render
    (V45, KAN-428). The slice's audit found the real gap here: human ``get`` printed
    a one-line summary and no description at all, so the body an agent needs was
    invisible unless it paid for ``--json``.

    ``head`` is returned **unchanged** when there is no description (null or empty),
    which is why "a card with no description renders unchanged" holds structurally
    rather than by test. The hint goes on its own line after the text — a
    description is multi-line prose, so a trailing parenthetical would read as part
    of it — and carries the true original length."""
    if not description:
        return head
    text, total = _truncate_text(str(description), limit)
    lines = [head, "description:", text]
    if total is not None:
        lines.append(_truncation_hint(total))
    return "\n".join(lines)


def _card_block(card: dict[str, Any], *, limit: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """A **single** card: its ``_card_line``, then its truncated description (V45).

    Only the single-entity render uses this — ``list`` rows keep calling
    ``_card_line`` directly, so a 100-card list is still 100 lines."""
    return _description_block(_card_line(card), card.get("description"), limit=limit)


def _fmt_progress(epic: dict[str, Any]) -> str:
    """Render an epic's derived rollup (V32, KAN-296) for human output: ``60% (3/5)``
    plus a ``[health]`` tag when the API reports one (on_track/at_risk/overdue). Falls
    back to ``-`` on an older API that doesn't carry ``progress``."""
    progress = epic.get("progress")
    if not isinstance(progress, dict):
        return "-"
    percent = progress.get("percent", 0)
    done = progress.get("done", 0)
    total = progress.get("total", 0)
    out = f"{percent}% ({done}/{total})"
    health = epic.get("health")
    if health:
        out += f" [{health}]"
    return out


def _epic_line(epic: dict[str, Any]) -> str:
    """One concise line for an epic: ticket, name, progress rollup (tab-separated).

    Progress reads the API's derived ``progress``/``health`` (V32, KAN-296), rendered
    ``<pct>% (<done>/<total>) [<health>]`` so an epic's completion + risk are visible
    in human output; ``--json`` shows the full objects."""
    return "\t".join(
        (
            str(epic.get("ticket_number", epic.get("id", "?"))),
            _flatten(str(epic.get("name", ""))),
            _fmt_progress(epic),
        )
    )


def _epic_block(epic: dict[str, Any], *, limit: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """A **single** epic: its ``_epic_line``, then its truncated description (V45).

    Same shape as ``_card_block`` — an epic's description is the other unbounded
    prose field a single-entity read was hiding. ``epic list`` rows are unaffected."""
    return _description_block(_epic_line(epic), epic.get("description"), limit=limit)


def _board_line(board: dict[str, Any]) -> str:
    """One concise line for a board: id, name (tab-separated)."""
    return "\t".join((str(board.get("id", "?")), _flatten(str(board.get("name", "")))))


def _me_line(principal: dict[str, Any]) -> str:
    """One concise line for the authenticated principal: id, email (tab-separated).

    Two columns because ``GET /api/v1/me`` returns exactly two fields, and that
    minimum is deliberate (KAN-530 — it is a cross-app contract, so pandan does not
    grow it). Id first, like every other row here, so ``cut -f1`` is always the
    handle and ``cut -f2`` the part a human reads."""
    return "\t".join(
        (
            str(principal.get("id", "?")),
            _flatten(str(principal.get("email") or "-")),
        )
    )


def _label_line(label: dict[str, Any]) -> str:
    """One concise line for a label: id, name, color (tab-separated)."""
    return "\t".join(
        (
            str(label.get("id", "?")),
            _flatten(str(label.get("name", ""))),
            _flatten(str(label.get("color", ""))),
        )
    )


def _view_line(view: dict[str, Any]) -> str:
    """One concise line for a saved view: id, name, its query as compact JSON.

    The query needs no flattening — ``json.dumps`` escapes a control character
    inside a string value, so the cell is single-line by construction."""
    return "\t".join(
        (
            str(view.get("id", "?")),
            _flatten(str(view.get("name", ""))),
            json.dumps(view.get("query", {}), default=str, sort_keys=True),
        )
    )


def _cycle_line(cycle: dict[str, Any]) -> str:
    """One concise line for a cycle: id, name, starts_on, ends_on (tab-separated).

    Dates read the API's ``starts_on`` / ``ends_on`` (rendered ``-`` when unset), so
    an iteration's window is visible without ``--json``."""
    return "\t".join(
        (
            str(cycle.get("id", "?")),
            _flatten(str(cycle.get("name", ""))),
            str(cycle.get("starts_on") or "-"),
            str(cycle.get("ends_on") or "-"),
        )
    )


def _template_line(tmpl: dict[str, Any]) -> str:
    """One concise line for a card template: id, name, card count (tab-separated).

    Matches the other list verbs' human output (KAN-287) — ``template list`` used
    to dump raw JSON even without ``--json``. The stored ``cards`` list is a JSON
    array of card payloads; we show its length rather than the payloads."""
    cards = tmpl.get("cards") or []
    return "\t".join(
        (
            str(tmpl.get("id", "?")),
            _flatten(str(tmpl.get("name", ""))),
            f"{len(cards)} cards",
        )
    )


def _activity_line(row: dict[str, Any]) -> str:
    """One concise line for an activity row: timestamp, actor, action, summary.

    ``summary`` is a server-composed sentence that **embeds the card's title**
    (``created KAN-3: Fix login``) and ``actor_label`` a denormalised human handle, so
    both are free text and both are flattened — one activity row, one line (KAN-485)."""
    return "\t".join(
        (
            str(row.get("ts", "")),
            _flatten(str(row.get("actor_label") or "-")),
            str(row.get("action", "")),
            _flatten(str(row.get("summary", ""))),
        )
    )


def _notification_line(n: dict[str, Any], *, limit: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """One concise line for a notification (V37, KAN-301): id, kind, read/unread
    state, body (tab-separated). The body is a ``Text`` column like a comment's, so
    it truncates the same way (V45, KAN-428) — and, since KAN-485, flattens the same
    way too: **flatten first, then truncate**, so a newline near the limit cannot
    change how much real text survives and the size hint stays on this row's line."""
    return "\t".join(
        (
            str(n.get("id", "?")),
            str(n.get("kind", "")),
            "read" if n.get("read_at") else "unread",
            _truncate_inline(_flatten(str(n.get("body", ""))), limit),
        )
    )


def _warmup_line(result: dict[str, Any]) -> str:
    """One concise line for a warmup result: the status, plus any detail.

    ``ok`` → the API is awake; ``waking``/``error`` carry a ``detail`` explaining
    what to do next (call again shortly / what failed). ``detail`` is flattened
    (KAN-485): on the error path it is a stringified API error, which can carry a
    response body, and this is a two-column row like any other."""
    status = str(result.get("status", "?"))
    if status == "ok":
        return "ok\tAPI is awake"
    detail = result.get("detail")
    return f"{status}\t{_flatten(str(detail))}" if detail else status


def _fmt_duration(seconds: float | None) -> str:
    """A compact human duration (e.g. ``2h3m``, ``45s``) — ``-`` when there's none."""
    if seconds is None:
        return "-"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if hours else f"{days}d"


def _metrics_block(result: dict[str, Any]) -> str:
    """Render board metrics (V17) as a compact multi-line stats readout."""
    since = result.get("since") or "all time"
    cycle = result.get("cycle_time", {})
    aging = result.get("aging_wip", {})
    lines = [
        f"board {result.get('board_id', '?')}  (since: {since})",
        f"throughput:  {result.get('throughput', 0)} done",
        (
            "cycle time:  "
            f"avg {_fmt_duration(cycle.get('avg_seconds'))}  "
            f"median {_fmt_duration(cycle.get('median_seconds'))}  "
            f"p90 {_fmt_duration(cycle.get('p90_seconds'))}  "
            f"(n={cycle.get('count', 0)})"
        ),
        (
            "aging WIP:   "
            f"{aging.get('count', 0)} in progress  "
            f"avg {_fmt_duration(aging.get('avg_seconds'))}  "
            f"max {_fmt_duration(aging.get('max_seconds'))}"
        ),
    ]
    # The per-row cells below are one line each, so the caller-supplied ``assignee``
    # is flattened like any other row's free text (KAN-485).
    for item in aging.get("items", []):
        assignee = _flatten(str(item.get("assignee") or "(unassigned)"))
        lines.append(
            f"  {item.get('ticket_number', '?')}\t{assignee}\t"
            f"{_fmt_duration(item.get('age_seconds'))}"
        )
    by_assignee = result.get("by_assignee", [])
    if by_assignee:
        lines.append("by assignee:")
        for row in by_assignee:
            who = _flatten(str(row.get("assignee") or "(unassigned)"))
            lines.append(f"  {who}\tdone {row.get('throughput', 0)}\twip {row.get('wip', 0)}")
    return "\n".join(lines)


def _cycle_metrics_block(result: dict[str, Any]) -> str:
    """Render cycle burndown / velocity (V34) as a compact multi-line readout."""
    unit = result.get("unit", "points")
    committed = result.get("committed", {})
    completed = result.get("completed", {})
    lines = [
        f"cycle {result.get('cycle_id', '?')}  (board {result.get('board_id', '?')}, unit: {unit})",
        f"committed:   {committed.get('count', 0)} stories  {committed.get('points', 0)} pts",
        f"completed:   {completed.get('count', 0)} stories  {completed.get('points', 0)} pts",
        f"velocity:    {result.get('velocity', 0)} pts done",
    ]
    burndown = result.get("burndown", [])
    if burndown:
        lines.append(f"burndown ({unit}):")
        for point in burndown:
            lines.append(
                f"  {point.get('date', '?')}\t"
                f"remaining {point.get('remaining', 0)}\t"
                f"ideal {point.get('ideal', 0)}"
            )
    else:
        lines.append("burndown:    (no dated window)")
    return "\n".join(lines)


# --- dependency / link / comment render helpers (KAN-270) -------------------


def _fmt_ids(ids: list[int]) -> str:
    """A compact, comma-separated id list — ``(none)`` when empty."""
    return ", ".join(str(i) for i in ids) if ids else "(none)"


def _dep_block(result: dict[str, Any]) -> str:
    """Render a card's dependency edges (``list_dependencies``): the ids that block
    it (``blocked_by``) and the ids it blocks (``blocks``)."""
    return "\n".join(
        (
            f"card {result.get('card_id', '?')}",
            f"blocked_by:\t{_fmt_ids(result.get('blocked_by', []))}",
            f"blocks:\t{_fmt_ids(result.get('blocks', []))}",
        )
    )


def _comment_line(comment: dict[str, Any], *, limit: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """One concise line for a comment: id, created_at, body (tab-separated).

    The body is truncated to ``limit`` characters with a size hint (V45, KAN-428) —
    this was the CLI's other unbounded surface: a ``comment list`` on a card with a
    few long notes returned all of them in full.

    It is also **flattened before it is truncated** (KAN-485). A body with newlines —
    which the board's own comments frequently have — used to spill across several
    output lines, so an agent splitting on newline over-counted comments and
    mis-associated ids with bodies. V45's truncation bounded that spill without ending
    it: 500 characters of prose with two newlines in it is still three lines. Flatten
    first so the hint lands on this row rather than on a fragment of it."""
    return "\t".join(
        (
            str(comment.get("id", "?")),
            str(comment.get("created_at", "")),
            _truncate_inline(_flatten(str(comment.get("body", ""))), limit),
        )
    )


def _link_line(link: dict[str, Any]) -> str:
    """One concise line for a work-link: id, label, url (tab-separated).

    Both cells are caller-supplied strings, so both are flattened (KAN-485)."""
    return "\t".join(
        (
            str(link.get("id", "?")),
            _flatten(str(link.get("label", ""))),
            _flatten(str(link.get("url", ""))),
        )
    )


def _link_block(result: dict[str, Any]) -> str:
    """Render a card's work-links (add/rm result): a header line then one line per
    link (id, label, url), or ``(no links)`` when there are none."""
    links = result.get("links", [])
    header = f"card {result.get('card_id', '?')}"
    if not links:
        return f"{header}\n(no links)"
    return "\n".join([header, *(_link_line(la) for la in links)])


# --- --fields projection (V42, KAN-425 — AXI 2) -----------------------------
# The default human row is deliberately minimal (4 fields for a card), which is
# right for the common case but means anything else needs `--json` + jq. `--fields
# a,b,c` widens that row on any list verb without leaving the tab-separated form.
#
# The vocabulary is **the row's own `--json` keys** rather than a hand-maintained
# table, so it can never drift from the API (the repo has three-places-in-sync
# problems already — see CLAUDE.md on `column`). Two aliases exist for the names
# the default row displays but the payload spells differently.
#
# A SECOND COPY of this table lives in `mcp/pandan_mcp/shaping.py` (KAN-501 gave the
# MCP read tools a `fields` argument and could not import this module — the MCP
# server depends on `pandan-client` only, never on `pandan-cli`). KAN-502 considered
# hoisting it into the shared client and **deliberately kept it duplicated**: it is
# presentation vocabulary, and `pandan-client` is transport. If you change this
# table, change that one; the canonical-key rule must stay identical in both.

FIELD_ALIASES = {
    "ticket": "ticket_number",
    "pts": "story_points",
    "points": "story_points",
}

# The list envelopes the shared client returns (README §"The --json output shape").
# Order mirrors the checks in ``_humanize``; a result carries exactly one of these.
_LIST_ENVELOPES = (
    "cards",
    "created",
    "updated",
    "boards",
    "epics",
    "labels",
    "views",
    "templates",
    "cycles",
    "notifications",
    "activity",
    "comments",
)

# The envelopes whose rows are **cards**, so they share one renderer and one
# aggregate shape (KAN-502). ``created`` is ``create_cards``' own key — ``batch-create``
# returns ``{"created": [<card>, …]}`` verbatim rather than re-labelling it ``cards``,
# because ``--format json`` is documented as the client's raw dict. ``apply_template``
# returns the same ``created`` key (``response_model=list[CardRead]``), so ``template
# apply`` has rendered rows since KAN-502 — KAN-519 filed it as still broken and the
# audit that card asked for found the claim stale by one slice. ``updated`` is
# ``update_cards``' key (``batch-update``, ``PATCH /cards/batch``, also
# ``list[CardRead]``) and was the family's real live instance: unrecognised here, it
# fell through ``_humanize`` to raw ``json.dumps`` with no aggregate.
_CARD_ENVELOPES = ("cards", "created", "updated")

# Envelope key → the singular noun used in the unknown-field error message.
_ROW_NOUN = {
    "cards": "card",
    "created": "card",
    "updated": "card",
    "boards": "board",
    "epics": "epic",
    "labels": "label",
    "views": "view",
    "templates": "template",
    "cycles": "cycle",
    "notifications": "notification",
    "activity": "activity",
    "comments": "comment",
}


def _fields_arg(value: str) -> list[str]:
    """argparse ``type`` for ``--fields``: a comma-separated field list, lower-cased
    and de-blanked. An empty / all-blank value is a usage error (exit 2); an
    *unknown* name is a runtime error raised at render time (exit 1), because the
    valid names are the keys of the rows actually returned."""
    names = [part.strip().lower() for part in value.split(",")]
    names = [n for n in names if n]
    if not names:
        raise argparse.ArgumentTypeError(
            "expected a comma-separated list of field names, e.g. --fields ticket,title,assignee"
        )
    return names


def _resolve_field(name: str) -> str:
    return FIELD_ALIASES.get(name, name)


def _field_value(value: Any) -> str:
    """Render one projected value as compact text: ``-`` for null, ``true``/``false``
    for booleans, a comma-joined summary for a list (each item by its ``name`` /
    ``ticket_number`` / ``id`` when it's an object), compact JSON for anything else
    nested. Never multi-line — a projected row stays one line."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        if not value:
            return "-"
        return ",".join(_field_item(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    # ``_flatten`` is this line's own former body, lifted into a shared helper so the
    # default row helpers cut free text exactly the way this projection does (KAN-485).
    # It also picks up ``\r``, which this branch used to let through.
    return _flatten(str(value))


def _field_item(item: Any) -> str:
    """One element of a projected list: an object shows its most identifying key
    (``name`` for labels, ``ticket_number`` for cards, else ``id``)."""
    if isinstance(item, dict):
        for key in ("name", "ticket_number", "id"):
            if item.get(key) is not None:
                return str(item[key])
        return json.dumps(item, default=str, sort_keys=True, separators=(",", ":"))
    return str(item)


def _validate_fields(fields: list[str], rows: list[Any], noun: str) -> None:
    """Reject an unknown field name, naming the offender and listing what's valid.

    Valid names are the union of the keys the returned rows carry, plus the aliases
    that resolve onto one of them."""
    known: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            known |= {str(k) for k in row}
    available = sorted(known | {a for a, target in FIELD_ALIASES.items() if target in known})
    for name in fields:
        if _resolve_field(name) not in known:
            raise CliError(
                f"unknown --fields name {name!r} for {noun} rows; "
                f"available: {', '.join(available)}",
                code="unknown_field",
                arg=name,
            )


def _project_line(row: Any, fields: list[str], *, limit: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """One projected row. A cell naming a ``_TEXT_FIELDS`` column is truncated to
    ``limit`` (V45, KAN-428) — ``--fields ticket,description`` was otherwise a way to
    put a 3.4k-character body back on a TSV row. The truncation is keyed on the
    **resolved** field name, the same allow-list ``_truncate_payload`` uses, so the
    human and structured surfaces cut exactly the same columns."""
    if not isinstance(row, dict):
        return _field_value(row)
    cells = []
    for name in fields:
        resolved = _resolve_field(name)
        cell = _field_value(row.get(resolved))
        if resolved in _TEXT_FIELDS:
            cell = _truncate_inline(cell, limit)
        cells.append(cell)
    return "\t".join(cells)


def _project_rows(
    result: Any, fields: list[str], *, limit: int = DEFAULT_MAX_TEXT_CHARS
) -> str | None:
    """Render a list result's rows projected onto ``fields``, or ``None`` when the
    result isn't a list envelope (then the caller falls back to the default render).

    The definitive empty state (AXI 5) and the ``next_cursor`` hint are preserved
    verbatim — a projection changes which columns print, nothing else.

    List-ness comes from ``_list_envelope``, the same one place ``_humanize`` and
    V44's aggregate ask (KAN-478) — so the third copy of "is this a list?" is gone
    along with its own hand-written KAN-277 exception for a ``CardRead``'s ``labels``."""
    found = _list_envelope(result)
    if found is None:
        return None
    key, rows = found
    if not rows:
        return f"(no {key})"
    _validate_fields(fields, rows, _ROW_NOUN.get(key, key))
    lines = [_project_line(row, fields, limit=limit) for row in rows]
    if isinstance(result, dict) and result.get("next_cursor"):
        lines.append(f"(more — next cursor: {result['next_cursor']})")
    return "\n".join(lines)


# --- pre-computed list aggregates (V44, KAN-427 — AXI 4) --------------------
# Every list verb ends with one aggregate line, so an agent never pays a second
# round trip for counts it could have been handed. The aggregate describes **the
# returned set** — under `--limit`, a filter, or one keyset page it totals the rows
# actually returned and nothing else. That is not a limitation to fix: the CLI has
# exactly one response in hand, and a line that silently described the whole board
# would be a number the caller cannot reconcile with the rows above it.
#
# One dispatcher (`_summary_for`) decides the shape and computes the numbers once;
# `_structured_payload` attaches its dict as `summary` and `_emit` renders the human
# line **from that same dict**. So human / json / toon cannot disagree about counts.

# Envelope key → (singular, plural) noun for the leading `<n> <noun>` clause.
# Every `_LIST_ENVELOPES` key needs an entry — a test pins the two tuples together
# so a new list verb cannot ship a summary line reading "1 cycles".
_SUMMARY_NOUN: dict[str, tuple[str, str]] = {
    "cards": ("card", "cards"),
    # ``batch-create``/``template apply`` and ``batch-update`` both hold cards, so they
    # total like a card list.
    "created": ("card", "cards"),
    "updated": ("card", "cards"),
    "boards": ("board", "boards"),
    "epics": ("epic", "epics"),
    "labels": ("label", "labels"),
    "views": ("view", "views"),
    "templates": ("template", "templates"),
    "cycles": ("cycle", "cycles"),
    "notifications": ("notification", "notifications"),
    # "activity" is already a mass noun — "50 activitys" is not a sentence.
    "activity": ("activity row", "activity rows"),
    "comments": ("comment", "comments"),
}

# The epic health vocabulary (backend ``schemas.EpicHealth``). ``health`` is null
# when the epic has no ``target_date``, so these buckets need NOT sum to ``count``.
_EPIC_HEALTHS = ("on_track", "at_risk", "overdue")

# `dep list` is the one list verb whose response is two arrays rather than one
# envelope, so its summary gets a pseudo-key of its own.
_DEPENDENCIES = "dependencies"


def _list_envelope(result: Any) -> tuple[str, list[Any]] | None:
    """The ``(envelope key, rows)`` of a list response, or ``None`` for anything else.

    Two **single-entity** payloads carry an envelope key of their own and must not be
    counted as lists: a ``CardRead`` has a ``labels`` array (the KAN-277 trap) and a
    single template has a ``cards`` array (``template create``). One rule excludes
    both — a list envelope has no ``id`` / ``ticket_number`` of its own.

    **This is the CLI's only definition of "is this a list?"** (KAN-478). ``_humanize``
    (the human rows), ``_project_rows`` (``--fields``) and ``_summary_for`` (V44's
    aggregate) all dispatch on this one answer. They each used to carry their own
    version, and they disagreed: the aggregate declined to summarise a ``template
    create`` result while ``_humanize`` printed the template's unsaved card
    definitions as rows with ``?`` for a ticket number. A test pins the three
    together, because that class of bug has now been hit twice."""
    if not isinstance(result, dict):
        return None
    if "id" in result or "ticket_number" in result:
        return None
    for key in _LIST_ENVELOPES:
        rows = result.get(key)
        if isinstance(rows, list):
            return key, rows
    return None


def _card_summary(rows: list[Any]) -> dict[str, Any]:
    """Per-column counts + the needs-human tally for a card list.

    Buckets are derived from ``COLUMNS``, so adding a board column (a `varchar` +
    CHECK, deliberately cheap to extend — see CLAUDE.md) extends the summary with
    it. A row whose ``column`` is outside ``COLUMNS`` still counts in ``count`` but
    lands in no bucket, so the buckets need not sum to ``count``."""
    counts = dict.fromkeys(COLUMNS, 0)
    needs_human = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        column = row.get("column")
        if column in counts:
            counts[column] += 1
        if row.get("needs_human"):
            needs_human += 1
    return {**counts, "needs_human": needs_human}


def _epic_summary(rows: list[Any]) -> dict[str, Any]:
    """The rollup spread over an epic list: child stories done / total across the
    returned epics (``percent`` computed the way the API computes a single epic's —
    ``round(done/total*100)``, ``0`` when there are no children), plus how many epics
    sit in each health bucket."""
    total = 0
    done = 0
    health = dict.fromkeys(_EPIC_HEALTHS, 0)
    for row in rows:
        if not isinstance(row, dict):
            continue
        progress = row.get("progress")
        if isinstance(progress, dict):
            total += int(progress.get("total") or 0)
            done += int(progress.get("done") or 0)
        bucket = row.get("health")
        if bucket in health:
            health[bucket] += 1
    return {
        "stories_total": total,
        "stories_done": done,
        "percent": round(done / total * 100) if total else 0,
        **health,
    }


def _notification_summary(rows: list[Any]) -> dict[str, Any]:
    """Read/unread split for a notification list — ``read_at`` unset means unread,
    the same test ``_notification_line`` renders."""
    unread = sum(1 for row in rows if isinstance(row, dict) and not row.get("read_at"))
    return {"unread": unread, "read": len(rows) - unread}


def _summary_for(result: Any) -> tuple[str, dict[str, Any]] | None:
    """The pre-computed aggregate for a list result — ``(kind, summary)`` — or
    ``None`` when the result is not a list (a single entity, metrics, a delete
    receipt: nothing to total).

    ``kind`` is the envelope key (or ``_DEPENDENCIES`` for ``dep list``) and is
    deliberately **not** part of the structured payload: the payload already names
    the rows. It only tells ``_summary_line`` which shape to render."""
    # `dep list` first — its response is two arrays, not an envelope, and `card_id`
    # + `blocked_by` is the same pair ``_humanize`` keys its dep branch off.
    if isinstance(result, dict) and "card_id" in result and "blocked_by" in result:
        return _DEPENDENCIES, {
            "blocked_by": len(result.get("blocked_by") or []),
            "blocks": len(result.get("blocks") or []),
        }
    found = _list_envelope(result)
    if found is None:
        return None
    key, rows = found
    summary: dict[str, Any] = {"count": len(rows)}
    if key in _CARD_ENVELOPES:
        summary.update(_card_summary(rows))
    elif key == "epics":
        summary.update(_epic_summary(rows))
    elif key == "notifications":
        summary.update(_notification_summary(rows))
    return key, summary


def _summary_line(kind: str, summary: dict[str, Any]) -> str:
    """The human aggregate, e.g. ``42 cards · 12 todo · 5 in_progress · 25 done``
    (``· 3 needs-human`` appended only when non-zero, so a board with no handoffs
    pending doesn't carry a permanent ``· 0``).

    Rendered from the very dict ``_structured_payload`` attaches, never recomputed:
    a structured consumer and a human read the same numbers by construction."""
    if kind == _DEPENDENCIES:
        return f"{summary['blocked_by']} blocked_by · {summary['blocks']} blocks"
    count = summary["count"]
    singular, plural = _SUMMARY_NOUN.get(kind, (kind, kind))
    parts = [f"{count} {singular if count == 1 else plural}"]
    if kind in _CARD_ENVELOPES:
        # The column buckets print even at zero — that IS the definitive state of a
        # filtered set (`--column todo` → `· 0 done`), and AXI 5 asks for definitive.
        parts += [f"{summary[column]} {column}" for column in COLUMNS]
        if summary["needs_human"]:
            parts.append(f"{summary['needs_human']} needs-human")
    elif kind == "epics":
        parts.append(
            f"{summary['stories_done']}/{summary['stories_total']} stories done "
            f"({summary['percent']}%)"
        )
        parts += [f"{summary[b]} {b}" for b in _EPIC_HEALTHS if summary[b]]
    elif kind == "notifications":
        parts.append(f"{summary['unread']} unread")
    return " · ".join(parts)


# --- next-step hints (V46, KAN-429 — AXI 9) ---------------------------------
# Contextual disclosure: a result says what the *plausible next command* is, so the
# caller doesn't have to go read `--help` to find out. Three rules make this a
# feature rather than noise:
#
# * **A hint is a template, never a filled-in command.** Runtime values stay
#   parameterised — `<id>`, `"…"`, `N` — because a template teaches the shape of the
#   next call, while a pre-filled `pandan move 412 in_progress` invites executing a
#   mutation nobody chose. It is also the only honest rendering after a *set* of
#   rows, where there is no single id to fill. Pinned by a test that asserts both
#   that the placeholder survives AND that no identifier from the result leaked in.
# * **Fixed flags are carried forward.** Exactly one: an explicit `--board <n>`,
#   substituted into the `{board}` slot of the templates that accept it. A board
#   that resolved from `PANDAN_BOARD_ID` is deliberately NOT carried — the next
#   command resolves it the same way, so spelling it out would be noise. Only
#   templates carrying the `{board}` slot are board-scoped, so a hint can never
#   grow a flag its verb doesn't accept.
# * **A list verb may carry hints, because the hints print ABOVE the aggregate.**
#   V46 excluded list verbs outright: the parser epilog promises "Every list verb ends
#   with a pre-computed aggregate", i.e. `tail -1`, and V46 printed hints *after* the
#   summary line, so a hinted list verb would have broken that contract. KAN-492
#   reversed the ordering in ``_emit`` instead (hints, then aggregate), which preserves
#   the contract literally and word-for-word while letting `list` carry what is
#   arguably the most useful hint in the tool — `pandan move <id> in_progress`, the
#   next step after looking at the board. What is left of the old rule is the part that
#   was really about usefulness, not ordering: hints go where the next step is
#   genuinely ambiguous (a single entity, a mutation's receipt, the overview, a card
#   list), not on every list verb by reflex — `label list` / `view list` and friends
#   suggest nothing a caller isn't already about to type.
# * **A hint that names an entity is dropped when the result names none** (KAN-526).
#   Letting a list verb carry hints created a state that could not exist before it:
#   `pandan list` on an empty board printed `(no cards)` and then offered
#   `pandan get <id>` / `pandan move <id> in_progress` — next steps on rows the same
#   call had just said do not exist. The rule is structural, not per-verb: a template
#   carrying the `<id>` slot takes its referent FROM the result, so on a result that
#   names no entity the slot has nothing to fill and the hint is dropped. Everything
#   else survives, which is why the answer differs per verb without a per-verb table:
#   an empty `overview` still prints `pandan list --column todo` and
#   `pandan next --claim` — the two hints that tell a new user what to do with an
#   empty board — and drops only `pandan get <id>`. The predicate lives in
#   ``_hint_lines``, so ``_emit`` still receives a finished list of lines and stays a
#   printer that never inspects a payload.
HINT_PREFIX = "help:"

# The slot an explicit ``--board`` is substituted into. Plain ``str.replace``, not
# ``str.format`` — the templates are full of ``"…"`` and ``<id>`` and must never
# depend on brace escaping.
_HINT_BOARD_SLOT = "{board}"

# The slot that makes a hint *about a row*: `pandan get <id>` is only a next step if
# the result named an id to put there. Reused as the drop predicate on an empty
# result (KAN-526) — no second annotation, because "carries `<id>`" and "refers to an
# entity in the result" are the same property, and the hint guard in
# ``tests/test_content_first.py`` already treats them as one.
_HINT_ENTITY_SLOT = "<id>"

_HINTS: dict[str, tuple[str, ...]] = {
    "overview": (
        "pandan list --column todo{board}",
        "pandan next --claim{board}",
        "pandan get <id>",
    ),
    # The card list is the one list verb with hints (KAN-492) — `get` to read one,
    # `move` to start one. Neither template carries the `{board}` slot because neither
    # verb accepts `--board`, which is the rule that stops a hint growing a flag its
    # verb would reject.
    "list": ("pandan get <id>", "pandan move <id> in_progress"),
    "get": ("pandan move <id> in_progress", 'pandan comment add <id> --body "…"'),
    "create": ("pandan move <id> in_progress", "pandan update <id> --points N"),
    "update": ("pandan get <id>",),
    "move": ('pandan comment add <id> --body "…"', "pandan move <id> done"),
    # `claim` lands a card in in_progress, so its next steps are `move`'s (KAN-502).
    "claim": ('pandan comment add <id> --body "…"', "pandan move <id> done"),
    "next": ("pandan move <id> in_progress", 'pandan needs-human <id> --note "…"'),
    "needs-human": ("pandan resolve <id>",),
    "resolve": ("pandan move <id> done",),
    "comment add": ("pandan comment list <id>",),
    "board create": (
        "pandan config set --board-id <id>",
        'pandan create "<title>" --board <id>',
    ),
    "epic create": ('pandan create "<title>" --epic <id>{board}',),
}


def _names_no_entity(result: Any) -> bool:
    """True when ``result`` holds nothing an ``<id>`` hint could point at (KAN-526).

    Deliberately an **enumeration of the empty shapes**, not a general falsiness test:
    only two results can name nothing, and every other hinted verb returns exactly one
    entity (a card, a mutation receipt, a created board/epic/comment) that is never
    "empty". Guessing at the rest is how a hint would silently vanish from a verb that
    should have one.

    1. A list envelope with zero rows — ``list`` and ``overview``, the two
       aggregate-bearing hinted verbs. ``_list_envelope`` is the CLI's single
       definition of "is this a list?" (KAN-478), so this inherits its answer rather
       than growing a fourth one.
    2. ``next``/``dispatch``'s explicit miss, ``{"card": None}``, which ``_humanize``
       renders ``(no card ready)``. Not a list, no aggregate, and the case the KAN-526
       card did not name — but the worst instance of the problem, because an agent
       polling ``pandan next`` on a drained board is the state it reaches most often.
    """
    envelope = _list_envelope(result)
    if envelope is not None:
        return not envelope[1]
    return isinstance(result, dict) and "card" in result and result["card"] is None


def _hint_lines(args: argparse.Namespace, result: Any) -> list[str]:
    """The ``help[]`` lines for this invocation — empty for a verb with no hints.

    Read off the namespace (each hinted subparser ``set_defaults(hints=…)``), so the
    templates live in one table next to each other rather than at their raise sites.

    ``result`` is consulted for one thing only: a result that names no entity drops
    the templates whose ``<id>`` slot would have referred to one (KAN-526). Doing it
    here rather than in ``_emit`` is the whole point — ``run`` already holds both the
    namespace and the result, so the printer never has to learn what a payload is."""
    templates: tuple[str, ...] = getattr(args, "hints", ()) or ()
    if _names_no_entity(result):
        templates = tuple(t for t in templates if _HINT_ENTITY_SLOT not in t)
    if not templates:
        return []
    # `is not None` and not truthiness: `--board 0` is not a real board id, but the
    # distinction that matters here is "the caller named a board on the command line".
    board = getattr(args, "board", None)
    carried = f" --board {board}" if board is not None else ""
    return [f"{HINT_PREFIX} {t.replace(_HINT_BOARD_SLOT, carried)}" for t in templates]


# --- the content-first bare invocation (V46, KAN-429 — AXI 8) ----------------
# `pandan` with no verb used to print argparse's usage on stderr, one
# `error<TAB>usage<TAB>…` row on stdout, and exit 2 — a front door that answered a
# question nobody asked. It now shows live state and exits 0.

# The one-sentence "what is this" — shared with the parser's own ``description`` so
# the banner and ``--help`` can't drift.
TOOL_DESCRIPTION = "Manage Pandan cards, boards, and epics from the command line."

# The verb the bare invocation is rewritten to. Registered as a real (if unlisted)
# subcommand so `pandan overview` names the same code path and is testable by name.
OVERVIEW_COMMAND = "overview"

# "Open" = every column that isn't the terminal one, derived from COLUMNS so a new
# board column (a cheap varchar + CHECK, see CLAUDE.md) counts as open by default
# instead of silently vanishing from the front door.
OPEN_COLUMNS = tuple(column for column in COLUMNS if column != "done")

# Cards fetched in the overview's single request. One call, not one per column: the
# API filters by a single `column`, and a second round trip on the command a human
# types to "just look" is not worth the wall clock. A board bigger than this reports
# its keyset cursor rather than paginating.
OVERVIEW_FETCH_LIMIT = 200

# Per-attempt timeout for that one request, with the client's cold-start retry
# backoff dropped (see ``_client_options``).
OVERVIEW_TIMEOUT = 20.0


def _tool_identity(config: Config) -> dict[str, Any]:
    """What this tool *is*, for the banner and for the structured payload.

    ``executable`` is how to re-invoke **this** pandan (``context._self_argv``: the
    frozen binary, or ``<python> -m pandan_cli``), never a ``pandan`` found on
    ``$PATH`` — a stale one there has already caused two false bug reports on this
    project, and AXI 8's ask for "the executable path" is precisely about being able
    to tell which build answered."""
    return {
        "name": "pandan",
        "version": build_info.version_string(),
        "executable": shlex.join(context._self_argv()),
        "description": TOOL_DESCRIPTION,
        "api_url": config.api_url,
    }


def _tool_banner(tool: dict[str, Any]) -> str:
    """The three human lines above the rows: identity, purpose, and what view this is.

    The third line is load-bearing, not decoration — the rows below it are the *open*
    subset of one page, so a reader who assumes "this is the board" would be wrong."""
    lines = [
        f"{tool['version']} — {tool['executable']}",
        f"{tool['description']} `pandan --help` for usage.",
    ]
    board = tool.get("board_id")
    if board is None:
        lines.append(f"{tool['api_url']} · no default board configured · your boards:")
    else:
        lines.append(
            f"{tool['api_url']} · board {board} · open cards "
            f"({', '.join(OPEN_COLUMNS)}):"
        )
    return "\n".join(lines)


def _announce_wait(config: Config) -> None:
    """Tell a human at a terminal that we're about to wait on a possibly-sleeping API.

    On **stderr** only, and only when stderr is a tty: stdout is the machine channel,
    and a script or an agent capturing it must never find this line in its data. It
    exists because the alternative bound — failing fast — is the wrong trade for the
    one command someone types when they want to *see* something (see
    ``_client_options`` for the bound that is applied)."""
    if not getattr(sys.stderr, "isatty", lambda: False)():
        return
    print(
        f"contacting {config.api_url} … (a scaled-to-zero deploy can take ~30s to wake)",
        file=sys.stderr,
    )


def _cmd_overview(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """The bare invocation's content: identity + the default board's open cards.

    Two shapes, one call each. With a board: the open rows of one page, so V44's
    aggregate below them counts **the rows actually printed** (the filter is applied
    here, not in ``_emit``, precisely so that invariant holds — a count of 42 over 17
    printed rows would be a number the reader can't reconcile). The page's
    ``next_cursor`` is carried through unchanged, so "there are more" is still said
    out loud. Without a board: the board list, because that is the content a caller
    with no default board actually needs, and it costs the same single request."""
    _announce_wait(config)
    tool = _tool_identity(config)
    board = _resolve_board(args.board, config)
    if board is None:
        return {"tool": {**tool, "board_id": None}, **client.list_boards()}
    page = client.list_cards(board_id=board, limit=args.limit)
    cards = [
        card
        for card in (page.get("cards") or [])
        if isinstance(card, dict) and card.get("column") in OPEN_COLUMNS
    ]
    return {
        "tool": {**tool, "board_id": board},
        "cards": cards,
        "next_cursor": page.get("next_cursor"),
    }


_BARE_OK_FLAGS = frozenset({"--json", "--full"})


def _is_bare_invocation(argv: list[str]) -> bool:
    """True when argv names no command at all — at most the global output flags.

    Deliberately an **allow-list**, not "no positional found": every argv outside it
    (a verb, ``-h``, ``--version``, an unknown flag, a typo) reaches argparse exactly
    as it did before this slice, so the new branch cannot change the behaviour of any
    invocation that already worked. ``--json``/``--full``/``--format`` are admitted
    because they say how to render, not what to do — ``pandan --format toon`` is
    still a bare invocation."""
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _BARE_OK_FLAGS or token.startswith("--format="):
            index += 1
        elif token == "--format" and index + 1 < len(argv):
            index += 2
        else:
            return False
    return True


# --- board resolution -------------------------------------------------------


def _resolve_board(arg_board: int | None, config: Config) -> int | None:
    """The per-call ``--board`` wins, else ``PANDAN_BOARD_ID``, else None (let the
    API apply its own fallback). Mirrors the MCP server's ``_board`` helper.

    With ``require_board`` set (issue #277), the two fallbacks are refused instead:
    an absent ``--board`` is an error, so a verb can never act on a board the user
    did not name. This is the single chokepoint for the "default board" path — the
    handful of calls that pass ``board_id=None`` *deliberately* (ticket lookup, which
    spans every board because ticket sequences are globally unique) don't come
    through here, so they keep working with the switch on.
    """
    if arg_board is not None:
        return arg_board
    if config.require_board:
        raise CliError(
            "--board is required (require_board is set). "
            "Pass --board <id>, or turn the check off with "
            "`pandan config unset require_board`.",
            code="board_required",
            arg="--board",
        )
    return config.board_id


# --- id / ticket resolution (KAN-285) ---------------------------------------
# The CLI displays cards/epics by their ticket (``KAN-<n>`` / ``EPIC-<n>``), so
# every id-taking command should accept that ticket — not only the numeric DB id.
# We keep the resolution client-side (API-first: a thin adapter, no new endpoint):
# a bare integer passes through unchanged; a ticket is looked up via the query API
# and matched on ``ticket_number``. Ticket sequences are globally unique
# (``card_ticket_seq`` / ``epic_ticket_seq``), so the lookup spans all your boards
# (``board_id=None``) and needs no board scope to disambiguate.

_TICKET_RE = re.compile(r"^(KAN|EPIC)-(\d+)$", re.IGNORECASE)


def _id_or_ticket_arg(value: str) -> str:
    """argparse ``type`` for id arguments: accept a numeric DB id **or** a
    ``KAN-<n>`` / ``EPIC-<n>`` ticket (case-insensitive), both kept as a string for
    the handler to resolve (KAN-285). Malformed input is a usage error (exit 2)."""
    v = value.strip()
    if v.isdigit() or _TICKET_RE.match(v):
        return v
    raise argparse.ArgumentTypeError(
        f"expected a numeric id or a KAN-/EPIC- ticket, got {value!r}"
    )


def _parse_id_or_ticket(raw: str) -> tuple[int | None, str | None]:
    """Split a raw id-or-ticket value: a bare integer → ``(id, None)``; a
    ``KAN-<n>``/``EPIC-<n>`` ticket → ``(None, "KAN-5")`` (normalised upper-case)."""
    v = str(raw).strip()
    if v.isdigit():
        return int(v), None
    m = _TICKET_RE.match(v)
    if m is None:
        raise CliError(
            f"expected a numeric id or a KAN-/EPIC- ticket, got {raw!r}",
            code="invalid_ref",
            arg=str(raw),
        )
    return None, f"{m.group(1).upper()}-{m.group(2)}"


def _resolve_card_id(client: PandanClient, raw: str | int) -> int:
    """Resolve a card id-or-ticket to its numeric DB id (KAN-285). A bare integer is
    returned as-is (no request); a ``KAN-<n>`` ticket is looked up via the query API
    (paging its keyset cursor) and matched on ``ticket_number``."""
    id_, ticket = _parse_id_or_ticket(raw)
    if id_ is not None:
        return id_
    if not ticket.startswith("KAN-"):
        raise CliError(
            f"{ticket} is not a card ticket (cards are KAN-…)",
            code="invalid_ref",
            arg=ticket,
        )
    cursor: str | None = None
    while True:
        result = (
            client.list_cards(board_id=None, cursor=cursor)
            if cursor
            else client.list_cards(board_id=None)
        )
        for card in result.get("cards", []):
            if str(card.get("ticket_number", "")).upper() == ticket:
                return int(card["id"])
        cursor = result.get("next_cursor")
        if not cursor:
            # not_found → exit 5, the same code the API returns for `get <numeric id>`
            # of a card that doesn't exist. Before V43 this was exit 1, so one logical
            # failure reported two different codes depending on the identifier form.
            raise CliError(
                f"no card found with ticket {ticket}", code="not_found", arg=ticket
            )


def _resolve_epic_id(client: PandanClient, raw: str | int) -> int:
    """Resolve an epic id-or-ticket to its numeric DB id (KAN-285). A bare integer is
    returned as-is; an ``EPIC-<n>`` ticket is looked up via ``list_epics`` and
    matched on ``ticket_number``."""
    id_, ticket = _parse_id_or_ticket(raw)
    if id_ is not None:
        return id_
    if not ticket.startswith("EPIC-"):
        raise CliError(
            f"{ticket} is not an epic ticket (epics are EPIC-…)",
            code="invalid_ref",
            arg=ticket,
        )
    for epic in client.list_epics(board_id=None).get("epics", []):
        if str(epic.get("ticket_number", "")).upper() == ticket:
            return int(epic["id"])
    raise CliError(f"no epic found with ticket {ticket}", code="not_found", arg=ticket)


def _resolve_epic_opt(client: PandanClient, raw: str | int | None) -> int | None:
    """Resolve an optional ``--epic`` value (``None`` stays ``None``)."""
    return None if raw is None else _resolve_epic_id(client, raw)


# --- command handlers -------------------------------------------------------
# Each returns the client's result dict; printing + exit codes are handled centrally.


def _cmd_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    # --refs takes one mixed list of ids and/or tickets (issue #254); the shared
    # splitter puts each in the API's ids=/refs= bucket. A batch read is bounded by
    # the server's selector cap, so --limit (and, since KAN-615, --cursor) is refused
    # *there* rather than truncating — the CLI deliberately grows no second copy of
    # that rule, so the one authority on which parameters compose stays the API.
    ids = refs = None
    if getattr(args, "refs", None):
        ids, refs = split_card_selectors(args.refs)
    return client.list_cards(
        board_id=_resolve_board(args.board, config),
        ids=ids,
        refs=refs,
        column=args.column,
        epic_id=_resolve_epic_opt(client, args.epic),
        cycle_id=args.cycle,
        priority=args.priority,
        label=args.label,
        due_before=args.due_before,
        overdue=args.overdue or None,
        needs_human=args.needs_human or None,
        assignee=args.assignee,
        q=args.q,
        sort=args.sort,
        limit=args.limit,
        cursor=args.cursor,
    )


def _cmd_get(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.get_card(_resolve_card_id(client, args.card_id))


def _cmd_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.create_card(
        args.title,
        board_id=_resolve_board(args.board, config),
        description=args.description,
        column=args.column,
        story_points=args.points,
        assignee=args.assignee,
        epic_id=_resolve_epic_opt(client, args.epic),
        cycle_id=args.cycle,
        priority=args.priority,
        due_date=args.due,
        label_ids=args.label or None,
    )


def _cmd_update(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.update_card(
        _resolve_card_id(client, args.card_id),
        title=args.title,
        description=args.description,
        story_points=args.points,
        assignee=args.assignee,
        epic_id=_resolve_epic_opt(client, args.epic),
        cycle_id=args.cycle,
        priority=args.priority,
        due_date=args.due,
        label_ids=args.label if args.label is not None else None,
    )


def _cmd_move(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.move_card(
        _resolve_card_id(client, args.card_id), args.column, position=args.position
    )


def _cmd_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise CliError(
            f"refusing to delete card {args.card_id} without confirmation; pass --yes",
            code="confirmation_required",
            arg="--yes",
        )
    return client.delete_card(_resolve_card_id(client, args.card_id))


def _cmd_next(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Peek at (or, with ``--claim``, atomically dispatch) the next ready card on a
    board (M5 V12, KAN-245). Both need a board — the dispatch endpoints are
    path-scoped with no API-side fallback."""
    board = _resolve_board(args.board, config)
    if board is None:
        raise CliError(
            "a board is required; pass --board or set PANDAN_BOARD_ID",
            code="board_required",
            arg="--board",
        )
    if args.claim:
        return client.dispatch(
            board, assignee=args.assignee, label=args.label, priority=args.priority
        )
    return client.next_ready(board, label=args.label, priority=args.priority)


def _cmd_claim(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Claim a **named** card in one invocation (KAN-502): move it to ``in_progress``
    and set its assignee. ``next --claim`` claims whatever the board offers next, so
    it is not a substitute for claiming a card you have already chosen — that used to
    need ``move`` + ``update``, two round trips a reader had to know to pair.

    ``--assignee`` is **required**, exactly as it is on the MCP ``claim_card`` tool:
    the shared client's ``claim_card`` PATCHes the assignee it is handed, and the
    board API has no "the caller" default on that path (only ``dispatch`` does, which
    is what ``next --claim`` uses). Not transactional — see the client's docstring."""
    return client.claim_card(_resolve_card_id(client, args.card_id), args.assignee)


def _cmd_needs_human(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.flag_needs_human(
        _resolve_card_id(client, args.card_id), attention_note=args.note
    )


def _cmd_resolve(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.resolve_card(_resolve_card_id(client, args.card_id))


def _cmd_metrics(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Report derived flow metrics for a board (M5 V17, KAN-250). The metrics
    endpoint is path-scoped with no API-side fallback, so a board is required
    (``--board`` or PANDAN_BOARD_ID)."""
    board = _resolve_board(args.board, config)
    if board is None:
        raise CliError(
            "a board is required; pass --board or set PANDAN_BOARD_ID",
            code="board_required",
            arg="--board",
        )
    return client.board_metrics(board, since=args.since, window=args.window)


def _cmd_activity(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Read a board's activity feed (KAN-18), newest-first (M5 V16, KAN-261). The
    activity endpoint is path-scoped with no API-side fallback, so a board is
    required (``--board`` or PANDAN_BOARD_ID)."""
    board = _resolve_board(args.board, config)
    if board is None:
        raise CliError(
            "a board is required; pass --board or set PANDAN_BOARD_ID",
            code="board_required",
            arg="--board",
        )
    return client.list_activity(
        board,
        limit=args.limit,
        cursor=args.cursor,
        actor=args.actor,
        action=args.action,
    )


# --- notification handlers --------------------------------------------------
# Notifications are per-USER, not board-scoped (no --board): you only see your own,
# addressed to you as a board owner. Poll/pull only (ADR 0007).


def _cmd_notify_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_notifications(unread=args.unread or None)


def _cmd_notify_read(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.mark_notification_read(args.notification_id)


# --- ops handlers -----------------------------------------------------------


def _cmd_warmup(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    # The shared client's warmup() pings the public /api/health, rides a cold
    # start via the shared retry/timeout, and never throws — it returns a status
    # dict the caller maps to an exit code (see run()).
    return client.warmup()


# --- board handlers ---------------------------------------------------------
# Boards are owner-scoped, not board-scoped: no --board targeting here.


def _cmd_board_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_boards()


def _cmd_board_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.create_board(args.name)


def _cmd_board_get(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.get_board(args.board_id)


def _cmd_board_update(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Rename a board and/or configure its two per-board opt-ins: the EPIC-10 GitHub
    PR auto-sync (KAN-529) and the V38 signed outbound webhook (KAN-502) — the
    capability that was MCP-only until KAN-502, and the reason the packaged skill
    shipped a raw-``curl`` workaround.

    These six are exactly the API's ``BoardUpdate`` fields, so ``pandan board update``
    now reaches all of ``PATCH /api/v1/boards/{id}``. The two ``--autosync-*`` tri-states
    (KAN-529) close the last hole: they were reachable from *neither* adapter, which made
    a raw ``curl`` the only way to turn auto-sync on — the exact state this verb exists
    to end.

    Only the flags actually passed are sent; the client's ``_clean`` drops the rest, so
    an omitted field is left untouched. **The secret is write-only**: the API accepts it
    on PATCH and never returns it in a board read, so nothing below reads it back out of
    ``result`` — the CLI passes it *in* and forgets it. Prefer
    ``--outbound-webhook-secret-stdin``, which keeps it out of argv (and therefore out of
    ``ps`` and the shell history), the same reason ``login``/``config set`` have
    ``--token-stdin``."""
    secret = _read_secret_arg(args)
    fields = {
        "name": args.name,
        "autosync_enabled": args.autosync_enabled,
        "autosync_advance_to_done": args.autosync_advance_to_done,
        "outbound_webhook_url": args.outbound_webhook_url,
        "outbound_webhook_secret": secret,
        "outbound_webhook_enabled": args.outbound_webhook_enabled,
    }
    if all(value is None for value in fields.values()):
        raise CliError(
            "nothing to update (pass --name / --autosync-enabled|-disabled / "
            "--autosync-advance-to-done|--no-autosync-advance-to-done / "
            "--outbound-webhook-url / --outbound-webhook-secret[-stdin] / "
            "--outbound-webhook-enabled|-disabled)",
            code="invalid_input",
        )
    return client.update_board(args.board_id, **fields)


def _read_secret_arg(args: argparse.Namespace) -> str | None:
    """The outbound-webhook secret for ``board update``, or ``None`` when unset.

    ``--outbound-webhook-secret-stdin`` reads exactly one line from stdin so the value
    never enters argv — mirroring ``config set --token-stdin``. An empty read is an
    error rather than a silent no-op, because "I piped nothing" and "I want to clear it"
    must not look the same (clearing needs an explicit ``null``, which only the raw API
    accepts today)."""
    if getattr(args, "outbound_webhook_secret_stdin", False):
        secret = sys.stdin.readline().strip()
        if not secret:
            raise CliError(
                "no secret read from stdin",
                code="invalid_input",
                arg="--outbound-webhook-secret-stdin",
            )
        return secret
    return args.outbound_webhook_secret


def _cmd_board_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise CliError(
            f"refusing to delete board {args.board_id} without confirmation; pass --yes",
            code="confirmation_required",
            arg="--yes",
        )
    return client.delete_board(args.board_id)


# --- epic handlers ----------------------------------------------------------
# Epics are board-scoped, so list/create honour --board / PANDAN_BOARD_ID.


def _cmd_epic_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_epics(board_id=_resolve_board(args.board, config))


def _cmd_epic_get(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Read a single epic by id or ``EPIC-<n>`` (KAN-502). A verb gap rather than a
    capability gap — ``epic list`` could already show it — but ``get_epic`` had no
    twin, and the one-epic read is what an agent following a card's ``epic_id`` wants."""
    return client.get_epic(_resolve_epic_id(client, args.epic_id))


def _cmd_epic_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.create_epic(
        args.name,
        board_id=_resolve_board(args.board, config),
        description=args.description,
        target_date=args.target_date,
        lead=args.lead,
    )


def _cmd_epic_update(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.update_epic(
        _resolve_epic_id(client, args.epic_id),
        name=args.name,
        description=args.description,
        target_date=args.target_date,
        lead=args.lead,
    )


def _cmd_epic_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise CliError(
            f"refusing to delete epic {args.epic_id} without confirmation; pass --yes",
            code="confirmation_required",
            arg="--yes",
        )
    return client.delete_epic(_resolve_epic_id(client, args.epic_id))


# --- label handlers ---------------------------------------------------------
# Labels are board-scoped: list/create honour --board / PANDAN_BOARD_ID; delete
# is addressed by the label's own id (authorized via its board).


def _cmd_label_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    board = _resolve_board(args.board, config)
    if board is None:
        raise CliError(
            "a board is required; pass --board or set PANDAN_BOARD_ID",
            code="board_required",
            arg="--board",
        )
    return client.list_labels(board)


def _cmd_label_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    board = _resolve_board(args.board, config)
    if board is None:
        raise CliError(
            "a board is required; pass --board or set PANDAN_BOARD_ID",
            code="board_required",
            arg="--board",
        )
    # KAN-288: color accepts either the positional or the --color flag (flag wins),
    # falling back to a neutral default so it can be omitted entirely.
    color = args.color_opt or args.color_pos or DEFAULT_LABEL_COLOR
    return client.create_label(board, args.name, color)


def _cmd_label_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise CliError(
            f"refusing to delete label {args.label_id} without confirmation; pass --yes",
            code="confirmation_required",
            arg="--yes",
        )
    return client.delete_label(args.label_id)


# --- view handlers ----------------------------------------------------------
# Saved views are board-scoped: list/create/delete honour --board / PANDAN_BOARD_ID.
# ``view create`` reuses the same filter/sort flags as ``list`` to assemble the
# stored query (the filter+sort grammar), so a view is "the current list, saved".


def _build_view_query(client: PandanClient, args: argparse.Namespace) -> dict[str, Any]:
    """Assemble a saved view's stored query (the filter+sort grammar) from the
    list-style flags — only the ones the caller set. Field names match the GET
    /cards params exactly, so the stored query replays verbatim. ``--epic`` accepts
    an ``EPIC-<n>`` ticket and is resolved to its numeric id before storing (KAN-285)."""
    query: dict[str, Any] = {}
    if args.column:
        query["column"] = args.column
    if args.epic is not None:
        query["epic_id"] = _resolve_epic_id(client, args.epic)
    if args.priority:
        query["priority"] = args.priority
    if args.label is not None:
        query["label"] = args.label
    if args.due_before:
        query["due_before"] = args.due_before
    if args.overdue:
        query["overdue"] = True
    if args.needs_human:
        query["needs_human"] = True
    if args.assignee:
        query["assignee"] = args.assignee
    if args.sort:
        query["sort"] = args.sort
    return query


def _require_view_board(args: argparse.Namespace, config: Config) -> int:
    board = _resolve_board(args.board, config)
    if board is None:
        raise CliError(
            "a board is required; pass --board or set PANDAN_BOARD_ID",
            code="board_required",
            arg="--board",
        )
    return board


def _cmd_view_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_views(_require_view_board(args, config))


def _cmd_view_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.create_view(
        _require_view_board(args, config), args.name, _build_view_query(client, args)
    )


def _cmd_view_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise CliError(
            f"refusing to delete view {args.view_id} without confirmation; pass --yes",
            code="confirmation_required",
            arg="--yes",
        )
    return client.delete_view(_require_view_board(args, config), args.view_id)


# --- cycle handlers (V33 / KAN-297) -----------------------------------------
# Cycles are board-scoped: list/create/delete honour --board / PANDAN_BOARD_ID.
# Assigning a card to a cycle is a field edit — `pandan update <card> --cycle <id>`.


def _cmd_cycle_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_cycles(_require_view_board(args, config))


def _cmd_cycle_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.create_cycle(
        _require_view_board(args, config),
        args.name,
        starts_on=args.starts_on,
        ends_on=args.ends_on,
    )


def _cmd_cycle_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise CliError(
            f"refusing to delete cycle {args.cycle_id} without confirmation; pass --yes",
            code="confirmation_required",
            arg="--yes",
        )
    return client.delete_cycle(_require_view_board(args, config), args.cycle_id)


def _cmd_cycle_metrics(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Derived burndown / velocity metrics for a cycle (V34, KAN-298)."""
    return client.cycle_metrics(_require_view_board(args, config), args.cycle_id)


# --- batch update + card templates (M5 V19 API / KAN-252 adapter) ----------


def _load_json_arg(value: str) -> Any:
    """Parse a JSON argument: ``-`` reads it from stdin (so a big payload stays off
    the command line + shell history), otherwise ``value`` is parsed as a JSON
    string. Raises ``ConfigError`` on invalid JSON."""
    raw = sys.stdin.read() if value == "-" else value
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid JSON: {exc}", code="invalid_input") from exc


def _cmd_batch_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """File N stories from one JSON array (KAN-502) — the CLI twin of ``create_cards``,
    which needed N ``pandan create`` invocations before this slice.

    **Fail-fast, not atomic.** There is no batch-create endpoint: the shared client
    loops ``create_card``, so on the first rejection the cards *before* it stay created
    and nothing rolls back. That is the opposite of ``batch-update``, which is one
    server-side transaction, and it is why the two verbs are named differently rather
    than being one flag.

    Each object takes the same fields as ``create``'s flags, under the API's own names
    (``title`` required; ``description``/``column``/``story_points``/``assignee``/
    ``epic_id``/``cycle_id``/``priority``/``due_date``/``label_ids``/``board_id``).
    ``board_id`` is filled in from ``--board`` / ``PANDAN_BOARD_ID`` for any object that
    omits it, because a card dict with no board lands on your **earliest** board — the
    footgun every other verb's board resolution exists to avoid. An object that names
    its own ``board_id`` keeps it, so one batch can span boards."""
    cards = _load_json_arg(args.cards)
    if not isinstance(cards, list):
        raise CliError(
            "batch-create expects a JSON array of card objects (title required)",
            code="invalid_input",
            arg="JSON",
        )
    board = _resolve_board(args.board, config)
    prepared: list[dict[str, Any]] = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise CliError(
                f"batch-create item {index} is not a JSON object",
                code="invalid_input",
                arg="JSON",
            )
        if not card.get("title"):
            raise CliError(
                f"batch-create item {index} has no title",
                code="invalid_input",
                arg="JSON",
            )
        prepared.append(
            card if card.get("board_id") is not None or board is None
            else {**card, "board_id": board}
        )
    return client.create_cards(prepared)


def _cmd_batch_update(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    updates = _load_json_arg(args.updates)
    if not isinstance(updates, list):
        raise CliError(
            "batch-update expects a JSON array of {id, ...fields} objects",
            code="invalid_input",
            arg="JSON",
        )
    return client.update_cards(updates)


def _cmd_template_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_templates(_require_view_board(args, config))


def _cmd_template_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    cards = _load_json_arg(args.cards)
    if not isinstance(cards, list):
        raise CliError(
            "template create expects a JSON array of card objects for --cards",
            code="invalid_input",
            arg="--cards",
        )
    return client.create_template(_require_view_board(args, config), args.name, cards)


def _cmd_template_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise CliError(
            f"refusing to delete template {args.template_id} without confirmation; pass --yes",
            code="confirmation_required",
            arg="--yes",
        )
    return client.delete_template(_require_view_board(args, config), args.template_id)


def _cmd_template_apply(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.apply_template(_require_view_board(args, config), args.template_id)


# --- dependency / link / comment handlers (KAN-270) -------------------------
# Card-to-card dependencies, work-links, and notes. Thin adapters over the shared
# client — the API endpoints + client methods already existed; KAN-270 only adds
# the `pandan` verbs. All are card-scoped (addressed by card id), so no --board here.
#
# add_dependency/add_link (and their removes) return the whole refreshed card, but
# the verb is *about* the edge / link it changed — so we project just that facet
# (matching what the client's list_dependencies already does), which also renders
# cleanly and keeps `dep add|rm|list` (and `link add|rm`) consistent.


def _dep_facet(card: dict[str, Any], card_id: int) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "blocked_by": card.get("blocked_by", []),
        "blocks": card.get("blocks", []),
    }


def _link_facet(card: dict[str, Any], card_id: int) -> dict[str, Any]:
    return {"card_id": card_id, "links": card.get("links", [])}


def _cmd_dep_add(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    card_id = _resolve_card_id(client, args.card_id)
    blocker_id = _resolve_card_id(client, args.blocked_by)
    return _dep_facet(client.add_dependency(card_id, blocker_id), card_id)


def _cmd_dep_rm(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    card_id = _resolve_card_id(client, args.card_id)
    blocker_id = _resolve_card_id(client, args.blocked_by)
    return _dep_facet(client.remove_dependency(card_id, blocker_id), card_id)


def _cmd_dep_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_dependencies(_resolve_card_id(client, args.card_id))


def _cmd_link_add(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    card_id = _resolve_card_id(client, args.card_id)
    return _link_facet(client.add_link(card_id, args.label, args.url), card_id)


def _cmd_link_rm(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    card_id = _resolve_card_id(client, args.card_id)
    return _link_facet(client.remove_link(card_id, args.link_id), card_id)


def _cmd_comment_add(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.add_comment(_resolve_card_id(client, args.card_id), args.body)


def _cmd_comment_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_comments(_resolve_card_id(client, args.card_id))


# --- who am I (KAN-614) -----------------------------------------------------
# Sits beside the config handlers below because it answers the same onboarding
# question, but it is emphatically NOT one of them: `config show` reports what the
# CLI *resolved*, which is a statement about this machine's files and environment.
# Only a round trip can say whether the API accepted any of it.


def _cmd_me(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """``GET /api/v1/me`` — no arguments, no board, nothing to resolve first.

    The verb is one client call on purpose. Its value is the *exit code* as much as
    the row: 0 with an identity means the credential works, and a bad or revoked PAT
    is the shared 401 → ``unauthorized`` → exit 3 every other verb already maps. 403
    is not reachable here (there is no board to be denied), so the verb separates
    "your token is wrong" from "that board isn't yours" — which `board list`, the
    workaround people reach for today, cannot do."""
    return client.me()


# --- config handlers (local: no client, no network) -------------------------
# These operate on local config only, so ``run()`` dispatches them via
# ``local_func`` before building a PandanClient (and before any token is required).


def _redact_token(token: str) -> str:
    """Never print a usable token. Show only that one is set + its last 4 chars so
    a human can tell which PAT is in effect without exposing it."""
    if not token:
        return "(unset)"
    tail = token[-4:] if len(token) > 4 else ""
    return f"set (…{tail})"


def _cmd_config_path(args: argparse.Namespace) -> int:
    print(config_file_path())
    return EXIT_OK


def _cmd_config_show(args: argparse.Namespace) -> int:
    """Print the *effective* config after the env → file → .mcp.json chain, with
    the token redacted. Handy for 'why is pandan hitting the wrong board?'."""
    resolved = resolve_values()
    mcp = find_mcp_json()
    out = {
        "api_url": resolved.get("api_url") or DEFAULT_API_URL,
        "token": _redact_token(resolved.get("token", "")),
        "board_id": resolved.get("board_id"),
        # The effective truncation limit (V45, KAN-428) — reported here because
        # "why is my description cut off?" is otherwise unanswerable from outside.
        "max_text_chars": resolved.get("max_text_chars") or str(DEFAULT_MAX_TEXT_CHARS),
        # Issue #277 — reported for the same reason as max_text_chars: with it on,
        # "why did that fail?" is otherwise unanswerable from outside, and with it
        # off, "am I actually protected?" is the question that prompted the issue.
        "require_board": str(parse_require_board(resolved.get("require_board", ""))).lower(),
        "config_file": str(config_file_path()),
        "mcp_json": str(mcp) if mcp else None,
    }
    # ``run()`` stamps the resolved format onto the namespace before dispatching a
    # local handler, so `config show` honours --format json/toon and the --json alias.
    fmt = _resolve_format(args)
    if fmt in STRUCTURED_FORMATS:
        print(_render_structured(out, fmt))
    else:
        for key, val in out.items():
            print(f"{key}\t{val}")
    return EXIT_OK


def _validate_board_id_arg(raw: str | None) -> None:
    if raw is not None and raw.strip() and not raw.strip().lstrip("-").isdigit():
        raise CliError(
            f"--board-id must be an integer, got {raw!r}",
            code="invalid_input",
            arg="--board-id",
        )


def _cmd_config_set(args: argparse.Namespace) -> int:
    """Write api_url/board_id/token to the user config file (0600). ``--token-stdin``
    reads the PAT from stdin so it never lands in argv / shell history."""
    _validate_board_id_arg(args.board_id)
    token: str | None = None
    if getattr(args, "token_stdin", False):
        token = sys.stdin.readline().strip()
        if not token:
            raise CliError("no token read from stdin", code="no_token", arg="--token-stdin")
    elif args.token is not None:
        token = args.token
    require_board = getattr(args, "require_board", None)
    if (
        args.api_url is None
        and args.board_id is None
        and token is None
        and require_board is None
    ):
        raise CliError(
            "nothing to set (pass --api-url / --board-id / --token[-stdin] / "
            "--require-board)",
            code="invalid_input",
        )
    path = write_config_file(
        api_url=args.api_url,
        token=token,
        board_id=args.board_id,
        require_board=require_board,
    )
    print(f"wrote {path}")
    return EXIT_OK


def _cmd_config_unset(args: argparse.Namespace) -> int:
    """Remove keys from the user config file (issue #277).

    The gap this fills: ``config set`` could write a default board but nothing could
    clear one, and an empty env var doesn't override the file (empty is treated as
    unset, so the file wins — arguably right, but it left no escape hatch). Clearing
    a key meant hand-editing a ``0600`` file that also holds a live PAT.

    Reports per key whether it was actually removed, because "cleared it" and "it was
    never set" are different answers to "why is this still targeting board 5?" — the
    second one means the value is coming from the environment or ``.mcp.json``, which
    this command cannot and should not touch.
    """
    unknown = [k for k in args.keys if k not in _CONFIG_KEYS]
    if unknown:
        raise CliError(
            f"unknown config key(s): {', '.join(unknown)}. "
            f"Valid keys: {', '.join(_CONFIG_KEYS)}.",
            code="invalid_input",
            arg=unknown[0],
        )
    path, removed = unset_config_keys(tuple(args.keys))
    for key in args.keys:
        print(f"{key}\t{'removed' if key in removed else 'not set'}")
    print(f"wrote {path}")
    if removed:
        # Only worth saying when something changed, and only when it can still bite:
        # the file is the *middle* source, so a cleared key may just unmask an env
        # var or .mcp.json entry rather than actually clearing the effective value.
        still = {k: v for k, v in resolve_values().items() if k in removed}
        for key, val in still.items():
            shown = _redact_token(val) if key == "token" else val
            print(
                f"note: {key} still resolves to {shown} from the environment "
                f"or .mcp.json — see `pandan config show`",
                file=sys.stderr,
            )
    return EXIT_OK


def _stdin_is_tty() -> bool:
    """Whether stdin is an interactive terminal. Wrapped so it can be faked in tests
    and so the one place that decides "may I prompt?" is obvious."""
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):  # detached / closed stdin
        return False


def _cmd_login(args: argparse.Namespace) -> int:
    """Save a PAT to the config file, without it ever touching argv.

    **Never prompts non-interactively** (AXI 6, V43): the hidden ``getpass`` prompt is
    reached only when stdin is a real tty and ``--token-stdin`` wasn't asked for.
    Otherwise the token is read as one line from stdin (``… | pandan login``), and if
    nothing arrives the command fails with a structured error rather than blocking on a
    prompt no one can answer."""
    _validate_board_id_arg(args.board_id)
    from_stdin = getattr(args, "token_stdin", False) or not _stdin_is_tty()
    if from_stdin:
        token = sys.stdin.readline().strip()
    else:
        import getpass

        token = getpass.getpass("Paste your Pandan PAT (pandan_pat_…): ").strip()
    if not token:
        raise CliError(
            (
                "no token read from stdin — pipe one in (`… | pandan login "
                "--token-stdin`) or run in a terminal to be prompted"
                if from_stdin
                else "no token provided"
            ),
            code="no_token",
            arg="--token-stdin" if from_stdin else None,
        )
    path = write_config_file(api_url=args.api_url, token=token, board_id=args.board_id)
    print(f"saved token to {path} (mode 0600)")
    return EXIT_OK


# --- argument parser --------------------------------------------------------


def _add_fields_arg(parser: argparse.ArgumentParser, example: str) -> None:
    """Attach ``--fields`` to a list verb (V42, KAN-425 — AXI 2).

    Every list verb keeps its minimal default row; ``--fields`` replaces that row
    with exactly the named fields, tab-separated. Names are the row's own ``--json``
    keys (so ``--fields`` and the structured formats share one vocabulary and can't
    drift from the API), plus the aliases ``ticket`` → ``ticket_number`` and ``pts``/``points`` →
    ``story_points``. Values print **bare** (``-`` for null): the default row's
    ``pts=N`` labelling is a property of the default row, not of the field."""
    parser.add_argument(
        "--fields",
        type=_fields_arg,
        metavar="LIST",
        help=(
            "comma-separated fields to print instead of the default row, e.g. "
            f"--fields {example}. Names are the keys shown by --json (plus the "
            "aliases ticket/pts); values are printed bare and tab-separated. "
            "Affects human output only, never --format json/toon"
        ),
    )


class ErrorContractParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` whose failures obey the error contract (V43, KAN-426).

    argparse's own ``error()`` writes ``prog: error: …`` to **stderr** and exits 2. AXI
    6 wants the machine-readable failure on **stdout**, so we print the structured row
    there and keep only the human usage block on stderr. The exit code stays **2** —
    argparse's convention, and part of the published contract.

    Subparsers inherit this class automatically (``add_subparsers`` defaults
    ``parser_class`` to ``type(self)``), so nested verbs report identically."""

    def error(self, message: str):  # noqa: D102 - argparse API
        self.print_usage(sys.stderr)
        _print_error(CliError(message, code="usage"))
        raise SystemExit(EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = ErrorContractParser(
        prog="pandan",
        # Shared with the bare invocation's banner (V46) so the two can't drift.
        description=TOOL_DESCRIPTION,
        epilog=(
            "Configuration keys (api_url / token / board_id), resolved per value in\n"
            "this order — first non-empty wins:\n"
            "  1. env vars   PANDAN_API_URL / PANDAN_TOKEN / PANDAN_BOARD_ID\n"
            "  2. config file  ~/.config/pandan/config.toml  (see `pandan login`)\n"
            "  3. .mcp.json    nearest up the tree, .mcpServers.pandan.env.*\n"
            "So the PAT can stay in a file and never touch the command line. Run\n"
            "`pandan login` once to save it; `pandan config show` prints the effective config.\n"
            "\n"
            "Output: --format human (default, tab-separated) | json | toon.\n"
            "--json is a supported alias for --format json; --format wins if both\n"
            "are given. toon is the token-cheap rendering for nested payloads.\n"
            "\n"
            "Every list verb ends with a pre-computed aggregate, so counts never cost\n"
            "a second request:  42 cards · 12 todo · 5 in_progress · 25 done\n"
            "(· N needs-human when non-zero). It always describes the rows RETURNED —\n"
            "under --limit or a filter, not the whole board. Under --format json/toon\n"
            "the same numbers ride the payload as a `summary` object instead.\n"
            "\n"
            "Exit codes: 0 ok, 1 error, 2 usage, 3 unauthorized, 4 forbidden, 5 not found\n"
            "(a KAN-/EPIC- ticket that resolves to nothing is also 5).\n"
            "Errors print one row on STDOUT: error<TAB>code<TAB>message<TAB>arg\n"
            "(an {\"error\": {...}} object under --format json/toon). No verb ever\n"
            "prompts when stdin is not a terminal."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # `pandan --version` / `-v`: pure argparse action=version — prints to stdout and
    # exits 0 before the required subcommand is enforced. No importlib.metadata
    # lookup, so it works in the frozen PyInstaller onefile binary too.
    # The string also carries the *build provenance* (V50, KAN-435): a released
    # binary prints the commit it was frozen from, a source run says so outright,
    # so a stale install is detectable rather than silently identical to source.
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=build_info.version_string(),
        help="print the CLI version + build commit and exit",
    )
    # A shared parent so --format/--json work before OR after the subcommand
    # (e.g. `pandan --json list` and `pandan list --format toon` both parse).
    # Each flag is registered twice — on `common` with SUPPRESS so an absent
    # subcommand-level copy does not clobber a global one already parsed, and on
    # the main parser with the real default.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--format",
        dest="output_format",
        choices=OUTPUT_FORMATS,
        default=argparse.SUPPRESS,
        help=(
            "output format (default: human). 'json' is the raw API envelope, indented; "
            "'toon' is the same object in TOON, which prints a uniform array's field "
            "names once in a header instead of per row — much cheaper on the nested "
            "payloads (get / metrics / activity / epic list / dep list / template + "
            "view reads). The default human rows are tab-separated and already "
            "key-free, so they stay the cheapest list output"
        ),
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=OUTPUT_FORMATS,
        default=None,
        help=argparse.SUPPRESS,
    )
    common.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
        help=(
            "alias for --format json, supported and not deprecated. List verbs return "
            'the API envelope, not a bare array: `list --json | jq \'.cards[]\'`'
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=False,
        help=argparse.SUPPRESS,
    )
    # --full: opt out of V45's content truncation (KAN-428). Registered on the shared
    # parent the same way, so it works before OR after the subcommand and applies to
    # every verb — it is an output concern, not a per-verb one.
    common.add_argument(
        "--full",
        action="store_true",
        dest="full",
        default=argparse.SUPPRESS,
        help=(
            "print long free-text fields (a card/epic description, a comment or "
            "notification body, an attention note) in full. Default: cut at "
            f"{DEFAULT_MAX_TEXT_CHARS} characters with a '(truncated, N chars total …)' "
            "hint, so one `get` can't blow an agent's context. Applies to the human "
            "rows AND to --format json/toon. Set PANDAN_MAX_TEXT_CHARS (or "
            "max_text_chars in the config file) to change the limit; 0 disables it"
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        dest="full",
        default=False,
        help=argparse.SUPPRESS,
    )

    # ``required=True`` stays exactly as it was, and the bare invocation is an argv
    # rewrite in ``run()`` (``_is_bare_invocation``) rather than a relaxation of it.
    #
    # **Not** because `required=False` would change the usage line — it does not; a
    # positional with ``nargs=PARSER`` is never bracketed, so ``<command> ...`` renders
    # identically either way (an earlier comment here claimed otherwise and a mutation
    # test caught it). The reason is that `required=False` + a top-level
    # ``set_defaults(func=_cmd_overview)`` would make the overview the fallback for
    # *any* argv that happens to parse without a subcommand, now or after some future
    # flag is added — i.e. a network call reachable by accident. The allow-list makes
    # the set of argvs that reach the front door explicit, enumerable and tested, which
    # is what turns "no invocation that used to work changed" into a structural claim.
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    # The content-first bare invocation (V46, KAN-429 — AXI 8): `pandan` with no verb
    # is rewritten to `pandan overview` in ``run()``.
    #
    # V46 registered this parser with **no** ``help=`` kwarg, which is precisely what
    # kept it out of ``--help``: argparse builds the choices pseudo-action only
    # ``if 'help' in kwargs`` (``argparse._SubParsersAction.add_parser``), so a
    # help-less subparser is a working but invisible verb. That was done to keep V46's
    # AXI 10 golden green, and it inverted the principle the golden exists to serve —
    # AXI's disclosure rules ask a tool to say what it can do, and an undiscoverable
    # verb is the opposite. KAN-492 settles it: the freeze was a one-slice *regression*
    # guard ("V46 did not damage the usage text"), not a permanent contract, so the
    # verb gets its ``help=`` and the golden was regenerated in the same diff. The
    # guard now detects change instead of forbidding it, and a companion test asserts
    # no top-level verb is hidden at all, so this cannot silently recur.
    p_overview = sub.add_parser(
        OVERVIEW_COMMAND,
        parents=[common],
        help="live board state (what bare pandan prints)",
    )
    p_overview.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_overview.add_argument(
        "--limit", type=int, default=OVERVIEW_FETCH_LIMIT, help="max cards to fetch"
    )
    p_overview.set_defaults(
        func=_cmd_overview,
        hints=_HINTS[OVERVIEW_COMMAND],
        # A tighter transport budget than the shared default — see ``_client_options``.
        client_timeout=OVERVIEW_TIMEOUT,
    )

    # ``warmup`` pings the public /api/health to wake a scaled-to-zero Fly+Neon
    # deploy before a batch of work (handy as a CI pre-step). It needs no token
    # (require_token=False) and maps its non-throwing status to an exit code
    # (is_warmup=True): 0 when awake, 1 while still waking / on error.
    p_warmup = sub.add_parser(
        "warmup",
        parents=[common],
        help="wake the API (ping /api/health) before a batch of work",
    )
    p_warmup.set_defaults(func=_cmd_warmup, require_token=False, is_warmup=True)

    p_list = sub.add_parser("list", parents=[common], help="list / query cards")
    p_list.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_list.add_argument(
        "--refs",
        metavar="REFS",
        help=(
            "read a known set of cards in ONE request: a comma-separated list of ids "
            "and/or tickets (e.g. 'KAN-12,45,KAN-9'). Selectors that match nothing are "
            "omitted and listed under `unresolved`. Max 100; not combinable with "
            "--limit or --cursor"
        ),
    )
    p_list.add_argument("--column", choices=COLUMNS, help="filter by column")
    p_list.add_argument(
        "--epic", type=_id_or_ticket_arg, metavar="EPIC",
        help="filter by epic (id or EPIC-<n>)",
    )
    p_list.add_argument(
        "--cycle", type=int, metavar="CYCLE_ID", help="filter by cycle/iteration id"
    )
    p_list.add_argument("--priority", choices=PRIORITIES, help="filter by priority")
    p_list.add_argument("--label", type=int, metavar="LABEL_ID", help="filter by label id")
    p_list.add_argument(
        "--due-before", dest="due_before", metavar="ISO",
        help="only cards due strictly before this ISO-8601 timestamp",
    )
    p_list.add_argument(
        "--overdue", action="store_true", help="only past-due cards not yet done"
    )
    p_list.add_argument(
        "--needs-human", dest="needs_human", action="store_true",
        help="only cards flagged for a human (needs-human)",
    )
    p_list.add_argument("--assignee", help="filter by assignee (exact match)")
    p_list.add_argument(
        "--q", metavar="TEXT",
        help=(
            "full-text search over title+description (websearch grammar: bare terms "
            "AND-ed, \"quoted\" = phrase, -term = exclude). Ranks by relevance unless "
            "--sort is given"
        ),
    )
    p_list.add_argument(
        "--sort", metavar="SPEC",
        help=(
            "sort keys, comma-separated, '-' prefix = descending. Both the space "
            "and equals forms work, e.g. --sort -priority,position or "
            "--sort=-priority,position. Sort keys: position/priority/due_date/"
            "created_at/updated_at/story_points/assignee/title/column/id "
            "(these order the rows; to choose which COLUMNS print, use --fields)"
        ),
    )
    p_list.add_argument("--limit", type=int, help="max cards to return")
    # KAN-615: `list` printed `(more — next cursor: …)` under --limit and then had no
    # flag to hand that value back, so cards could not be paginated from the CLI at
    # all — the line advertised a continuation that did not exist. Mirrors
    # `activity --cursor` (the same keyset value, the same round trip); the client
    # method already took `cursor=`, so only this surface was missing.
    p_list.add_argument(
        "--cursor",
        help=(
            "pagination cursor from a previous page's next-cursor line. Keyset order "
            "only, so the API rejects it alongside --sort/--q or --refs"
        ),
    )
    _add_fields_arg(p_list, "ticket,title,assignee,priority")
    p_list.set_defaults(func=_cmd_list, hints=_HINTS["list"])

    p_get = sub.add_parser("get", parents=[common], help="get a single card by id")
    p_get.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_get.set_defaults(func=_cmd_get, hints=_HINTS["get"])

    p_create = sub.add_parser("create", parents=[common], help="create a card")
    p_create.add_argument("title")
    p_create.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_create.add_argument("--description")
    p_create.add_argument("--column", choices=COLUMNS, help="starting column (default: todo)")
    p_create.add_argument(
        "--points", type=int, metavar="N",
        help="story points (1/2/3/5/8/13); sets the card's story_points (shown as pts=N)",
    )
    p_create.add_argument("--assignee")
    p_create.add_argument(
        "--epic", type=_id_or_ticket_arg, metavar="EPIC",
        help="link to an epic (id or EPIC-<n>)",
    )
    p_create.add_argument(
        "--cycle", type=int, metavar="CYCLE_ID",
        help="assign to a cycle/iteration by id",
    )
    p_create.add_argument("--priority", choices=PRIORITIES, help="priority (default: none)")
    p_create.add_argument("--due", metavar="ISO", help="due date (ISO-8601 timestamp)")
    p_create.add_argument(
        "--label", type=int, action="append", metavar="LABEL_ID",
        help="attach a label by id (repeatable)",
    )
    p_create.set_defaults(func=_cmd_create, hints=_HINTS["create"])

    p_update = sub.add_parser("update", parents=[common], help="edit a card's fields")
    p_update.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_update.add_argument("--title")
    p_update.add_argument("--description")
    p_update.add_argument(
        "--points", type=int, metavar="N",
        help="story points (1/2/3/5/8/13); sets the card's story_points (shown as pts=N)",
    )
    p_update.add_argument("--assignee")
    p_update.add_argument(
        "--epic", type=_id_or_ticket_arg, metavar="EPIC", help="link to an epic (id or EPIC-<n>)"
    )
    p_update.add_argument(
        "--cycle", type=int, metavar="CYCLE_ID",
        help="assign to a cycle/iteration by id",
    )
    p_update.add_argument("--priority", choices=PRIORITIES, help="re-rank priority")
    p_update.add_argument("--due", metavar="ISO", help="due date (ISO-8601 timestamp)")
    p_update.add_argument(
        "--label", type=int, action="append", metavar="LABEL_ID",
        help="replace the card's labels with these ids (repeatable; omit to leave unchanged)",
    )
    p_update.set_defaults(func=_cmd_update, hints=_HINTS["update"])

    p_move = sub.add_parser("move", parents=[common], help="move a card to a column")
    p_move.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_move.add_argument("column", choices=COLUMNS)
    p_move.add_argument("--position", type=int, help="index within the column (default: append)")
    p_move.set_defaults(func=_cmd_move, hints=_HINTS["move"])

    p_delete = sub.add_parser("delete", parents=[common], help="delete a card")
    p_delete.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_delete.set_defaults(func=_cmd_delete)

    # ``next`` peeks at the next ready-to-work card; ``--claim`` atomically
    # dispatches it (move to in_progress + assign) via the fleet-safe endpoint.
    p_next = sub.add_parser(
        "next",
        parents=[common],
        help="show the next ready card (--claim to atomically dispatch it)",
    )
    p_next.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_next.add_argument(
        "--claim", action="store_true", help="atomically claim it (move to in_progress + assign)"
    )
    p_next.add_argument("--assignee", help="who to claim it as (with --claim; default: you)")
    p_next.add_argument("--label", type=int, metavar="LABEL_ID", help="only cards with this label")
    p_next.add_argument(
        "--priority", choices=PRIORITIES, help="only cards at this priority or higher"
    )
    p_next.set_defaults(func=_cmd_next, hints=_HINTS["next"])

    # ``claim`` is the *named-card* counterpart of ``next --claim`` (KAN-502): one
    # invocation that moves a card you chose to in_progress and assigns it, instead of
    # `move` + `update`. Parity with the MCP `claim_card` tool, `--assignee` and all.
    p_claim = sub.add_parser(
        "claim",
        parents=[common],
        help="claim a named card (move to in_progress + assign) in one call",
    )
    p_claim.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_claim.add_argument(
        "--assignee",
        required=True,
        help="who to claim it as (required — this path has no server-side default)",
    )
    p_claim.set_defaults(func=_cmd_claim, hints=_HINTS["claim"])

    # --- needs-human handoff (M5 V13, KAN-246) -------------------------------
    p_needs_human = sub.add_parser(
        "needs-human", parents=[common], help="flag a card as needing a human"
    )
    p_needs_human.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_needs_human.add_argument("--note", help="an optional note describing the ask")
    p_needs_human.set_defaults(func=_cmd_needs_human, hints=_HINTS["needs-human"])

    p_resolve = sub.add_parser(
        "resolve", parents=[common], help="clear a card's needs-human flag"
    )
    p_resolve.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_resolve.set_defaults(func=_cmd_resolve, hints=_HINTS["resolve"])

    # --- fleet reporting / metrics (M5 V17, KAN-250) -------------------------
    p_metrics = sub.add_parser(
        "metrics",
        parents=[common],
        help="derived flow metrics for a board (throughput / cycle time / aging / by-assignee)",
    )
    p_metrics.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_metrics.add_argument(
        "--since", metavar="ISO", help="lower bound of the period (ISO-8601 timestamp)"
    )
    p_metrics.add_argument(
        "--window",
        metavar="SPAN",
        help="relative period, e.g. 7d / 24h / 30m (ignored with --since)",
    )
    p_metrics.set_defaults(func=_cmd_metrics)

    # --- activity feed (M5 V16, KAN-261) -------------------------------------
    p_activity = sub.add_parser(
        "activity",
        parents=[common],
        help="a board's activity feed, newest-first (filter by --actor / --action)",
    )
    p_activity.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_activity.add_argument(
        "--actor", metavar="LABEL",
        help="only rows by this actor (exact match on email / agent handle)",
    )
    p_activity.add_argument(
        "--action", metavar="VERB",
        help="only rows with this action (created/updated/deleted/moved/restored/…)",
    )
    p_activity.add_argument("--limit", type=int, help="max rows to return")
    p_activity.add_argument(
        "--cursor", help="pagination cursor from a previous page's next-cursor line"
    )
    _add_fields_arg(p_activity, "ts,actor_label,action,summary")
    p_activity.set_defaults(func=_cmd_activity)

    # --- notify subcommands (nested group; parity with /api/v1/notifications) -
    # Per-user, not board-scoped: no --board targeting here.
    p_notify = sub.add_parser(
        "notify", help="your notification inbox (list / read)"
    )
    notify_sub = p_notify.add_subparsers(
        dest="notify_command", metavar="<subcommand>", required=True
    )

    p_notify_list = notify_sub.add_parser(
        "list", parents=[common], help="list your notifications, newest-first"
    )
    p_notify_list.add_argument(
        "--unread", action="store_true", help="only unread notifications"
    )
    _add_fields_arg(p_notify_list, "id,kind,body")
    p_notify_list.set_defaults(func=_cmd_notify_list, noun="notification")

    p_notify_read = notify_sub.add_parser(
        "read", parents=[common], help="mark a notification read by id"
    )
    p_notify_read.add_argument(
        "notification_id", type=int, metavar="ID", help="a notification id"
    )
    p_notify_read.set_defaults(func=_cmd_notify_read, noun="notification")

    # --- board subcommands (nested group; parity with /api/v1/boards) --------
    # ``get``/``update``/``delete`` land in KAN-502: until then the group had only
    # ``list``/``create``, so renaming a board — or setting up its V38 signed outbound
    # webhook — was reachable only from MCP or a raw ``curl`` (ADR 0019 rejected
    # "let the CLI be the surface" partly on this).
    p_board = sub.add_parser(
        "board", help="manage boards (list / get / create / update / delete)"
    )
    board_sub = p_board.add_subparsers(
        dest="board_command", metavar="<subcommand>", required=True
    )

    p_board_list = board_sub.add_parser("list", parents=[common], help="list your boards")
    _add_fields_arg(p_board_list, "id,name,owner_id")
    p_board_list.set_defaults(func=_cmd_board_list, noun="board")

    p_board_get = board_sub.add_parser("get", parents=[common], help="get a single board by id")
    p_board_get.add_argument("board_id", type=int, metavar="BOARD", help="a board id")
    p_board_get.set_defaults(func=_cmd_board_get, noun="board")

    p_board_create = board_sub.add_parser("create", parents=[common], help="create a board")
    p_board_create.add_argument("name")
    p_board_create.set_defaults(
        func=_cmd_board_create, noun="board", hints=_HINTS["board create"]
    )

    p_board_update = board_sub.add_parser(
        "update",
        parents=[common],
        help="rename a board / configure its auto-sync + signed outbound webhook",
    )
    p_board_update.add_argument("board_id", type=int, metavar="BOARD", help="a board id")
    p_board_update.add_argument("--name", help="rename the board")
    # EPIC-10 / ADR 0016 GitHub PR auto-sync (KAN-529). Both were reachable from neither
    # the CLI nor MCP, so `curl` was the only way to opt a board in. Tri-states for the
    # same reason as the webhook switch below: `--name`-only must not flip them.
    autosync_group = p_board_update.add_mutually_exclusive_group()
    autosync_group.add_argument(
        "--autosync-enabled",
        dest="autosync_enabled",
        action="store_const",
        const=True,
        default=None,
        help="turn GitHub PR auto-sync ON for this board (needs WEBHOOK_SECRET server-side)",
    )
    autosync_group.add_argument(
        "--autosync-disabled",
        dest="autosync_enabled",
        action="store_const",
        const=False,
        help="turn GitHub PR auto-sync OFF for this board",
    )
    advance_group = p_board_update.add_mutually_exclusive_group()
    advance_group.add_argument(
        "--autosync-advance-to-done",
        dest="autosync_advance_to_done",
        action="store_const",
        const=True,
        default=None,
        help="let a merged PR move its card to done (only effective while auto-sync is on)",
    )
    advance_group.add_argument(
        "--no-autosync-advance-to-done",
        dest="autosync_advance_to_done",
        action="store_const",
        const=False,
        help="keep merge→done off: attach links + comment, but you move the card",
    )
    p_board_update.add_argument(
        "--outbound-webhook-url",
        dest="outbound_webhook_url",
        metavar="URL",
        help="where to POST each notification (V38 signed outbound webhook)",
    )
    # The secret is a credential: argv is visible in `ps` and lands in shell history, so
    # the stdin form is the documented path and the flag exists for parity/scripting.
    secret_group = p_board_update.add_mutually_exclusive_group()
    secret_group.add_argument(
        "--outbound-webhook-secret",
        dest="outbound_webhook_secret",
        metavar="SECRET",
        help=(
            "the HMAC-SHA256 signing key (write-only: the API never reads it back, and "
            "neither does this CLI). Prefer --outbound-webhook-secret-stdin — a value "
            "here is visible in `ps` and your shell history"
        ),
    )
    secret_group.add_argument(
        "--outbound-webhook-secret-stdin",
        dest="outbound_webhook_secret_stdin",
        action="store_true",
        help="read the signing key as one line from stdin, so it never enters argv",
    )
    # A tri-state: absent leaves the flag alone, which is what makes `--name`-only
    # renames safe. store_const rather than store_true/false so "unset" stays None.
    enabled_group = p_board_update.add_mutually_exclusive_group()
    enabled_group.add_argument(
        "--outbound-webhook-enabled",
        dest="outbound_webhook_enabled",
        action="store_const",
        const=True,
        default=None,
        help="turn outbound webhook delivery ON for this board",
    )
    enabled_group.add_argument(
        "--outbound-webhook-disabled",
        dest="outbound_webhook_enabled",
        action="store_const",
        const=False,
        help="turn outbound webhook delivery OFF for this board",
    )
    p_board_update.set_defaults(func=_cmd_board_update, noun="board")

    p_board_delete = board_sub.add_parser(
        "delete", parents=[common], help="delete a board (its cards + epics cascade)"
    )
    p_board_delete.add_argument("board_id", type=int, metavar="BOARD", help="a board id")
    p_board_delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_board_delete.set_defaults(func=_cmd_board_delete, noun="board")

    # --- epic subcommands (nested group; parity with /api/v1/epics) ----------
    p_epic = sub.add_parser(
        "epic", help="manage epics (list / get / create / update / delete)"
    )
    epic_sub = p_epic.add_subparsers(
        dest="epic_command", metavar="<subcommand>", required=True
    )

    p_epic_list = epic_sub.add_parser("list", parents=[common], help="list / query epics")
    p_epic_list.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    _add_fields_arg(p_epic_list, "ticket,name,lead,target_date")
    p_epic_list.set_defaults(func=_cmd_epic_list, noun="epic")

    p_epic_get = epic_sub.add_parser(
        "get", parents=[common], help="get a single epic by id or EPIC-<n>"
    )
    p_epic_get.add_argument(
        "epic_id", type=_id_or_ticket_arg, metavar="EPIC",
        help="an epic id or EPIC-<n> ticket",
    )
    p_epic_get.set_defaults(func=_cmd_epic_get, noun="epic")

    p_epic_create = epic_sub.add_parser("create", parents=[common], help="create an epic")
    p_epic_create.add_argument("name")
    p_epic_create.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_epic_create.add_argument("--description")
    p_epic_create.add_argument(
        "--target-date", dest="target_date", metavar="ISO",
        help="a target/ship date (ISO-8601 timestamp)",
    )
    p_epic_create.add_argument("--lead", help="a free-text owner (person/agent handle)")
    p_epic_create.set_defaults(
        func=_cmd_epic_create, noun="epic", hints=_HINTS["epic create"]
    )

    p_epic_update = epic_sub.add_parser("update", parents=[common], help="edit an epic's fields")
    p_epic_update.add_argument(
        "epic_id", type=_id_or_ticket_arg, metavar="EPIC",
        help="an epic id or EPIC-<n> ticket",
    )
    p_epic_update.add_argument("--name")
    p_epic_update.add_argument("--description")
    p_epic_update.add_argument(
        "--target-date", dest="target_date", metavar="ISO",
        help="a target/ship date (ISO-8601 timestamp)",
    )
    p_epic_update.add_argument("--lead", help="a free-text owner (person/agent handle)")
    p_epic_update.set_defaults(func=_cmd_epic_update, noun="epic")

    p_epic_delete = epic_sub.add_parser("delete", parents=[common], help="delete an epic")
    p_epic_delete.add_argument(
        "epic_id", type=_id_or_ticket_arg, metavar="EPIC",
        help="an epic id or EPIC-<n> ticket",
    )
    p_epic_delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_epic_delete.set_defaults(func=_cmd_epic_delete, noun="epic")

    # --- label subcommands (nested group; parity with /api/v1 labels) --------
    p_label = sub.add_parser("label", help="manage labels (list / create / delete)")
    label_sub = p_label.add_subparsers(
        dest="label_command", metavar="<subcommand>", required=True
    )

    p_label_list = label_sub.add_parser("list", parents=[common], help="list a board's labels")
    p_label_list.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    _add_fields_arg(p_label_list, "id,name,color")
    p_label_list.set_defaults(func=_cmd_label_list, noun="label")

    p_label_create = label_sub.add_parser("create", parents=[common], help="create a label")
    p_label_create.add_argument("name")
    # KAN-288: color is accepted as an optional positional OR the --color flag, so
    # both `label create bug '#hex'` and `label create bug --color '#hex'` work.
    # Omit both → a neutral default (DEFAULT_LABEL_COLOR); --color wins over the
    # positional when both are given.
    p_label_create.add_argument(
        "color_pos", nargs="?", metavar="COLOR",
        help=f"a color string, e.g. #0ea5e9 (or use --color; default {DEFAULT_LABEL_COLOR})",
    )
    p_label_create.add_argument(
        "--color", dest="color_opt", metavar="COLOR",
        help="a color string, e.g. #0ea5e9 (alternative to the positional)",
    )
    p_label_create.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_label_create.set_defaults(func=_cmd_label_create, noun="label")

    p_label_delete = label_sub.add_parser("delete", parents=[common], help="delete a label")
    p_label_delete.add_argument("label_id", type=int)
    p_label_delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_label_delete.set_defaults(func=_cmd_label_delete, noun="label")

    # --- view subcommands (nested group; parity with /api/v1 saved views) ----
    # Saved, named card queries on a board. ``create`` takes the same filter/sort
    # flags as ``list`` and stores them as the view's query.
    p_view = sub.add_parser("view", help="manage saved views (list / create / delete)")
    view_sub = p_view.add_subparsers(
        dest="view_command", metavar="<subcommand>", required=True
    )

    p_view_list = view_sub.add_parser("list", parents=[common], help="list a board's saved views")
    p_view_list.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    _add_fields_arg(p_view_list, "id,name,query")
    p_view_list.set_defaults(func=_cmd_view_list, noun="view")

    p_view_create = view_sub.add_parser(
        "create", parents=[common], help="save the given filters/sort as a named view"
    )
    p_view_create.add_argument("name")
    p_view_create.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    # The same filter/sort grammar as `list` — assembled into the stored query.
    p_view_create.add_argument("--column", choices=COLUMNS, help="filter by column")
    p_view_create.add_argument(
        "--epic", type=_id_or_ticket_arg, metavar="EPIC",
        help="filter by epic (id or EPIC-<n>)",
    )
    p_view_create.add_argument("--priority", choices=PRIORITIES, help="filter by priority")
    p_view_create.add_argument("--label", type=int, metavar="LABEL_ID", help="filter by label id")
    p_view_create.add_argument(
        "--due-before", dest="due_before", metavar="ISO",
        help="only cards due strictly before this ISO-8601 timestamp",
    )
    p_view_create.add_argument(
        "--overdue", action="store_true", help="only past-due cards not yet done"
    )
    p_view_create.add_argument(
        "--needs-human", dest="needs_human", action="store_true",
        help="only cards flagged for a human (needs-human)",
    )
    p_view_create.add_argument("--assignee", help="filter by assignee (exact match)")
    p_view_create.add_argument("--sort", metavar="SPEC", help="sort keys ('-' = descending)")
    p_view_create.set_defaults(func=_cmd_view_create, noun="view")

    p_view_delete = view_sub.add_parser("delete", parents=[common], help="delete a saved view")
    p_view_delete.add_argument("view_id", type=int)
    p_view_delete.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_view_delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_view_delete.set_defaults(func=_cmd_view_delete, noun="view")

    # --- cycle subcommands (V33 / KAN-297): board iterations ----------------
    # Board-scoped, named iterations. Assign a card to one with
    # `pandan update <card> --cycle <id>`; filter with `pandan list --cycle <id>`.
    p_cycle = sub.add_parser("cycle", help="manage cycles / iterations (list / create / delete)")
    cycle_sub = p_cycle.add_subparsers(
        dest="cycle_command", metavar="<subcommand>", required=True
    )

    p_cycle_list = cycle_sub.add_parser("list", parents=[common], help="list a board's cycles")
    p_cycle_list.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    _add_fields_arg(p_cycle_list, "id,name,starts_on,ends_on")
    p_cycle_list.set_defaults(func=_cmd_cycle_list, noun="cycle")

    p_cycle_create = cycle_sub.add_parser("create", parents=[common], help="create a cycle")
    p_cycle_create.add_argument("name")
    p_cycle_create.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_cycle_create.add_argument(
        "--starts-on", dest="starts_on", metavar="ISO",
        help="iteration start (ISO-8601 timestamp)",
    )
    p_cycle_create.add_argument(
        "--ends-on", dest="ends_on", metavar="ISO",
        help="iteration end (ISO-8601 timestamp)",
    )
    p_cycle_create.set_defaults(func=_cmd_cycle_create, noun="cycle")

    p_cycle_delete = cycle_sub.add_parser("delete", parents=[common], help="delete a cycle")
    p_cycle_delete.add_argument("cycle_id", type=int)
    p_cycle_delete.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_cycle_delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_cycle_delete.set_defaults(func=_cmd_cycle_delete, noun="cycle")

    p_cycle_metrics = cycle_sub.add_parser(
        "metrics",
        parents=[common],
        help="burndown / velocity for a cycle (committed vs completed + per-day burndown)",
    )
    p_cycle_metrics.add_argument("cycle_id", type=int)
    p_cycle_metrics.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_cycle_metrics.set_defaults(func=_cmd_cycle_metrics, noun="cycle")

    # --- batch create (KAN-502): N creates in one invocation -----------------
    # Deliberately NOT atomic and deliberately a separate verb from `batch-update`,
    # which is: there is no batch-create endpoint, so the shared client loops
    # `create_card` and the cards before a rejection stay created. Naming the two
    # differently is how a caller finds that out without reading the source.
    p_batch_create = sub.add_parser(
        "batch-create",
        parents=[common],
        help="create several cards in one call (JSON array; fail-fast, NOT atomic)",
        # The one place a caller reads before running it, so the non-atomicity is
        # stated here rather than only in the source. `batch-update` is atomic;
        # this is not, and the difference decides how you recover from a failure.
        description=(
            "Create several cards in one invocation. Fail-fast and NOT atomic: there is "
            "no batch-create endpoint, so this loops one POST per card and the cards "
            "created BEFORE a rejection stay created — nothing is rolled back. Re-run "
            "with the remainder rather than the whole array. (`batch-update` is the "
            "atomic one: it is a single server-side transaction.)"
        ),
    )
    p_batch_create.add_argument(
        "cards",
        metavar="JSON",
        help=(
            "a JSON array of card objects (\"title\" required), or '-' to read stdin "
            "(so `pandan batch-create - < cards.json` files a whole plan). Fields are "
            "the API's own names: description/column/story_points/assignee/epic_id/"
            "cycle_id/priority/due_date/label_ids/board_id"
        ),
    )
    p_batch_create.add_argument(
        "--board", type=int,
        help="board id filled into objects that omit board_id (default: PANDAN_BOARD_ID)",
    )
    # KAN-583: the response is `{"created": [<card>, …]}`, a recognised card
    # envelope since KAN-502 — so `_project_rows` already serves a projection here.
    # The flag is declared per-subparser, though, so until now the capability was
    # unreachable: the renderer would have printed it and the parser rejected the
    # ask. Same shape as KAN-529, one layer in.
    _add_fields_arg(p_batch_create, "ticket,title,column")
    p_batch_create.set_defaults(func=_cmd_batch_create)

    # --- batch update (M5 V19 / KAN-252): atomic multi-card PATCH ------------
    # One transaction server-side: all cards update or none (any bad id fails the
    # whole batch). Field edits only — use `move` for column/position changes.
    p_batch_update = sub.add_parser(
        "batch-update",
        parents=[common],
        help="atomically PATCH several cards (JSON array of {id, ...fields})",
    )
    p_batch_update.add_argument(
        "updates",
        metavar="JSON",
        help="a JSON array of {\"id\": <id>, ...fields} objects, or '-' to read stdin",
    )
    # KAN-583, as above: `{"updated": [<card>, …]}` became a recognised card
    # envelope in KAN-519, which taught the renderer the key and left the flag.
    _add_fields_arg(p_batch_update, "ticket,assignee,column")
    p_batch_update.set_defaults(func=_cmd_batch_update)

    # --- template subcommands (M5 V19 / KAN-252): card templates ------------
    # A named, reusable plan of cards on a board; `apply` seeds them in one call.
    p_template = sub.add_parser(
        "template", help="manage card templates (list / create / delete / apply)"
    )
    template_sub = p_template.add_subparsers(
        dest="template_command", metavar="<subcommand>", required=True
    )

    p_template_list = template_sub.add_parser(
        "list", parents=[common], help="list a board's card templates"
    )
    p_template_list.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    _add_fields_arg(p_template_list, "id,name,cards")
    p_template_list.set_defaults(func=_cmd_template_list, noun="template")

    p_template_create = template_sub.add_parser(
        "create", parents=[common], help="create a card template from a JSON list of cards"
    )
    p_template_create.add_argument("name")
    p_template_create.add_argument(
        "--cards",
        required=True,
        metavar="JSON",
        help="a JSON array of card objects (title required), or '-' to read stdin",
    )
    p_template_create.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_template_create.set_defaults(func=_cmd_template_create, noun="template")

    p_template_delete = template_sub.add_parser(
        "delete", parents=[common], help="delete a card template"
    )
    p_template_delete.add_argument("template_id", type=int)
    p_template_delete.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_template_delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_template_delete.set_defaults(func=_cmd_template_delete, noun="template")

    p_template_apply = template_sub.add_parser(
        "apply", parents=[common], help="instantiate a template's cards on the board"
    )
    p_template_apply.add_argument("template_id", type=int)
    p_template_apply.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    # KAN-583: `apply_template` returns `batch-create`'s own `created` envelope, so
    # the rows are cards and the projection noun is "card" — not this parser's
    # ``noun="template"``, which only names the *single*-entity render it never hits.
    _add_fields_arg(p_template_apply, "ticket,title,column")
    p_template_apply.set_defaults(func=_cmd_template_apply, noun="template")

    # --- me (KAN-614): the identity behind the token -------------------------
    # Placed with `login`/`config` because it belongs to the same onboarding moment —
    # "did my token work, and who am I?" — and deliberately ABOVE their section
    # header, because unlike those it is a real API call that needs a token and the
    # network. That is the whole point: `config show` can only report what this
    # machine resolved.
    #
    # No `--board` (`GET /api/v1/me` is the one `/api/v1` route with no board), no
    # `--fields` (two fields are not a list envelope — `tests/test_envelope_audit.py`
    # asserts the flag and the payload agree), and no `help[]` hints: after `me` the
    # next step is whatever the caller was already doing, which is the case the
    # `_HINTS` table exists to stay out of.
    p_me = sub.add_parser(
        "me",
        parents=[common],
        help="who your token authenticates as (id + email; exit 3 if it doesn't)",
    )
    p_me.set_defaults(func=_cmd_me)

    # --- login / config (local: no token, no network) ------------------------
    # ``login`` saves a PAT to ~/.config/pandan/config.toml without it touching argv:
    # a hidden prompt on a TTY, else one line from stdin.
    p_login = sub.add_parser(
        "login",
        parents=[common],
        help="save your PAT to the config file (prompts; never on the command line)",
    )
    p_login.add_argument("--api-url", help="also save the API origin")
    p_login.add_argument("--board-id", help="also save a default board id")
    p_login.add_argument(
        "--token-stdin",
        action="store_true",
        help="read the token from stdin instead of prompting (`… | pandan login --token-stdin`)",
    )
    p_login.set_defaults(local_func=_cmd_login)

    p_config = sub.add_parser(
        "config", help="inspect / set the config file (set / unset / show / path)"
    )
    config_sub = p_config.add_subparsers(
        dest="config_command", metavar="<subcommand>", required=True
    )

    p_config_set = config_sub.add_parser(
        "set",
        parents=[common],
        help="write api_url / board_id / token / require_board to the config file",
    )
    p_config_set.add_argument("--api-url")
    p_config_set.add_argument("--board-id")
    require_grp = p_config_set.add_mutually_exclusive_group()
    require_grp.add_argument(
        "--require-board",
        dest="require_board",
        action="store_true",
        default=None,
        help=(
            "fail any board-scoped verb given no --board, instead of falling back to "
            "the default board (safer with several boards on one account)"
        ),
    )
    require_grp.add_argument(
        "--no-require-board",
        dest="require_board",
        action="store_false",
        default=None,
        help="allow the default-board fallback again (the default)",
    )
    token_grp = p_config_set.add_mutually_exclusive_group()
    token_grp.add_argument(
        "--token", help="the PAT (discouraged — ends up in shell history; prefer --token-stdin)"
    )
    token_grp.add_argument(
        "--token-stdin", action="store_true", help="read the PAT from stdin (keeps it out of argv)"
    )
    p_config_set.set_defaults(local_func=_cmd_config_set)

    p_config_unset = config_sub.add_parser(
        "unset",
        parents=[common],
        help="remove keys from the config file (so you needn't hand-edit a file holding your PAT)",
    )
    p_config_unset.add_argument(
        "keys",
        nargs="+",
        metavar="KEY",
        help=f"one or more of: {', '.join(_CONFIG_KEYS)}",
    )
    p_config_unset.set_defaults(local_func=_cmd_config_unset)

    p_config_show = config_sub.add_parser(
        "show", parents=[common], help="print the effective config (token redacted)"
    )
    p_config_show.set_defaults(local_func=_cmd_config_show)

    p_config_path = config_sub.add_parser(
        "path", parents=[common], help="print the config file path"
    )
    p_config_path.set_defaults(local_func=_cmd_config_path)

    # --- context (V48, KAN-431): ambient board state for an agent session ----
    # Also local (`local_func`): install/uninstall/status touch only files, and
    # `show --hook` deliberately owns its own client + soft-fail behaviour instead
    # of the shared error contract, because a structured error on stdout would be
    # injected into the model's context as if it were board state. All four verbs
    # print the tab-separated human form; `--format` doesn't apply to them.
    context.add_parser(sub, common)

    # --- dependency subcommands (KAN-270): card-to-card blocking edges -------
    # Card-scoped (addressed by card id), so no --board targeting here. `blocked_by`
    # is the id of the card that BLOCKS the given card (the edge blocker → card).
    p_dep = sub.add_parser(
        "dep", help="manage card dependencies (add / rm / list blocking edges)"
    )
    dep_sub = p_dep.add_subparsers(dest="dep_command", metavar="<subcommand>", required=True)

    p_dep_add = dep_sub.add_parser(
        "add", parents=[common], help="record that a card is blocked-by another card"
    )
    p_dep_add.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_dep_add.add_argument(
        "--blocked-by", dest="blocked_by", type=_id_or_ticket_arg, required=True,
        metavar="BLOCKER",
        help="the blocker (card id or KAN-<n> ticket)",
    )
    p_dep_add.set_defaults(func=_cmd_dep_add)

    p_dep_rm = dep_sub.add_parser(
        "rm", parents=[common], help="remove a blocked-by edge"
    )
    p_dep_rm.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_dep_rm.add_argument(
        "--blocked-by", dest="blocked_by", type=_id_or_ticket_arg, required=True,
        metavar="BLOCKER",
        help="the blocker to detach (card id or KAN-<n> ticket)",
    )
    p_dep_rm.set_defaults(func=_cmd_dep_rm)

    p_dep_list = dep_sub.add_parser(
        "list", parents=[common], help="list a card's blocked_by / blocks edges"
    )
    p_dep_list.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_dep_list.set_defaults(func=_cmd_dep_list)

    # --- link subcommands (KAN-270): card work-links (PR / branch / CI URLs) -
    # The API's LinkCreate requires BOTH a non-empty label and url, so --label is
    # required here too (the issue said --title, but the field is `label`).
    p_link = sub.add_parser("link", help="manage card work-links (add / rm)")
    link_sub = p_link.add_subparsers(dest="link_command", metavar="<subcommand>", required=True)

    p_link_add = link_sub.add_parser(
        "add", parents=[common], help="attach a work-link (label + url) to a card"
    )
    p_link_add.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_link_add.add_argument(
        "--url", required=True, help="the link URL (e.g. a PR / branch / CI run)"
    )
    p_link_add.add_argument(
        "--label", required=True,
        help="a short label for the link (e.g. PR / branch / CI) — required by the API",
    )
    p_link_add.set_defaults(func=_cmd_link_add)

    p_link_rm = link_sub.add_parser(
        "rm", parents=[common], help="detach a work-link by its id"
    )
    p_link_rm.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_link_rm.add_argument(
        "--link-id", dest="link_id", type=int, required=True, metavar="LINK_ID",
        help="id of the link to remove",
    )
    p_link_rm.set_defaults(func=_cmd_link_rm)

    # --- comment subcommands (KAN-270): card notes ---------------------------
    p_comment = sub.add_parser("comment", help="manage card notes (add / list)")
    comment_sub = p_comment.add_subparsers(
        dest="comment_command", metavar="<subcommand>", required=True
    )

    p_comment_add = comment_sub.add_parser(
        "add", parents=[common], help="post a note to a card"
    )
    p_comment_add.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_comment_add.add_argument("--body", required=True, help="the note text (non-empty)")
    p_comment_add.set_defaults(func=_cmd_comment_add, hints=_HINTS["comment add"])

    p_comment_list = comment_sub.add_parser(
        "list", parents=[common], help="list a card's notes, oldest-first"
    )
    p_comment_list.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    _add_fields_arg(p_comment_list, "id,created_at,body")
    p_comment_list.set_defaults(func=_cmd_comment_list)

    return parser


# --- entry point ------------------------------------------------------------


def _normalize_sort_argv(argv: list[str]) -> list[str]:
    """Rewrite ``--sort -spec`` → ``--sort=-spec`` so a sort value that leads with
    ``-`` (descending, e.g. ``-priority,position``) isn't mistaken for a flag
    (KAN-286). argparse can't consume an option value beginning with ``-`` in the
    space form — only the ``=`` form worked — so the documented
    ``pandan list --sort -priority,position`` failed with "expected one argument".

    We only rewrite when the next token starts with a **single** ``-`` (a
    descending sort key); a real long flag (``--json``) or a missing value is left
    alone so argparse still reports it. The ``=`` form and plain values are
    untouched. Applies to the ``--sort`` of ``list`` and ``view create``."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if (
            tok == "--sort"
            and i + 1 < len(argv)
            and argv[i + 1].startswith("-")
            and not argv[i + 1].startswith("--")
        ):
            out.append(f"--sort={argv[i + 1]}")
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def _format_from_argv(argv: list[str]) -> str:
    """Best-effort read of the output format straight from argv (V47, KAN-430).

    Used only for the window *before* argparse has produced a namespace, where an
    argparse failure still has to render as the format the caller asked for. Both
    ``--format toon`` and ``--format=toon`` are recognised, last one wins, and an
    unknown value is ignored here — argparse rejects it a moment later, and its
    usage error should not itself be rendered in a format we don't understand."""
    chosen: str | None = None
    for index, token in enumerate(argv):
        if token.startswith("--format="):
            candidate = token.split("=", 1)[1]
        elif token == "--format" and index + 1 < len(argv):
            candidate = argv[index + 1]
        else:
            continue
        if candidate in OUTPUT_FORMATS:
            chosen = candidate
    if chosen is not None:
        return chosen
    return FORMAT_JSON if "--json" in argv else FORMAT_HUMAN


def _resolve_format(args: argparse.Namespace) -> str:
    """The effective output format: an explicit ``--format`` wins, then the ``--json``
    alias, else ``human``."""
    fmt = getattr(args, "output_format", None)
    if fmt:
        return fmt
    return FORMAT_JSON if getattr(args, "as_json", False) else FORMAT_HUMAN


def _client_options(args: argparse.Namespace) -> dict[str, Any]:
    """Per-verb transport overrides for the shared client — empty for every verb but
    the bare overview (V46, KAN-429), so nothing else changes shape.

    ``PandanClient`` defaults to a **35 s** read timeout plus one retry after a
    **1 s** backoff (``pandan-client/pandan_client/client.py:36-39``), i.e. a ~71 s
    worst case. That is the right trade for batch work against a scale-to-zero
    deploy, and the wrong one for the single command a human types when they just
    want to see the board. The overview halves the ceiling by shortening each attempt
    and dropping the backoff: **two back-to-back ~20 s attempts ≈ 40 s**, which still
    spans an observed ~30-40 s Fly cold wake (attempt 1 times out while the machine
    boots; attempt 2 lands on it awake), while a genuinely dead host still fails at
    the short connect timeout. Failing *faster* than that was rejected on purpose: a
    front door that reports a transport error on a sleeping board is a front door the
    caller just runs again, having learned nothing (``_announce_wait`` says what
    we're waiting for instead). The retry itself is not disable-able from here —
    ``retry_backoff=0`` only removes its sleep."""
    timeout = getattr(args, "client_timeout", None)
    if timeout is None:
        return {}
    return {"timeout": timeout, "retry_backoff": 0.0}


def run(argv: Sequence[str] | None = None) -> int:
    """Parse args, dispatch, print, and return an exit code (no ``sys.exit``).

    Every failure funnels through ``_print_error``: one structured row on **stdout**
    plus the exit code its machine code maps to (V43, KAN-426)."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    # Content first (V46, KAN-429 — AXI 8): no verb → show state, not usage.
    # **Prepended**, never appended: a trailing `--format` with no value must still
    # fail argparse's own way ("expected one argument"), not as an invalid choice.
    if _is_bare_invocation(raw_argv):
        raw_argv = [OVERVIEW_COMMAND, *raw_argv]
    # An argparse failure is itself a structured error, and it happens before there is
    # a parsed namespace to read the format from — so seed the render mode from argv.
    _set_error_format(_format_from_argv(raw_argv))
    parser = build_parser()
    args = parser.parse_args(_normalize_sort_argv(raw_argv))
    fmt = _resolve_format(args)
    _set_error_format(fmt)
    # Local handlers take only the namespace, so hand them the resolved format there.
    args.output_format = fmt

    # Local commands (login / config …) touch only the config file — no token, no
    # client, no network. Dispatch them before resolving or requiring config.
    local_func = getattr(args, "local_func", None)
    if local_func is not None:
        try:
            return local_func(args)
        except Exception as exc:
            return _print_error(_as_cli_error(exc), fmt=fmt)

    try:
        # warmup hits the public /api/health, so it doesn't need a token.
        config = load_config(require_token=getattr(args, "require_token", True))
    except ConfigError as exc:
        return _print_error(CliError(str(exc), code="config"), fmt=fmt)

    try:
        with PandanClient(config.api_url, config.token, **_client_options(args)) as client:
            result = args.func(client, config, args)
    except Exception as exc:
        # CliError (delete without --yes, an unresolvable ticket …), PandanApiError
        # (status → code), httpx (transport), anything else (unexpected).
        return _print_error(_as_cli_error(exc), fmt=fmt)

    # ``noun`` defaults to "card" (card verbs are top-level and set no noun);
    # the board/epic subparsers set it so the delete summary reads correctly.
    # ``--fields`` (list verbs only) can still fail on an unknown field name — the
    # valid names are the keys of the rows we just fetched — so rendering is guarded
    # the same way the call was.
    try:
        _emit(
            result,
            fmt=fmt,
            noun=getattr(args, "noun", "card"),
            fields=getattr(args, "fields", None),
            # V45 (KAN-428): the limit comes from config (env / file), the opt-out
            # from the flag — so a whole session can be widened once, or one call.
            full=getattr(args, "full", False),
            limit=config.max_text_chars,
            # V46 (KAN-429): the next-step templates for this verb, human-only.
            hints=_hint_lines(args, result),
        )
    except CliError as exc:
        return _print_error(exc, fmt=fmt)
    # warmup never throws (a still-waking/failed server is a status, not an
    # exception), so it maps that status to a scripting-friendly exit code:
    # 0 when awake, 1 otherwise (retry the CI pre-step / investigate).
    if getattr(args, "is_warmup", False):
        return EXIT_OK if result.get("status") == "ok" else EXIT_ERROR
    return EXIT_OK
