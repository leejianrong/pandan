#!/usr/bin/env python
"""Measure what an MCP **read result** costs a model, before and after KAN-501.

Why this exists. ADR 0019 (V49) measured the *resident* cost of the 49 tool schemas
at 7,388 ``o200k_base`` tokens and then found the expensive thing somewhere else
entirely: one ``list_cards`` against the live 121-card Roadmap board returns ~44,900
tokens **in a single tool result**, 5.1× the whole schema surface. Its decomposition
said the cost is *field breadth* (121 rows × 22 keys, 1,111 null/empty values
serialized), not pretty-printing. KAN-501 acts on that, and this script is the
before/after evidence — the payload counterpart of
``measure_tool_schema_tokens.py``.

Method
------
* **Unit.** ``o200k_base`` via ``tiktoken`` — the same yardstick V47 and ADR 0019
  used, so every number in this project's token measurements is comparable. Not
  Claude's tokenizer; a consistent proxy, not a billing figure.
* **What is counted.** The tool-result *text a client shows the model*. That is not
  our JSON: the SDK serializes a tool’s return value with
  ``pydantic_core.to_json(result, fallback=str, indent=2)``
  (``mcp/server/mcpserver/utilities/func_metadata.py:572`` in SDK 2.0.0 — verified,
  not assumed), so the baseline row is produced by calling **that exact function**
  rather than ``json.dumps``.
* **The shaping is the production code.** Every post-KAN-501 row is produced by
  ``pandan_mcp.shaping.shape`` — the function the tools call. V49 learned this the
  hard way: its first harness kept a private copy of the compaction rule and would
  have over-reported the saving. A measurement that re-implements what it measures
  is measuring itself.
* **Success is asserted, never assumed.** Both modes fail loudly and non-zero. The
  capture asserts every read returned its expected envelope with rows in it; the
  measurement asserts the fixture has the shape it claims. ADR 0019 records a
  per-task measurement that counted a CLI **usage error** as a cheap successful
  result — short output reads as cheap, so this flaw class always biases toward the
  answer you were hoping for.

Run it
------
Capture a real payload once (needs a PAT — from ``PANDAN_TOKEN``/``PANDAN_API_URL``
in the environment, or ``--credentials`` pointing at a TOML file such as the CLI's
``~/.config/pandan/config.toml``; the token is never printed or logged)::

    cd mcp && uv run --with tiktoken python scripts/measure_read_payload_tokens.py \
        --capture /path/to/roadmap.json --board 5

Then measure offline, as often as you like::

    cd mcp && uv run --with tiktoken python scripts/measure_read_payload_tokens.py \
        --payload /path/to/roadmap.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pydantic_core

from pandan_mcp.shaping import shape

#: The narrowed field set each read is measured with — "what a task actually needs",
#: not a minimum. Cards keep the five ADR 0019 used, so the two measurements line up.
NARROW_FIELDS: dict[str, list[str]] = {
    "list_cards": ["ticket_number", "title", "column", "assignee", "priority"],
    "get_card": ["ticket_number", "title", "column", "description"],
    "list_epics": ["ticket_number", "name", "progress", "health"],
    "activity": ["ts", "actor_label", "action", "summary"],
    "metrics": ["throughput", "cycle_time"],
    # KAN-517's two additions. `list_notifications` is the one that mattered: the
    # inbox takes no `limit` and returns no cursor (backend/app/routers/
    # notifications.py:32-44), so it hands back the caller's entire history and only
    # grows — 127 rows measured at 14,326 tokens, 1.8× the whole resident surface.
    "list_notifications": ["id", "kind", "body"],
    "list_boards": ["id", "name"],
}

#: Envelope key each captured read must carry, so a capture that silently returned
#: something else (an error body, an empty object) cannot be measured as if it were
#: a page of rows. ``None`` = a single object, asserted non-empty instead.
EXPECTED_ENVELOPE: dict[str, str | None] = {
    "list_cards": "cards",
    "get_card": None,
    "list_epics": "epics",
    "activity": "activity",
    "metrics": None,
    "list_notifications": "notifications",
    "list_boards": "boards",
}


def _encoder():
    import tiktoken

    return tiktoken.get_encoding("o200k_base")


def _sdk_render(payload: Any) -> str:
    """Exactly what the SDK puts in the model’s context for a dict-returning tool."""
    return pydantic_core.to_json(payload, fallback=str, indent=2).decode()


def _compact_render(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), default=str)


# --- capture ----------------------------------------------------------------


def _credentials(path: Path | None) -> tuple[str, str]:
    """``(api_url, token)`` from the environment, else from a TOML file.

    The file may be flat or use a single ``[table]`` (the CLI's config uses ``[kan]``
    /``[pandan]``), and only ``api_url``/``token`` are read from it. The token is
    returned, never printed — nothing downstream logs it.
    """
    from pandan_mcp.config import load_config

    config = load_config()
    if config.token:
        return config.api_url, config.token
    if path is None:
        raise SystemExit(
            "no credentials: set PANDAN_API_URL + PANDAN_TOKEN, or pass "
            "--credentials <file.toml> (e.g. ~/.config/pandan/config.toml)"
        )
    import tomllib

    data = tomllib.loads(path.expanduser().read_text(encoding="utf-8"))
    tables = [data] + [v for v in data.values() if isinstance(v, dict)]
    for table in tables:
        token = str(table.get("token") or "").strip()
        if token:
            return str(table.get("api_url") or config.api_url).strip(), token
    raise SystemExit(f"no `token` key found in {path}")


def capture(out: Path, board_id: int, credentials: Path | None) -> None:
    """Fetch one real payload per read tool and write them to ``out``.

    Every read is asserted: the client raises ``PandanApiError`` on any non-2xx, and
    each result is then checked for its expected envelope **with rows in it**, so an
    authorized-but-empty board cannot be measured as a cheap read.
    """
    from pandan_client import PandanClient

    api_url, token = _credentials(credentials)
    client = PandanClient(api_url, token)

    reads = {
        "list_cards": lambda: client.list_cards(board_id=board_id),
        "list_epics": lambda: client.list_epics(board_id=board_id),
        "activity": lambda: client.list_activity(board_id, limit=20),
        "metrics": lambda: client.board_metrics(board_id),
        # Neither of these is board-scoped: the inbox is per-user and the board list
        # is the account's. Captured here anyway because they are read tools whose
        # payload this measures, and the ``--board`` argument simply does not apply.
        "list_notifications": lambda: client.list_notifications(),
        "list_boards": lambda: client.list_boards(),
    }
    captured: dict[str, Any] = {}
    for name, call in reads.items():
        captured[name] = call()  # raises PandanApiError on any non-2xx
        _assert_shape(name, captured[name])
        print(f"  {name}: ok", file=sys.stderr)

    first = captured["list_cards"]["cards"][0]
    card_id = first["id"]
    captured["get_card"] = client.get_card(card_id)
    _assert_shape("get_card", captured["get_card"])
    print(f"  get_card({card_id}): ok", file=sys.stderr)

    out.write_text(
        json.dumps({"board_id": board_id, "reads": captured}, indent=2), encoding="utf-8"
    )
    print(f"captured {len(captured)} reads from board {board_id} → {out}", file=sys.stderr)


def _assert_shape(name: str, payload: Any) -> None:
    """Fail loudly unless ``payload`` really is the read it claims to be."""
    if not isinstance(payload, dict) or not payload:
        raise SystemExit(f"{name}: expected a non-empty object, got {type(payload).__name__}")
    envelope = EXPECTED_ENVELOPE[name]
    if envelope is None:
        return
    rows = payload.get(envelope)
    if not isinstance(rows, list) or not rows:
        raise SystemExit(
            f"{name}: expected a non-empty {envelope!r} list; got "
            f"{type(rows).__name__} with {len(rows) if isinstance(rows, list) else '?'} rows. "
            "Measuring an empty read would report a fake saving."
        )


# --- measure ----------------------------------------------------------------


def _rows(payload: Any, name: str) -> int:
    envelope = EXPECTED_ENVELOPE[name]
    return len(payload[envelope]) if envelope else 1


def measure(fixture: dict[str, Any], enc) -> None:
    reads = fixture["reads"]
    print(f"MCP read-result cost, o200k_base tokens (board {fixture['board_id']})")
    header = (
        f"{'read':19s} {'rows':>5s} {'BEFORE':>9s} {'default':>9s} "
        f"{'narrowed':>9s} {'saving':>8s}"
    )
    print(header)
    print("-" * len(header))

    totals = {"before": 0, "default": 0, "narrowed": 0}
    for name, payload in reads.items():
        _assert_shape(name, payload)
        fields = NARROW_FIELDS[name]
        before = len(enc.encode(_sdk_render(payload)))
        default = len(enc.encode(_sdk_render(shape(payload))))
        narrowed = len(enc.encode(_sdk_render(shape(payload, fields=fields))))
        if narrowed >= before and _rows(payload, name) > 1:
            raise SystemExit(
                f"{name}: narrowing did not shrink the payload ({narrowed} >= {before}). "
                "Either the fields are wrong or shaping is a no-op — do not report this "
                "as a saving."
            )
        totals["before"] += before
        totals["default"] += default
        totals["narrowed"] += narrowed
        pct = (narrowed - before) / before * 100
        print(
            f"{name:19s} {_rows(payload, name):5d} {before:9d} {default:9d} "
            f"{narrowed:9d} {pct:7.0f}%"
        )
    pct = (totals["narrowed"] - totals["before"]) / totals["before"] * 100
    print("-" * len(header))
    print(
        f"{'TOTAL':19s} {'':5s} {totals['before']:9d} {totals['default']:9d} "
        f"{totals['narrowed']:9d} {pct:7.0f}%"
    )

    cards = reads["list_cards"]
    fields = NARROW_FIELDS["list_cards"]
    print("\nDecomposition of the one `list_cards` page (ADR 0019's table, re-run):")
    for label, text in (
        ("as shipped before KAN-501 (SDK indent=2)", _sdk_render(cards)),
        ("same fields, compact JSON", _compact_render(cards)),
        ("KAN-501 default (truncated only)", _sdk_render(shape(cards))),
        (f"narrowed to {len(fields)} fields, indent=2", _sdk_render(shape(cards, fields=fields))),
        ("narrowed, compact", _compact_render(shape(cards, fields=fields))),
    ):
        print(f"  {len(enc.encode(text)):7d}  {label}")

    keys = {k for row in cards["cards"] if isinstance(row, dict) for k in row}
    nulls = sum(
        1
        for row in cards["cards"]
        if isinstance(row, dict)
        for value in row.values()
        if value is None or value == [] or value == ""
    )
    print(f"\n  {len(cards['cards'])} rows × {len(keys)} keys; {nulls} null/empty values")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, help="fetch a real payload to this file")
    parser.add_argument("--payload", type=Path, help="measure a previously captured file")
    parser.add_argument("--board", type=int, default=5, help="board id to capture (default 5)")
    parser.add_argument(
        "--credentials", type=Path, help="TOML file holding api_url/token, if not in the env"
    )
    args = parser.parse_args()

    if args.capture:
        capture(args.capture, args.board, args.credentials)
        if not args.payload:
            return
    if not args.payload:
        parser.error("give --payload <file> to measure (and/or --capture <file> to fetch one)")
    fixture = json.loads(args.payload.read_text(encoding="utf-8"))
    measure(fixture, _encoder())


if __name__ == "__main__":
    main()
