"""The V49 freeze (ADR 0019): the tool surface is pinned, and the schema
compaction that pays for keeping it is proven cosmetic.

Two jobs, and they are different:

* **The pin** — the surface is frozen at exactly these 49 tools. This is a
  *decision* guard, not a correctness one: it exists so that adding a tool is a
  deliberate act with an ADR amendment behind it, rather than something that
  happens by appending a decorator.
* **The compaction guards** — ``pandan_mcp.schema`` rewrites the schema clients
  are shown. Every test below that touches it is there to prove the rewrite
  cannot change behaviour, because "it only affects the advertised schema" is an
  assertion about FastMCP internals and deserves to be pinned rather than
  trusted.
"""
from __future__ import annotations

import asyncio
import json

from mcp.server.fastmcp.tools.base import Tool

from pandan_mcp.schema import COLLAPSIBLE_SIBLING_KEYS, compact_schema
from pandan_mcp.server import mcp

#: **The V49 freeze.** Bare tool names (the agent sees ``mcp__pandan__<name>``;
#: the ``mcp__pandan__`` prefix comes from the client's ``mcpServers`` key, not
#: from here). ADR 0019 measured this surface at 8,775 ``o200k_base`` tokens
#: resident and kept it *as a frozen fallback* for consumers that cannot run the
#: CLI. New capability goes in the CLI.
FROZEN_TOOLS = frozenset(
    {
        "list_boards", "create_board", "get_board", "update_board", "delete_board",
        "list_cards", "get_card", "create_card", "create_cards", "update_card",
        "update_cards", "move_card", "claim_card", "delete_card",
        "list_epics", "get_epic", "create_epic", "update_epic", "delete_epic",
        "add_dependency", "remove_dependency", "list_dependencies",
        "add_link", "remove_link",
        "add_comment", "list_comments",
        "list_labels", "create_label", "delete_label",
        "dispatch", "next", "needs_human", "resolve",
        "metrics", "activity",
        "list_notifications", "mark_read",
        "list_views", "create_view", "delete_view",
        "list_templates", "create_template", "delete_template", "apply_template",
        "list_cycles", "create_cycle", "delete_cycle", "cycle_metrics",
        "warmup",
    }
)

FROZEN_TOOL_COUNT = 49

_WHY_FROZEN = """
The MCP tool surface is FROZEN at {count} tools by ADR 0019 (V49) — this failure is
by design, not a stale fixture to update.

V49 measured the surface at 8,775 o200k_base tokens of schema that load into EVERY
agent session before it does any work, and deliberately kept the breadth as the
documented fallback for consumers that cannot run the CLI (e.g. the ghcr image,
which ships no CLI binary). The price of keeping it is that it does not grow: new
board capability lands in the `pandan` CLI, which costs a session nothing until it
is used.

If you are ADDING a tool: that is an ADR amendment, not a test edit. Say why the
CLI cannot serve the need, update docs/adr/0019-mcp-surface-right-sizing.md, and
change FROZEN_TOOLS + FROZEN_TOOL_COUNT in the same PR.

If you are REMOVING a tool: check the CLI actually covers the capability first.
ADR 0005 forbids a silent parity regression, and as of V49 the CLI could NOT reach
update_board or delete_board.
""".strip()


def _tools():
    return asyncio.run(mcp.list_tools())


def _by_name():
    return {tool.name: tool for tool in _tools()}


# --- the pin ---------------------------------------------------------------


def test_the_surface_is_frozen_at_exactly_these_tools():
    live = {tool.name for tool in _tools()}
    added = sorted(live - FROZEN_TOOLS)
    removed = sorted(FROZEN_TOOLS - live)
    assert live == FROZEN_TOOLS, (
        f"{_WHY_FROZEN.format(count=FROZEN_TOOL_COUNT)}\n\n"
        f"Added (not in the frozen set): {added or 'none'}\n"
        f"Removed (missing from the server): {removed or 'none'}"
    )


