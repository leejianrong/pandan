#!/usr/bin/env python
"""Measure the resident context cost of the MCP tool surface, and of the V49
alternatives, on one yardstick (KAN-432 / ADR 0019).

Why this exists: the 49 tool schemas are serialized into *every* agent session's
context before it does any work. That cost is measurable, and so is the cost of
each surface we might replace it with — so the V49 decision can be made on
numbers instead of intuition.

Method
------
* **Unit.** ``o200k_base`` tokens via ``tiktoken``. This is *not* Claude's
  tokenizer, so treat the absolute numbers as a consistent proxy, not a billing
  figure. It is the same encoding V47 used to measure TOON, so the two
  measurements are comparable — that is the whole reason for the choice.
* **What is counted.** For each tool, the JSON object a client sends to the model
  API: ``{"name": "mcp__pandan__<tool>", "description": <docstring>,
  "input_schema": <inputSchema>}``, from the server's real ``tools/list``
  response (``FastMCP.list_tools()``, the same call the stdio transport answers
  with). Serialized **compact** (``separators=(",", ":")``) for the headline
  number, and at ``indent=2`` as an upper bracket, because the client's exact
  framing is not observable from here and pretty-printing costs ~46% more.
* **What is counted SEPARATELY, and why** (KAN-518). A ``tools/list`` entry has a
  *third* schema field, ``outputSchema``, which the headline unit above does not
  include. That omission is deliberate but was undocumented until KAN-518: the
  headline unit is "what a client puts in the **model's context**", and whether
  ``outputSchema`` lands there is not observable from inside the server — the
  Anthropic Messages API tool definition has no ``output_schema`` field at all, so
  a bridging client has nowhere to put it, while an MCP-native client may well
  forward it. Rather than guess, :func:`measure_output_schemas` reports it as its
  own bracketed row: alone, and as the ceiling where a client forwards all three
  fields. Do **not** fold it into the headline — see ADR 0019, *The third field*.
* **The alternatives are built with FastMCP too**, not hand-written JSON, so
  options (a) and (b) go through the identical Pydantic→JSON-Schema serializer
  as the live surface. Any per-tool framing overhead is therefore counted the
  same way on both sides of the comparison.
* **Before vs. as-shipped.** Since Phase 2, ``server.py`` compacts the advertised
  schemas at import, so the live surface *is* the compacted one. The
  pre-compaction row is recovered with ``Tool.from_function`` (see
  :func:`raw_tool_payloads`) rather than estimated, and the compaction applied to
  option (a) is the **production** function, so nothing here can drift from what
  the server actually sends.

Run it::

    cd mcp && uv run --with tiktoken python scripts/measure_tool_schema_tokens.py

``--per-tool`` also prints the shipped surface broken down tool by tool.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool

from pandan_mcp.schema import compact_schema
from pandan_mcp.server import mcp as live_mcp

Column = Literal["todo", "in_progress", "done"]
Priority = Literal["none", "low", "medium", "high", "urgent"]

NAMESPACE = "mcp__pandan__"


# --- the yardstick ----------------------------------------------------------


def _encoder():
    import tiktoken

    return tiktoken.get_encoding("o200k_base")


def tool_payloads(server: FastMCP) -> list[dict[str, Any]]:
    """The per-tool JSON objects a client puts in the model's context."""
    return [
        {
            "name": f"{NAMESPACE}{tool.name}",
            "description": tool.description,
            "input_schema": tool.inputSchema,
        }
        for tool in asyncio.run(server.list_tools())
    ]


def measure(payloads: list[dict[str, Any]], enc) -> dict[str, int]:
    compact = [json.dumps(p, separators=(",", ":")) for p in payloads]
    pretty = [json.dumps(p, indent=2) for p in payloads]
    return {
        "tools": len(payloads),
        "compact": sum(len(enc.encode(s)) for s in compact),
        "indent2": sum(len(enc.encode(s)) for s in pretty),
        "descriptions": sum(len(enc.encode(p["description"] or "")) for p in payloads),
        "schemas": sum(
            len(enc.encode(json.dumps(p["input_schema"], separators=(",", ":"))))
            for p in payloads
        ),
        "names": sum(len(enc.encode(p["name"])) for p in payloads),
    }


