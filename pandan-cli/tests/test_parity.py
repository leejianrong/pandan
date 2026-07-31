"""CLI ↔ MCP parity, asserted **in both directions** — KAN-502.

## Why this file exists at all

The claim "the CLI and MCP are at full parity" was written in prose, believed, and then
inherited: the packaged skill asserted it in bold while documenting a `curl` workaround
for a missing verb forty lines below, and KAN-432's card repeated it as an established
fact. ADR 0019 falsified it by driving both surfaces from source, and rejected its
best-scoring option — a single exec-`pandan` tool, −96% resident schema — because making
the CLI the only surface would have deleted four capabilities the CLI could not reach.

So a prose note saying "parity now holds" is worth exactly nothing here; it is the
specific artefact that caused the problem. This file asserts the mapping **mechanically**,
so the claim cannot rot into a lie the way the last one did.

## What it asserts, and what it deliberately does not

Three things, and they are the whole contract:

1. **MCP ⊆ CLI** — every tool in ``mcp/pandan_mcp/server.py`` maps to a CLI invocation
   that reaches the same capability. ``MCP_ONLY`` records the exceptions and is asserted
   **empty**; before this slice it would have held ``update_board``, ``delete_board``,
   ``claim_card`` and ``create_cards``.
2. **CLI ⊆ MCP** — every leaf verb the parser accepts is either a mapped twin or an
   explicitly classified ``CLI_ONLY`` local verb (config/login/context/overview, which
   are about the CLI's own installation and have no board API behind them).
3. **The mapping names verbs that exist** — each argv path is resolved against the real
   ``build_parser()``, so an entry cannot describe a verb nobody implemented.

**It does not import ``pandan_mcp``.** ``pandan-cli`` must not depend on ``mcp/`` — that
would invert the dependency direction and couple two packages the repo keeps separate on
purpose. The tool names are read out of ``server.py`` as **text**, the same technique
``mcp/tests/test_prepush_hook.py`` uses to test a file from another part of the tree, and
the file's absence is a skip rather than a failure (a wheel/PyInstaller build of the CLI
carries no ``mcp/``).

**Honest limitation, stated rather than papered over:** CI's ``cli`` job is filtered on
``pandan-cli/**``, so a PR that adds an MCP tool and touches nothing here will not run
this test. That hole is covered from the other side: ``mcp/tests/test_schema.py`` pins the
49-tool surface by name *and* count (ADR 0019's freeze), so adding a tool fails there
first and forces the ADR amendment in which the CLI-parity question gets asked. The two
guards compose; neither alone is sufficient, and this docstring is the place that says so.
Adding ``mcp/pandan_mcp/server.py`` to the ``cli`` paths filter would close it directly
and is left as a follow-up (it is a ``.github/`` change).

Parity is about **capability, not spelling**. ``dispatch`` and ``next`` both map to
``pandan next`` (one flag apart), and ``claim_card`` maps to ``pandan claim`` — a
many-to-one mapping is fine; an unmapped tool is not.
"""
from __future__ import annotations

import argparse
import pathlib
import re

import pytest

from pandan_cli import cli

MCP_SERVER = pathlib.Path(__file__).resolve().parents[2] / "mcp" / "pandan_mcp" / "server.py"

# ``@mcp.tool()`` / ``@mcp.tool(name="next")`` followed by the decorated ``def``. The
# explicit ``name=`` wins, because that is the name the tool is advertised under (only
# ``next_ready`` uses it today, published as ``next``).
_TOOL_RE = re.compile(
    r"^@mcp\.tool\((?:\s*name\s*=\s*[\"'](?P<alias>[^\"']+)[\"']\s*)?\)\s*\n"
    r"(?:@[^\n]*\n)*"
    r"def\s+(?P<func>\w+)\s*\(",
    re.MULTILINE,
)

