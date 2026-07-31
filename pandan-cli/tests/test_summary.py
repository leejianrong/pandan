"""Pre-computed aggregates on every list verb — the V44 (KAN-427) contract.

Four promises, and they are the whole slice:

1. **The aggregate matches the rows actually returned.** Every list verb's human
   output ends with one summary line whose count is ``len(rows)``, and whose
   breakdown totals those same rows.
2. **It describes the RETURNED SET, not the board.** Under ``--limit``, a filter, or
   one keyset page, the numbers describe what was printed. The CLI holds exactly one
   response and makes no second request, so a board-wide number would be a figure the
   caller could not reconcile with the rows above it.
3. **An empty result still prints its definitive zero state** (AXI 5) — the
   ``(no <things>)`` line *and* a machine-parseable zero.
4. **Under ``--json``/``--format toon`` the numbers ride the payload as a ``summary``
   object** instead of a trailing line, and they are the *same* numbers, because both
   renderings read one dict computed once (``_summary_for``).

The verb table below is enumerated from ``cli._LIST_ENVELOPES`` + ``dep list`` (the one
list verb whose response is two arrays rather than an envelope), not from a doc — a
test pins the table against that tuple so a new list verb cannot skip its aggregate.
"""
from __future__ import annotations

import json

import pytest
from toon_decode import decode

from pandan_cli import cli, config

# --- fixtures ---------------------------------------------------------------


def _card(ticket: str, column: str = "todo", *, needs_human: bool = False) -> dict:
    """A realistic ``CardRead`` row — carries ``labels`` (the KAN-277 trap shape) and
    ``needs_human`` so the aggregate under test reads the real field names."""
    return {
        "id": int(ticket.split("-")[1]),
        "ticket_number": ticket,
        "board_id": 5,
        "title": f"card {ticket}",
        "column": column,
        "story_points": 3,
        "needs_human": needs_human,
        "labels": [],
    }


def _epic(ticket: str, done: int, total: int, health: str | None) -> dict:
    percent = round(done / total * 100) if total else 0
    return {
        "id": int(ticket.split("-")[1]),
        "ticket_number": ticket,
        "board_id": 5,
        "name": f"epic {ticket}",
        "target_date": None if health is None else "2026-08-15",
        "lead": None,
        "progress": {"total": total, "done": done, "percent": percent},
        "health": health,
    }


