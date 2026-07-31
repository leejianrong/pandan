"""``--format {human,json,toon}`` — the V47 (KAN-430) output-format contract.

Three promises are asserted here, and they are the whole slice:

1. **Round-trip equality.** For every nested payload, the TOON output parses back to
   data *equal* to the ``--json`` output. Deliberately not a golden string — the
   contract is that the two formats describe the same data, not that TOON is spelled
   a particular way — so the check runs through an independent decoder
   (``tests/toon_decode.py``).
2. **The TSV default is untouched.** ``--format human`` and no flag at all produce
   byte-identical output, and that output is exactly what ``_humanize`` produced
   before this slice. (The 270-odd human-output assertions in ``test_cli.py`` are
   the rest of that guard.)
3. **An unknown ``--format`` is a V43-shaped exit-2 error** on stdout, with the
   usage block on stderr.

Plus: ``--json`` remains a supported alias for ``--format json``.
"""
from __future__ import annotations

import json

import pytest
from toon_decode import decode

from pandan_cli import cli, config

# --- realistic payloads, trimmed from the live Pandan Roadmap board ----------
# Shapes matter more than sizes here: `get` is a flat-ish single object, `metrics`
# nests two objects plus two uniform arrays, `activity`/`epic list` are uniform
# arrays (the tabular case), and `dep list` is the smallest nested payload.

CARD = {
    "id": 430,
    "ticket_number": "KAN-430",
    "board_id": 5,
    "title": "V47 · --format toon for nested payloads",
    "description": "A6. AXI 1, scoped.\nSecond line, with a comma, a colon: and \"quotes\".",
    "column": "in_progress",
    "position": 0,
    "story_points": 3,
    "assignee": "agent:v47-toon",
    "epic_id": 67,
    "cycle_id": None,
    "priority": "low",
    "due_date": None,
    "needs_human": False,
    "attention_note": None,
    "labels": [],
    "blocked_by": [],
    "blocks": [],
    "blocked": False,
    "links": [],
    "created_at": "2026-07-30T18:08:46.913508Z",
    "updated_at": "2026-07-31T05:56:18.419656Z",
}

METRICS = {
    "board_id": 5,
    "generated_at": "2026-07-31T05:59:11.024748Z",
    "since": None,
    "until": "2026-07-31T05:59:11.024748Z",
    "throughput": 61,
    "cycle_time": {
        "count": 54,
        "avg_seconds": 3624.1043964444443,
        "median_seconds": 1216.9123835,
        "p90_seconds": 2080.421023,
    },
    "aging_wip": {
        "count": 2,
        "avg_seconds": 172.96977049999998,
        "max_seconds": 174.790673,
        "items": [
            {
                "card_id": 430,
                "ticket_number": "KAN-430",
                "assignee": "agent:v47-toon",
                "age_seconds": 174.790673,
            },
            {
                "card_id": 452,
                "ticket_number": "KAN-452",
                "assignee": None,
                "age_seconds": 171.148868,
            },
        ],
    },
    "by_assignee": [
        {"assignee": "agent:cli-ergonomics", "throughput": 4, "wip": 0},
        {"assignee": None, "throughput": 2, "wip": 1},
    ],
}

ACTIVITY = {
    "activity": [
        {
            "id": 1038,
            "board_id": 5,
            "actor_user_id": "c5e6f334-e548-4719-8f43-8460fe1940c9",
            "actor_label": "someone@example.com",
            "entity_type": "card",
            "entity_id": 452,
            "action": "updated",
            "summary": "updated KAN-452",
            "ts": "2026-07-31T05:56:22.042022Z",
        },
        {
            "id": 1036,
            "board_id": 5,
            "actor_user_id": None,
            "actor_label": None,
            "entity_type": "card",
            "entity_id": 452,
            "action": "moved",
            "summary": "moved KAN-452 from todo to in_progress",
            "ts": "2026-07-31T05:56:19.875880Z",
        },
    ],
    "next_cursor": "1036",
}

EPICS = {
    "epics": [
        {
            "id": 3,
            "ticket_number": "EPIC-3",
            "board_id": 5,
            "name": "M4: Board Collaboration",
            "description": "Turn owner-only boards into shared boards.",
            "target_date": None,
            "lead": None,
            "progress": {"total": 5, "done": 5, "percent": 100},
            "health": None,
            "created_at": "2026-07-09T08:52:12.236945Z",
            "updated_at": "2026-07-09T08:52:12.236945Z",
        },
        {
            "id": 67,
            "ticket_number": "EPIC-67",
            "board_id": 5,
            "name": "M7: Sharpen the Tools",
            "description": None,
            "target_date": "2026-08-15",
            "lead": "agent:pm",
            "progress": {"total": 8, "done": 3, "percent": 37},
            "health": "at_risk",
            "created_at": "2026-07-30T08:52:12.236945Z",
            "updated_at": "2026-07-31T08:52:12.236945Z",
        },
    ]
}