def test_the_frozen_count_is_pinned_independently_of_the_name_set():
    """Pin the *number* as well as the names. A same-size swap (one tool renamed)
    is caught by the set test; this one catches the frozen set itself being
    edited to accommodate a new tool without anyone noticing the total moved."""
    assert len(FROZEN_TOOLS) == FROZEN_TOOL_COUNT, (
        f"FROZEN_TOOLS has {len(FROZEN_TOOLS)} entries but FROZEN_TOOL_COUNT says "
        f"{FROZEN_TOOL_COUNT}. {_WHY_FROZEN.format(count=FROZEN_TOOL_COUNT)}"
    )
    assert len(_tools()) == FROZEN_TOOL_COUNT, _WHY_FROZEN.format(
        count=FROZEN_TOOL_COUNT
    )


# --- the compaction is provably cosmetic -----------------------------------


def _raw_tool(tool):
    """Rebuild a tool from its own function to recover the schema FastMCP would
    have advertised *before* compaction (``Tool.from_function`` regenerates it
    from the signature — see mcp/server/fastmcp/tools/base.py:77)."""
    return Tool.from_function(tool.fn, name=tool.name)


def test_compaction_changes_no_tool_name():
    """The headline safety property: this is a schema rewrite, not a rename."""
    assert {t.name for t in _tools()} == {
        _raw_tool(t).name for t in mcp._tool_manager.list_tools()
    }


def test_compaction_preserves_every_property_name_and_required_set():
    """Argument *identity* is untouched — no argument is added, removed or
    renamed, and nothing becomes newly optional or newly mandatory."""
    for tool in mcp._tool_manager.list_tools():
        raw = _raw_tool(tool).parameters
        live = tool.parameters
        assert set(live.get("properties", {})) == set(raw.get("properties", {})), (
            f"{tool.name}: compaction changed the argument names"
        )
        assert live.get("required", []) == raw.get("required", []), (
            f"{tool.name}: compaction changed which arguments are required"
        )
        for name, prop in live["properties"].items():
            assert prop.get("default", "\0") == raw["properties"][name].get(
                "default", "\0"
            ), f"{tool.name}.{name}: compaction changed the advertised default"


def test_compaction_does_not_touch_the_validator():
    """**The whole safety argument.** FastMCP validates an incoming call with
    ``fn_metadata.arg_model`` (``Tool.run`` → ``call_fn_with_arg_validation``,
    mcp/server/fastmcp/tools/base.py:101), and advertises ``Tool.parameters``
    (built separately at base.py:84). Compaction rewrites only the latter — so
    the validator must still carry the very ``title`` keys we stripped from the
    advertised copy. If this ever fails, compaction has reached the call path and
    is no longer cosmetic.

    **Mutation-tested, with an honest caveat.** The *second* assertion carries the
    weight: dropping an argument during compaction turns it red. The first one is
    weaker than it looks — a mutation setting ``arg_model.model_config["title"] =
    None`` left it GREEN, because Pydantic's ``model_json_schema()`` derives the
    title from the class and ignores that config change after the fact. So read
    assertion 1 as cheap insurance against someone rebuilding ``arg_model`` from the
    compacted schema, not as a tight guard.
    """
    for tool in mcp._tool_manager.list_tools():
        validator_schema = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)
        assert "title" in validator_schema, (
            f"{tool.name}: the validating arg_model lost its title — compaction "
            "is mutating the validator, not just the advertised schema"
        )
        assert set(validator_schema.get("properties", {})) == set(
            tool.parameters.get("properties", {})
        ), f"{tool.name}: validator and advertised schema disagree on arguments"


def test_no_generated_titles_remain_anywhere():
    """Walk every advertised schema and assert no ``title`` *annotation* survives.

    Written deliberately as a second, independent traversal rather than by calling
    the production walker — but it has to make the same distinction production
    does: under ``properties``, ``title`` is an argument NAME (``create_card`` has
    one), not an annotation. This test's first draft got that wrong and failed on
    `create_card`, which is exactly the confusion worth pinning.
    """

    def walk_schema(node, path):
        if not isinstance(node, dict):
            return
        assert "title" not in node, f"leftover generated title annotation at {path}"
        for name, sub in node.get("properties", {}).items():
            walk_schema(sub, f"{path}.properties[{name}]")
        for i, sub in enumerate(node.get("anyOf", [])):
            walk_schema(sub, f"{path}.anyOf[{i}]")
        if isinstance(node.get("items"), dict):
            walk_schema(node["items"], f"{path}.items")

    for tool in _tools():
        walk_schema(tool.inputSchema, tool.name)