# One populated response per list verb: (argv, result, expected summary line).
# The expected line is spelled out literally — that is the deliverable, and a
# computed expectation would restate the implementation instead of pinning it.
POPULATED: dict[str, tuple[list[str], dict, str]] = {
    "list": (
        ["list", "--board", "5"],
        {
            "cards": [
                _card("KAN-1", "todo"),
                _card("KAN-2", "todo"),
                _card("KAN-3", "in_progress", needs_human=True),
                _card("KAN-4", "done"),
            ],
            "next_cursor": None,
        },
        "4 cards · 2 todo · 1 in_progress · 1 done · 1 needs-human",
    ),
    # `batch-create` (KAN-502) returns `create_cards`' own {"created": [...]} envelope,
    # whose rows are cards — so it totals exactly like `list`, and the aggregate is the
    # cheapest way for the caller to confirm what actually landed on a fail-fast verb.
    "batch-create": (
        ["batch-create", '[{"title": "a"}, {"title": "b"}, {"title": "c"}]', "--board", "5"],
        {"created": [
            _card("KAN-11", "todo"),
            _card("KAN-12", "todo"),
            _card("KAN-13", "in_progress"),
        ]},
        "3 cards · 2 todo · 1 in_progress · 0 done",
    ),
    # `batch-update` (KAN-519) returns `update_cards`' own {"updated": [...]} envelope —
    # `PATCH /cards/batch`, `response_model=list[CardRead]`, so the rows are cards and it
    # totals like `list`. It reached this table late: the key was unrecognised, so the
    # verb printed raw `json.dumps` and no aggregate at all.
    "batch-update": (
        ["batch-update", '[{"id": 21, "assignee": "a"}, {"id": 22, "assignee": "a"}]'],
        {"updated": [_card("KAN-21", "in_progress"), _card("KAN-22", "done")]},
        "2 cards · 0 todo · 1 in_progress · 1 done",
    ),
    "board list": (
        ["board", "list"],
        {"boards": [{"id": 5, "name": "Roadmap", "owner_id": 1}]},
        "1 board",
    ),
    "epic list": (
        ["epic", "list", "--board", "5"],
        {
            "epics": [
                _epic("EPIC-3", 5, 5, None),
                _epic("EPIC-67", 3, 8, "at_risk"),
                _epic("EPIC-70", 0, 2, "overdue"),
            ]
        },
        "3 epics · 8/15 stories done (53%) · 1 at_risk · 1 overdue",
    ),
    "label list": (
        ["label", "list", "--board", "5"],
        {"labels": [
            {"id": 1, "name": "bug", "color": "#f00"},
            {"id": 2, "name": "chore", "color": "#0f0"},
        ]},
        "2 labels",
    ),
    "view list": (
        ["view", "list", "--board", "5"],
        {"views": [{"id": 1, "board_id": 5, "name": "My WIP", "query": {"column": "todo"}}]},
        "1 view",
    ),
    "template list": (
        ["template", "list", "--board", "5"],
        {"templates": [
            {"id": 1, "board_id": 5, "name": "Slice", "cards": [{"title": "a"}, {"title": "b"}]},
            {"id": 2, "board_id": 5, "name": "Bug", "cards": [{"title": "c"}]},
        ]},
        "2 templates",
    ),
    "cycle list": (
        ["cycle", "list", "--board", "5"],
        {"cycles": [
            {"id": 1, "name": "S1", "starts_on": "2026-07-01", "ends_on": "2026-07-14"}
        ]},
        "1 cycle",
    ),
    "notify list": (
        ["notify", "list"],
        {"notifications": [
            {"id": 1, "kind": "needs_human", "body": "b1", "read_at": None},
            {"id": 2, "kind": "mention", "body": "b2", "read_at": "2026-07-31T00:00:00Z"},
            {"id": 3, "kind": "blocked", "body": "b3", "read_at": None},
        ]},
        "3 notifications · 2 unread",
    ),
    "activity": (
        ["activity", "--board", "5"],
        {"activity": [
            {"ts": "t1", "actor_label": "me", "action": "moved", "summary": "s1"},
            {"ts": "t2", "actor_label": None, "action": "updated", "summary": "s2"},
        ], "next_cursor": None},
        "2 activity rows",
    ),
    "comment list": (
        ["comment", "list", "7"],
        {"comments": [
            {"id": 9, "body": "hi", "author_id": None, "created_at": "t"},
        ]},
        "1 comment",
    ),
    "dep list": (
        ["dep", "list", "7"],
        {"card_id": 7, "blocked_by": [3, 9], "blocks": [11]},
        "2 blocked_by · 1 blocks",
    ),
}

