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
"""
from __future__ import annotations

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
    assert keys["list_cards"] == {"cards", "next_cursor"}
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

    **Honest limitation, at the level this test actually reaches:** this pins the
    *renderer*. The ``--fields`` **flag** is per-subparser (``_add_fields_arg``), and
    neither ``batch-create``, ``batch-update`` nor ``template apply`` declares it — so a
    caller cannot yet ask for a projection on those three verbs even though the renderer
    would serve it. KAN-519 assumed ``--fields`` came "for free" with the envelope; it
    does not, and widening three parsers was left out of that card's diff on purpose."""
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