DEPS = {"card_id": 430, "blocked_by": [428, 429], "blocks": []}

VIEWS = {
    "views": [
        {"id": 1, "board_id": 5, "name": "My WIP", "query": {"column": "in_progress"}},
        {
            "id": 2,
            "board_id": 5,
            "name": "Overdue",
            "query": {"overdue": True, "sort": "-priority"},
        },
    ]
}

TEMPLATES = {
    "templates": [
        {
            "id": 1,
            "board_id": 5,
            "name": "Vertical slice",
            "cards": [
                {"title": "API", "column": "todo", "story_points": 3},
                {"title": "UI", "column": "todo", "story_points": 2},
            ],
        }
    ]
}

CARDS_PAGE = {
    "cards": [
        {**CARD, "id": 1, "ticket_number": "KAN-1", "title": "one"},
        {
            **CARD,
            "id": 2,
            "ticket_number": "KAN-2",
            "title": "two",
            "labels": [{"id": 9, "n": "x"}],
        },
    ],
    "next_cursor": None,
}

# The payloads the slice names, keyed by the verb that returns them.
NESTED_PAYLOADS = {
    "get": CARD,
    "metrics": METRICS,
    "activity": ACTIVITY,
    "epic list": EPICS,
    "dep list": DEPS,
    "view list": VIEWS,
    "template list": TEMPLATES,
    # Not a "nested payload" the slice targets (its human default is TSV and stays
    # so), but `--format` is a global flag, so its structured output must be sound.
    "list": CARDS_PAGE,
}


# --- fixtures ---------------------------------------------------------------


class FakeClient:
    """Returns one canned result for whatever method the verb calls."""

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
    """Same hermeticity the main suite's autouse fixture provides: no ambient config
    file, no ``.mcp.json`` discovery, no ``PANDAN_*``/``KANBAN_*`` from the shell."""
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
def without_hints(out: str) -> str:
    """``out`` minus V46's ``help:`` next-step lines (KAN-429), which ``_emit`` prints
    for the hinted verbs (``get``/``create``/``move``/``list``/…) after the result and,
    since KAN-492, above the V44 aggregate line rather than below it.

    Applied at the assertion site and deliberately **not** inside ``run_capture``:
    every "stdout still parses as JSON/TOON" check in this suite must stay able to
    catch a hint leaking into a structured format. The hints themselves are pinned in
    ``tests/test_content_first.py``."""
    return "".join(f"{line}\n" for line in out.splitlines() if not line.startswith(cli.HINT_PREFIX))


# --- 1. round-trip equality -------------------------------------------------


@pytest.mark.parametrize("name", sorted(NESTED_PAYLOADS))
def test_toon_and_json_describe_the_same_data(name):
    """The V47 contract, at the shared-serializer seam both formats go through."""
    payload = NESTED_PAYLOADS[name]
    as_json = cli._render_structured(payload, cli.FORMAT_JSON)
    as_toon = cli._render_structured(payload, cli.FORMAT_TOON)
    assert decode(as_toon) == json.loads(as_json)


@pytest.mark.parametrize(
    ("argv", "result"),
    [
        (["get", "430"], CARD),
        (["metrics", "--board", "5"], METRICS),
        (["activity", "--board", "5"], ACTIVITY),
        (["epic", "list", "--board", "5"], EPICS),
        (["dep", "list", "430"], DEPS),
        (["view", "list", "--board", "5"], VIEWS),
        (["template", "list", "--board", "5"], TEMPLATES),
        (["list", "--board", "5"], CARDS_PAGE),
    ],
    ids=["get", "metrics", "activity", "epic-list", "dep-list", "view-list", "template", "list"],
)
def test_each_verb_round_trips_end_to_end(monkeypatch, capsys, argv, result):
    """The same contract driven through argv, so the flag plumbing is covered too."""
    json_out = run_capture(monkeypatch, capsys, [*argv, "--json"], result)
    toon_out = run_capture(monkeypatch, capsys, [*argv, "--format", "toon"], result)
    assert decode(toon_out) == json.loads(json_out)


