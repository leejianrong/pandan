"""MCP server exposing the Pandan API as agent tools (stdio transport).

Each tool is a thin wrapper over one ``/api/v1`` endpoint via ``PandanClient``.
Type hints + docstrings here become the tool schema + description the agent sees
(the SDK's high-level decorator layer — ``MCPServer``, which is what v1's
``FastMCP`` was renamed to in **SDK 2.0.0**; see ``pyproject.toml`` for the bound
and KAN-585). Since M3 V8 (ADR 0013) ``/api/v1`` is auth-required, so
``PANDAN_TOKEN`` must be a valid personal access token (V9/ADR 0014); it
authenticates as its owning user and can only reach boards that user owns.

**Board scoping (V10, ADR 0015):** the agent works across multiple boards
dynamically. ``list_boards``/``create_board`` discover and make boards; the
board-scoped tools take an optional per-call ``board_id`` (defaulting to
``PANDAN_BOARD_ID`` when set, else the API's own fallback — list = all your
boards, create = your earliest board). Card-id-addressed tools
(``get_card``/``update_card``/``move_card``/``delete_card``) need no ``board_id``:
the server authorizes via the card's own board.

**The surface is frozen (V49, ADR 0019) — currently at 56 tools.** It was measured
against a consolidated verb set and a single exec-``pandan`` tool and deliberately
kept, as the documented fallback for a consumer that cannot run the CLI — but it
does not grow silently. New board capability lands in the **CLI** first; adding a
tool here means amending ADR 0019 and the pin in ``tests/test_schema.py``, the way
M9 V69 (KAN-1058) did to add the 5 team tools below. See ``README.md`` (*Why the
surface is frozen*) for the reasoning and the numbers.

**Two tests read THIS FILE, and both must stay green** (KAN-502): the freeze pin in
``tests/test_schema.py``, and ``pandan-cli/tests/test_parity.py``, which parses the
tool names out of this module *as text* — it must never ``import pandan_mcp``,
because an adapter importing another adapter inverts ADR 0005 — and asserts parity
in **both** directions. So a tool added here without a CLI route fails the **CLI**
suite, and CI's ``cli`` paths filter includes this file for exactly that reason.
Parity runs MCP ⊇ CLI *and* CLI ⊇ MCP as of KAN-502; it is no longer aspirational.

**The read tools are shaped (KAN-501).** ADR 0019 measured one un-narrowed
``list_cards`` against a real 121-card board at ~44,900 tokens — 5.1× the entire
schema surface, in a single result — and found the cost is *field breadth*, not
pretty-printing. So every read below takes ``fields`` (the keys to keep; ~-84% on
that page) and truncates long free text with a true-total hint unless ``full=true``.
Omit both and you get exactly what the API returned. See ``shaping.py``, and
``scripts/measure_read_payload_tokens.py`` to re-run the numbers.

Run with ``python -m pandan_mcp`` (or the ``pandan-mcp`` script); Claude Code
launches it over stdio per the .mcp.json snippet in the README.
"""
from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from pandan_client import PandanClient, split_card_selectors

from .config import load_config
from .schema import compact_advertised_schemas
from .shaping import shape

Column = Literal["todo", "in_progress", "done"]
Priority = Literal["none", "low", "medium", "high", "urgent"]

# The local name stays ``mcp`` on purpose: ``pandan-cli/tests/test_parity.py``
# parses ``@mcp.tool(...)`` out of this file as TEXT (it must not import this
# package — ADR 0005). Renaming the variable used to *silently* empty its regex;
# since KAN-592 that test anchors on this binding line instead, so a rename fails
# loudly and names the two regexes to update. Keep the binding on one line at
# column 0, or the anchor stops finding it.
mcp = MCPServer("pandan")

_client: PandanClient | None = None
_default_board_id: int | None = None


def _client_instance() -> PandanClient:
    """Lazily build the API client from the environment on first tool use."""
    global _client, _default_board_id
    if _client is None:
        config = load_config()
        _client = PandanClient(config.api_url, config.token)
        _default_board_id = config.board_id
    return _client


def _board(board_id: int | None) -> int | None:
    """Resolve the target board: the per-call ``board_id`` wins, else the
    ``PANDAN_BOARD_ID`` default, else ``None`` (let the API apply its fallback)."""
    return board_id if board_id is not None else _default_board_id


def _require_board(board_id: int | None) -> int:
    """Like :func:`_board`, but the target board id is **required** (the path-scoped
    board tools have no API-side fallback). Raises when neither a per-call
    ``board_id`` nor ``PANDAN_BOARD_ID`` is set."""
    resolved = _board(board_id)
    if resolved is None:
        raise ValueError("board_id is required (set PANDAN_BOARD_ID or pass board_id)")
    return resolved


# --- ops: warmup ------------------------------------------------------------


@mcp.tool()
def warmup() -> dict[str, Any]:
    """Wake the API if it has scaled to zero (Fly free tier). Pings the health
    endpoint using the shared cold-start retry/timeout and returns a status
    without throwing, always naming the ``origin`` it tried: ``ok`` once healthy;
    ``waking`` if it's still coming up (call again shortly); ``unreachable`` if the
    connection was refused or the host didn't resolve, which retrying will NOT fix
    (check PANDAN_API_URL); ``error`` for any other API failure. Call this before a
    burst of work to absorb the cold start in one place instead of on your first
    real tool call.
    """
    return _client_instance().warmup()


# --- boards: discover + create (V10) ---------------------------------------


