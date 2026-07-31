"""``pandan`` — card / board / epic CRUD over the Pandan API (KAN-22, KAN-23).

Framework choice: **stdlib ``argparse``** with subparsers. No new dependency —
consistent with the repo's thin ethos (the MCP server likewise leans on the SDK +
httpx and nothing else). ``typer``/``click`` would buy nicer help/colour but add a
dependency for a handful of subcommands; not worth it here.

Card verbs are top-level (``pandan list``/``create``/…); boards and epics are nested
groups (``pandan board list``, ``pandan epic create``) so their verbs don't collide with
the card verbs — parity with the board/epic surface of ``/api/v1`` (KAN-23).

The CLI is a thin adapter over the shared ``PandanClient``: parse args → env
config → one client call → print. ``--json`` prints the client's raw dict (for
``pandan list --json | jq …``); otherwise a concise ``ticket  column  title  pts=N``
line (``pts=-`` when unestimated, reading the API's ``story_points``).

Exit codes (for scripting):
    0  success
    1  general / config / non-mapped API error
    2  usage error (argparse's own convention)
    3  401 unauthorized (bad/missing token)
    4  403 forbidden (board isn't yours)
    5  404 not found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from typing import Any

from pandan_client import PandanApiError, PandanClient

from . import build_info
from .config import (
    DEFAULT_API_URL,
    Config,
    ConfigError,
    config_file_path,
    find_mcp_json,
    load_config,
    resolve_values,
    write_config_file,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2  # argparse's own convention; documented here for completeness.
EXIT_AUTH = 3
EXIT_FORBIDDEN = 4
EXIT_NOT_FOUND = 5

_STATUS_EXIT = {401: EXIT_AUTH, 403: EXIT_FORBIDDEN, 404: EXIT_NOT_FOUND}

COLUMNS = ("todo", "in_progress", "done")
PRIORITIES = ("none", "low", "medium", "high", "urgent")

# Fallback color for `label create` when neither the positional nor --color is
# given (KAN-288). A neutral slate so an unspecified label still renders sensibly;
# the API requires a non-empty color string.
DEFAULT_LABEL_COLOR = "#64748b"


# --- output helpers ---------------------------------------------------------


def _emit(result: Any, *, as_json: bool, noun: str = "card") -> None:
    """Print a command result: raw JSON when ``--json``, else a human summary.

    ``noun`` (``card``/``epic``/``board``) only disambiguates the delete summary,
    whose result dict (``{"deleted": id}``) is otherwise shape-identical across
    entities; everything else is detected from the result's shape.
    """
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    print(_humanize(result, noun=noun))


def _humanize(result: Any, *, noun: str = "card") -> str:
    """Render a client result as concise human text (one entity per line)."""
    if isinstance(result, dict) and "cards" in result:  # list_cards
        cards = result["cards"]
        if not cards:
            return "(no cards)"
        lines = [_card_line(c) for c in cards]
        if result.get("next_cursor"):
            lines.append(f"(more — next cursor: {result['next_cursor']})")
        return "\n".join(lines)
    if isinstance(result, dict) and "boards" in result:  # list_boards
        boards = result["boards"]
        return "\n".join(_board_line(b) for b in boards) if boards else "(no boards)"
    if isinstance(result, dict) and "epics" in result:  # list_epics
        epics = result["epics"]
        return "\n".join(_epic_line(e) for e in epics) if epics else "(no epics)"
    # list_labels returns ``{"labels": [...]}``. Guard with ``"ticket_number" not
    # in result`` because a single ``CardRead`` also *carries* a ``labels`` array
    # (alongside its ``ticket_number``); without this, ``get``/``create``/``update``/
    # ``move`` (which all return one card) would match here and print ``(no labels)``
    # instead of the card line (KAN-277). A label-LIST response never has a ticket.
    if isinstance(result, dict) and "labels" in result and "ticket_number" not in result:
        labels = result["labels"]
        return "\n".join(_label_line(la) for la in labels) if labels else "(no labels)"
    if isinstance(result, dict) and "views" in result:  # list_views
        views = result["views"]
        return "\n".join(_view_line(v) for v in views) if views else "(no views)"
    if isinstance(result, dict) and "templates" in result:  # list_templates
        templates = result["templates"]
        return (
            "\n".join(_template_line(t) for t in templates)
            if templates
            else "(no templates)"
        )
    if isinstance(result, dict) and "cycles" in result:  # list_cycles
        cycles = result["cycles"]
        return "\n".join(_cycle_line(c) for c in cycles) if cycles else "(no cycles)"
    if isinstance(result, dict) and "notifications" in result:  # list_notifications
        rows = result["notifications"]
        return (
            "\n".join(_notification_line(n) for n in rows)
            if rows
            else "(no notifications)"
        )
    if isinstance(result, dict) and "activity" in result:  # list_activity
        rows = result["activity"]
        if not rows:
            return "(no activity)"
        lines = [_activity_line(r) for r in rows]
        if result.get("next_cursor"):
            lines.append(f"(more — next cursor: {result['next_cursor']})")
        return "\n".join(lines)
    if isinstance(result, dict) and "comments" in result:  # list_comments
        comments = result["comments"]
        return "\n".join(_comment_line(c) for c in comments) if comments else "(no comments)"
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
        return _comment_line(result)
    # A single notification (mark_read) carries ``kind`` (distinctive — nothing else
    # does) + ``body``; matched before the generic branches below.
    if isinstance(result, dict) and "kind" in result and "body" in result:
        return _notification_line(result)
    if isinstance(result, dict) and "card" in result:  # dispatch / next (peek/claim)
        card = result["card"]
        return _card_line(card) if card else "(no card ready)"
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
    # A single entity: epics/boards carry ``name`` (no ``title``); cards carry
    # ``title``. Epics additionally have a ``ticket_number`` (``EPIC-…``).
    if isinstance(result, dict) and "name" in result and "title" not in result:
        return _epic_line(result) if "ticket_number" in result else _board_line(result)
    if isinstance(result, dict) and "ticket_number" in result:  # a single card
        return _card_line(result)
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
    human output (KAN-269). The ticket/column/title prefix is unchanged."""
    return "\t".join(
        (
            str(card.get("ticket_number", card.get("id", "?"))),
            str(card.get("column", "")),
            str(card.get("title", "")),
            _fmt_points(card.get("story_points")),
        )
    )


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
            str(epic.get("name", "")),
            _fmt_progress(epic),
        )
    )