def output_schemas(server: FastMCP) -> list[dict[str, Any] | None]:
    """Each tool's ``outputSchema`` — the third field of a ``tools/list`` entry.

    FastMCP generates one from the return annotation; for every pandan tool
    (``-> dict[str, Any]``) that is the same three-key object with a Pydantic
    class name in it: ``{"additionalProperties": true, "title":
    "<fn>DictOutput", "type": "object"}`` (the title comes from the *function*
    name at ``mcp/server/fastmcp/utilities/func_metadata.py:501``, not the
    registered tool name — so the tool registered as ``next`` reads
    ``next_readyDictOutput``).

    ``None`` for a tool with no structured output, which is why the row below
    reports how many were actually present rather than assuming the tool count.
    """
    return [tool.outputSchema for tool in asyncio.run(server.list_tools())]


def measure_output_schemas(
    payloads: list[dict[str, Any]], schemas: list[dict[str, Any] | None], enc
) -> dict[str, int]:
    """Measure ``outputSchema`` as its own bracketed row (KAN-518).

    Two numbers, because the honest answer is a range and not a point:

    * ``alone_*`` — the ``outputSchema`` objects on their own, i.e. what a client
      that forwards them adds on top of the headline.
    * ``combined_*`` — the headline payload with ``output_schema`` spliced in as a
      fourth key, i.e. the ceiling for a client that forwards all three fields
      (this is slightly more than ``headline + alone``, because the extra key name
      and separators are counted too).
    """
    if len(payloads) != len(schemas):  # pragma: no cover - guards a caller bug
        raise ValueError("payloads and schemas must line up tool-for-tool")
    present = [s for s in schemas if s is not None]
    combined = [
        {**payload, "output_schema": schema} if schema is not None else payload
        for payload, schema in zip(payloads, schemas)
    ]

    def total(objs: list[Any], **dump_kwargs: Any) -> int:
        return sum(len(enc.encode(json.dumps(o, **dump_kwargs))) for o in objs)

    return {
        "tools": len(schemas),
        "with_output_schema": len(present),
        "alone_compact": total(present, separators=(",", ":")),
        "alone_indent2": total(present, indent=2),
        "combined_compact": total(combined, separators=(",", ":")),
        "combined_indent2": total(combined, indent=2),
    }


def raw_tool_payloads(server: FastMCP) -> list[dict[str, Any]]:
    """The payloads as FastMCP *would* advertise them without V49's compaction.

    ``server.py`` applies :func:`pandan_mcp.schema.compact_advertised_schemas` at
    import, so the live surface is already compacted and the pre-compaction number
    cannot simply be read back. ``Tool.from_function`` regenerates the schema from
    the function signature (mcp/server/fastmcp/tools/base.py:77), which is exactly
    what registration did in the first place — so this recovers the "before" side
    of the comparison honestly rather than estimating it.
    """
    return [
        {
            "name": f"{NAMESPACE}{tool.name}",
            "description": tool.description,
            "input_schema": Tool.from_function(tool.fn, name=tool.name).parameters,
        }
        for tool in server._tool_manager.list_tools()
    ]