def test_toon_actually_deduplicates_the_keys_it_claims_to():
    """A round-trip check alone would pass on a TOON encoder that just re-emitted
    JSON, so assert the saving is real: one header, N bare rows."""
    toon_out = cli._render_structured(EPICS, cli.FORMAT_TOON)
    lines = toon_out.splitlines()
    assert lines[0].startswith("epics[2]{id,ticket_number,")
    # `progress` expands into child columns rather than costing a nested block.
    assert "progress{total,done,percent}" in lines[0]
    assert len(lines) == 3
    assert toon_out.count("ticket_number") == 1
    assert len(toon_out) < len(cli._render_structured(EPICS, cli.FORMAT_JSON))


# --- 2. the TSV default is untouched ----------------------------------------


@pytest.mark.parametrize(
    ("argv", "result"),
    [
        (["list", "--board", "5"], CARDS_PAGE),
        (["get", "430"], CARD),
        (["metrics", "--board", "5"], METRICS),
        (["activity", "--board", "5"], ACTIVITY),
        (["epic", "list", "--board", "5"], EPICS),
        (["dep", "list", "430"], DEPS),
    ],
    ids=["list", "get", "metrics", "activity", "epic-list", "dep-list"],
)
def test_no_flag_and_format_human_are_byte_identical(monkeypatch, capsys, argv, result):
    bare = run_capture(monkeypatch, capsys, argv, result)
    human = run_capture(monkeypatch, capsys, [*argv, "--format", "human"], result)
    assert bare == human
    # …and the ROWS are still exactly what the pre-V47 humanizer produced. V44 appends
    # one aggregate line to a list result, so compare against humanize + that line —
    # which is also the guard that V44 never rewrote a row.
    expected = cli._humanize(result)
    found = cli._summary_for(result)
    if found is not None:
        expected += "\n" + cli._summary_line(*found)
    assert without_hints(bare) == expected + "\n"


def test_the_default_list_row_is_still_tab_separated_with_no_keys(monkeypatch, capsys):
    out = run_capture(monkeypatch, capsys, ["list", "--board", "5"], CARDS_PAGE)
    # `list` carries hints since KAN-492, printed between the rows and the aggregate;
    # they are listed here rather than filtered so this stays a whole-stdout pin.
    assert out.splitlines() == [
        "KAN-1\tin_progress\tone\tpts=3",
        "KAN-2\tin_progress\ttwo\tpts=3",
        "help: pandan get <id>",
        "help: pandan move <id> in_progress",
        "2 cards · 0 todo · 2 in_progress · 0 done",
    ]


def test_fields_projection_still_applies_only_to_human_output(monkeypatch, capsys):
    human = run_capture(
        monkeypatch, capsys, ["list", "--board", "5", "--fields", "ticket,title"], CARDS_PAGE
    )
    assert human.splitlines()[:2] == ["KAN-1\tone", "KAN-2\ttwo"]
    toon_out = run_capture(
        monkeypatch,
        capsys,
        ["list", "--board", "5", "--fields", "ticket,title", "--format", "toon"],
        CARDS_PAGE,
    )
    # The structured rows stay a verbatim passthrough — the projection is a property
    # of the human row, not of the payload. Only V44's `summary` joins them.
    decoded = decode(toon_out)
    assert decoded.pop("summary") == {
        "count": 2, "todo": 0, "in_progress": 2, "done": 0, "needs_human": 0
    }
    assert decoded == CARDS_PAGE


# --- 3. an unknown --format is a V43-shaped exit-2 error --------------------


def test_unknown_format_is_a_usage_error_on_stdout(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["--format", "yaml", "list"])
    assert exc.value.code == cli.EXIT_USAGE
    captured = capsys.readouterr()
    row = captured.out.strip().split("\t")
    assert row[0] == "error"
    assert row[1] == "usage"
    assert "yaml" in row[2]
    # The human usage block stays on stderr; stdout is the machine channel.
    assert "usage:" in captured.err
    assert "usage:" not in captured.out


def test_unknown_format_after_the_subcommand_is_the_same_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["list", "--format", "yaml"])
    assert exc.value.code == cli.EXIT_USAGE
    assert capsys.readouterr().out.split("\t")[1] == "usage"


def test_unknown_format_still_honours_an_accompanying_json_flag(capsys):
    """The rejected value can't select the error rendering, but ``--json`` can."""
    with pytest.raises(SystemExit) as exc:
        cli.run(["--json", "--format", "yaml", "list"])
    assert exc.value.code == cli.EXIT_USAGE
    err = json.loads(capsys.readouterr().out)["error"]
    assert err["code"] == "usage" and err["exit_code"] == cli.EXIT_USAGE