@mcp.tool()
def list_boards(fields: list[str] | None = None) -> dict[str, Any]:
    """List the boards you own. Call this first to discover which boards you can
    target with ``board_id`` on the other tools. A row also carries autosync and
    outbound-webhook settings a discovery call rarely reads, so pass
    ``fields=["id","name"]`` (−84%). No ``full``: a board has no free text."""
    return shape(_client_instance().list_boards(), fields=fields)


@mcp.tool()
def create_board(name: str, key: str | None = None, team_id: int | None = None) -> dict[str, Any]:
    """Create a new board owned by you; returns it (including its id and key).

    ``key`` is the board's short ref prefix — the ``ENG`` in a board-local ``ENG-14``
    — 2-10 chars, an uppercase letter then uppercase letters/digits, and unique among
    YOUR boards (another user may hold the same key). Usually omit it: one is derived
    from the name and suffixed on collision, so a create never fails on naming. Pass
    it to ask for a specific prefix: malformed or reserved (``KAN``/``EPIC``) is a
    422, already used by your boards is a 409.

    ``team_id`` (M9 V67) optionally links the board to a team you belong to — call
    ``list_teams`` to find one. 403 if you aren't a member (uniformly for an unknown
    id too). Omit it and the board stays personal (``team_id: null``)."""
    return _client_instance().create_board(name, key=key, team_id=team_id)


@mcp.tool()
def get_board(board_id: int) -> dict[str, Any]:
    """Fetch a single board by its numeric id (id + name). Authorized via the
    board's own id — you must own it."""
    return _client_instance().get_board(board_id)


@mcp.tool()
def update_board(
    board_id: int,
    name: str | None = None,
    key: str | None = None,
    autosync_enabled: bool | None = None,
    autosync_advance_to_done: bool | None = None,
    outbound_webhook_url: str | None = None,
    outbound_webhook_secret: str | None = None,
    outbound_webhook_enabled: bool | None = None,
    team_id: int | None = None,
) -> dict[str, Any]:
    """Update a board's settings (only the arguments you pass are changed): ``name``;
    ``key`` (the board-local ref prefix — safe to change, since nothing about a card
    is stored per key and the canonical ``KAN-…`` ticket never moves; 422 if malformed
    or reserved, 409 if another of your boards uses it);
    the GitHub PR auto-sync opt-in — ``autosync_enabled`` (master switch; PRs mentioning
    a ticket attach links and post CI comments) and ``autosync_advance_to_done``
    (separately allow a merged PR to move the card to done; effective only while
    ``autosync_enabled`` is on); the V38 signed outbound webhook opt-in —
    ``outbound_webhook_url`` (the target), ``outbound_webhook_secret`` (the write-only
    HMAC-SHA256 key; never read back), and ``outbound_webhook_enabled`` (turn delivery
    on/off); and ``team_id`` (M9 V67) to link the board to a team you belong to (403
    otherwise) — this argument only *sets* the link, since omitted args are left
    untouched, not cleared. When enabled with a URL set, every notification is POSTed
    there, signed like the inbound GitHub webhook. Authorized via the board's own id —
    you must own it."""
    return _client_instance().update_board(
        board_id,
        name=name,
        key=key,
        autosync_enabled=autosync_enabled,
        autosync_advance_to_done=autosync_advance_to_done,
        outbound_webhook_url=outbound_webhook_url,
        outbound_webhook_secret=outbound_webhook_secret,
        outbound_webhook_enabled=outbound_webhook_enabled,
        team_id=team_id,
    )


@mcp.tool()
def delete_board(board_id: int) -> dict[str, Any]:
    """Delete a board by id; its cards + epics cascade away. Authorized via the
    board's own id — you must own it."""
    return _client_instance().delete_board(board_id)


# --- teams (M9 V69, KAN-1058; ADR 0021, ADR 0019 amendment) -----------------
#
# Five tools, mirroring the board CRUD group above 1:1 (list/create/get/update/
# delete) — the surface grows 49 -> 54, an ADR 0019 amendment (see the ADR's
# 2026-09-01 amendment note). Team *membership* management has deliberately NO
# MCP twin here, mirroring board_member (which has none either): it is a
# CLI/human-ergonomics affordance (`pandan team member add/rm/list/set-role`),
# not something an agent's normal workflow needs. Re-opening that is a further
# ADR 0019 amendment, not a side effect of a CLI card (the `label update` /
# `cycle update` precedent — see pandan-cli/tests/test_parity.py's CLI_ONLY dict).


@mcp.tool()
def list_teams(fields: list[str] | None = None) -> dict[str, Any]:
    """List the teams you are a member of. Call this to discover a ``team_id`` for
    ``create_board``/``update_board``'s ``team_id`` argument. A row also carries
    your role on the team, so pass ``fields=["id","name"]`` to shave it if you
    don't need it."""
    return shape(_client_instance().list_teams(), fields=fields)


@mcp.tool()
def create_team(name: str) -> dict[str, Any]:
    """Create a new team; you are auto-added as its **owner**-role member. Returns
    it (including its id — link a board to it with ``create_board``/
    ``update_board``'s ``team_id``)."""
    return _client_instance().create_team(name)


@mcp.tool()
def get_team(team_id: int) -> dict[str, Any]:
    """Fetch a single team by its numeric id. You must be a member (any role)."""
    return _client_instance().get_team(team_id)


@mcp.tool()
def update_team(team_id: int, name: str | None = None) -> dict[str, Any]:
    """Rename a team. Owner-role members only — 403 otherwise."""
    return _client_instance().update_team(team_id, name=name)


@mcp.tool()
def delete_team(team_id: int) -> dict[str, Any]:
    """Delete a team. Owner-role members only. Any board linked to it is
    **unclaimed** (its ``team_id`` set to null), not deleted."""
    return _client_instance().delete_team(team_id)