def strip_pydantic_noise(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply **the shipped compaction** to a set of payloads.

    Deliberately delegates to :func:`pandan_mcp.schema.compact_schema` rather than
    keeping a private copy of the rule, so the number this script reports is the
    number the server actually delivers. An earlier draft duplicated the logic and
    would have over-reported the saving by ~6 enum-bearing optionals that the real
    rule refuses to collapse (collapsing a nullable enum narrows it — see
    ``pandan_mcp/schema.py``).
    """
    return [
        {**payload, "input_schema": compact_schema(copy.deepcopy(payload["input_schema"]))}
        for payload in payloads
    ]


# --- option (a): one tool per entity, with an `action` argument -------------

option_a = FastMCP("pandan")


@option_a.tool()
def warmup() -> dict[str, Any]:
    """Wake the API if it has scaled to zero (Fly free tier); returns a status
    without throwing. Call before a burst of work to absorb the cold start."""


@option_a.tool()
def board(
    action: Literal["list", "get", "create", "update", "delete"],
    board_id: int | None = None,
    name: str | None = None,
    outbound_webhook_url: str | None = None,
    outbound_webhook_secret: str | None = None,
    outbound_webhook_enabled: bool | None = None,
) -> dict[str, Any]:
    """Boards you own. ``action``: ``list`` (id+name of all of them, call this to
    discover ids) | ``get``/``delete`` (need ``board_id``; delete cascades its
    cards+epics) | ``create`` (needs ``name``) | ``update`` (``board_id`` plus any
    of ``name`` and the V38 signed-outbound-webhook opt-in:
    ``outbound_webhook_url``, ``outbound_webhook_secret`` — write-only, never read
    back — and ``outbound_webhook_enabled``). Owner-gated throughout."""


@option_a.tool()
def card(
    action: Literal[
        "list", "get", "create", "create_many", "update", "update_many",
        "move", "claim", "delete", "dispatch", "next", "needs_human", "resolve",
    ],
    card_id: int | None = None,
    board_id: int | None = None,
    title: str | None = None,
    description: str | None = None,
    column: Column | None = None,
    position: int | None = None,
    story_points: int | None = None,
    assignee: str | None = None,
    epic_id: int | None = None,
    cycle_id: int | None = None,
    priority: Priority | None = None,
    due_date: str | None = None,
    label_ids: list[int] | None = None,
    label: int | None = None,
    updated_since: str | None = None,
    due_before: str | None = None,
    overdue: bool | None = None,
    needs_human_filter: bool | None = None,
    attention_note: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    cards: list[dict[str, Any]] | None = None,
    updates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Stories. ``board_id`` defaults to PANDAN_BOARD_ID; card-id-addressed
    actions need no board. ``action``:

    - ``list`` — filters AND-ed: column, epic_id, cycle_id, priority, label (id),
      assignee, updated_since / due_before (ISO-8601), overdue,
      needs_human_filter. ``q`` = full-text over title+description (websearch
      grammar: bare terms AND-ed, "quoted" phrase, ``-term`` excludes), ranked by
      relevance unless ``sort`` is given. ``sort`` = comma-separated keys, ``-``
      for descending (position/priority/due_date/created_at/updated_at/
      story_points/assignee/title/column/id). Paginate with ``limit`` +
      ``cursor`` (not available with ``sort``/``q``).
    - ``get``/``delete`` — need ``card_id``.
    - ``create`` — ``title`` required; lands at the end of ``column`` (default
      todo). ``story_points`` ∈ 1/2/3/5/8/13. ``epic_id``/``cycle_id`` must be on
      the same board; ``label_ids`` attaches board labels.
    - ``create_many`` — ``cards``: a list of create payloads. **Fail-fast, not
      atomic**: cards before a rejected one stay created.
    - ``update`` — ``card_id`` + only the fields you pass. Not column/position
      (use ``move``). ``label_ids`` **replaces** the set (``[]`` clears).
    - ``update_many`` — ``updates``: a list of ``{"id": …, …fields}``. **Atomic**,
      unlike ``create_many``.
    - ``move`` — ``card_id`` + ``column``, optional ``position`` (omit to append).
    - ``claim`` — ``card_id`` + ``assignee``: move to in_progress *and* assign.
    - ``dispatch`` — atomically claim the next ready story and start it (the
      agent's "give me something to do"): next unblocked todo, highest priority
      first, under ``FOR UPDATE SKIP LOCKED`` so a fleet never double-grabs.
      ``label``/``priority`` (a *minimum*) narrow it. Returns ``{"card": null}``
      when nothing is ready.
    - ``next`` — the same selection, read-only (peek without claiming).
    - ``needs_human`` — flag ``card_id`` for a person (a decision, missing access,
      a stuck PR) with an optional ``attention_note``; findable via
      ``list``+needs_human_filter. ``resolve`` clears the flag."""


@option_a.tool()
def epic(
    action: Literal["list", "get", "create", "update", "delete"],
    epic_id: int | None = None,
    board_id: int | None = None,
    name: str | None = None,
    description: str | None = None,
    target_date: str | None = None,
    lead: str | None = None,
) -> dict[str, Any]:
    """Epics — per-board groupings a story links to via its ``epic_id``.
    ``board_id`` defaults to PANDAN_BOARD_ID. ``action``: ``list`` | ``get`` |
    ``create`` (needs ``name``; optional ``description``, ISO-8601
    ``target_date``, free-text ``lead``) | ``update`` (``epic_id`` + the fields
    you pass) | ``delete`` (``epic_id``; child stories are **detached**, their
    epic_id cleared, not deleted)."""


@option_a.tool()
def card_relation(
    action: Literal[
        "dependency_add", "dependency_remove", "dependency_list",
        "link_add", "link_remove", "comment_add", "comment_list",
    ],
    card_id: int,
    blocker_id: int | None = None,
    link_id: int | None = None,
    label: str | None = None,
    url: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Things hanging off a story ``card_id`` (authorized via its own board).
    ``action``:

    - ``dependency_add``/``dependency_remove`` — ``blocker_id`` must finish
      first; same board. 422 on a self-link, duplicate, or cycle.
      ``dependency_list`` returns ``{"blocked_by": [...], "blocks": [...]}`` (card
      reads already inline these).
    - ``link_add`` — a work-link: ``label`` ("PR", "branch", "CI") + ``url``.
      ``link_remove`` takes ``link_id``.
    - ``comment_add`` — post a note (``body``): a decision, a handoff, why
      something is blocked. The author is your PAT's owner, never the body.
      ``comment_list`` returns them oldest-first (not inlined on card reads)."""


@option_a.tool()
def label(
    action: Literal["list", "create", "delete"],
    board_id: int | None = None,
    label_id: int | None = None,
    name: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Board-scoped labels (``board_id`` defaults to PANDAN_BOARD_ID).
    ``action``: ``list`` (id, name, color — use the ids in ``label_ids`` on a card
    create/update, or as the ``label`` filter) | ``create`` (``name`` + ``color``,
    e.g. ``#0ea5e9``) | ``delete`` (``label_id``; detaches from every card)."""


@option_a.tool()
def view(
    action: Literal["list", "create", "delete"],
    board_id: int | None = None,
    view_id: int | None = None,
    name: str | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Saved views — named, persisted card queries on a board (``board_id``
    defaults to PANDAN_BOARD_ID). ``action``: ``list`` (id, name, query — spread a
    view's ``query`` as ``card(action="list", …)`` args to reproduce its cards) |
    ``create`` (``name`` + optional ``query``, the same filter+sort keys as a card
    list, e.g. ``{"assignee": "agent-7", "sort": "-priority"}``) | ``delete``
    (``view_id``)."""


@option_a.tool()
def cycle(
    action: Literal["list", "create", "delete", "metrics"],
    board_id: int | None = None,
    cycle_id: int | None = None,
    name: str | None = None,
    starts_on: str | None = None,
    ends_on: str | None = None,
) -> dict[str, Any]:
    """Cycles / iterations on a board (``board_id`` defaults to PANDAN_BOARD_ID).
    ``action``: ``list`` (id, name, starts_on, ends_on) | ``create`` (``name`` +
    optional ISO-8601 ``starts_on``/``ends_on``) | ``delete`` (``cycle_id``; its
    cards are detached, not deleted) | ``metrics`` (``cycle_id``: committed vs
    completed stories+points, velocity, and a per-day burndown over the cycle's
    window — empty when it has no dates). Assign a card with
    ``card(action="update", cycle_id=…)``."""


@option_a.tool()
def template(
    action: Literal["list", "create", "delete", "apply"],
    board_id: int | None = None,
    template_id: int | None = None,
    name: str | None = None,
    cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Card templates — named, reusable plans of cards on a board (``board_id``
    defaults to PANDAN_BOARD_ID). ``action``: ``list`` (id, name, cards) |
    ``create`` (``name`` + a non-empty ``cards`` list of create payloads without
    ``board_id``) | ``delete`` (``template_id``) | ``apply`` (``template_id``:
    instantiate the cards for real, atomically — all or none)."""


@option_a.tool()
def report(
    action: Literal["metrics", "activity"],
    board_id: int | None = None,
    since: str | None = None,
    window: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    actor: str | None = None,
    action_verb: str | None = None,
) -> dict[str, Any]:
    """Read-only board reporting (``board_id`` defaults to PANDAN_BOARD_ID);
    nothing is written. ``action``:

    - ``metrics`` — throughput (cards done in the period), cycle time (first
      in_progress → done: avg/median/p90 seconds), aging WIP, and a per-assignee
      breakdown. Bound with ``since`` (ISO-8601) or ``window`` (``7d``/``24h``/
      ``30m``); omit both for all time.
    - ``activity`` — the board's feed, newest-first: one row per successful
      create/update/delete/move of a card, epic or board. Filters (AND-ed):
      ``actor`` (email / agent handle) and ``action_verb``
      (created/updated/deleted/moved/restored/…). Paginate with ``limit`` +
      ``cursor``."""


@option_a.tool()
def notification(
    action: Literal["list", "mark_read"],
    notification_id: int | None = None,
    unread: bool = False,
) -> dict[str, Any]:
    """YOUR notification inbox — **per-user, not board-scoped**: a card flagged
    needs_human, a card newly blocked, a linked PR's CI failing, an assignment.
    Poll/pull only (ADR 0007 — there is no push channel). ``action``: ``list``
    (newest-first; ``unread=true`` for unread only) | ``mark_read``
    (``notification_id``; idempotent, 404 if not yours)."""


# --- option (b): a single exec tool, the CLI is the surface -----------------

option_b = FastMCP("pandan")


@option_b.tool()
def pandan(args: list[str], timeout: int | None = None) -> dict[str, Any]:
    """Run the ``pandan`` CLI — the full Pandan board surface (cards, epics,
    boards, labels, saved views, card templates, cycles, dependencies,
    work-links, comments, dispatch/claim, needs-human handoff, notifications,
    metrics, activity). Pass ``args`` as an argv list, **without** the leading
    ``pandan`` (e.g. ``["list", "--column", "todo"]``). Returns
    ``{"stdout": …, "stderr": …, "exit_code": …}``.

    Discover the grammar from the tool itself rather than guessing: ``["--help"]``
    lists every verb, ``["<verb>", "--help"]`` documents one. A bare ``[]`` prints
    the board's current state. Every verb takes ``--format {human,json,toon}``
    (human is a compact key-free TSV and the cheapest), ``--fields a,b,c`` to
    narrow the columns, and ``--full`` to defeat the 500-char truncation of long
    free text. Errors are structured on stdout with a stable ``code`` and a
    documented exit status, so a failure is machine-readable.

    Config (``PANDAN_API_URL``/``PANDAN_TOKEN``/``PANDAN_BOARD_ID``) is already in
    this server's environment; you never pass or see the token."""


# --- reporting --------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-tool", action="store_true", help="break the live surface down")
    parser.add_argument("--json", action="store_true", help="emit the table as JSON")
    args = parser.parse_args()

    enc = _encoder()
    raw = raw_tool_payloads(live_mcp)
    surfaces = {
        "49 typed tools, before compaction": raw,
        "49 typed tools, AS SHIPPED (V49)": tool_payloads(live_mcp),
        "(a) one tool per entity + action arg": tool_payloads(option_a),
        "(a) + the same compaction": strip_pydantic_noise(tool_payloads(option_a)),
        "(b) single exec-pandan tool": tool_payloads(option_b),
    }
    results = {name: measure(payloads, enc) for name, payloads in surfaces.items()}

    # outputSchema is measured per *live* surface only: the "before compaction"
    # and "+ the same compaction" rows are inputSchema variants of a surface whose
    # outputSchema is identical either way, so re-reporting them would be noise.
    output_rows = {
        name: measure_output_schemas(surfaces[name], output_schemas(server), enc)
        for name, server in (
            ("49 typed tools, AS SHIPPED (V49)", live_mcp),
            ("(a) one tool per entity + action arg", option_a),
            ("(b) single exec-pandan tool", option_b),
        )
    }

    if args.json:
        print(json.dumps({"input_schema": results, "output_schema": output_rows}, indent=2))
        return

    baseline = results["49 typed tools, before compaction"]["compact"]
    print("Resident tool-schema cost, o200k_base tokens")
    print(f"{'surface':38s} {'tools':>5s} {'compact':>8s} {'indent2':>8s} {'vs base':>8s}")
    print("-" * 72)
    for name, row in results.items():
        delta = f"{(row['compact'] - baseline) / baseline * 100:+.0f}%"
        print(
            f"{name:38s} {row['tools']:5d} {row['compact']:8d} "
            f"{row['indent2']:8d} {delta:>8s}"
        )
    print()
    print("Where the shipped cost sits (compact):")
    cur = results["49 typed tools, AS SHIPPED (V49)"]
    print(f"  descriptions (prose) {cur['descriptions']:6d}")
    print(f"  input schemas        {cur['schemas']:6d}")
    print(f"  tool names           {cur['names']:6d}")

    print()
    print("outputSchema — the THIRD field of a tools/list entry, NOT in the table above.")
    print("Whether a client forwards it into the model's context is not observable from")
    print("here (the Anthropic Messages API tool definition has no output_schema field),")
    print("so it is bracketed on its own rather than folded into the headline. KAN-518.")
    print(
        f"{'surface':38s} {'n':>3s} {'alone-c':>8s} {'alone-i2':>8s} "
        f"{'all3-c':>8s} {'all3-i2':>8s}"
    )
    print("-" * 78)
    for name, row in output_rows.items():
        print(
            f"{name:38s} {row['with_output_schema']:3d} {row['alone_compact']:8d} "
            f"{row['alone_indent2']:8d} {row['combined_compact']:8d} "
            f"{row['combined_indent2']:8d}"
        )

    if args.per_tool:
        print("\nPer-tool, as shipped (compact):")
        rows = sorted(
            (
                (len(enc.encode(json.dumps(p, separators=(",", ":")))), p["name"])
                for p in surfaces["49 typed tools, AS SHIPPED (V49)"]
            ),
            reverse=True,
        )
        for count, name in rows:
            print(f"  {count:5d}  {name}")


if __name__ == "__main__":
    main()
