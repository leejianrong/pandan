"""Every envelope key the shared client can return is one ``_humanize`` recognises —
KAN-519, and the end of a family that reached three instances by being spot-fixed.

## The family

``_humanize`` dispatches on a result's shape and ends in ``json.dumps``. That fallback is
the correct safe default for a genuinely unknown payload, but a *known* payload reaching
it means one verb prints a JSON blob where its siblings print rows:

- **KAN-287** — ``template list`` fell through to ``json.dumps``.
- **KAN-478** — ``template create`` rendered as the *wrong* entity (its unsaved card
  definitions as card rows with ``?`` for a ticket), and made ``_list_envelope`` the CLI's
  single definition of list-ness so ``_humanize`` / ``_project_rows`` / ``_summary_for``
  could not disagree again.
- **KAN-519** — filed as ``template apply`` falling through the same way.

## What the audit found, and where the card was wrong

KAN-519's headline claim **did not survive contact**. ``apply_template`` returns
``{"created": [...]}`` (``pandan-client/pandan_client/client.py``), and KAN-502 had already
added ``created`` to ``_LIST_ENVELOPES`` for ``batch-create``'s identical envelope — so
``template apply`` has printed card rows plus a V44 aggregate since that slice landed, one
card earlier than the report. ``test_template_apply_*`` below pins that behaviour rather
than changing it.

The class audit the card asked for is the part that paid: ``update_cards`` returns
``{"updated": [...]}`` (``PATCH /cards/batch``, ``response_model=list[CardRead]``), and
``updated`` was in **no** table — so ``pandan batch-update`` printed indented JSON with no
``--json`` asked for, and no aggregate line. That is the family's real live third
instance, found only because the audit enumerated the class instead of the two reported
names.

## Why this file is a scanner and not a list

A hand-written list of envelope keys is the artefact that let three instances ship: it
agrees with the code on the day it is written. ``test_every_returned_envelope_key_is_
classified`` reads the keys **out of the client's source** with ``ast``, so a new client
method returning ``{"restored": [...]}`` fails here on the PR that adds it.

The scanner is the weak link, so it is proved non-empty **and** non-lossy before anything
is concluded from it: ``test_the_scanner_actually_found_the_shapes_it_claims_to`` pins the
exact key sets of five specific methods, including the two multi-key and two
assignment-built shapes that a naive "``return`` a dict literal" walk would miss. A subset
assertion over a set the test computed itself is worth nothing without that — the pattern
``tests/test_parity.py`` established when it cross-checked its tool regex against a raw
decorator count.

## Section 4 (KAN-583): the other half, and a different enumeration

Recognising an envelope buys the rows, the aggregate and V45's truncation. It does **not**
buy ``--fields``, which ``_add_fields_arg`` attaches per-subparser — so ``batch-create``,
``batch-update`` and ``template apply`` reached KAN-583 with a projection the renderer
would happily serve and a parser that rejected the ask. Sections 0-2 enumerate envelope
*keys* out of ``client.py``; section 4 enumerates *flag declarations* out of the parser
tree, and the two sets are not the same question — which is why the audit that closed one
missed the other, and why the guard here is mechanical rather than a list of three names.
It found a **fourth** verb (``overview``) that sections 0-2 could not see at all, because
that payload is assembled in the CLI and never passes through a client method.

## Section 5 (KAN-591): the scanner's own input set

That last sentence is the whole of KAN-591. Sections 0-2 read ``client.py``, which was
where envelopes came from the day KAN-519 chose it, and ``overview`` — which builds
``{"tool": …, "cards": …, "next_cursor": …}`` in the handler — was already the
counterexample. A guard that exists to *enumerate a class* had a member outside its
reach, and that member was found by a different walk entirely.

So section 5 scans the handlers. ``_payload_keys`` (section 4) already read three of the
handler return shapes; what was missing is a **class** guard over its output — section 4
keeps only the keys already in ``_LIST_ENVELOPES`` and discards the rest, so a brand-new
``return {"restored": rows}`` contributed nothing and nothing failed.
``test_every_handler_returned_key_is_classified`` is that guard, and ``HANDLER_ONLY_KEYS``
records the two keys (``tool``, ``links``) that only a handler produces — the live proof
that the client-source input set is incomplete rather than merely theoretically so.

``test_every_handler_return_is_a_shape_the_scanner_can_read`` is the part meant to
outlive the card. The class guard inherits ``_payload_keys``' reach, so a handler written
in a shape it cannot parse is silently reported as envelope-less — the same failure one
level down. The readable shapes are therefore enumerated and pinned, and a new one fails
with the offending source line rather than being waved through.

**It caught one within hours, and not a synthetic one.** KAN-613 landed on ``main`` while
this was in review and rewrote ``_cmd_warmup`` to ``result = client.warmup()`` … ``result
= {**result, "detail": …}`` … ``return result`` — a fourth return shape, the exact form
this section's own mutation test had used as its counterexample. The merge was textually
clean (branch protection here is ``strict: false``, so nothing else would have stopped
it); the meta-guard was the only thing that noticed. It was resolved the way the guard's
message recommends — teach ``_payload_keys`` the shape, do not reshape the product code —
so ``local variable`` is now a readable shape and ``_cmd_warmup`` is its anchor.

**What section 5 still cannot see**, stated plainly because a scanner that implies
completeness is worse than one that doesn't, and re-checked against the code on
2026-08-16:

- **Non-constant keys.** ``{noun: rows}`` or a dict comprehension's key is dropped —
  there is no static string to read, and the enclosing dict still counts as a readable
  shape, so nothing fails. **This is the nearest live hole**, and it is the one to close
  next if a handler ever computes a key.
- **Keys the renderer invents.** ``_humanize`` / ``_structured_payload`` reshape *after*
  the handler returns; only what a handler returns is scanned.
- **Whatever section 0 cannot read.** A ``client.<method>()`` return is looked up in the
  client-source scanner rather than re-derived, so this section inherits that scanner's
  own limits exactly.
- **The MCP server.** ``mcp/`` assembles its own payloads and is a separate surface with a
  separate contract; nothing here says anything about it.

Two things it deliberately over-reports, which is the safe direction: a local's keys are
unioned across **every** assignment to it, so a key set only on a branch that cannot be
taken still counts; and a self-referential spread (``result = {**result, …}``) is resolved
by breaking the cycle rather than by ordering the assignments.

What it no longer misses: a ``**`` spread of something unreadable, and a dict built into a
local. Both used to read as "no envelope" in silence. Both now fail by name — the second
one having done so for real.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib

import pytest

from pandan_cli import cli, config

CLIENT_SOURCE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "pandan-client" / "pandan_client" / "client.py"
)


# --- the scanner -------------------------------------------------------------


def _returned_keys(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every top-level key of every dict this method can return, as far as it is
    statically visible.

    Three shapes occur in ``client.py`` and all three are collected, because the one it
    would be easiest to miss (``list_cards``) is a real list envelope:

    1. ``return {"created": created}`` — a dict literal at the return.
    2. ``result: dict[str, Any] = {"cards": ...}`` … ``return result`` — built up first.
    3. ``result["next_cursor"] = …`` — a key added by subscript before that return.

    A ``return self._request(...).json()`` contributes nothing: it is the API's own
    single-entity body, which ``_humanize`` matches on entity fields, not an envelope."""
    returned_names = {
        node.value.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name)
    }
    keys: set[str] = set()

    def add_dict(node: ast.AST) -> None:
        if isinstance(node, ast.Dict):
            keys.update(
                k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            )

    for node in ast.walk(fn):
        if isinstance(node, ast.Return):
            add_dict(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id in returned_names:
                add_dict(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in returned_names:
                    add_dict(node.value)
                elif (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in returned_names
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    keys.add(target.slice.value)
    return keys


def client_return_keys() -> dict[str, set[str]]:
    """``{public method name: the dict keys it can return}`` for every public
    ``PandanClient`` method. Skipped, not failed, when ``pandan-client/`` is absent — a
    wheel/PyInstaller checkout of the CLI carries only its own tree, the same stance
    ``tests/test_parity.py`` takes towards ``mcp/``."""
    if not CLIENT_SOURCE.is_file():
        pytest.skip(f"{CLIENT_SOURCE} not present — CLI-only checkout")
    tree = ast.parse(CLIENT_SOURCE.read_text(encoding="utf-8"))
    cls = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "PandanClient"
    )
    return {
        fn.name: _returned_keys(fn)
        for fn in cls.body
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not fn.name.startswith("_")
    }


# Keys a client method returns that are deliberately **not** list envelopes. Each has its
# own branch in ``_humanize`` (cited), so none of them reaches ``json.dumps`` either.
NON_ENVELOPE_KEYS = {
    "deleted": "delete_* receipt — `deleted {noun} {id}`",
    "card": "dispatch / next_ready — `_card_block`, or `(no card ready)` for a null",
    "status": "warmup — `_warmup_line`",
    "health": "warmup's nested probe body, under `status`",
    "detail": "warmup's error branch, under `status`",
    "origin": "KAN-613 — the URL warmup tried, a cell of `_warmup_line`, under `status`",
    "card_id": "list_dependencies — `_dep_block` (a card keys itself under `id`)",
    "blocked_by": "list_dependencies, beside `card_id`",
    "blocks": "list_dependencies, beside `card_id`",
    "next_cursor": "a pagination string beside `cards`/`activity`, never rows itself",
    "unresolved": (
        "issue #254 — the ids=/refs= selectors that matched nothing, a string list "
        "beside `cards`; rendered by `_humanize`'s `_CARD_ENVELOPES` branch as an "
        "`(unresolved: …)` line, never rows itself"
    ),
}


# --- 0. the scanner is sound before anything is concluded from it ------------


def test_the_scanner_actually_found_the_shapes_it_claims_to():
    """The non-emptiness proof, spelled out as exact sets rather than a count.

    A scanner that silently returned ``{}`` would make every assertion below pass
    vacuously — the canonical blind guard on this project. These five methods cover all
    three collection shapes ``_returned_keys`` handles plus the passthrough it must
    ignore, so a walk that quietly stopped seeing any one of them fails HERE, naming it,
    instead of turning the audit into a tautology."""
    keys = client_return_keys()
    # Enough methods to be the real class, not a fixture.
    assert len(keys) > 40, f"only scanned {len(keys)} methods — the class walk broke"
    # Shape 1: a dict literal at the return.
    assert keys["update_cards"] == {"updated"}
    assert keys["apply_template"] == {"created"}
    # …and the card's own claim, checked at the source: `template apply` returns
    # `created`, the very key `batch-create` already put in `_LIST_ENVELOPES`.
    assert keys["apply_template"] == keys["create_cards"]
    # Shapes 2 + 3: built into a local, one key by literal and one by subscript.
    assert keys["list_cards"] == {"cards", "next_cursor", "unresolved"}
    assert keys["list_activity"] == {"activity", "next_cursor"}
    # The passthrough contributes nothing — a single entity is not an envelope.
    assert keys["get_card"] == set()


def test_every_returned_envelope_key_is_classified():
    """The class guard. Every key any client method can return is either a known list
    envelope or an explicitly classified non-envelope — set **equality**, so a new
    unrecognised key fails and so does a stale exemption for one that no longer exists.

    This is the assertion that would have caught ``updated`` in KAN-252, ``templates`` in
    KAN-287 and would catch the fourth instance on the PR that introduces it."""
    seen: set[str] = set()
    for method_keys in client_return_keys().values():
        seen |= method_keys
    unclassified = seen - set(cli._LIST_ENVELOPES) - set(NON_ENVELOPE_KEYS)
    assert not unclassified, (
        f"client methods return {sorted(unclassified)}, which `_list_envelope` does not "
        "recognise and this file does not classify — a payload reaching `_humanize`'s "
        "`json.dumps` fallback (the KAN-287/478/519 family). Add it to `_LIST_ENVELOPES` "
        "(+ `_ROW_NOUN`, `_SUMMARY_NOUN`, and `_CARD_ENVELOPES` if its rows are cards), "
        "or classify it in NON_ENVELOPE_KEYS with the `_humanize` branch that handles it."
    )
    # …and nothing is exempted that the client stopped returning.
    assert set(NON_ENVELOPE_KEYS) <= seen
    # Every list envelope this CLI knows is one the client can actually produce: the two
    # tables describe one wire contract, so neither may carry a name the other lacks.
    assert set(cli._LIST_ENVELOPES) <= seen


# --- 1. identity: what already rendered correctly is untouched ---------------
# Asserted before the intended effect, per the repo's own convention.


def _card(ticket: str, column: str = "todo") -> dict:
    return {
        "id": int(ticket.split("-")[1]),
        "ticket_number": ticket,
        "board_id": 5,
        "title": f"card {ticket}",
        "column": column,
        "story_points": 3,
        "needs_human": False,
        "labels": [],
    }


ROWS = [_card("KAN-21", "in_progress"), _card("KAN-22", "done")]


def test_the_cards_envelope_is_byte_identical():
    """The verb the family never broke. Adding a key to the tables must not move it."""
    assert cli._humanize({"cards": ROWS, "next_cursor": None}) == (
        "KAN-21\tin_progress\tcard KAN-21\tpts=3\n"
        "KAN-22\tdone\tcard KAN-22\tpts=3"
    )
    assert cli._summary_for({"cards": ROWS}) == (
        "cards",
        {"count": 2, "todo": 0, "in_progress": 1, "done": 1, "needs_human": 0},
    )


def test_the_json_dumps_fallback_is_still_reachable():
    """The fallback is the safe default for a genuinely unknown shape and is **kept** —
    KAN-519 asks to stop *hitting* it for a known payload, not to remove it. A payload
    with no envelope, no entity fields and no receipt key still serialises whole."""
    unknown = {"quux": 1, "wibble": ["a", "b"]}
    rendered = cli._humanize(unknown)
    assert json.loads(rendered) == unknown
    assert cli._list_envelope(unknown) is None
    assert cli._summary_for(unknown) is None


# --- 2. the fix: `updated` renders as cards, like `created` ------------------


@pytest.mark.parametrize("key", ["created", "updated"])
def test_a_card_bearing_envelope_renders_rows_and_never_json(key):
    """One noun group, one output shape. ``batch-create`` / ``template apply``
    (``created``) and ``batch-update`` (``updated``) all carry ``CardRead`` rows, so all
    three print the same card rows the plain ``list`` verb does.

    Asserted as the exact rendered text (not ``in``), and as *not parseable as JSON* —
    the specific failure being fixed, and a shape a row-count assertion would miss."""
    rendered = cli._humanize({key: ROWS})
    assert rendered == cli._humanize({"cards": ROWS})
    assert rendered == "\n".join(cli._card_line(row) for row in ROWS)
    assert len(rendered.splitlines()) == len(ROWS)
    with pytest.raises(json.JSONDecodeError):
        json.loads(rendered)


@pytest.mark.parametrize("key", ["created", "updated"])
def test_a_card_bearing_envelope_gets_the_card_aggregate(key):
    """V44's aggregate follows from the same ``_list_envelope`` answer, so recognising
    the key buys the summary line too — the count a caller reads off ``tail -1`` to
    confirm what a batch actually touched."""
    assert cli._summary_for({key: ROWS}) == (
        key,
        {"count": 2, "todo": 0, "in_progress": 1, "done": 1, "needs_human": 0},
    )
    assert cli._summary_line(*cli._summary_for({key: ROWS})) == (
        "2 cards · 0 todo · 1 in_progress · 1 done"
    )


@pytest.mark.parametrize("key", ["created", "updated"])
def test_a_card_bearing_envelope_supports_fields_and_truncation(key):
    """``_project_rows`` (``--fields``) and V45 truncation both dispatch on
    ``_list_envelope``, so recognising the key is all either needs — KAN-478's payoff.

    The projection is checked against a *long* body, because a ``--fields description``
    cell that skipped truncation is exactly the regression V45 shipped to prevent.

    **This reaches the renderer only.** The ``--fields`` *flag* is declared
    per-subparser by ``_add_fields_arg``, which is a separate question and was KAN-519's
    one wrong assumption ("``--fields`` comes for free with the envelope" — it does
    not). Section 4 below is the flag half, and it is a **different enumeration**: this
    file's sections 0-2 enumerate envelope *keys* out of the client, section 4
    enumerates *flag declarations* out of the parser tree."""
    rows = [dict(row, description="x" * 400) for row in ROWS]
    projected = cli._project_rows({key: rows}, ["ticket", "description"], limit=50)
    assert projected == cli._project_rows({"cards": rows}, ["ticket", "description"], limit=50)
    assert len(projected.splitlines()) == 2
    assert "x" * 400 not in projected
    # An unknown field names the right noun — `_ROW_NOUN` has to know the key too.
    with pytest.raises(cli.CliError) as excinfo:
        cli._project_rows({key: rows}, ["nope"])
    assert "for card rows" in str(excinfo.value)


# --- 3. end to end, because that is what an agent scripting the verb sees ----


class FakeClient:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, _name):
        return lambda *a, **k: self.result


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch, tmp_path):
    """No ambient config file, no ``.mcp.json`` discovery, no ``PANDAN_*``/``KANBAN_*``
    from the shell — a stray ``PANDAN_MAX_TEXT_CHARS`` would move the expectations."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: None)
    for names in config._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    config._warned.clear()
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_test")


def run_capture(monkeypatch, capsys, argv, result) -> str:
    monkeypatch.setattr(cli, "PandanClient", lambda *a, **k: FakeClient(result))
    assert cli.run(argv) == cli.EXIT_OK
    return capsys.readouterr().out


EXPECTED_ROWS = [
    "KAN-21\tin_progress\tcard KAN-21\tpts=3",
    "KAN-22\tdone\tcard KAN-22\tpts=3",
    "2 cards · 0 todo · 1 in_progress · 1 done",
]


def test_batch_update_prints_card_rows_end_to_end(monkeypatch, capsys):
    """The bug, at the surface an agent actually sees: ``pandan batch-update`` printed
    ``{"updated": [ … ]}`` indented over many lines with no ``--json`` asked for."""
    out = run_capture(
        monkeypatch,
        capsys,
        ["batch-update", '[{"id": 21, "assignee": "a"}, {"id": 22, "assignee": "a"}]'],
        {"updated": ROWS},
    )
    assert out.splitlines() == EXPECTED_ROWS


def test_template_apply_prints_card_rows_end_to_end(monkeypatch, capsys):
    """KAN-519's *reported* instance, pinned rather than fixed: it already renders rows,
    because ``apply_template`` shares ``created`` with ``batch-create``. Nothing here
    changed it; this exists so the card's claim can never become true by accident."""
    out = run_capture(
        monkeypatch,
        capsys,
        ["template", "apply", "1", "--board", "5"],
        {"created": ROWS},
    )
    assert out.splitlines() == EXPECTED_ROWS


