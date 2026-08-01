"""Compact the *advertised* JSON Schema of each tool (V49 / ADR 0019).

Why this exists. The 49 tool schemas are serialized into every agent session's
context before it does any work, and V49 measured **1,429 of those ~8,775
`o200k_base` tokens (16%) as pure serializer artefact** — text that carries no
information a model can act on:

* The SDK builds each tool's advertised schema with
  ``arg_model.model_json_schema()``, and Pydantic stamps a generated ``title`` on
  the model *and* on every property: ``"title": "warmupArguments"``,
  ``"title": "Board Id"``. Each is a restatement of a name the model can already
  read off the key.
* Pydantic renders every optional as ``anyOf: [{"type": T}, {"type": "null"}]``
  rather than the equivalent ``{"type": [T, "null"]}`` — about three times the
  tokens for the same constraint.

**This is provably cosmetic, and that is the whole safety argument for doing it.**
The SDK keeps two separate things on a ``Tool``: ``parameters`` — the schema it
*advertises* to clients, built at
``mcp/server/mcpserver/tools/base.py:100`` — and ``fn_metadata``,
whose ``arg_model`` is what actually *validates* an incoming call
(``Tool.run`` → ``fn_metadata.call_fn_with_arg_validation``,
``mcp/server/mcpserver/tools/base.py:152``). Line numbers are against SDK **2.0.0**
(KAN-585); under 1.x the same two objects lived at ``mcp/server/fastmcp/tools/base.py``
:84 and :101. This module rewrites only the former. No tool is renamed, no argument is added or
removed, and no call can be accepted or rejected differently, because the
validator is a different object and is never touched. ``tests/test_schema.py``
pins exactly that.

### The one non-obvious correctness trap

The naive collapse is **wrong for an enum**. Pydantic renders
``Literal["todo", "in_progress", "done"] | None`` as::

    {"anyOf": [{"enum": ["todo", "in_progress", "done"], "type": "string"},
               {"type": "null"}]}

which accepts ``"todo"`` *or* ``null``. Collapsing that to
``{"enum": [...], "type": ["string", "null"]}`` **rejects null**, because ``enum``
applies to the whole value and ``null`` is not a member — a real narrowing of the
advertised contract. ``items`` and ``additionalProperties`` are inert for ``null``
(they only constrain arrays and objects respectively), but ``enum`` is not, and
neither would ``pattern``/``minimum``/``format`` be.

So the collapse is **allow-listed, not deny-listed**: it fires only when the
non-null branch carries nothing but ``type`` and those two inert structural keys.
Anything else — an enum today, some future constraint keyword — is left as an
``anyOf``. Giving up the ~6 enum-bearing optionals is cheap; silently narrowing a
schema is not.
"""
from __future__ import annotations

from typing import Any

#: Keys that may accompany ``type`` in the non-null branch of a nullable
#: ``anyOf`` and still permit the collapse. Both are inert for ``null``: ``items``
#: constrains array members, ``additionalProperties`` object members. Deliberately
#: an allow-list — an unrecognised keyword blocks the collapse rather than being
#: assumed harmless. See the module docstring's enum trap.
COLLAPSIBLE_SIBLING_KEYS = frozenset({"items", "additionalProperties"})

#: ``"title"`` is a JSON Schema *annotation* — and also a perfectly good argument
#: name (``create_card(title=...)``, ``update_card(title=...)``). So the walk below
#: must know which dicts are schemas and which are ``name -> schema`` maps; a blanket
#: "drop every key called title" deletes the ``title`` **argument**. That bug was
#: written, caught by ``test_compaction_preserves_every_property_name_and_required_set``,
#: and is the reason this traversal is keyword-driven instead of naive recursion.
#: Values are maps of ``name -> schema``: never treat their keys as keywords.
_SCHEMA_MAP_KEYS = frozenset({"properties", "$defs", "definitions", "patternProperties"})
#: Values are lists of schemas.
_SCHEMA_LIST_KEYS = frozenset({"anyOf", "oneOf", "allOf", "prefixItems"})
#: Values are a single subschema.
_SUBSCHEMA_KEYS = frozenset(
    {"items", "additionalProperties", "not", "if", "then", "else", "propertyNames", "contains"}
)

_NULL = {"type": "null"}


def _collapse_nullable(prop: dict[str, Any]) -> dict[str, Any]:
    """Rewrite ``anyOf: [{type: T, ...}, {type: null}]`` → ``{type: [T, null], ...}``
    when — and only when — the non-null branch constrains nothing but its type."""
    options = prop.get("anyOf")
    if not isinstance(options, list) or len(options) != 2 or _NULL not in options:
        return prop
    other = next((o for o in options if o != _NULL), None)
    if not isinstance(other, dict) or not isinstance(other.get("type"), str):
        return prop
    if set(other) - {"type"} - COLLAPSIBLE_SIBLING_KEYS:
        return prop  # an enum or some other constraint — collapsing would narrow it
    collapsed = {k: v for k, v in prop.items() if k != "anyOf"}
    collapsed.update(other)
    collapsed["type"] = [other["type"], "null"]
    return collapsed


def compact_schema(schema: Any) -> Any:
    """Return ``schema`` with generated ``title`` annotations dropped and safely
    collapsible nullable ``anyOf``s flattened.

    Pure and **idempotent** — a second pass is a no-op, so an accidental double
    application cannot compound. The traversal is driven by JSON Schema keywords
    rather than recursing blindly, for two reasons: a ``properties`` key holds
    *argument names* (one of which is legitimately ``title``), and a ``default`` or
    ``enum`` holds *data*, which must never be rewritten as if it were a schema.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title":
            continue  # a generated annotation at schema level, not an argument
        if key in _SCHEMA_MAP_KEYS and isinstance(value, dict):
            # name -> schema: keep every name verbatim, compact only the values.
            out[key] = {name: compact_schema(sub) for name, sub in value.items()}
        elif key in _SCHEMA_LIST_KEYS and isinstance(value, list):
            out[key] = [compact_schema(item) for item in value]
        elif key in _SUBSCHEMA_KEYS:
            out[key] = compact_schema(value)
        else:
            out[key] = value  # plain data (type, enum, default, …) — left alone
    return _collapse_nullable(out)


def compact_advertised_schemas(server: Any) -> int:
    """Compact the advertised schema of every tool registered on ``server``,
    in place. Returns the number of tools whose schema actually changed.

    Touches only ``Tool.parameters`` (what clients are shown). ``Tool.fn`` and
    ``Tool.fn_metadata`` — the callable and the validator — are left alone, so
    this cannot alter behaviour.
    """
    changed = 0
    for tool in server._tool_manager.list_tools():
        compacted = compact_schema(tool.parameters)
        if compacted != tool.parameters:
            tool.parameters = compacted
            changed += 1
    return changed