# Every MCP tool → the CLI argv path reaching the same capability. Keys are asserted
# against the parsed server surface, values against the real parser, so neither side can
# drift silently. The four entries KAN-502 added are marked.
MCP_TO_CLI: dict[str, tuple[str, ...]] = {
    # ops
    "warmup": ("warmup",),
    # boards
    "list_boards": ("board", "list"),
    "create_board": ("board", "create"),
    "get_board": ("board", "get"),        # KAN-502
    "update_board": ("board", "update"),  # KAN-502 — was MCP-only
    "delete_board": ("board", "delete"),  # KAN-502 — was MCP-only
    # cards
    "list_cards": ("list",),
    "get_card": ("get",),
    "create_card": ("create",),
    "create_cards": ("batch-create",),  # KAN-502 — was N invocations
    "update_card": ("update",),
    "update_cards": ("batch-update",),
    "move_card": ("move",),
    "claim_card": ("claim",),  # KAN-502 — was `move` + `update`, non-atomic
    "delete_card": ("delete",),
    # epics
    "list_epics": ("epic", "list"),
    "get_epic": ("epic", "get"),  # KAN-502 (a verb gap, not a capability gap)
    "create_epic": ("epic", "create"),
    "update_epic": ("epic", "update"),
    "delete_epic": ("epic", "delete"),
    # relations / links / notes
    "add_dependency": ("dep", "add"),
    "remove_dependency": ("dep", "rm"),
    "list_dependencies": ("dep", "list"),
    "add_link": ("link", "add"),
    "remove_link": ("link", "rm"),
    "add_comment": ("comment", "add"),
    "list_comments": ("comment", "list"),
    # labels
    "list_labels": ("label", "list"),
    "create_label": ("label", "create"),
    "delete_label": ("label", "delete"),
    # dispatch / handoff — `dispatch` is `next --claim`, one flag from `next`
    "dispatch": ("next",),
    "next": ("next",),
    "needs_human": ("needs-human",),
    "resolve": ("resolve",),
    # reporting
    "metrics": ("metrics",),
    "activity": ("activity",),
    "cycle_metrics": ("cycle", "metrics"),
    # notifications
    "list_notifications": ("notify", "list"),
    "mark_read": ("notify", "read"),
    # saved views
    "list_views": ("view", "list"),
    "create_view": ("view", "create"),
    "delete_view": ("view", "delete"),
    # templates
    "list_templates": ("template", "list"),
    "create_template": ("template", "create"),
    "delete_template": ("template", "delete"),
    "apply_template": ("template", "apply"),
    # cycles
    "list_cycles": ("cycle", "list"),
    "create_cycle": ("cycle", "create"),
    "delete_cycle": ("cycle", "delete"),
}

# MCP tools with no CLI route. **Asserted empty** — that assertion IS the deliverable of
# KAN-502's acceptance criterion. An entry here is a documented parity gap, and ADR 0019
# forbids one existing silently: it is the condition that blocks "let the CLI be the
# surface" (option (b)) from being reconsidered.
MCP_ONLY: dict[str, str] = {}

# CLI verbs with no MCP twin, each because it touches the *local installation* rather
# than the board API — there is nothing on ``/api/v1`` for an MCP tool to wrap. This is
# not a parity gap in the direction ADR 0005 cares about (the API is still the only way
# to change board state); it is the CLI having a front door and a config file.
CLI_ONLY: dict[tuple[str, ...], str] = {
    ("overview",): "the CLI's content-first bare invocation (V46) — board state, no new capability",
    ("login",): "writes the local config file; a PAT never travels over MCP",
    ("config", "set"): "local config file",
    ("config", "show"): "local config file",
    ("config", "path"): "local config file",
    ("context", "install"): "installs the packaged skill / SessionStart hook (V48)",
    ("context", "uninstall"): "removes them",
    ("context", "show"): "renders the ambient session block",
    ("context", "status"): "reports the installed skill's provenance (KAN-505)",
}


def mcp_tool_names() -> set[str]:
    """The advertised tool names, read from ``server.py`` as text (no import)."""
    if not MCP_SERVER.is_file():
        pytest.skip(f"{MCP_SERVER} not present — CLI-only checkout")
    source = MCP_SERVER.read_text(encoding="utf-8")
    names = {m.group("alias") or m.group("func") for m in _TOOL_RE.finditer(source)}
    # The regex is the weak link in this file, so it is checked against a second,
    # independent count of the decorator — the same cross-check ADR 0019 used to
    # establish "the surface is 49 tools, not 48".
    decorators = len(re.findall(r"^@mcp\.tool\(", source, re.MULTILINE))
    assert len(names) == decorators, (
        f"parsed {len(names)} tool names from {decorators} @mcp.tool decorators — the "
        "regex missed one (a new decorator form?), so every assertion below is unsound"
    )
    return names