def test_every_format_name_is_accepted(capsys):
    for name in cli.OUTPUT_FORMATS:
        parser = cli.build_parser()
        assert parser.parse_args(["--format", name, "list"]).output_format == name


# --- --json remains a supported alias ---------------------------------------


def test_json_alias_is_byte_identical_to_format_json(monkeypatch, capsys):
    alias = run_capture(monkeypatch, capsys, ["get", "430", "--json"], CARD)
    explicit = run_capture(monkeypatch, capsys, ["get", "430", "--format", "json"], CARD)
    assert alias == explicit
    assert json.loads(alias) == CARD


def test_format_wins_when_both_are_given(monkeypatch, capsys):
    out = run_capture(monkeypatch, capsys, ["--json", "--format", "toon", "get", "430"], CARD)
    assert decode(out) == CARD
    assert not out.lstrip().startswith("{")


@pytest.mark.parametrize(
    "argv",
    [
        ["--format", "toon", "get", "430"],
        ["get", "--format", "toon", "430"],
        ["get", "430", "--format", "toon"],
        ["--format=toon", "get", "430"],
        ["get", "430", "--format=toon"],
    ],
    ids=["global", "mid", "trailing", "global-equals", "trailing-equals"],
)
def test_format_parses_in_every_position(monkeypatch, capsys, argv):
    assert decode(run_capture(monkeypatch, capsys, argv, CARD)) == CARD


# --- errors and local commands render in the chosen format ------------------


def test_errors_render_as_toon_and_carry_the_same_object_as_json(monkeypatch, capsys):
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    assert cli.run(["--format", "toon", "list"]) == cli.EXIT_ERROR
    toon_err = decode(capsys.readouterr().out)
    assert cli.run(["--json", "list"]) == cli.EXIT_ERROR
    json_err = json.loads(capsys.readouterr().out)
    assert toon_err == json_err
    assert toon_err["error"]["code"] == "config"
    # Every key is present even when it doesn't apply (the V43 promise).
    assert toon_err["error"]["arg"] is None and toon_err["error"]["status"] is None


def test_config_show_honours_the_format(capsys):
    cli.run(["config", "show", "--format", "toon"])
    as_toon = decode(capsys.readouterr().out)
    cli.run(["config", "show", "--json"])
    as_json = json.loads(capsys.readouterr().out)
    assert as_toon == as_json
    assert as_toon["token"].startswith("set (")

    cli.run(["config", "show"])
    human = capsys.readouterr().out
    assert human.splitlines()[0].startswith("api_url\t")


# --- the extension points the next three slices need ------------------------


def test_the_structured_payload_seam_feeds_both_formats(monkeypatch, capsys):
    """V44 reshaped ``_structured_payload`` and V45 did too; assert ``_emit`` really
    routes **both** structured formats through it, so neither slice can change one and
    miss the other — and that the human branch does *not* go through it (V44's summary
    reaches a human as a trailing line, not as a payload key).

    The stub also records the kwargs, pinning that V45's ``full``/``limit`` reach the
    seam for *both* formats: truncating json but not toon (or vice versa) is exactly
    the drift this one shared serializer exists to prevent."""
    marker = {"cards": [{"id": 1}], "summary": {"total": 1}}
    seen: list[dict] = []

    def stub(result, **kwargs):
        seen.append(kwargs)
        return marker

    monkeypatch.setattr(cli, "_structured_payload", stub)

    cli._emit({"cards": []}, fmt=cli.FORMAT_JSON, full=True, limit=7)
    assert json.loads(capsys.readouterr().out) == marker

    cli._emit({"cards": []}, fmt=cli.FORMAT_TOON, full=True, limit=7)
    assert decode(capsys.readouterr().out) == marker

    assert seen == [{"full": True, "limit": 7}, {"full": True, "limit": 7}]

    # The human branch bypassed the (patched) payload seam entirely: it printed the
    # real empty state and V44's own summary line, not the marker's `{"total": 1}`.
    cli._emit({"cards": []}, fmt=cli.FORMAT_HUMAN)
    out = capsys.readouterr().out
    assert out == "(no cards)\n0 cards · 0 todo · 0 in_progress · 0 done\n"
    assert "total" not in out


def test_structured_formats_are_exactly_json_and_toon():
    """V46 suppresses ``help[]`` hints for ``fmt in STRUCTURED_FORMATS``; pin the set
    so 'human' can never accidentally join it."""
    assert cli.STRUCTURED_FORMATS == ("json", "toon")
    assert cli.OUTPUT_FORMATS == ("human", "json", "toon")
    assert cli.FORMAT_HUMAN not in cli.STRUCTURED_FORMATS