# One EMPTY response per list verb: (argv, result, expected full human output).
# Both lines matter: the prose zero state (AXI 5) and the machine-parseable zero.
EMPTY: dict[str, tuple[list[str], dict, str]] = {
    "list": (
        ["list", "--board", "5"],
        {"cards": [], "next_cursor": None},
        # `list` is the one hinted verb here (KAN-492), and its hints land between the
        # prose zero-state and the aggregate — which is what keeps `tail -1` the count.
        # Both of them carry `<id>`, though, so on an EMPTY result both are dropped
        # (KAN-526): they were next steps on rows this very call said do not exist.
        # The zero state and the aggregate are untouched by that — this line is what
        # asserts the drop did not eat either of them.
        "(no cards)\n0 cards · 0 todo · 0 in_progress · 0 done\n",
    ),
    # The zero state keeps the envelope's own name (`created`), like every other verb
    # here — the CLI never re-labels the client's key (see `cli._CARD_ENVELOPES`).
    "batch-create": (
        ["batch-create", "[]", "--board", "5"],
        {"created": []},
        "(no created)\n0 cards · 0 todo · 0 in_progress · 0 done\n",
    ),
    # Same rule, same envelope name kept verbatim: `(no updated)`, not `(no cards)`.
    "batch-update": (
        ["batch-update", "[]"],
        {"updated": []},
        "(no updated)\n0 cards · 0 todo · 0 in_progress · 0 done\n",
    ),
    "board list": (["board", "list"], {"boards": []}, "(no boards)\n0 boards\n"),
    "epic list": (
        ["epic", "list", "--board", "5"],
        {"epics": []},
        "(no epics)\n0 epics · 0/0 stories done (0%)\n",
    ),
    "label list": (
        ["label", "list", "--board", "5"], {"labels": []}, "(no labels)\n0 labels\n"
    ),
    "view list": (["view", "list", "--board", "5"], {"views": []}, "(no views)\n0 views\n"),
    "template list": (
        ["template", "list", "--board", "5"],
        {"templates": []},
        "(no templates)\n0 templates\n",
    ),
    "cycle list": (
        ["cycle", "list", "--board", "5"], {"cycles": []}, "(no cycles)\n0 cycles\n"
    ),
    "notify list": (
        ["notify", "list"],
        {"notifications": []},
        "(no notifications)\n0 notifications · 0 unread\n",
    ),
    "activity": (
        ["activity", "--board", "5"],
        {"activity": [], "next_cursor": None},
        "(no activity)\n0 activity rows\n",
    ),
    "comment list": (
        ["comment", "list", "7"], {"comments": []}, "(no comments)\n0 comments\n"
    ),
    "dep list": (
        ["dep", "list", "7"],
        {"card_id": 7, "blocked_by": [], "blocks": []},
        "card 7\nblocked_by:\t(none)\nblocks:\t(none)\n0 blocked_by · 0 blocks\n",
    ),
}

VERBS = sorted(POPULATED)


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
    """Same hermeticity the other suites' autouse fixtures provide: no ambient config
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
    since KAN-492, **above** the aggregate line this suite is about.

    Applied at the assertion site and deliberately **not** inside ``run_capture``:
    every "stdout still parses as JSON/TOON" check in this suite must stay able to
    catch a hint leaking into a structured format. The hints themselves are pinned in
    ``tests/test_content_first.py``."""
    return "".join(f"{line}\n" for line in out.splitlines() if not line.startswith(cli.HINT_PREFIX))


# --- 1. every list verb ends with its aggregate -----------------------------


@pytest.mark.parametrize("verb", VERBS)
def test_every_list_verb_ends_with_its_aggregate(monkeypatch, capsys, verb):
    argv, result, expected = POPULATED[verb]
    out = run_capture(monkeypatch, capsys, argv, result)
    assert out.splitlines()[-1] == expected


@pytest.mark.parametrize("verb", VERBS)
def test_the_aggregate_does_not_disturb_the_rows_above_it(monkeypatch, capsys, verb):
    """The summary is *appended*: strip the last line and what remains is exactly what
    ``_humanize`` produced before this slice. (Hints are stripped first — since KAN-492
    ``list`` carries them, and they sit between the rows and the aggregate.)"""
    argv, result, _ = POPULATED[verb]
    out = without_hints(run_capture(monkeypatch, capsys, argv, result))
    rows = "\n".join(out.splitlines()[:-1])
    assert rows == cli._humanize(result)