def cli_leaf_paths() -> set[tuple[str, ...]]:
    """Every argv path the parser accepts as a complete command, e.g. ``("board",
    "update")``. Walks the real ``build_parser()``, so it cannot go stale."""

    def walk(parser: argparse.ArgumentParser, path: tuple[str, ...]):
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not actions:
            yield path
            return
        for action in actions:
            for name, sub in action.choices.items():
                yield from walk(sub, (*path, name))

    return set(walk(cli.build_parser(), ()))


# --- 1. MCP ⊆ CLI ------------------------------------------------------------


def test_every_mcp_tool_has_a_cli_route():
    """The direction that was broken, and the reason ADR 0019 could not take option (b)."""
    tools = mcp_tool_names()
    unclassified = tools - set(MCP_TO_CLI) - set(MCP_ONLY)
    assert not unclassified, (
        f"MCP tool(s) {sorted(unclassified)} have no CLI mapping and are not recorded as "
        "a gap. Add the CLI verb (preferred — the CLI is where new capability lands, "
        "ADR 0019 §Decision) or record it in MCP_ONLY with a reason."
    )
    stale = set(MCP_TO_CLI) - tools
    assert not stale, f"MCP_TO_CLI names tool(s) the server no longer exposes: {sorted(stale)}"


def test_there_are_no_mcp_only_capabilities():
    """**KAN-502's acceptance criterion, as an assertion rather than a claim.** Four
    entries would have sat here before this slice: ``update_board``, ``delete_board``,
    ``claim_card``, ``create_cards``. Emptying this dict is what "parity in both
    directions" means, and re-adding one is the ADR-0019-blocking event."""
    assert MCP_ONLY == {}


# --- 2. CLI ⊆ MCP ------------------------------------------------------------


def test_every_cli_verb_is_either_an_mcp_twin_or_a_classified_local_verb():
    mapped = set(MCP_TO_CLI.values())
    unclassified = cli_leaf_paths() - mapped - set(CLI_ONLY)
    assert not unclassified, (
        f"CLI verb(s) {sorted(unclassified)} are neither an MCP twin nor a classified "
        "local verb. Map them in MCP_TO_CLI, or add them to CLI_ONLY with the reason "
        "there is no board-API capability behind them."
    )


def test_the_local_verb_list_does_not_go_stale():
    """CLI_ONLY must describe verbs that exist — otherwise a renamed verb quietly turns
    into an 'unclassified' one nobody notices, and its exemption lives on."""
    leaves = cli_leaf_paths()
    missing = set(CLI_ONLY) - leaves
    assert not missing, f"CLI_ONLY names verb(s) that no longer exist: {sorted(missing)}"
    # A local verb must not also be claimed as an MCP twin — the two sets are disjoint.
    assert not set(CLI_ONLY) & set(MCP_TO_CLI.values())


# --- 3. the mapping describes reality ----------------------------------------


def test_every_mapped_cli_path_exists_in_the_parser():
    """Without this, the table above could assert parity against verbs nobody wrote —
    which is precisely the failure mode ("it says so, therefore it is") this file exists
    to end."""
    leaves = cli_leaf_paths()
    for tool, path in sorted(MCP_TO_CLI.items()):
        assert path in leaves, (
            f"{tool} maps to `pandan {' '.join(path)}`, which the parser has no route for"
        )


def test_the_four_gaps_kan_502_closed_are_reachable():
    """Named explicitly, so the slice's deliverable is legible in the test names and a
    later refactor that drops one of these verbs fails with the reason attached."""
    leaves = cli_leaf_paths()
    for path in [
        ("board", "get"),
        ("board", "update"),   # gap 1: board rename + the V38 outbound-webhook opt-in
        ("board", "delete"),   # gap 1
        ("claim",),            # gap 2: an atomic claim of a CHOSEN card
        ("batch-create",),     # gap 3: N creates in one invocation
        ("epic", "get"),       # gap 4 (a verb gap only)
    ]:
        assert path in leaves, f"`pandan {' '.join(path)}` is gone — KAN-502 regressed"


def test_the_mcp_surface_is_still_the_frozen_49():
    """ADR 0019 froze the surface at 49 tools; ``mcp/tests/test_schema.py`` is the
    authoritative pin. Restating the count here is what makes the ``cli`` job notice a
    *removal* on the MCP side, which is the direction that would break parity from the
    other end — and it keeps this file's own mapping honest about its scope."""
    assert len(mcp_tool_names()) == 49