def test_the_three_template_verbs_agree_on_output_shape(monkeypatch, capsys):
    """The consistency complaint KAN-519 opens with — ``template list`` rows,
    ``template create`` a template line, ``template apply`` a JSON blob. All three now
    print tab-separated rows of the entity they returned, and none prints JSON."""
    template = {"id": 1, "board_id": 5, "name": "Slice", "cards": [{"title": "a"}]}
    outputs = {
        "list": run_capture(
            monkeypatch, capsys, ["template", "list", "--board", "5"],
            {"templates": [template]},
        ),
        "create": run_capture(
            monkeypatch, capsys,
            ["template", "create", "Slice", "--board", "5", "--cards", '[{"title": "a"}]'],
            template,
        ),
        "apply": run_capture(
            monkeypatch, capsys, ["template", "apply", "1", "--board", "5"],
            {"created": ROWS},
        ),
    }
    for verb, out in outputs.items():
        first = out.splitlines()[0]
        assert "\t" in first, f"template {verb} did not print a tab-separated row: {out!r}"
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)
    template_line = "1\tSlice\t1 cards"
    assert outputs["list"].splitlines()[0] == template_line
    assert outputs["create"].splitlines()[0] == template_line


# --- 4. the flag-declaration audit (KAN-583) ---------------------------------
# Every verb whose payload `_list_envelope` recognises must also DECLARE `--fields`,
# because the renderer serving a projection is worth nothing if the parser rejects
# the ask. Enumerated from the parser tree + the handlers' own source, so a fifth
# instance fails on the PR that introduces it rather than in a later audit.