@pytest.mark.parametrize("verb", VERBS)
def test_the_count_matches_the_rows_actually_printed(monkeypatch, capsys, verb):
    """The headline number is ``len(rows)`` — the rows the verb printed, counted."""
    argv, result, _ = POPULATED[verb]
    if verb == "dep list":
        pytest.skip("dep list has two arrays and no single row count")
    kind, summary = cli._summary_for(result)
    out = without_hints(run_capture(monkeypatch, capsys, argv, result))
    printed_rows = len(out.splitlines()) - 1  # minus the aggregate itself
    assert summary["count"] == printed_rows
    assert summary["count"] == len(result[kind])
    assert out.splitlines()[-1].startswith(f"{summary['count']} ")


def test_card_buckets_total_the_returned_rows():
    _, result, _ = POPULATED["list"]
    _, summary = cli._summary_for(result)
    assert sum(summary[column] for column in cli.COLUMNS) == summary["count"]
    # Buckets are derived from COLUMNS, so a new board column extends the summary
    # rather than silently vanishing from it.
    assert set(cli.COLUMNS) <= set(summary)


def test_epic_rollup_spread_sums_the_returned_epics_child_stories():
    _, result, _ = POPULATED["epic list"]
    _, summary = cli._summary_for(result)
    epics = result["epics"]
    assert summary["stories_total"] == sum(e["progress"]["total"] for e in epics)
    assert summary["stories_done"] == sum(e["progress"]["done"] for e in epics)
    assert summary["percent"] == round(
        summary["stories_done"] / summary["stories_total"] * 100
    )
    # `health` is null for an epic with no target_date, so the buckets need not sum
    # to `count` — EPIC-3 is in none of them.
    assert summary["on_track"] + summary["at_risk"] + summary["overdue"] == 2
    assert summary["count"] == 3


def test_notification_read_unread_split_totals_the_rows():
    """A sums-to-count assertion alone is a **blind guard** — `unread = 0` satisfies it
    (mutation-tested). So pin the split itself against the rows' `read_at`."""
    _, result, _ = POPULATED["notify list"]
    _, summary = cli._summary_for(result)
    rows = result["notifications"]
    assert summary["unread"] == sum(1 for n in rows if not n["read_at"]) == 2
    assert summary["read"] == sum(1 for n in rows if n["read_at"]) == 1
    assert summary["unread"] + summary["read"] == summary["count"]


def test_dep_summary_counts_both_edge_directions():
    _, result, _ = POPULATED["dep list"]
    _, summary = cli._summary_for(result)
    assert summary == {"blocked_by": 2, "blocks": 1}


def test_needs_human_is_appended_only_when_non_zero(monkeypatch, capsys):
    """A board with no pending handoff must not carry a permanent ``· 0 needs-human``;
    one with a handoff must say so without a second request."""
    quiet = {"cards": [_card("KAN-1", "todo")]}
    out = run_capture(monkeypatch, capsys, ["list", "--board", "5"], quiet)
    assert out.splitlines()[-1] == "1 card · 1 todo · 0 in_progress · 0 done"
    assert "needs-human" not in out

    flagged = {"cards": [_card("KAN-1", "todo", needs_human=True)]}
    out = run_capture(monkeypatch, capsys, ["list", "--board", "5"], flagged)
    assert out.splitlines()[-1] == (
        "1 card · 1 todo · 0 in_progress · 0 done · 1 needs-human"
    )
    # …but the structured form always carries the key, so a consumer never has to
    # test for absence.
    _, summary = cli._summary_for(quiet)
    assert summary["needs_human"] == 0


def test_the_noun_is_singular_for_exactly_one_row(monkeypatch, capsys):
    out = run_capture(monkeypatch, capsys, ["board", "list"], {"boards": [{"id": 1, "name": "a"}]})
    assert out.splitlines()[-1] == "1 board"
    out = run_capture(
        monkeypatch,
        capsys,
        ["board", "list"],
        {"boards": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]},
    )
    assert out.splitlines()[-1] == "2 boards"


# --- 2. the aggregate describes the RETURNED SET, not the board --------------