def test_compaction_is_idempotent():
    """A second pass must be a no-op, so an accidental double-application (e.g. a
    re-import) cannot compound into something lossy."""
    for tool in _tools():
        assert compact_schema(tool.inputSchema) == tool.inputSchema


def test_plain_nullables_are_collapsed():
    """The saving actually happened — `anyOf: [{integer}, {null}]` is now
    `type: [integer, null]`."""
    board_id = _by_name()["list_cards"].inputSchema["properties"]["board_id"]
    assert board_id["type"] == ["integer", "null"]
    assert "anyOf" not in board_id


def test_a_nullable_enum_is_never_collapsed():
    """**The correctness trap, pinned.** Collapsing
    ``anyOf: [{enum: [...], type: string}, {type: null}]`` to
    ``{enum: [...], type: [string, null]}`` would REJECT null, because ``enum``
    applies to the whole value and null is not a member — silently narrowing the
    advertised contract. The collapse is allow-listed to inert sibling keys
    precisely so this cannot happen.
    """
    column = _by_name()["list_cards"].inputSchema["properties"]["column"]
    assert "anyOf" in column, "a nullable enum was collapsed — this narrows it"
    assert {"type": "null"} in column["anyOf"]
    enum_branch = next(o for o in column["anyOf"] if o != {"type": "null"})
    assert enum_branch["enum"] == ["todo", "in_progress", "done"]

    # And directly, so the guard holds even if list_cards' signature changes.
    nullable_enum = {
        "anyOf": [{"enum": ["a", "b"], "type": "string"}, {"type": "null"}],
        "default": None,
    }
    assert compact_schema(nullable_enum) == nullable_enum


def test_an_unrecognised_constraint_blocks_the_collapse():
    """The allow-list is a deny-by-default: a constraint keyword nobody has
    reasoned about must block the collapse rather than be assumed inert."""
    exotic = {"anyOf": [{"type": "string", "pattern": "^x"}, {"type": "null"}]}
    assert compact_schema(exotic) == exotic
    assert "pattern" not in COLLAPSIBLE_SIBLING_KEYS


def test_inert_structural_keys_survive_the_collapse():
    """``items`` must be carried through, not dropped, when a nullable array is
    collapsed — otherwise the element type silently disappears."""
    label_ids = _by_name()["create_card"].inputSchema["properties"]["label_ids"]
    assert label_ids["type"] == ["array", "null"]
    assert label_ids["items"] == {"type": "integer"}


def test_an_argument_literally_named_title_survives():
    """**The trap that actually bit.** ``title`` is a JSON Schema annotation *and*
    the name of ``create_card``/``update_card``'s first argument. The first draft of
    ``compact_schema`` dropped every key called ``title`` at any depth, which
    silently deleted the ``title`` **argument** from two tools — a real behaviour
    change disguised as a cosmetic one. Three invariant tests caught it. This pins
    the specific case so the naive implementation can never come back.
    """
    for name in ("create_card", "update_card"):
        properties = _by_name()[name].inputSchema["properties"]
        assert "title" in properties, (
            f"{name} lost its `title` argument — compact_schema is treating a "
            "property NAME as a schema annotation"
        )
    assert _by_name()["create_card"].inputSchema["required"] == ["title"]


def test_required_arguments_are_untouched_by_compaction():
    """A required, non-nullable argument has no ``anyOf`` to collapse and no
    default; only its annotation should have gone."""
    create_card = _by_name()["create_card"].inputSchema
    assert create_card["required"] == ["title"]
    assert create_card["properties"]["title"] == {"type": "string"}


def test_the_compacted_schema_is_still_valid_json():
    for tool in _tools():
        json.dumps(tool.inputSchema)