CLI_SOURCE = pathlib.Path(cli.__file__)


def _cli_module_functions() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every module-level function in ``cli.py``, by name — the handlers plus the
    small reshaping helpers (``_dep_facet``, ``_link_facet``) they return through."""
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _local_assignments(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[dict[str, list[ast.expr]], dict[str, set[str]]]:
    """``({local: [every value assigned to it]}, {local: keys set on it by subscript})``.

    Every assignment is collected, not the last one, because a handler that rebinds a
    name (``result = client.warmup()`` then ``result = {**result, "detail": …}``) can
    return either shape depending on a branch — so the readable answer is the union.
    ``AugAssign`` counts: ``result |= {"restored": rows}`` is the same move written
    shorter, and would otherwise be a free way past the guard."""
    values: dict[str, list[ast.expr]] = {}
    subscripts: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                if node.value is not None:
                    values.setdefault(target.id, []).append(node.value)
            elif (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                subscripts.setdefault(target.value.id, set()).add(target.slice.value)
    return values, subscripts


def _payload_keys(
    name: str,
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    client_keys: dict[str, set[str]],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    """Every top-level key the handler ``name`` can return, statically.

    Four return shapes occur among the ``_cmd_*`` handlers and all four matter:

    1. ``return client.list_cards(...)`` — the client's own envelope, looked up in
       the section-0 scanner rather than re-derived.
    2. ``return {"tool": …, "cards": cards, …}`` / ``{"tool": …, **client.list_boards()}``
       — a dict the CLI assembles itself. This is ``overview``, and it is invisible to
       a client-only scan, which is exactly how it survived KAN-519's audit.
    3. ``return _dep_facet(client.add_dependency(...), card_id)`` — reshaped through a
       module-level helper, so the walk recurses into it (``seen`` guards a cycle).
    4. ``result = client.warmup()`` … ``result = {**result, "detail": …}`` …
       ``return result`` — built into a local first, so the walk resolves the name
       through **every** value assigned to it (plus any key set on it by subscript)
       and unions the lot. ``_cmd_warmup`` (KAN-613) is the live instance; a
       self-referential spread like the one above is why the resolution carries its
       own cycle guard.

    Shape 4 was **not** readable when this section shipped, and the meta-guard below
    caught ``_cmd_warmup`` adopting it on ``main`` four hours later — the widening is
    that catch, resolved the way the guard's own message recommends (teach the
    scanner, don't reshape the product code).

    Anything else contributes nothing, which is the safe direction: an unrecognised
    return shape reports "no envelope", and a verb wrongly reported as envelope-less
    can only make the guard below *miss*, never false-positive. It is also no longer
    silent — ``test_every_handler_return_is_a_shape_the_scanner_can_read`` fails on a
    return this function cannot read."""
    if name in seen or name not in funcs:
        return set()
    seen = seen | {name}
    values, subscripts = _local_assignments(funcs[name])

    def from_expr(node: ast.AST, locals_seen: frozenset[str] = frozenset()) -> set[str]:
        keys: set[str] = set()
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is None:  # `**expr` — expand whatever it returns
                    keys |= from_expr(value, locals_seen)
                elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "client"
            ):
                keys |= client_keys.get(func.attr, set())
            elif isinstance(func, ast.Name):
                keys |= _payload_keys(func.id, funcs, client_keys, seen)
        elif isinstance(node, ast.Name) and node.id not in locals_seen:
            inner = locals_seen | {node.id}
            for value in values.get(node.id, ()):
                keys |= from_expr(value, inner)
            keys |= subscripts.get(node.id, set())
        return keys

    return {
        key
        for node in ast.walk(funcs[name])
        if isinstance(node, ast.Return) and node.value is not None
        for key in from_expr(node.value)
    }


def _leaf_verbs(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> list[tuple[str, argparse.ArgumentParser]]:
    """``[("template apply", <parser>), …]`` for every verb a caller can actually
    invoke — the leaves of the subparser tree, at whatever depth. A subparsers action
    is the one action whose ``choices`` is a ``dict`` (``--column``'s is a list), so
    this needs no private argparse class."""
    groups = [
        action
        for action in parser._actions
        if isinstance(getattr(action, "choices", None), dict)
    ]
    if not groups:
        return [(" ".join(path), parser)]
    return [
        leaf
        for action in groups
        for name, sub in action.choices.items()
        for leaf in _leaf_verbs(sub, path + (name,))
    ]


def verb_audit() -> dict[str, tuple[set[str], bool]]:
    """``{verb: (the list-envelope keys its payload can carry, declares --fields)}``.

    A ``config``/``login``/``context`` verb dispatches via ``local_func`` and prints
    for itself — no client, no payload — so it contributes an empty key set and is
    simply never an envelope verb."""
    funcs = _cli_module_functions()
    client_keys = client_return_keys()
    audit = {}
    for verb, parser in _leaf_verbs(cli.build_parser()):
        handler = getattr(parser.get_default("func"), "__name__", None)
        keys = _payload_keys(handler, funcs, client_keys) if handler else set()
        audit[verb] = (
            {key for key in keys if key in cli._LIST_ENVELOPES},
            "--fields" in parser._option_string_actions,
        )
    return audit


# Verbs whose payload IS a recognised list envelope and which deliberately do **not**
# declare ``--fields``. Each carries its reason; a stale entry fails below, so this
# cannot quietly become the list-of-names the mechanical guard exists to replace.
FIELDS_EXEMPT = {
    "overview": (
        "PERMANENT (decided in KAN-591; KAN-583 found it and deferred it). `overview` "
        "returns one of TWO envelopes depending on board resolution — `{tool, cards, "
        "next_cursor}` with a board, `{tool, **list_boards()}` without — so a single "
        "`--fields ticket,title` is a valid card projection against the first and an "
        "unknown-field error against the second, for the same argv. A flag whose "
        "accepted values move with ambient config is worse than an absent one, and "
        "argparse cannot declare it conditionally, so it is not declared at all: the "
        "vocabulary belongs to `list` / `board list`, which both take it. The same "
        "reasoning is written into `_cmd_overview`'s docstring, so a reader of the "
        "handler sees the decision without having to find this file."
    ),
}


def test_the_verb_walk_and_payload_scanner_found_what_they_claim_to():
    """The non-emptiness proof, as exact values rather than a count — the same stance
    ``test_the_scanner_actually_found_the_shapes_it_claims_to`` takes one section up,
    because a walk that quietly returned ``{}`` would make the guard below a tautology.

    Both halves are pinned: the parser walk must reach the real verb tree (including
    nested and local-only verbs), and the payload scanner must still see all three
    return shapes it handles."""
    audit = verb_audit()
    # The walk reached the whole tree, at every depth, including the local verbs.
    assert len(audit) > 50, f"only walked {len(audit)} verbs — the parser walk broke"
    for verb in ("list", "overview", "batch-create", "template apply", "config show"):
        assert verb in audit, f"{verb} missing — the walk is not enumerating the tree"
    # Shape 1: straight through to a client method.
    assert audit["list"][0] == {"cards"}
    assert audit["batch-update"][0] == {"updated"}
    # Shape 2: a dict the CLI assembles — both branches, incl. the `**` expansion.
    # This is the one no client-only scan can see.
    assert audit["overview"][0] == {"cards", "boards"}
    # Shape 3: reshaped through a module-level helper. `dep add` carries no envelope,
    # but the recursion is what establishes that — so assert the raw keys too.
    assert _payload_keys("_cmd_dep_add", _cli_module_functions(), client_return_keys()) == {
        "card_id", "blocked_by", "blocks",
    }
    assert audit["dep add"][0] == set()
    # A single-entity passthrough is not an envelope (see the `get` finding below).
    assert audit["get"][0] == set()


def test_every_list_envelope_verb_declares_fields():
    """The guard. Set **equality**, so it fails in both directions: a verb that renders
    a list envelope and cannot be asked for a projection (KAN-583's three), and a verb
    that declares a flag its payload can never use (a projection ``_project_rows``
    would decline, leaving ``--fields`` a silent no-op)."""
    audit = verb_audit()
    should = {verb for verb, (envelopes, _) in audit.items() if envelopes}
    declares = {verb for verb, (_, has_flag) in audit.items() if has_flag}
    assert declares == should - set(FIELDS_EXEMPT), (
        "`--fields` declarations and list-envelope payloads disagree.\n"
        f"  envelope verbs missing the flag: {sorted(should - declares - set(FIELDS_EXEMPT))}\n"
        f"  verbs declaring a flag they cannot use: {sorted(declares - should)}\n"
        "Add `_add_fields_arg(<parser>, \"<example>\")` to the verb's subparser block, "
        "or classify it in FIELDS_EXEMPT with the reason."
    )


def test_the_fields_exemptions_are_not_stale():
    """An exemption that stopped being true is the artefact that lets the next instance
    ship. Each one must still name a real verb, whose payload really is an envelope,
    which really does lack the flag — so fixing ``overview`` deletes its entry here
    instead of leaving a comment that has quietly become false."""
    audit = verb_audit()
    for verb, reason in FIELDS_EXEMPT.items():
        assert verb in audit, f"FIELDS_EXEMPT names {verb!r}, which is not a verb"
        envelopes, has_flag = audit[verb]
        assert envelopes, f"{verb} carries no list envelope — the exemption is stale"
        assert not has_flag, f"{verb} now declares --fields — drop its exemption"
        assert reason.strip(), f"{verb} is exempted with no reason"


@pytest.mark.parametrize(
    ("argv", "result"),
    [
        (["batch-create", '[{"title": "a"}]'], {"created": ROWS}),
        (["batch-update", '[{"id": 21, "assignee": "a"}]'], {"updated": ROWS}),
        (["template", "apply", "1", "--board", "5"], {"created": ROWS}),
    ],
    ids=["batch-create", "batch-update", "template-apply"],
)
def test_the_three_widened_verbs_serve_a_projection_end_to_end(
    monkeypatch, capsys, argv, result
):
    """KAN-583 at the surface an agent sees: the projection the renderer already
    supported, now reachable. Asserted as exact lines, and with the V44 aggregate still
    last — ``--fields`` chooses which columns print and changes nothing else, so the
    published "read your counts off ``tail -1``" contract survives it."""
    out = run_capture(monkeypatch, capsys, argv + ["--fields", "ticket,column"], result)
    assert out.splitlines() == [
        "KAN-21\tin_progress",
        "KAN-22\tdone",
        "2 cards · 0 todo · 1 in_progress · 1 done",
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["batch-create", '[{"title": "a"}]'],
        ["batch-update", '[{"id": 21}]'],
        ["template", "apply", "1", "--board", "5"],
    ],
    ids=["batch-create", "batch-update", "template-apply"],
)
def test_the_widened_verbs_name_card_rows_on_an_unknown_field(monkeypatch, capsys, argv):
    """The error contract (V43) reaches the new flag too, and names the right noun.
    ``template apply``'s parser sets ``noun="template"``, but its rows are cards —
    the noun comes from ``_ROW_NOUN[envelope]``, not from the verb."""
    monkeypatch.setattr(cli, "PandanClient", lambda *a, **k: FakeClient({"created": ROWS}))
    assert cli.run(argv + ["--fields", "nope"]) == cli.EXIT_ERROR
    out = capsys.readouterr().out
    assert "unknown_field" in out
    assert "for card rows" in out


# --- 5. the handler-side envelope scan (KAN-591) ------------------------------
# Sections 0-2 read envelope keys out of ``client.py``. That input set was correct on
# the day KAN-519 chose it and is *structurally* incomplete: ``overview`` assembles its
# payload in the CLI and never passes through a client method, so no client-source walk
# can see it — which is why the fourth instance of the family was found by KAN-583's
# unrelated flag audit rather than by the guard whose whole job is enumerating the class.
# This section closes that by scanning the handlers themselves, and then guards the
# scanner's own input set so the hole cannot silently regrow in a new shape.


# Keys a **handler** can return that no client method returns, so sections 0-2 are
# blind to them by construction. Each is a real live instance of the blind spot and
# each has its own ``_humanize`` branch (cited), so none reaches ``json.dumps``.
HANDLER_ONLY_KEYS = {
    "tool": (
        "`overview`'s ambient-context banner (V48) — `{**_tool_identity(config), "
        "board_id}`, assembled in `_cmd_overview`. `_humanize`'s FIRST branch strips it, "
        "renders `_tool_banner`, and recurses on the rest; nothing on the wire has a "
        "`tool` key. This is the key that proves the client-source scan is incomplete."
    ),
    "links": (
        "`link add` / `link rm` reshape a full card into `{card_id, links}` via "
        "`_link_facet` — the client returns the whole card, and the CLI narrows it to "
        "the facet the verb is about. Rendered by `_humanize`'s `card_id`+`links` "
        "branch (`_link_block`), never rows itself."
    ),
}


def handler_return_keys() -> dict[str, set[str]]:
    """``{_cmd_* handler name: the top-level keys it can return}`` for every handler in
    ``cli.py``.

    Walked from the **module's functions**, not from the parser tree, and the two are
    not the same input set: ``verb_audit`` above reaches a handler through a subparser's
    ``func`` default, and the five ``config``/``login`` verbs dispatch via ``local_func``
    instead — so they are invisible to it, and visible here. They return an exit code
    today; the day one returns a payload, this walk sees it and that one does not."""
    funcs = _cli_module_functions()
    client_keys = client_return_keys()
    return {
        name: _payload_keys(name, funcs, client_keys)
        for name in funcs
        if name.startswith("_cmd_")
    }


def _union(keys: dict[str, set[str]]) -> set[str]:
    return set().union(*keys.values()) if keys else set()


def test_the_handler_scanner_sees_what_the_client_scanner_cannot():
    """The non-emptiness proof, as exact sets rather than a count — the standard
    ``test_the_scanner_actually_found_the_shapes_it_claims_to`` sets one section up, and
    the one ``tests/test_parity.py`` had to be repaired for (KAN-592): every anchor below
    is a **literal written in this file**, never a second derivation from the same walk,
    so a walk that quietly matched nothing fails here naming what it lost instead of
    making the guards below pass over an empty set.

    The last two assertions are the card's actual claim, checked at the source rather
    than taken on trust: there exist keys a handler returns that no client method does."""
    keys = handler_return_keys()
    assert len(keys) > 50, f"only scanned {len(keys)} handlers — the module walk broke"
    # One literal per return shape `_payload_keys` handles, so a walk that stopped
    # seeing any one of them fails HERE, naming it.
    assert keys["_cmd_overview"] == {"tool", "cards", "next_cursor", "boards"}
    assert keys["_cmd_list"] == {"cards", "next_cursor", "unresolved"}
    assert keys["_cmd_link_add"] == {"card_id", "links"}
    # Shape 4, the one the meta-guard below caught `main` adopting: a local rebound
    # through a self-referential spread, `client.warmup()` ∪ the `detail` KAN-613 adds.
    assert keys["_cmd_warmup"] == {"status", "origin", "health", "detail"}
    # A `local_func` verb: no payload, and unreachable from `verb_audit`'s parser walk.
    assert keys["_cmd_config_show"] == set()
    # The blind spot itself, named as literals. `overview` — the known counterexample —
    # is now visible, and `links` is a second instance that was equally invisible.
    invisible = _union(keys) - _union(client_return_keys())
    assert {"tool", "links"} <= invisible, (
        f"handler-only keys are {sorted(invisible)}; `tool` (overview) and `links` "
        "(link add/rm) are the two this section was written for, so losing either "
        "means the handler walk stopped reading the shape that motivated it"
    )


def test_every_handler_returned_key_is_classified():
    """The class guard, handler side. Every key any ``_cmd_*`` handler can return is
    either a known list envelope, a key the client also returns and section 0 already
    classifies, or a handler-only key classified here.

    This is the assertion the card asks for: a new envelope introduced in a **handler**
    — ``return {"restored": rows}`` — fails on the PR that adds it, instead of printing
    ``json.dumps`` in production until an unrelated audit trips over it."""
    unclassified = (
        _union(handler_return_keys())
        - set(cli._LIST_ENVELOPES)
        - set(NON_ENVELOPE_KEYS)
        - set(HANDLER_ONLY_KEYS)
    )
    assert not unclassified, (
        f"CLI handlers return {sorted(unclassified)}, which `_list_envelope` does not "
        "recognise and neither classification table covers — a payload assembled in "
        "`cli.py` reaching `_humanize`'s `json.dumps` fallback (the KAN-287/478/519/591 "
        "family, and the half no client-source scan can see). Add it to "
        "`_LIST_ENVELOPES` (+ `_ROW_NOUN`, `_SUMMARY_NOUN`, and `_CARD_ENVELOPES` if "
        "its rows are cards), or classify it in HANDLER_ONLY_KEYS with the `_humanize` "
        "branch that handles it."
    )


def test_the_handler_only_classifications_are_not_stale():
    """A classification that stopped being true is the artefact that lets the next
    instance ship, so each entry must still be a key a handler really returns **and**
    one the client-source scan really cannot see. A key that migrated onto the wire
    belongs in ``NON_ENVELOPE_KEYS``, where section 0 also polices it."""
    handler_union = _union(handler_return_keys())
    client_union = _union(client_return_keys())
    for key, reason in HANDLER_ONLY_KEYS.items():
        assert key in handler_union, f"no handler returns {key!r} any more — drop it"
        assert key not in client_union, (
            f"{key!r} is now returned by a client method too, so it is no longer "
            "handler-only — move it to NON_ENVELOPE_KEYS (or `_LIST_ENVELOPES`), "
            "where the client-source scanner covers it as well"
        )
        assert reason.strip(), f"{key} is classified with no reason"


# The return shapes ``_payload_keys`` can actually read. Anything else is a shape the
# scanner would silently report as envelope-less — the exact failure mode this whole
# section exists to end — so a handler adopting one must fail loudly instead.
_READABLE_RETURN_SHAPES = frozenset({
    "dict literal",          # `return {"tool": …, "cards": …}` — overview
    "client method call",    # `return client.list_cards(…)`
    "module-level helper",   # `return _link_facet(client.add_link(…), card_id)`
    "exit code",             # `return EXIT_OK` — a local verb that printed for itself
    "local variable",        # `result = …` … `return result` — warmup (KAN-613)
})

# Names a handler may return that are an exit status rather than a payload.
_EXIT_NAMES = frozenset({"EXIT_OK", "EXIT_ERROR", "EXIT_USAGE"})


def _return_shape(
    value: ast.expr,
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    values: dict[str, list[ast.expr]],
    locals_seen: frozenset[str] = frozenset(),
) -> str | None:
    """Which of ``_payload_keys``' readable shapes this returned expression is, or
    ``None`` when the scanner cannot read it.

    **Recursive, and that is the point.** A local is only readable if everything
    assigned to it is readable too: ``payload = dict(restored=rows)`` … ``return
    payload`` is a ``Name`` bound to a call ``_payload_keys`` cannot see through, so
    answering "local variable — fine" would restore the blind spot one level down,
    which is precisely the mistake this guard exists to prevent. A ``**`` spread is
    checked the same way; its sibling *values* are not, because only keys are read."""
    if isinstance(value, ast.Dict):
        spreads = [v for k, v in zip(value.keys, value.values) if k is None]
        if any(
            _return_shape(spread, funcs, values, locals_seen) is None
            for spread in spreads
        ):
            return None
        return "dict literal"
    if isinstance(value, ast.Call):
        func = value.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "client"
        ):
            return "client method call"
        if isinstance(func, ast.Name) and func.id in funcs:
            return "module-level helper"
    if isinstance(value, ast.Name):
        if value.id in _EXIT_NAMES:
            return "exit code"
        if value.id in locals_seen:  # self-referential spread — already being checked
            return "local variable"
        if value.id in values:
            inner = locals_seen | {value.id}
            if all(
                _return_shape(assigned, funcs, values, inner) is not None
                for assigned in values[value.id]
            ):
                return "local variable"
    return None


def handler_returns() -> list[tuple[str, str, str | None]]:
    """``[(handler, the return's source, its shape or None), …]`` for every ``return``
    in every ``_cmd_*`` handler."""
    funcs = _cli_module_functions()
    return [
        (
            name,
            "return" if node.value is None else ast.unparse(node.value),
            None
            if node.value is None
            else _return_shape(node.value, funcs, _local_assignments(fn)[0]),
        )
        for name, fn in funcs.items()
        if name.startswith("_cmd_")
        for node in ast.walk(fn)
        if isinstance(node, ast.Return)
    ]


def test_every_handler_return_is_a_shape_the_scanner_can_read():
    """The meta-guard, and the part of KAN-591 meant to outlive it.

    A scanner is only as complete as its input set, and the input set is a design
    decision that ages — that is the card's own generalisation, and the class guard
    above inherits the weakness one level down: it reads whatever ``_payload_keys``
    can parse, and a handler written in a shape ``_payload_keys`` does not handle is
    reported as carrying no envelope at all. Silently. Exactly how ``overview`` sat
    outside KAN-519's walk for three slices.

    So the shapes are enumerated and pinned rather than assumed. A handler that
    returns something new fails here with the source line, and whoever wrote it either
    teaches ``_payload_keys`` the shape or explains why it carries no payload — a
    decision, not a default. The second assertion is the mirror: every allow-listed
    shape must be exercised by a real handler, so the list cannot grow an entry that
    waves through a shape nothing actually uses."""
    returns = handler_returns()
    assert len(returns) > 50, f"only walked {len(returns)} returns — the walk broke"

    unreadable = sorted(
        f"{name}: return {source}" for name, source, shape in returns if shape is None
    )
    assert not unreadable, (
        "these handler returns are in a shape `_payload_keys` cannot read, so any "
        "envelope they carry is invisible to the guards above:\n  "
        + "\n  ".join(unreadable)
        + f"\nReadable shapes are {sorted(_READABLE_RETURN_SHAPES)}. Teach "
        "`_payload_keys` (and `_return_shape`) the new shape, or return one of the "
        "existing ones. Do not widen `_READABLE_RETURN_SHAPES` without widening the "
        "scanner: that would restore the blind spot KAN-591 closed."
    )

    shapes: dict[str, set[str | None]] = {}
    for name, _source, shape in returns:
        shapes.setdefault(name, set()).add(shape)
    # Literal anchors again — one named handler per allow-listed shape.
    assert shapes["_cmd_overview"] == {"dict literal"}
    assert shapes["_cmd_list"] == {"client method call"}
    assert shapes["_cmd_link_add"] == {"module-level helper"}
    assert shapes["_cmd_config_show"] == {"exit code"}
    assert shapes["_cmd_warmup"] == {"local variable"}
    assert {shape for _n, _s, shape in returns} == set(_READABLE_RETURN_SHAPES), (
        "an allow-listed return shape no handler uses — it is waving through a shape "
        "nobody writes, which is how an allow-list stops describing the code"
    )
