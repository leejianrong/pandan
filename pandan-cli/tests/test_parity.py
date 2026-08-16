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
   explicitly classified ``CLI_ONLY`` verb. That dict carries **two** reasons, spelled
   out at its definition: a verb about the CLI's own installation (config/login/
   context/overview), or a board-API verb deliberately left out of the ADR-0019-frozen
   MCP surface (``me``, since KAN-614).
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

**A third limitation, found by KAN-614 and worth naming because the card assumed
otherwise:** "parity in both directions" here means *between the two client surfaces*.
Neither direction can see an API endpoint that **neither** surface exposes.
``GET /api/v1/me`` shipped in KAN-530 and no CLI verb wrapped it for months; this file
stayed green throughout, and had to — ``cli_leaf_paths()`` enumerates verbs that exist,
so a verb that was never written is not an unclassified one. Section 1 catches a tool
with no verb; section 2 catches a verb with no tool; **nothing here reads
``/api/v1``**. Closing that would take a third input (the OpenAPI schema, or
``PandanClient``'s public methods) — see the KAN-614 PR body for a sketch and why it
was reported rather than built inside a one-verb card.

Parity is about **capability, not spelling**. ``dispatch`` and ``next`` both map to
``pandan next`` (one flag apart), and ``claim_card`` maps to ``pandan claim`` — a
many-to-one mapping is fine; an unmapped tool is not.

## Section 0 (KAN-592): the parser proves itself before anything is concluded from it

Everything below section 0 is a statement about a set this file *parsed out of another
file's text*, so an empty parse makes all of it true and none of it meaningful. The
original cross-check — tool names counted against raw ``@mcp.tool(`` decorators — was
built for exactly that and was still blind in one direction, because **both counts were
derived from the string ``mcp``**: rename the server variable and 0 == 0 passes. Only
``test_the_mcp_surface_is_still_the_frozen_49``'s hardcoded ``49`` caught it, which is a
constant doing the work of a design.

The generalisable rule, and the reason this is documented rather than quietly patched:
**a non-emptiness proof must not share an input with the thing whose non-emptiness it
proves.** Two counts derived from the same regex target are one count. So the proof is
now anchored on ``_SERVER_BINDING_RE``, which reads the decorator target out of
``server.py``'s binding line and is the only thing here that does not hardcode ``mcp``;
section 0 runs both mutations in-process so the guard is watched failing on every CI run
rather than in a PR description.
"""
from __future__ import annotations

import argparse
import pathlib
import re

import pytest

from pandan_cli import cli

MCP_SERVER = pathlib.Path(__file__).resolve().parents[2] / "mcp" / "pandan_mcp" / "server.py"

#: The variable ``server.py`` binds its server object to, and therefore the name every
#: ``@<target>.tool()`` decorator carries. Both regexes below hardcode it, which is the
#: whole reason this file needs the anchor two definitions down (KAN-592).
DECORATOR_TARGET = "mcp"

# ``@mcp.tool()`` / ``@mcp.tool(name="next")`` followed by the decorated ``def``. The
# explicit ``name=`` wins, because that is the name the tool is advertised under (only
# ``next_ready`` uses it today, published as ``next``).
_TOOL_RE = re.compile(
    rf"^@{DECORATOR_TARGET}\.tool\((?:\s*name\s*=\s*[\"'](?P<alias>[^\"']+)[\"']\s*)?\)\s*\n"
    r"(?:@[^\n]*\n)*"
    r"def\s+(?P<func>\w+)\s*\(",
    re.MULTILINE,
)

_DECORATOR_RE = re.compile(rf"^@{DECORATOR_TARGET}\.tool\(", re.MULTILINE)

# **The anchor (KAN-592), and the one thing here that does NOT mention ``mcp``.** The
# server binding — ``mcp = MCPServer("pandan")``, ``FastMCP`` before SDK 2.0.0 (KAN-585)
# — names its own variable, so it is the one place in ``server.py`` that can tell this
# file what the decorators are actually called. Anchored on the *class*, matched at line
# start so the ``from mcp.server import MCPServer`` line cannot satisfy it.
_SERVER_BINDING_RE = re.compile(
    r"^(?P<var>\w+)\s*=\s*(?:MCPServer|FastMCP)\s*\(", re.MULTILINE
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

# CLI verbs with no MCP twin. **Two distinct reasons live here and each entry has to
# say which**, because a classification whose stated rationale does not describe its
# contents is the same defect family section 0 above exists to prevent — an exemption
# that reads as covered when it is merely filed:
#
# 1. **Local installation.** The verb touches this machine's files — a config file, the
#    packaged skill, the CLI's own front door — so there is nothing on ``/api/v1`` for
#    an MCP tool to wrap. Not a parity gap in the direction ADR 0005 cares about (the
#    API is still the only way to change board state); it is the CLI having a front
#    door and a config file.
# 2. **A board-API call deliberately out of scope for the frozen MCP surface.** A tool
#    *could* wrap it, and one is not being added: ADR 0019 froze the surface at 49
#    tools and ``mcp/tests/test_schema.py`` pins that by name **and** by count, so
#    adding one is an ADR amendment rather than a side effect of a CLI card. An entry
#    of this kind is a recorded *decision*, not an absence, and must say so — otherwise
#    it is indistinguishable from the parity gap ``MCP_ONLY`` is asserted empty to
#    forbid, only pointing the other way.
#
# Until KAN-614 this dict held nothing but reason 1, and the comment said so. ``me`` is
# the first reason-2 entry, so the rationale was widened in the same diff rather than
# slipping an entry in under a sentence that did not describe it.
CLI_ONLY: dict[tuple[str, ...], str] = {
    ("overview",): "the CLI's content-first bare invocation (V46) — board state, no new capability",
    ("login",): "writes the local config file; a PAT never travels over MCP",
    # Reason 2 — the only one, so far.
    ("me",): (
        "reason 2 (KAN-614): `GET /api/v1/me` IS a board API call, so this is a "
        "declined tool and not a missing one. No `me` tool is added because ADR 0019 "
        "freezes the MCP surface at 49; an MCP client also never needs it, since every "
        "other `/api/v1` route already knows the caller and the CLI is where the "
        "question is asked (a human or an agent checking `did my token work?`). "
        "Re-opening this is an ADR 0019 amendment, not an edit here."
    ),
    ("config", "set"): "local config file",
    ("config", "unset"): "local config file (issue #277)",
    ("config", "show"): "local config file",
    ("config", "path"): "local config file",
    ("context", "install"): "installs the packaged skill / SessionStart hook (V48)",
    ("context", "uninstall"): "removes them",
    ("context", "show"): "renders the ambient session block",
    ("context", "status"): "reports the installed skill's provenance (KAN-505)",
}


def _parse_tool_names(source: str) -> set[str]:
    """The advertised tool names, parsed out of ``server.py``'s text (no import).

    Split from :func:`mcp_tool_names` so the guards below can be *run against a mutated
    copy of the source* — see
    ``test_the_non_vacuity_proof_survives_renaming_the_decorator_target``.

    **The non-vacuity proof is three assertions deep, and their ORDER is the fix
    KAN-592 shipped.** The original had one cross-check — tool names counted against
    raw ``@mcp.tool(`` decorators — and it was blind in the one direction it was built
    to cover, because *both* counts were derived from the string ``mcp``. Rename the
    server variable and the tool regex matches 0, the decorator count is 0, ``0 == 0``
    passes, ``MCP_TOOLS`` is empty, and every subset assertion below holds trivially:
    the whole file goes green while asserting nothing. It was saved only by
    ``test_the_mcp_surface_is_still_the_frozen_49``'s hardcoded constant — by luck, not
    by its own design.

    The general rule, which is why this is documented rather than just patched: **a
    non-emptiness proof must not share an input with the thing whose non-emptiness it
    proves.** Two counts derived from the same regex target are one count.

    So, in order:

    1. **The anchor.** ``_SERVER_BINDING_RE`` reads the decorator target out of the
       binding line, which is the only statement in ``server.py`` that names that
       variable without being a ``@mcp.`` decorator. A rename now fails *here*, naming
       the new variable and the two regexes to update — an actionable message instead of
       a silent zero. Deliberately an assertion rather than an adaptation: this file
       building its regexes from whatever it found would keep passing through a rename,
       which is the same "it says so, therefore it is" the docstring at the top rejects.
    2. **Non-emptiness**, before any comparison, so an empty parse fails as *parsed
       nothing* rather than as *the counts agree*.
    3. **The cross-check**, which is now only being asked the question it is good at:
       did the tool-name regex miss a decorator whose *shape* changed?
    """
    # 1. the anchor — independent of the name both regexes below hardcode.
    binding = _SERVER_BINDING_RE.search(source)
    assert binding, (
        f"found no `<var> = MCPServer(...)` binding in {MCP_SERVER.name}, so this file "
        "cannot confirm what its `@<target>.tool(` regexes should be matching. If the "
        "SDK renamed the server class again (FastMCP → MCPServer was SDK 2.0.0, "
        "KAN-585), add the new name to _SERVER_BINDING_RE."
    )
    assert binding.group("var") == DECORATOR_TARGET, (
        f"{MCP_SERVER.name} binds its server to `{binding.group('var')}`, but this "
        f"file matches `@{DECORATOR_TARGET}.tool(` — so it would parse ZERO tools and "
        "every assertion below would pass vacuously (KAN-592). Set DECORATOR_TARGET to "
        f"`{binding.group('var')}`, or rename it back in server.py."
    )

    names = {m.group("alias") or m.group("func") for m in _TOOL_RE.finditer(source)}
    decorators = len(_DECORATOR_RE.findall(source))

    # 2. parsed *something* — proven before anything is compared to anything.
    assert decorators, (
        f"parsed NOTHING from {MCP_SERVER.name}: zero `@{DECORATOR_TARGET}.tool(` "
        "decorators. Every parity assertion in this file would hold trivially over an "
        "empty set, so this is a failure, not a pass (KAN-592)."
    )

    # 3. the cross-check, in its remaining useful direction: a decorator whose SHAPE
    #    the tool-name regex cannot read (a new form, or one reflowed across lines).
    assert len(names) == decorators, (
        f"parsed {len(names)} tool names from {decorators} @{DECORATOR_TARGET}.tool "
        "decorators — the regex missed one (a new decorator form?), so every assertion "
        "below is unsound"
    )
    return names


def mcp_server_source() -> str:
    if not MCP_SERVER.is_file():
        pytest.skip(f"{MCP_SERVER} not present — CLI-only checkout")
    return MCP_SERVER.read_text(encoding="utf-8")


def mcp_tool_names() -> set[str]:
    """The advertised tool names of the real ``server.py``."""
    return _parse_tool_names(mcp_server_source())


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


# --- 0. the parser is sound before anything is concluded from it -------------
# KAN-592. Everything below section 0 is a statement about a set this file *parsed*, so
# a parse that silently returns ``set()`` makes all of it true and none of it meaningful.
# These two tests are the mutations run by hand when the hole was found, kept in-process
# so they run on every CI run rather than living in a PR description.


def test_the_non_vacuity_proof_survives_renaming_the_decorator_target():
    """**The mutation that used to pass.** Rename ``mcp`` in ``server.py`` and, before
    KAN-592, the tool regex matched 0, the raw decorator count was 0, the cross-check
    asserted ``0 == 0``, and the file went green over an empty set — saved only by
    ``test_the_mcp_surface_is_still_the_frozen_49``'s hardcoded ``49``, i.e. by a
    constant rather than by its own non-vacuity design.

    Both halves are asserted, because the first is what makes the second non-trivial:
    the mutated source really does defeat the regexes (0 names, 0 decorators), and the
    parse fails anyway — on the anchor, which is the only thing in this file that reads
    the decorator target out of ``server.py`` instead of hardcoding it."""
    source = mcp_server_source()
    renamed = source.replace(
        f"{DECORATOR_TARGET} = MCPServer(", "server = MCPServer("
    ).replace(f"@{DECORATOR_TARGET}.tool(", "@server.tool(")

    # A mutation that mutated nothing would make this test as vacuous as the hole it
    # pins — the same lesson, one level up.
    assert renamed != source, "the rename mutation found nothing to rename"
    assert not _TOOL_RE.findall(renamed), "the mutation did not actually defeat the regex"
    assert not _DECORATOR_RE.findall(renamed), "the mutation did not zero the cross-check"

    with pytest.raises(AssertionError) as excinfo:
        _parse_tool_names(renamed)
    # Named the right thing: the rename, not "the counts agree".
    assert "binds its server to `server`" in str(excinfo.value)


def test_an_empty_parse_fails_as_parsed_nothing_and_not_as_counts_agree():
    """The floor beneath the anchor: a server whose decorators vanished for some *other*
    reason (a form the regexes cannot read at all) must fail as ``parsed NOTHING``, so
    ``0 == 0`` can never be the sentence that lets an empty set through."""
    with pytest.raises(AssertionError) as excinfo:
        _parse_tool_names(f'{DECORATOR_TARGET} = MCPServer("pandan")\n')
    assert "parsed NOTHING" in str(excinfo.value)
    assert "would hold trivially over an empty set" in str(excinfo.value)


def test_a_reshaped_decorator_still_fails_the_cross_check():
    """The direction the original cross-check *did* cover, kept: a decorator the
    tool-name regex cannot read (here, reflowed across lines) is a mismatch, not a
    silent omission. This is the assertion the anchor above did not replace."""
    source = mcp_server_source()
    reshaped = source.replace(
        f"@{DECORATOR_TARGET}.tool()\ndef warmup(",
        f"@{DECORATOR_TARGET}.tool(\n)\ndef warmup(",
        1,
    )
    assert reshaped != source, "the reshape mutation found nothing to reshape"
    with pytest.raises(AssertionError) as excinfo:
        _parse_tool_names(reshaped)
    assert "the regex missed one" in str(excinfo.value)


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