def test_a_limited_page_reports_the_page_not_the_board(monkeypatch, capsys):
    """``--limit 2`` over a board of many: the aggregate counts the two rows returned.
    Asserted explicitly because the opposite (a board-wide total) is the tempting
    reading of "pre-computed aggregate" and would be a number the caller cannot
    reconcile with the rows above it."""
    page = {"cards": [_card("KAN-1", "todo"), _card("KAN-2", "done")], "next_cursor": "KAN-2"}
    out = run_capture(monkeypatch, capsys, ["list", "--board", "5", "--limit", "2"], page)
    assert out.splitlines()[-1] == "2 cards · 1 todo · 0 in_progress · 1 done"
    # The keyset hint says more rows exist; the aggregate still describes this page.
    assert "(more — next cursor: KAN-2)" in out


def test_a_filtered_list_reports_the_filtered_set(monkeypatch, capsys):
    """``--column todo`` → the other buckets are a definitive 0, not the board's."""
    page = {"cards": [_card("KAN-1", "todo"), _card("KAN-2", "todo")], "next_cursor": None}
    out = run_capture(
        monkeypatch, capsys, ["list", "--board", "5", "--column", "todo"], page
    )
    assert out.splitlines()[-1] == "2 cards · 2 todo · 0 in_progress · 0 done"


def test_a_board_wide_total_in_the_payload_is_never_borrowed():
    """The count is computed from the rows, never read off a field. If the API ever
    grows a board-wide `total`, the aggregate must keep describing the returned set —
    so a payload carrying a bogus one is ignored."""
    _, summary = cli._summary_for(
        {"cards": [_card("KAN-1", "todo")], "total": 9999, "count": 9999}
    )
    assert summary["count"] == 1
    assert summary["todo"] == 1


# --- 3. an empty result still prints its definitive zero state (AXI 5) -------


@pytest.mark.parametrize("verb", VERBS)
def test_an_empty_result_prints_its_definitive_zero_state(monkeypatch, capsys, verb):
    argv, result, expected = EMPTY[verb]
    assert run_capture(monkeypatch, capsys, argv, result) == expected


@pytest.mark.parametrize("verb", VERBS)
def test_an_empty_result_keeps_its_prose_zero_state_too(monkeypatch, capsys, verb):
    """The pre-V44 ``(no cards)`` line is the AXI 5 promise and must survive the
    aggregate landing beneath it — asserted separately so a regression names itself.

    The obvious spelling of this (``_humanize(result) in out``) is a **blind guard**:
    it passes for a humanizer that returns the empty string, because ``"" in out`` is
    always true. Mutation-tested. So assert the prose exists, is non-empty, and comes
    FIRST — above the aggregate, where a reader meets it."""
    argv, result, _ = EMPTY[verb]
    out = without_hints(run_capture(monkeypatch, capsys, argv, result))
    prose = cli._humanize(result).splitlines()
    assert prose and all(line.strip() for line in prose)
    assert out.splitlines()[: len(prose)] == prose
    assert len(out.splitlines()) == len(prose) + 1  # exactly one aggregate line


# --- 4. structured formats carry a `summary` object, not a trailing line -----


@pytest.mark.parametrize("verb", VERBS)
def test_json_carries_summary_beside_the_rows_and_no_trailing_line(
    monkeypatch, capsys, verb
):
    argv, result, _ = POPULATED[verb]
    out = run_capture(monkeypatch, capsys, [*argv, "--json"], result)
    parsed = json.loads(out)  # the whole of stdout is one JSON document …
    assert "·" not in out  # … so there is no trailing human line anywhere in it
    assert parsed["summary"] == cli._summary_for(result)[1]
    # The rows themselves are untouched — `summary` is the only added key.
    assert {k: v for k, v in parsed.items() if k != "summary"} == result