# --- cards + epics (board-scoped) ------------------------------------------


@mcp.tool()
def list_cards(
    board_id: int | None = None,
    refs: str | None = None,
    column: Column | None = None,
    epic_id: int | None = None,
    cycle_id: int | None = None,
    updated_since: str | None = None,
    priority: Priority | None = None,
    label: int | None = None,
    due_before: str | None = None,
    overdue: bool | None = None,
    needs_human: bool | None = None,
    backlog: bool | None = None,
    parked: bool | None = None,
    assignee: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    fields: list[str] | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """List/query stories. ``board_id`` targets one board (defaults to
    PANDAN_BOARD_ID; omit both to span all your boards). Other filters (AND-ed):
    column, epic_id, cycle_id (stories in that cycle/iteration),
    updated_since (an ISO-8601 timestamp — stories changed
    at/after it), priority, label (a label id), due_before (an ISO-8601 timestamp —
    stories due strictly before it), overdue (true → past-due and not done),
    needs_human (true → cards flagged for a human via needs_human; false → the rest),
    backlog (true → no cycle assigned — the backlog is derived, not stored; false →
    assigned to a cycle), parked (true/false — the stored "deliberately parked" flag,
    independent of backlog), and assignee (exact match). ``q`` is a free-text full-text search over
    title+description (websearch grammar: bare terms AND-ed, "quoted" = phrase,
    ``-term`` = exclude); with no explicit ``sort`` it ranks by relevance (best
    first, a title hit above a description-only hit). ``sort`` re-orders the result —
    comma-separated keys with an optional ``-`` for descending (e.g. ``-priority``,
    ``-due_date,position``; fields: position/priority/due_date/created_at/updated_at/
    story_points/assignee/title/column/id). ``priority`` sorts by rank (none→urgent);
    an explicit ``sort`` overrides ``q`` ranking. Paginate with limit; if more results
    remain the response includes ``next_cursor`` to pass back as ``cursor`` (not
    available together with ``sort`` or ``q``).

    **``refs`` reads a known set of stories in ONE call** — a comma-separated list of
    ids and/or references, e.g. ``"KAN-12,45,KAN-9"``. Use it instead of N ``get_card``
    calls whenever you already hold the refs. Capped at 100, cannot be combined with
    ``limit``/``cursor``, and any selector matching nothing is left out of ``cards``
    and named in ``unresolved`` rather than failing the call.

    Board-local references work too (``"ENG-14"``) **but only with ``board_id``**: a
    board key is unique per owner, so ``ENG-14`` names a different card for different
    people and is only decidable inside a known board. Without a board, use the
    canonical ``KAN-<n>``, which resolves from anywhere.

    **Pass ``fields``** — the keys to keep on each row, e.g.
    ``["ticket_number","title","column","assignee"]`` (aliases: ticket, pts). A full
    22-key page of a busy board costs ~9× a narrowed one; an unknown name errors and
    lists the valid ones. Descriptions are cut to 500 chars with a
    ``(truncated, N chars total …)`` hint — ``full=true`` returns them whole.
    """
    ids_param, refs_param = split_card_selectors(refs) if refs else (None, None)
    result = _client_instance().list_cards(
        board_id=_board(board_id),
        ids=ids_param,
        refs=refs_param,
        column=column,
        epic_id=epic_id,
        cycle_id=cycle_id,
        updated_since=updated_since,
        priority=priority,
        label=label,
        due_before=due_before,
        overdue=overdue,
        needs_human=needs_human,
        backlog=backlog,
        parked=parked,
        assignee=assignee,
        q=q,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    return shape(result, fields=fields, full=full)


@mcp.tool()
def list_epics(
    board_id: int | None = None,
    fields: list[str] | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """List epics. ``board_id`` targets one board (defaults to PANDAN_BOARD_ID;
    omit both to span all your boards). ``fields`` narrows each row to those keys
    (e.g. ``["ticket_number","name","progress"]``); descriptions are truncated with a
    size hint unless ``full=true``."""
    return shape(
        _client_instance().list_epics(board_id=_board(board_id)),
        fields=fields,
        full=full,
    )


@mcp.tool()
def get_card(
    card_id: int,
    fields: list[str] | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """Fetch a single story by its numeric id. ``fields`` narrows the returned keys;
    a long description is truncated with a size hint unless ``full=true`` (this
    project's own cards run to ~3.4k characters)."""
    return shape(_client_instance().get_card(card_id), fields=fields, full=full)


@mcp.tool()
def get_epic(epic_id: int, full: bool = False) -> dict[str, Any]:
    """Fetch a single epic by its numeric id. Authorized via the epic's own
    board — no ``board_id`` needed. A long description is truncated with a size hint
    unless ``full=true`` — the same cut ``list_epics`` applies, so the listing and
    this read agree about the same epic."""
    return shape(_client_instance().get_epic(epic_id), full=full)


@mcp.tool()
def create_card(
    title: str,
    board_id: int | None = None,
    description: str | None = None,
    column: Column | None = None,
    story_points: int | None = None,
    assignee: str | None = None,
    epic_id: int | None = None,
    cycle_id: int | None = None,
    priority: Priority | None = None,
    due_date: str | None = None,
    label_ids: list[int] | None = None,
    parked: bool | None = None,
) -> dict[str, Any]:
    """Create a story. Only ``title`` is required; it lands at the end of its
    column (default ``todo``). ``board_id`` targets one board (defaults to
    PANDAN_BOARD_ID; omit both to use your earliest board). ``story_points`` must
    be one of 1/2/3/5/8/13. ``epic_id`` links it to an existing epic on the same
    board; ``cycle_id`` assigns it to a cycle/iteration on the same board.
    ``priority`` is one of none/low/medium/high/urgent (default none);
    ``due_date`` is an ISO-8601 timestamp; ``label_ids`` attaches board labels
    (each must belong to the card's board — see create_label/list_labels);
    ``parked`` creates it already marked deliberately parked (default false).
    """
    return _client_instance().create_card(
        title,
        board_id=_board(board_id),
        description=description,
        column=column,
        story_points=story_points,
        assignee=assignee,
        epic_id=epic_id,
        cycle_id=cycle_id,
        priority=priority,
        due_date=due_date,
        label_ids=label_ids,
        parked=parked,
    )


@mcp.tool()
def create_cards(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch-create several stories in one call — hand it a list of card objects,
    each with the same fields as ``create_card`` (``title`` required; optional
    ``board_id``/``description``/``column``/``story_points``/``assignee``/
    ``epic_id``). Ideal for filing a whole epic's worth of stories at once: one
    tool call over a warm connection instead of N. A card that omits ``board_id``
    falls back to PANDAN_BOARD_ID (then the API default), same as ``create_card``.
    Returns ``{"created": [<card>, ...]}`` in the order given.

    **Fail-fast, not atomic:** if one card is rejected (e.g. a bad ``story_points``)
    the call errors and the cards created *before* it stay created — resubmit only
    the remainder.
    """
    resolved = []
    for card in cards:
        merged = dict(card)
        merged["board_id"] = _board(merged.get("board_id"))
        resolved.append(merged)
    return _client_instance().create_cards(resolved)


@mcp.tool()
def create_epic(
    name: str,
    board_id: int | None = None,
    description: str | None = None,
    target_date: str | None = None,
    lead: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Create an epic (a per-board grouping stories can link to via epic_id).
    ``board_id`` targets one board (defaults to PANDAN_BOARD_ID; omit both to use
    your earliest board). ``target_date`` is an optional ISO-8601 target/ship date;
    ``lead`` is an optional free-text owner (a person/agent handle). ``color``
    (M8 V63) is an optional palette token (sky/blue/cyan/fuchsia/mulberry/pink/ink)
    or hex, so cards belonging to this epic are recognisable on the board at a
    glance; omit for no colour.
    """
    return _client_instance().create_epic(
        name,
        board_id=_board(board_id),
        description=description,
        target_date=target_date,
        lead=lead,
        color=color,
    )


@mcp.tool()
def update_card(
    card_id: int,
    title: str | None = None,
    description: str | None = None,
    story_points: int | None = None,
    assignee: str | None = None,
    epic_id: int | None = None,
    cycle_id: int | None = None,
    priority: Priority | None = None,
    due_date: str | None = None,
    label_ids: list[int] | None = None,
    parked: bool | None = None,
) -> dict[str, Any]:
    """Edit a story's fields (only the arguments you pass are changed). Use
    move_card to change column/position, not this. ``priority`` re-ranks;
    ``due_date`` is an ISO-8601 timestamp; ``epic_id`` re-links the parent epic and
    ``cycle_id`` (re)assigns the cycle/iteration (both on the card's board; pass
    them to move the card, or clear with a separate call); ``label_ids``
    **replaces** the card's label set (``[]`` clears it — each id must belong to the
    card's board); ``parked`` marks/unmarks it deliberately parked (distinct from
    the backlog itself, which is derived from having no cycle). Authorized via the
    card's own board — no ``board_id`` needed.
    """
    return _client_instance().update_card(
        card_id,
        title=title,
        description=description,
        story_points=story_points,
        assignee=assignee,
        epic_id=epic_id,
        cycle_id=cycle_id,
        priority=priority,
        due_date=due_date,
        label_ids=label_ids,
        parked=parked,
    )


@mcp.tool()
def move_card(card_id: int, column: Column, position: int | None = None) -> dict[str, Any]:
    """Move a story to a column (and optionally to an index within it; omit
    ``position`` to append to the end). Authorized via the card's own board — no
    ``board_id`` needed.
    """
    return _client_instance().move_card(card_id, column, position=position)


@mcp.tool()
def claim_card(card_id: int, assignee: str) -> dict[str, Any]:
    """Claim a story in one step: move it to ``in_progress`` **and** set its
    ``assignee`` together. A convenience over calling move_card then update_card
    yourself. Returns the updated card. Authorized via the card's own board — no
    ``board_id`` needed.
    """
    return _client_instance().claim_card(card_id, assignee)


@mcp.tool()
def delete_card(card_id: int) -> dict[str, Any]:
    """Delete a story by id. Authorized via the card's own board."""
    return _client_instance().delete_card(card_id)


@mcp.tool()
def update_epic(
    epic_id: int,
    name: str | None = None,
    description: str | None = None,
    target_date: str | None = None,
    lead: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Edit an epic's fields (only the arguments you pass are changed). ``target_date``
    is an ISO-8601 target/ship date; ``lead`` is a free-text owner; ``color`` (M8 V63)
    is a palette token or hex (see ``create_epic``). Authorized via the epic's own
    board — no ``board_id`` needed.
    """
    return _client_instance().update_epic(
        epic_id,
        name=name,
        description=description,
        target_date=target_date,
        lead=lead,
        color=color,
    )


@mcp.tool()
def delete_epic(epic_id: int) -> dict[str, Any]:
    """Delete an epic by id; its child stories are detached (their epic_id is
    cleared), not deleted. Authorized via the epic's own board.
    """
    return _client_instance().delete_epic(epic_id)


# --- card-to-card dependencies (KAN-28 API / KAN-31 tools) -----------------


@mcp.tool()
def add_dependency(card_id: int, blocker_id: int) -> dict[str, Any]:
    """Mark story ``card_id`` as **blocked-by** story ``blocker_id`` (blocker_id
    must finish first). Both must be on the same board (which you own). Returns the
    now-blocked card with its refreshed ``blocked_by`` / ``blocks`` arrays.
    Authorized via the card's own board — no ``board_id`` needed. Rejected (422) on
    a self-link, a duplicate edge, or one that would create a cycle.
    """
    return _client_instance().add_dependency(card_id, blocker_id)


@mcp.tool()
def remove_dependency(card_id: int, blocker_id: int) -> dict[str, Any]:
    """Remove the blocked-by link so story ``card_id`` is no longer blocked-by
    story ``blocker_id``. Returns the card with refreshed dependency arrays.
    Authorized via the card's own board — no ``board_id`` needed. 404 if that link
    doesn't exist.
    """
    return _client_instance().remove_dependency(card_id, blocker_id)


@mcp.tool()
def list_dependencies(card_id: int) -> dict[str, Any]:
    """List a story's dependencies: ``{"card_id": id, "blocked_by": [...],
    "blocks": [...]}``. ``blocked_by`` = ids of stories that block this one (must
    finish first); ``blocks`` = ids it blocks. Reads the card itself (the API
    surfaces these arrays on the card, so ``get_card``/``list_cards`` already
    include them too). Authorized via the card's own board.
    """
    return _client_instance().list_dependencies(card_id)


# --- card work-links (KAN-32 API / KAN-34 tools) ---------------------------


@mcp.tool()
def add_link(card_id: int, label: str, url: str) -> dict[str, Any]:
    """Attach a work-link to story ``card_id`` — a ``label`` (e.g. "PR", "branch",
    "CI") and a ``url`` (the PR URL, branch, CI run, …) — closing the board↔git gap.
    Returns the card with its refreshed ``links`` array. Authorized via the card's
    own board — no ``board_id`` needed. 404 if the card doesn't exist.
    """
    return _client_instance().add_link(card_id, label, url)


@mcp.tool()
def remove_link(card_id: int, link_id: int) -> dict[str, Any]:
    """Detach work-link ``link_id`` from story ``card_id``. Returns the card with its
    refreshed ``links`` array. Authorized via the card's own board — no ``board_id``
    needed. 404 if no such link belongs to the card.
    """
    return _client_instance().remove_link(card_id, link_id)


# --- card notes / comments (KAN-33 API / KAN-34 tools) ---------------------


@mcp.tool()
def add_comment(card_id: int, body: str) -> dict[str, Any]:
    """Post a note (comment) to story ``card_id`` — human/agent-authored context
    like a decision, a handoff, or why something is blocked. The author is the
    acting user (your PAT's owner), never the body. Returns the created comment.
    Authorized via the card's own board — no ``board_id`` needed. 404 if the card
    doesn't exist.
    """
    return _client_instance().add_comment(card_id, body)


@mcp.tool()
def list_comments(
    card_id: int,
    fields: list[str] | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """List a story's notes (comments), oldest-first: ``{"comments": [...]}``. Each
    comment carries id, body, author_id, and created_at. Comments are not inlined on
    card reads (a card can accumulate many), so this is a dedicated read. Authorized
    via the card's own board — no ``board_id`` needed. ``fields`` narrows each row;
    bodies are truncated with a size hint unless ``full=true``.
    """
    return shape(_client_instance().list_comments(card_id), fields=fields, full=full)


# --- board labels (M5 V11 API / KAN-244 tools) ----------------------------
# No ``update_label`` tool, deliberately (V61, KAN-982). ``PATCH /labels/{id}`` exists
# and ``PandanClient.update_label`` wraps it, but ADR 0019 freezes this surface at 49
# tools and a rename/recolour is a *human*-ergonomics affordance: KAN-982 exists because
# a human could not manage labels without a terminal, which was never true of an agent.
# Attaching labels to cards — the thing an agent actually does — is ``label_ids`` on
# create_card/update_card and is untouched. Same call as ``me`` (KAN-614): a declined
# tool, not a missing one. Re-opening it is an ADR 0019 amendment, not an edit here;
# ``pandan-cli/tests/test_parity.py`` CLI_ONLY carries the matching entry.


@mcp.tool()
def list_labels(board_id: int | None = None) -> dict[str, Any]:
    """List a board's labels (id, name, color, usage_count — how many cards carry
    it). ``board_id`` targets one board (defaults to PANDAN_BOARD_ID). Use the
    returned ids in ``label_ids`` on create_card/update_card, or as the ``label``
    filter on list_cards."""
    resolved = _board(board_id)
    if resolved is None:
        raise ValueError("board_id is required (set PANDAN_BOARD_ID or pass board_id)")
    return _client_instance().list_labels(resolved)


@mcp.tool()
def create_label(
    name: str, color: str, board_id: int | None = None, emoji: str | None = None
) -> dict[str, Any]:
    """Create a board-scoped label — a ``name`` and a ``color`` (e.g. a hex like
    ``#0ea5e9``). ``board_id`` targets one board (defaults to PANDAN_BOARD_ID).
    ``emoji`` (M8 V64) is an optional single grapheme cluster — a second,
    independent visual dimension from colour, so two labels sharing a colour are
    still distinguishable at a glance; omit for no emoji. Returns the created
    label; attach it to cards via ``label_ids``."""
    resolved = _board(board_id)
    if resolved is None:
        raise ValueError("board_id is required (set PANDAN_BOARD_ID or pass board_id)")
    return _client_instance().create_label(resolved, name, color, emoji=emoji)


@mcp.tool()
def delete_label(label_id: int) -> dict[str, Any]:
    """Delete a label by id; it detaches from every card that carried it.
    Authorized via the label's own board — no ``board_id`` needed."""
    return _client_instance().delete_label(label_id)


# --- dispatch + fleet-safe claim (M5 V12 API / KAN-245 tools) --------------


@mcp.tool()
def dispatch(
    board_id: int | None = None,
    assignee: str | None = None,
    label: int | None = None,
    priority: Priority | None = None,
) -> dict[str, Any]:
    """Atomically claim the next ready-to-work story on a board and start it — the
    agent's "give me something to do" call. The API picks the next unblocked
    ``todo`` story (highest ``priority`` first, then board order), sets its
    ``assignee`` (defaults to you), and moves it to ``in_progress`` in one
    ``FOR UPDATE SKIP LOCKED`` transaction, so many agents can dispatch at once and
    never grab the same card. ``board_id`` targets one board (defaults to
    PANDAN_BOARD_ID). ``label`` / ``priority`` (a *minimum*) narrow the selection.
    Returns ``{"card": <story>}``, or ``{"card": null}`` when nothing is ready.
    """
    return _client_instance().dispatch(
        _require_board(board_id), assignee=assignee, label=label, priority=priority
    )


@mcp.tool(name="next")
def next_ready(
    board_id: int | None = None,
    label: int | None = None,
    priority: Priority | None = None,
) -> dict[str, Any]:
    """Peek at the next ready-to-work story on a board **without** claiming it — the
    same selection as ``dispatch`` (next unblocked ``todo`` story, highest
    ``priority`` first) but read-only, so you can see what's up next before pulling
    it. ``board_id`` targets one board (defaults to PANDAN_BOARD_ID). ``label`` /
    ``priority`` (a *minimum*) narrow the selection. Returns ``{"card": <story>}``,
    or ``{"card": null}`` when nothing is ready.
    """
    return _client_instance().next_ready(
        _require_board(board_id), label=label, priority=priority
    )


# --- needs-human handoff (M5 V13 API / KAN-246 tools) ----------------------


@mcp.tool()
def needs_human(card_id: int, attention_note: str | None = None) -> dict[str, Any]:
    """Flag story ``card_id`` as needing a human — use this when you hit something
    only a person can settle (a decision, missing access, a stuck PR). Pass an
    optional ``attention_note`` describing the ask. Returns the updated card
    (``needs_human=true``); it then shows on the board with a needs-human badge and
    is findable via ``list_cards(needs_human=true)``. A human clears it with
    ``resolve`` and typically replies via a comment — poll the card's flag +
    comments to see the resolution. Authorized via the card's own board.
    """
    return _client_instance().flag_needs_human(card_id, attention_note=attention_note)


@mcp.tool()
def resolve(card_id: int) -> dict[str, Any]:
    """Clear the needs-human flag on story ``card_id`` (``needs_human=false``, the
    attention note is cleared). The human-facing counterpart to ``needs_human``;
    typically you also add a comment explaining the resolution. Returns the updated
    card. Authorized via the card's own board — no ``board_id`` needed.
    """
    return _client_instance().resolve_card(card_id)


# --- fleet reporting / metrics (M5 V17 API / KAN-250 tools) ----------------


@mcp.tool()
def metrics(
    board_id: int | None = None,
    since: str | None = None,
    window: str | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Report derived flow metrics for a board — throughput (cards done in the
    period), cycle time (first in_progress → done: avg/median/p90 seconds), aging
    WIP (how long each in-flight card has sat in progress), and a per-assignee
    breakdown (completed + open WIP per agent). All computed from the activity feed
    + card timestamps; nothing is written. ``board_id`` targets one board (defaults
    to PANDAN_BOARD_ID). Bound the period with ``since`` (an ISO-8601 timestamp) or
    ``window`` (``7d`` / ``24h`` / ``30m``); omit both for all time. Authorized via
    the board (you must be able to read it). ``fields`` narrows the report to whole
    top-level sections (e.g. ``["throughput","cycle_time"]``) — the aging-WIP and
    per-assignee sections grow with the board, so drop the ones you won't read.
    """
    return shape(
        _client_instance().board_metrics(
            _require_board(board_id), since=since, window=window
        ),
        fields=fields,
    )


@mcp.tool()
def activity(
    board_id: int | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    fields: list[str] | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """Read a board's activity feed (KAN-18), newest-first — one row per successful
    create / update / delete / move of a card, epic or board. ``board_id`` targets
    one board (defaults to PANDAN_BOARD_ID). Optional filters (M5 V16, KAN-249,
    AND-ed): ``actor`` (exact match on an actor's email / agent handle) and
    ``action`` (the action verb — created/updated/deleted/moved/restored/…).
    Paginate with ``limit``; if more rows remain the response includes
    ``next_cursor`` to pass back as ``cursor``. Authorized via the board (you must
    be able to read it). Returns ``{"activity": [...], "next_cursor"?: str}``.
    ``fields`` narrows each row (e.g. ``["created_at","actor","action","summary"]``);
    a row's ``summary`` sentence is truncated with a size hint unless ``full=true``.
    """
    return shape(
        _client_instance().list_activity(
            _require_board(board_id),
            limit=limit,
            cursor=cursor,
            actor=actor,
            action=action,
        ),
        fields=fields,
        full=full,
    )


# --- notification inbox (V37 API / KAN-301 tools) --------------------------


@mcp.tool()
def list_notifications(
    unread: bool = False,
    fields: list[str] | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """List YOUR notification inbox (V37) — items for events a human shouldn't miss:
    a card flagged needs_human, a card newly blocked by a dependency, a linked PR's
    CI failing, or a card being assigned. Notifications are **per-user, not
    board-scoped** (no board_id): you only ever see your own, addressed to you as a
    board owner. ``unread=true`` returns only unread ones; default returns all,
    newest-first. Poll/pull only (ADR 0007 — there is no push channel; poll this).
    Returns ``{"notifications": [...]}``.

    **Pass ``fields``** (e.g. ``["id","kind","body"]``, −67%) — the inbox has no
    ``limit`` and no cursor, so it returns your whole history and only grows: 127 rows
    already cost ~14,300 tokens. Bodies truncate unless ``full=true``."""
    return shape(
        _client_instance().list_notifications(unread=unread or None),
        fields=fields,
        full=full,
    )


@mcp.tool()
def mark_read(notification_id: int) -> dict[str, Any]:
    """Mark one of YOUR notifications read (stamp its read_at); idempotent —
    re-marking leaves the timestamp untouched. 404 if it doesn't exist or isn't
    yours. Returns the updated notification."""
    return _client_instance().mark_notification_read(notification_id)


# --- saved views (M5 V14 API / KAN-247 tools) ------------------------------


@mcp.tool()
def list_views(board_id: int | None = None) -> dict[str, Any]:
    """List a board's saved views (id, name, query). ``board_id`` targets one board
    (defaults to PANDAN_BOARD_ID). A view's ``query`` is the same filter+sort grammar
    ``list_cards`` takes — spread it as ``list_cards`` args to reproduce the view's
    cards. Returns ``{"views": [...]}``."""
    return _client_instance().list_views(_require_board(board_id))


@mcp.tool()
def create_view(
    name: str, query: dict[str, Any] | None = None, board_id: int | None = None
) -> dict[str, Any]:
    """Create a saved view — a named, persisted card query on a board. ``query`` is
    the structured filter+sort grammar (any of column/epic_id/priority/label/
    due_before/overdue/needs_human/assignee/sort — same keys as ``list_cards``), e.g.
    ``{"assignee": "agent-7", "sort": "-priority"}``; omit it for an unfiltered view.
    ``board_id`` targets one board (defaults to PANDAN_BOARD_ID). Returns the created
    view."""
    return _client_instance().create_view(_require_board(board_id), name, query)


@mcp.tool()
def delete_view(view_id: int, board_id: int | None = None) -> dict[str, Any]:
    """Delete a saved view by id on a board. ``board_id`` targets one board (defaults
    to PANDAN_BOARD_ID). 404 if no such view is on that board."""
    return _client_instance().delete_view(_require_board(board_id), view_id)


# --- batch update + card templates (M5 V19, KAN-252) -----------------------


@mcp.tool()
def update_cards(updates: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch-update several cards **atomically** in one call — hand it a list of
    ``{"id": <id>, ...fields}`` objects, each taking the same field edits as
    ``update_card`` (title/description/story_points/assignee/epic_id/priority/
    due_date/label_ids; **not** column/position — use ``move_card`` for those). Hits
    ``PATCH /cards/batch``, so it is **all-or-nothing**: if any id is missing the whole
    batch fails and no card changes (unlike ``create_cards``, which is a fail-fast
    loop). Ideal for retriaging several cards at once. Returns
    ``{"updated": [<card>, ...]}`` in request order."""
    return _client_instance().update_cards(updates)


@mcp.tool()
def list_templates(board_id: int | None = None) -> dict[str, Any]:
    """List a board's card templates (id, name, cards). ``board_id`` targets one board
    (defaults to PANDAN_BOARD_ID). A template's ``cards`` is the list of card payloads
    ``apply_template`` will instantiate. Returns ``{"templates": [...]}``."""
    return _client_instance().list_templates(_require_board(board_id))


@mcp.tool()
def create_template(
    name: str, cards: list[dict[str, Any]], board_id: int | None = None
) -> dict[str, Any]:
    """Create a card template — a named, reusable plan of cards on a board. ``cards``
    is a non-empty list of card payloads (each with the same fields as ``create_card``
    minus ``board_id``: ``title`` required; optional description/column/story_points/
    assignee/epic_id/priority/due_date/label_ids). ``board_id`` targets one board
    (defaults to PANDAN_BOARD_ID). Returns the created template."""
    return _client_instance().create_template(_require_board(board_id), name, cards)


@mcp.tool()
def delete_template(template_id: int, board_id: int | None = None) -> dict[str, Any]:
    """Delete a card template by id on a board. ``board_id`` targets one board
    (defaults to PANDAN_BOARD_ID). 404 if no such template is on that board."""
    return _client_instance().delete_template(_require_board(board_id), template_id)


@mcp.tool()
def apply_template(template_id: int, board_id: int | None = None) -> dict[str, Any]:
    """Seed a plan from a template in one call: instantiate the template's cards as
    real cards on the board (atomic — all created or none). ``board_id`` targets one
    board (defaults to PANDAN_BOARD_ID). Returns ``{"created": [<card>, ...]}`` in
    template order."""
    return _client_instance().apply_template(_require_board(board_id), template_id)


# --- cycles / iterations (V33, KAN-297) ------------------------------------


@mcp.tool()
def list_cycles(board_id: int | None = None) -> dict[str, Any]:
    """List a board's cycles/iterations (id, name, starts_on, ends_on). ``board_id``
    targets one board (defaults to PANDAN_BOARD_ID). Use a cycle's id as the
    ``cycle_id`` filter on list_cards, or to assign a card via update_card. Returns
    ``{"cycles": [...]}``."""
    return _client_instance().list_cycles(_require_board(board_id))


@mcp.tool()
def create_cycle(
    name: str,
    starts_on: str | None = None,
    ends_on: str | None = None,
    board_id: int | None = None,
) -> dict[str, Any]:
    """Create a cycle/iteration — a ``name`` and optional ISO-8601 ``starts_on`` /
    ``ends_on`` bounds. ``board_id`` targets one board (defaults to PANDAN_BOARD_ID).
    Returns the created cycle; assign cards to it with update_card(card_id,
    cycle_id=<id>)."""
    return _client_instance().create_cycle(
        _require_board(board_id), name, starts_on=starts_on, ends_on=ends_on
    )


@mcp.tool()
def delete_cycle(cycle_id: int, board_id: int | None = None) -> dict[str, Any]:
    """Delete a cycle by id on a board; its cards are detached (their cycle_id is
    cleared), not deleted. ``board_id`` targets one board (defaults to
    PANDAN_BOARD_ID). 404 if no such cycle is on that board."""
    return _client_instance().delete_cycle(_require_board(board_id), cycle_id)


@mcp.tool()
def cycle_metrics(
    cycle_id: int,
    board_id: int | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Report derived burndown / velocity metrics for a cycle/iteration (V34).
    Reports committed vs completed (stories + story points), velocity (completed
    points), and a per-day burndown of remaining work over the cycle's
    starts_on..ends_on window (empty when the cycle has no dates). All computed
    from the cycle's card state + the activity feed; nothing is written.
    ``board_id`` targets one board (defaults to PANDAN_BOARD_ID). 404 if no such
    cycle is on that board; authorized via the board (you must be able to read it).
    ``fields`` narrows the report to whole top-level sections — drop ``burndown`` if
    you only want the velocity numbers, it is one row per day of the cycle.
    """
    return shape(
        _client_instance().cycle_metrics(_require_board(board_id), cycle_id),
        fields=fields,
    )


@mcp.tool()
def close_cycle(
    cycle_id: int, rollover_to: int | None = None, board_id: int | None = None
) -> dict[str, Any]:
    """Close a cycle/iteration explicitly (M8 V59, KAN-980) — rollover is a verb,
    never something that happens on its own on the cycle's ``ends_on`` date.
    Freezes the committed/completed snapshot ``cycle_metrics`` reports from now on
    (a later ``cycle_metrics`` call for this cycle stops recomputing from live
    membership, and its ``burndown`` goes empty), then moves every card still in
    the cycle and not ``done`` to ``rollover_to`` — another **open** cycle on the
    same board — or the backlog when ``rollover_to`` is omitted/``None`` (422 if
    the target is closed, cross-board, this same cycle, or doesn't exist).
    ``board_id`` targets one board (defaults to PANDAN_BOARD_ID). 404 if no such
    cycle is on that board; 409 if it's already closed. Returns
    ``{cycle_id, closed_at, rolled_over_count, rollover_to}`` — what moved, not
    the cycle itself; call ``get`` on any of its cards or ``cycle_metrics`` for
    the details.
    """
    return _client_instance().close_cycle(
        _require_board(board_id), cycle_id, rollover_to=rollover_to
    )


# --- planning intervals (M8 V57, KAN-978) -----------------------------------
# Exactly two tools: reading is what an agent plausibly wants. Creating/renaming/
# deleting a planning interval is a human planning-setup action (the same
# disposition `update_cycle` already has — see the `("cycle", "update")` entry in
# `pandan-cli/tests/test_parity.py`'s CLI_ONLY dict), so it stays CLI-only
# (`pandan pi create/update/delete`). This is a tool-COUNT addition against the
# ADR 0019 freeze (54 → 56) — see the amendment note in
# docs/adr/0019-mcp-surface-right-sizing.md.


@mcp.tool()
def list_planning_intervals(board_id: int | None = None) -> dict[str, Any]:
    """List a board's planning intervals — a grouping one level above the cycle,
    e.g. a quarter containing several sprints (id, name, starts_on, ends_on).
    ``board_id`` targets one board (defaults to PANDAN_BOARD_ID). Use a planning
    interval's id as the ``planning_interval_id`` filter on ``list_cycles``, or
    to (re)assign a cycle via the CLI's ``cycle update --pi``. Returns
    ``{"planning_intervals": [...]}``, matching ``list_cycles``'s own shape (no
    ``fields`` narrowing — this list is small and unshaped like that one)."""
    return _client_instance().list_planning_intervals(_require_board(board_id))


@mcp.tool()
def planning_interval_metrics(
    planning_interval_id: int,
    board_id: int | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Report the rolled-up committed/completed/velocity metrics across a
    planning interval's member cycles (M8 V57, KAN-978) — a **sum**, not a
    series: unlike ``cycle_metrics`` there is no ``burndown`` field, because a
    per-cycle day-by-day series doesn't compose across member cycles into
    anything meaningful. All computed from each member cycle's own metrics;
    nothing is written. ``board_id`` targets one board (defaults to
    PANDAN_BOARD_ID). 404 if no such planning interval is on that board;
    authorized via the board (you must be able to read it). A planning interval
    with no member cycles reports all zeros.
    """
    return shape(
        _client_instance().planning_interval_metrics(
            _require_board(board_id), planning_interval_id
        ),
        fields=fields,
    )


# --- V49: shrink what every session pays for the schemas above --------------

# Runs once at import, after every ``@mcp.tool()`` above has registered. Drops the
# Pydantic-generated ``title`` noise and flattens safely collapsible nullable
# ``anyOf``s in the schemas clients are *shown* — ~16% of the resident cost, for no
# change in behaviour (the validator is a separate object; see schema.py).
_COMPACTED_TOOL_COUNT = compact_advertised_schemas(mcp)


def main() -> None:
    """Entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
