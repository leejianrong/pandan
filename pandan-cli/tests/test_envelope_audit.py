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


def _payload_keys(
    name: str,
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    client_keys: dict[str, set[str]],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    """Every top-level key the handler ``name`` can return, statically.

    Three return shapes occur among the ``_cmd_*`` handlers and all three matter:

    1. ``return client.list_cards(...)`` — the client's own envelope, looked up in
       the section-0 scanner rather than re-derived.
    2. ``return {"tool": …, "cards": cards, …}`` / ``{"tool": …, **client.list_boards()}``
       — a dict the CLI assembles itself. This is ``overview``, and it is invisible to
       a client-only scan, which is exactly how it survived KAN-519's audit.
    3. ``return _dep_facet(client.add_dependency(...), card_id)`` — reshaped through a
       module-level helper, so the walk recurses into it (``seen`` guards a cycle).

    Anything else contributes nothing, which is the safe direction: an unrecognised
    return shape reports "no envelope", and a verb wrongly reported as envelope-less
    can only make the guard below *miss*, never false-positive."""
    if name in seen or name not in funcs:
        return set()
    seen = seen | {name}

    def from_expr(node: ast.AST) -> set[str]:
        keys: set[str] = set()
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is None:  # `**expr` — expand whatever it returns
                    keys |= from_expr(value)
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
        "returns one of TWO envelopes depending on board resolution — `{tool, cards, "
        "next_cursor}` with a board, `{tool, **list_boards()}` without — so a single "
        "`--fields ticket,title` is a valid card projection against the first and an "
        "unknown-field error against the second. Which vocabulary the flag advertises "
        "is a behaviour question of its own; KAN-583 found it here and reported it "
        "rather than answering it inside a card scoped to three other verbs."
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