@pytest.mark.parametrize("verb", VERBS)
def test_toon_carries_the_same_summary_and_round_trips(monkeypatch, capsys, verb):
    """The V47 round-trip contract has to survive V44's new nested object: the TOON
    rendering must decode back to exactly the ``--json`` one, ``summary`` included."""
    argv, result, _ = POPULATED[verb]
    json_out = run_capture(monkeypatch, capsys, [*argv, "--json"], result)
    toon_out = run_capture(monkeypatch, capsys, [*argv, "--format", "toon"], result)
    assert decode(toon_out) == json.loads(json_out)
    assert decode(toon_out)["summary"] == cli._summary_for(result)[1]
    assert "·" not in toon_out


@pytest.mark.parametrize("verb", VERBS)
def test_the_human_line_and_the_structured_summary_report_one_number(
    monkeypatch, capsys, verb
):
    """Human and ``--json`` must never disagree about the count. Both read the dict
    ``_summary_for`` computes once; this asserts it end-to-end, through argv."""
    argv, result, _ = POPULATED[verb]
    if verb == "dep list":
        pytest.skip("dep list's line leads with an edge count, not a row count")
    human = run_capture(monkeypatch, capsys, argv, result)
    structured = json.loads(run_capture(monkeypatch, capsys, [*argv, "--json"], result))
    leading = int(human.splitlines()[-1].split(" ")[0])
    assert leading == structured["summary"]["count"]


def test_the_human_line_is_rendered_from_the_summary_dict_not_recomputed():
    """``_summary_line`` reads the very dict ``_structured_payload`` attaches — feed it
    a doctored one and the line follows. That is *why* the two renderings cannot drift:
    there is one computation, not two."""
    kind, summary = cli._summary_for(POPULATED["list"][1])
    doctored = cli._summary_line(kind, {**summary, "count": 999})
    assert doctored.startswith("999 cards")
    bumped = cli._summary_line(kind, {**summary, "todo": 42})
    assert bumped.split(" · ")[1] == "42 todo"


# --- 5. only list results get an aggregate ----------------------------------
# A single entity, a delete receipt, metrics: nothing to total, and a stray count
# line would be noise an agent has to learn to ignore.

NON_LIST_RESULTS = {
    "get": (["get", "1"], _card("KAN-1", "todo")),
    "create": (["create", "T"], _card("KAN-1", "todo")),
    "move": (["move", "1", "done"], _card("KAN-1", "done")),
    "delete": (["delete", "1", "--yes"], {"deleted": 1}),
    "epic create": (["epic", "create", "E"], _epic("EPIC-1", 1, 2, "on_track")),
    "warmup": (["warmup"], {"status": "ok"}),
    "next": (["next", "--board", "5"], {"card": _card("KAN-1", "todo")}),
    "link add": (
        ["link", "add", "1", "--url", "https://e.example/1", "--label", "PR"],
        {"card_id": 1, "links": [{"id": 1, "label": "PR", "url": "https://e.example/1"}]},
    ),
    "notify read": (
        ["notify", "read", "1"],
        {"id": 1, "kind": "mention", "body": "b", "read_at": "t"},
    ),
    "metrics": (
        ["metrics", "--board", "5"],
        {"board_id": 5, "throughput": 3, "cycle_time": {"count": 3}, "aging_wip": {}},
    ),
}


@pytest.mark.parametrize("name", sorted(NON_LIST_RESULTS))
def test_a_non_list_result_gets_no_aggregate(monkeypatch, capsys, name):
    argv, result = NON_LIST_RESULTS[name]
    assert cli._summary_for(result) is None
    out = run_capture(monkeypatch, capsys, argv, result)
    assert "·" not in out
    assert without_hints(out) == cli._humanize(result, noun="card") + "\n"
    # …and no `summary` key sneaks into the structured rendering either.
    structured = run_capture(monkeypatch, capsys, [*argv, "--json"], result)
    assert "summary" not in json.loads(structured)