def _board_line(board: dict[str, Any]) -> str:
    """One concise line for a board: id, name (tab-separated)."""
    return "\t".join((str(board.get("id", "?")), str(board.get("name", ""))))


def _label_line(label: dict[str, Any]) -> str:
    """One concise line for a label: id, name, color (tab-separated)."""
    return "\t".join(
        (
            str(label.get("id", "?")),
            str(label.get("name", "")),
            str(label.get("color", "")),
        )
    )


def _view_line(view: dict[str, Any]) -> str:
    """One concise line for a saved view: id, name, its query as compact JSON."""
    return "\t".join(
        (
            str(view.get("id", "?")),
            str(view.get("name", "")),
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
            str(cycle.get("name", "")),
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
            str(tmpl.get("name", "")),
            f"{len(cards)} cards",
        )
    )


def _activity_line(row: dict[str, Any]) -> str:
    """One concise line for an activity row: timestamp, actor, action, summary."""
    return "\t".join(
        (
            str(row.get("ts", "")),
            str(row.get("actor_label") or "-"),
            str(row.get("action", "")),
            str(row.get("summary", "")),
        )
    )


def _notification_line(n: dict[str, Any]) -> str:
    """One concise line for a notification (V37, KAN-301): id, kind, read/unread
    state, body (tab-separated)."""
    return "\t".join(
        (
            str(n.get("id", "?")),
            str(n.get("kind", "")),
            "read" if n.get("read_at") else "unread",
            str(n.get("body", "")),
        )
    )


def _warmup_line(result: dict[str, Any]) -> str:
    """One concise line for a warmup result: the status, plus any detail.

    ``ok`` → the API is awake; ``waking``/``error`` carry a ``detail`` explaining
    what to do next (call again shortly / what failed)."""
    status = str(result.get("status", "?"))
    if status == "ok":
        return "ok\tAPI is awake"
    detail = result.get("detail")
    return f"{status}\t{detail}" if detail else status


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
    for item in aging.get("items", []):
        assignee = item.get("assignee") or "(unassigned)"
        lines.append(
            f"  {item.get('ticket_number', '?')}\t{assignee}\t"
            f"{_fmt_duration(item.get('age_seconds'))}"
        )
    by_assignee = result.get("by_assignee", [])
    if by_assignee:
        lines.append("by assignee:")
        for row in by_assignee:
            who = row.get("assignee") or "(unassigned)"
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


def _comment_line(comment: dict[str, Any]) -> str:
    """One concise line for a comment: id, created_at, body (tab-separated)."""
    return "\t".join(
        (
            str(comment.get("id", "?")),
            str(comment.get("created_at", "")),
            str(comment.get("body", "")),
        )
    )


def _link_line(link: dict[str, Any]) -> str:
    """One concise line for a work-link: id, label, url (tab-separated)."""
    return "\t".join(
        (
            str(link.get("id", "?")),
            str(link.get("label", "")),
            str(link.get("url", "")),
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


# --- board resolution -------------------------------------------------------


def _resolve_board(arg_board: int | None, config: Config) -> int | None:
    """The per-call ``--board`` wins, else ``PANDAN_BOARD_ID``, else None (let the
    API apply its own fallback). Mirrors the MCP server's ``_board`` helper."""
    return arg_board if arg_board is not None else config.board_id


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
        raise ConfigError(f"expected a numeric id or a KAN-/EPIC- ticket, got {raw!r}")
    return None, f"{m.group(1).upper()}-{m.group(2)}"


def _resolve_card_id(client: PandanClient, raw: str | int) -> int:
    """Resolve a card id-or-ticket to its numeric DB id (KAN-285). A bare integer is
    returned as-is (no request); a ``KAN-<n>`` ticket is looked up via the query API
    (paging its keyset cursor) and matched on ``ticket_number``."""
    id_, ticket = _parse_id_or_ticket(raw)
    if id_ is not None:
        return id_
    if not ticket.startswith("KAN-"):
        raise ConfigError(f"{ticket} is not a card ticket (cards are KAN-…)")
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
            raise ConfigError(f"no card found with ticket {ticket}")


def _resolve_epic_id(client: PandanClient, raw: str | int) -> int:
    """Resolve an epic id-or-ticket to its numeric DB id (KAN-285). A bare integer is
    returned as-is; an ``EPIC-<n>`` ticket is looked up via ``list_epics`` and
    matched on ``ticket_number``."""
    id_, ticket = _parse_id_or_ticket(raw)
    if id_ is not None:
        return id_
    if not ticket.startswith("EPIC-"):
        raise ConfigError(f"{ticket} is not an epic ticket (epics are EPIC-…)")
    for epic in client.list_epics(board_id=None).get("epics", []):
        if str(epic.get("ticket_number", "")).upper() == ticket:
            return int(epic["id"])
    raise ConfigError(f"no epic found with ticket {ticket}")


def _resolve_epic_opt(client: PandanClient, raw: str | int | None) -> int | None:
    """Resolve an optional ``--epic`` value (``None`` stays ``None``)."""
    return None if raw is None else _resolve_epic_id(client, raw)


# --- command handlers -------------------------------------------------------
# Each returns the client's result dict; printing + exit codes are handled centrally.


def _cmd_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_cards(
        board_id=_resolve_board(args.board, config),
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
        raise ConfigError(
            f"refusing to delete card {args.card_id} without confirmation; pass --yes"
        )
    return client.delete_card(_resolve_card_id(client, args.card_id))


def _cmd_next(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Peek at (or, with ``--claim``, atomically dispatch) the next ready card on a
    board (M5 V12, KAN-245). Both need a board — the dispatch endpoints are
    path-scoped with no API-side fallback."""
    board = _resolve_board(args.board, config)
    if board is None:
        raise ConfigError("a board is required; pass --board or set PANDAN_BOARD_ID")
    if args.claim:
        return client.dispatch(
            board, assignee=args.assignee, label=args.label, priority=args.priority
        )
    return client.next_ready(board, label=args.label, priority=args.priority)


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
        raise ConfigError("a board is required; pass --board or set PANDAN_BOARD_ID")
    return client.board_metrics(board, since=args.since, window=args.window)


def _cmd_activity(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    """Read a board's activity feed (KAN-18), newest-first (M5 V16, KAN-261). The
    activity endpoint is path-scoped with no API-side fallback, so a board is
    required (``--board`` or PANDAN_BOARD_ID)."""
    board = _resolve_board(args.board, config)
    if board is None:
        raise ConfigError("a board is required; pass --board or set PANDAN_BOARD_ID")
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


# --- epic handlers ----------------------------------------------------------
# Epics are board-scoped, so list/create honour --board / PANDAN_BOARD_ID.


def _cmd_epic_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_epics(board_id=_resolve_board(args.board, config))


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
        raise ConfigError(
            f"refusing to delete epic {args.epic_id} without confirmation; pass --yes"
        )
    return client.delete_epic(_resolve_epic_id(client, args.epic_id))


# --- label handlers ---------------------------------------------------------
# Labels are board-scoped: list/create honour --board / PANDAN_BOARD_ID; delete
# is addressed by the label's own id (authorized via its board).


def _cmd_label_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    board = _resolve_board(args.board, config)
    if board is None:
        raise ConfigError("a board is required; pass --board or set PANDAN_BOARD_ID")
    return client.list_labels(board)


def _cmd_label_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    board = _resolve_board(args.board, config)
    if board is None:
        raise ConfigError("a board is required; pass --board or set PANDAN_BOARD_ID")
    # KAN-288: color accepts either the positional or the --color flag (flag wins),
    # falling back to a neutral default so it can be omitted entirely.
    color = args.color_opt or args.color_pos or DEFAULT_LABEL_COLOR
    return client.create_label(board, args.name, color)


def _cmd_label_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise ConfigError(
            f"refusing to delete label {args.label_id} without confirmation; pass --yes"
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
        raise ConfigError("a board is required; pass --board or set PANDAN_BOARD_ID")
    return board


def _cmd_view_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_views(_require_view_board(args, config))


def _cmd_view_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.create_view(
        _require_view_board(args, config), args.name, _build_view_query(client, args)
    )


def _cmd_view_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise ConfigError(
            f"refusing to delete view {args.view_id} without confirmation; pass --yes"
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
        raise ConfigError(
            f"refusing to delete cycle {args.cycle_id} without confirmation; pass --yes"
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
        raise ConfigError(f"invalid JSON: {exc}") from exc


def _cmd_batch_update(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    updates = _load_json_arg(args.updates)
    if not isinstance(updates, list):
        raise ConfigError("batch-update expects a JSON array of {id, ...fields} objects")
    return client.update_cards(updates)


def _cmd_template_list(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    return client.list_templates(_require_view_board(args, config))


def _cmd_template_create(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    cards = _load_json_arg(args.cards)
    if not isinstance(cards, list):
        raise ConfigError("template create expects a JSON array of card objects for --cards")
    return client.create_template(_require_view_board(args, config), args.name, cards)


def _cmd_template_delete(client: PandanClient, config: Config, args: argparse.Namespace) -> Any:
    if not args.yes:
        raise ConfigError(
            f"refusing to delete template {args.template_id} without confirmation; pass --yes"
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
        "config_file": str(config_file_path()),
        "mcp_json": str(mcp) if mcp else None,
    }
    if getattr(args, "as_json", False):
        print(json.dumps(out, indent=2))
    else:
        for key, val in out.items():
            print(f"{key}\t{val}")
    return EXIT_OK


def _validate_board_id_arg(raw: str | None) -> None:
    if raw is not None and raw.strip() and not raw.strip().lstrip("-").isdigit():
        raise ConfigError(f"--board-id must be an integer, got {raw!r}")


def _cmd_config_set(args: argparse.Namespace) -> int:
    """Write api_url/board_id/token to the user config file (0600). ``--token-stdin``
    reads the PAT from stdin so it never lands in argv / shell history."""
    _validate_board_id_arg(args.board_id)
    token: str | None = None
    if getattr(args, "token_stdin", False):
        token = sys.stdin.readline().strip()
        if not token:
            print("pandan: no token read from stdin", file=sys.stderr)
            return EXIT_ERROR
    elif args.token is not None:
        token = args.token
    if args.api_url is None and args.board_id is None and token is None:
        print(
            "pandan: nothing to set (pass --api-url / --board-id / --token[-stdin])",
            file=sys.stderr,
        )
        return EXIT_ERROR
    path = write_config_file(api_url=args.api_url, token=token, board_id=args.board_id)
    print(f"wrote {path}")
    return EXIT_OK


def _cmd_login(args: argparse.Namespace) -> int:
    """Save a PAT to the config file. Prompts (hidden) on a TTY, else reads one line
    from stdin — so the token never appears on the command line."""
    _validate_board_id_arg(args.board_id)
    if getattr(args, "token_stdin", False) or not sys.stdin.isatty():
        token = sys.stdin.readline().strip()
    else:
        import getpass

        token = getpass.getpass("Paste your Pandan PAT (pandan_pat_…): ").strip()
    if not token:
        print("pandan: no token provided", file=sys.stderr)
        return EXIT_ERROR
    path = write_config_file(api_url=args.api_url, token=token, board_id=args.board_id)
    print(f"saved token to {path} (mode 0600)")
    return EXIT_OK


# --- argument parser --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pandan",
        description="Manage Pandan cards, boards, and epics from the command line.",
        epilog=(
            "Configuration keys (api_url / token / board_id), resolved per value in\n"
            "this order — first non-empty wins:\n"
            "  1. env vars   PANDAN_API_URL / PANDAN_TOKEN / PANDAN_BOARD_ID\n"
            "  2. config file  ~/.config/pandan/config.toml  (see `pandan login`)\n"
            "  3. .mcp.json    nearest up the tree, .mcpServers.pandan.env.*\n"
            "So the PAT can stay in a file and never touch the command line. Run\n"
            "`pandan login` once to save it; `pandan config show` prints the effective config.\n"
            "\n"
            "Exit codes: 0 ok, 1 error, 2 usage, 3 unauthorized, 4 forbidden, 5 not found."
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
    # A shared parent so --json works before OR after the subcommand
    # (e.g. `pandan --json list` and `pandan list --json` both parse).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        # SUPPRESS so an absent subcommand-level --json does not clobber a global
        # `pandan --json <cmd>` already parsed by the main parser below.
        default=argparse.SUPPRESS,
        help=(
            "print the raw JSON from the API (for piping, e.g. | jq). List verbs return "
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

    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

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
            "--sort=-priority,position. Fields: position/priority/due_date/"
            "created_at/updated_at/story_points/assignee/title/column/id"
        ),
    )
    p_list.add_argument("--limit", type=int, help="max cards to return")
    p_list.set_defaults(func=_cmd_list)

    p_get = sub.add_parser("get", parents=[common], help="get a single card by id")
    p_get.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_get.set_defaults(func=_cmd_get)

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
    p_create.set_defaults(func=_cmd_create)

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
    p_update.set_defaults(func=_cmd_update)

    p_move = sub.add_parser("move", parents=[common], help="move a card to a column")
    p_move.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_move.add_argument("column", choices=COLUMNS)
    p_move.add_argument("--position", type=int, help="index within the column (default: append)")
    p_move.set_defaults(func=_cmd_move)

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
    p_next.set_defaults(func=_cmd_next)

    # --- needs-human handoff (M5 V13, KAN-246) -------------------------------
    p_needs_human = sub.add_parser(
        "needs-human", parents=[common], help="flag a card as needing a human"
    )
    p_needs_human.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_needs_human.add_argument("--note", help="an optional note describing the ask")
    p_needs_human.set_defaults(func=_cmd_needs_human)

    p_resolve = sub.add_parser(
        "resolve", parents=[common], help="clear a card's needs-human flag"
    )
    p_resolve.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
    p_resolve.set_defaults(func=_cmd_resolve)

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
    p_notify_list.set_defaults(func=_cmd_notify_list, noun="notification")

    p_notify_read = notify_sub.add_parser(
        "read", parents=[common], help="mark a notification read by id"
    )
    p_notify_read.add_argument(
        "notification_id", type=int, metavar="ID", help="a notification id"
    )
    p_notify_read.set_defaults(func=_cmd_notify_read, noun="notification")

    # --- board subcommands (nested group; parity with /api/v1/boards) --------
    p_board = sub.add_parser("board", help="manage boards (list / create)")
    board_sub = p_board.add_subparsers(
        dest="board_command", metavar="<subcommand>", required=True
    )

    p_board_list = board_sub.add_parser("list", parents=[common], help="list your boards")
    p_board_list.set_defaults(func=_cmd_board_list, noun="board")

    p_board_create = board_sub.add_parser("create", parents=[common], help="create a board")
    p_board_create.add_argument("name")
    p_board_create.set_defaults(func=_cmd_board_create, noun="board")

    # --- epic subcommands (nested group; parity with /api/v1/epics) ----------
    p_epic = sub.add_parser("epic", help="manage epics (list / create / update / delete)")
    epic_sub = p_epic.add_subparsers(
        dest="epic_command", metavar="<subcommand>", required=True
    )

    p_epic_list = epic_sub.add_parser("list", parents=[common], help="list / query epics")
    p_epic_list.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_epic_list.set_defaults(func=_cmd_epic_list, noun="epic")

    p_epic_create = epic_sub.add_parser("create", parents=[common], help="create an epic")
    p_epic_create.add_argument("name")
    p_epic_create.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_epic_create.add_argument("--description")
    p_epic_create.add_argument(
        "--target-date", dest="target_date", metavar="ISO",
        help="a target/ship date (ISO-8601 timestamp)",
    )
    p_epic_create.add_argument("--lead", help="a free-text owner (person/agent handle)")
    p_epic_create.set_defaults(func=_cmd_epic_create, noun="epic")

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
    p_template_apply.set_defaults(func=_cmd_template_apply, noun="template")

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

    p_config = sub.add_parser("config", help="inspect / set the config file (set / show / path)")
    config_sub = p_config.add_subparsers(
        dest="config_command", metavar="<subcommand>", required=True
    )

    p_config_set = config_sub.add_parser(
        "set", parents=[common], help="write api_url / board_id / token to the config file"
    )
    p_config_set.add_argument("--api-url")
    p_config_set.add_argument("--board-id")
    token_grp = p_config_set.add_mutually_exclusive_group()
    token_grp.add_argument(
        "--token", help="the PAT (discouraged — ends up in shell history; prefer --token-stdin)"
    )
    token_grp.add_argument(
        "--token-stdin", action="store_true", help="read the PAT from stdin (keeps it out of argv)"
    )
    p_config_set.set_defaults(local_func=_cmd_config_set)

    p_config_show = config_sub.add_parser(
        "show", parents=[common], help="print the effective config (token redacted)"
    )
    p_config_show.set_defaults(local_func=_cmd_config_show)

    p_config_path = config_sub.add_parser(
        "path", parents=[common], help="print the config file path"
    )
    p_config_path.set_defaults(local_func=_cmd_config_path)

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
    p_comment_add.set_defaults(func=_cmd_comment_add)

    p_comment_list = comment_sub.add_parser(
        "list", parents=[common], help="list a card's notes, oldest-first"
    )
    p_comment_list.add_argument(
        "card_id", type=_id_or_ticket_arg, metavar="CARD",
        help="a card id or KAN-<n> ticket",
    )
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


def run(argv: Sequence[str] | None = None) -> int:
    """Parse args, dispatch, print, and return an exit code (no ``sys.exit``)."""
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(_normalize_sort_argv(raw_argv))

    # Local commands (login / config …) touch only the config file — no token, no
    # client, no network. Dispatch them before resolving or requiring config.
    local_func = getattr(args, "local_func", None)
    if local_func is not None:
        try:
            return local_func(args)
        except ConfigError as exc:
            print(f"pandan: {exc}", file=sys.stderr)
            return EXIT_ERROR

    try:
        # warmup hits the public /api/health, so it doesn't need a token.
        config = load_config(require_token=getattr(args, "require_token", True))
    except ConfigError as exc:
        print(f"pandan: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        with PandanClient(config.api_url, config.token) as client:
            result = args.func(client, config, args)
    except ConfigError as exc:  # e.g. delete without --yes
        print(f"pandan: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except PandanApiError as exc:
        print(f"pandan: {exc}", file=sys.stderr)
        return _STATUS_EXIT.get(exc.status_code, EXIT_ERROR)
    except Exception as exc:  # network/timeout/unexpected — keep it clean for scripts
        print(f"pandan: {exc}", file=sys.stderr)
        return EXIT_ERROR

    # ``noun`` defaults to "card" (card verbs are top-level and set no noun);
    # the board/epic subparsers set it so the delete summary reads correctly.
    _emit(result, as_json=args.as_json, noun=getattr(args, "noun", "card"))
    # warmup never throws (a still-waking/failed server is a status, not an
    # exception), so it maps that status to a scripting-friendly exit code:
    # 0 when awake, 1 otherwise (retry the CI pre-step / investigate).
    if getattr(args, "is_warmup", False):
        return EXIT_OK if result.get("status") == "ok" else EXIT_ERROR
    return EXIT_OK