def test_a_single_template_is_not_counted_as_a_card_list(monkeypatch, capsys):
    """``template create`` returns ONE template whose payload carries a top-level
    ``cards`` array — the KAN-277 trap, second instance. It must not be aggregated as
    a card list (``2 cards · 2 todo …`` would be a lie about a template)."""
    template = {
        "id": 1, "board_id": 5, "name": "Slice",
        "cards": [{"title": "API", "column": "todo"}, {"title": "UI", "column": "todo"}],
    }
    assert cli._summary_for(template) is None
    out = run_capture(
        monkeypatch,
        capsys,
        [
            "template", "create", "Slice",
            "--board", "5", "--cards", json.dumps(template["cards"]),
        ],
        template,
    )
    assert "cards ·" not in out
    # KAN-478 sharpened this. The original second assertion was ``"2 cards" not in
    # out``, which passed for the wrong reason: the verb was printing the template's
    # unsaved card *definitions* as rows (``?\ttodo\tAPI\tpts=3``), so no aggregate and
    # no card count appeared. The template's own row legitimately reports its card
    # count — ``template list`` has always printed ``2 cards`` for this same entity —
    # so what must be absent is the card *aggregate*, asserted above. Pin the whole
    # line instead: exactly one row, and it is the template's.
    assert without_hints(out) == f"{cli._template_line(template)}\n"


def test_a_single_card_is_not_counted_as_a_label_list(monkeypatch, capsys):
    """The original KAN-277 trap: a ``CardRead`` carries a ``labels`` array. ``get``
    must not report ``2 labels``."""
    card = {**_card("KAN-1", "todo"), "labels": [
        {"id": 1, "name": "bug", "color": "#f00"},
        {"id": 2, "name": "chore", "color": "#0f0"},
    ]}
    assert cli._summary_for(card) is None
    out = run_capture(monkeypatch, capsys, ["get", "1"], card)
    assert "labels" not in out
    assert "·" not in out


# --- 6. drift guards --------------------------------------------------------


def test_every_list_envelope_has_a_summary_noun():
    """``_SUMMARY_NOUN`` and ``_LIST_ENVELOPES`` are pinned together: a new list verb
    cannot ship an aggregate reading "1 cycles" (or KeyError on a missing noun)."""
    assert set(cli._SUMMARY_NOUN) == set(cli._LIST_ENVELOPES)
    assert set(cli._ROW_NOUN) == set(cli._LIST_ENVELOPES)
    for key, (singular, plural) in cli._SUMMARY_NOUN.items():
        assert singular and plural, key
        assert singular != plural or key == "activity", key


def test_the_verb_table_covers_every_list_envelope():
    """This file's own coverage guard: every envelope in ``_LIST_ENVELOPES`` is
    exercised by a populated AND an empty case, plus ``dep list`` on top."""
    covered = {cli._list_envelope(result)[0] for _, result, _ in POPULATED.values()
               if cli._list_envelope(result) is not None}
    assert covered == set(cli._LIST_ENVELOPES)
    assert set(POPULATED) == set(EMPTY)
    assert "dep list" in POPULATED


def test_epic_health_buckets_match_the_api_vocabulary():
    """``_EPIC_HEALTHS`` mirrors the backend's ``EpicHealth`` enum; a value the CLI
    doesn't know is ignored rather than crashing the aggregate."""
    assert cli._EPIC_HEALTHS == ("on_track", "at_risk", "overdue")
    _, summary = cli._summary_for({"epics": [_epic("EPIC-1", 1, 2, "brand_new")]})
    assert summary["count"] == 1
    assert summary["on_track"] == summary["at_risk"] == summary["overdue"] == 0


def test_an_unknown_column_still_counts_in_the_headline():
    """``column`` is a varchar + CHECK precisely so a value can be added cheaply. Until
    ``COLUMNS`` learns it, such a row lands in no bucket — but it must still be
    counted, so the headline number never under-reports the rows printed."""
    _, summary = cli._summary_for({"cards": [_card("KAN-1", "todo"), _card("KAN-2", "blocked")]})
    assert summary["count"] == 2
    assert sum(summary[column] for column in cli.COLUMNS) == 1
