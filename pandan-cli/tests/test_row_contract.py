"""The row contract of the default human output — KAN-478 + KAN-485.

Two bugs in the same output helpers, both about a row being something other than it
claims, and both a *second* instance of a trap this project had already hit once:

**KAN-478 — a row must belong to the entity the verb returned.** ``_humanize``
dispatched on shape, and its ``list_cards`` branch keyed off the mere presence of a
``cards`` key. ``template create`` returns ONE template carrying a top-level ``cards``
array of card *definitions*, so it rendered as a card list — rows with ``?`` where a
ticket number would be, because unsaved definitions have no ticket. The ``?`` is the
tell. That is the KAN-277 trap (a single ``CardRead`` carries a ``labels`` array) in a
second shape, so the fix is the class and not the instance: ``_list_envelope`` already
knew the rule — a list envelope has no ``id``/``ticket_number`` of its own — and is now
the CLI's **only** definition of list-ness, shared by ``_humanize``, ``_project_rows``
and V44's ``_summary_for``.

**KAN-485 — one row must be one line.** Every list verb documents tab-separated rows,
one per entity, but a free-text cell with a newline in it has always spilled across
several output lines, so an agent counting rows over-counted and mis-associated ids
with bodies. The CLI already flattened this exact hazard on the ``--fields`` path
(V42) and not on the default row, which is what makes it a bug rather than a design
choice: ``comment list --fields body`` was safe while ``comment list`` was not. V45's
truncation *bounded* the spill (a 5692-char body no longer yields hundreds of lines)
but 500 characters of prose with two newlines in it is still three lines — do not
mistake the bound for a fix. There is now ONE flattening rule, ``cli._flatten``.

Every assertion here is written to fail for the right reason: the KAN-485 tests count
LINES (a "the text appears in the output" check passes whether or not the row is
flattened), and the KAN-478 tests pin whole rendered lines rather than the absence of
a substring.
"""
from __future__ import annotations

import json

import pytest

from pandan_cli import cli, config

LIMIT = config.DEFAULT_MAX_TEXT_CHARS

# The three characters that would break a tab-separated row, in the combinations real
# prose produces them: a bare LF, a CRLF pair, a lone CR, an embedded tab.
NASTY = "first\nsecond\r\nthird\rfourth\tfifth"


# --- fixtures ---------------------------------------------------------------


def _card(**extra) -> dict:
    """A realistic ``CardRead`` — carrying the ``labels`` array that is the original
    KAN-277 trap shape, plus the ``links``/``blocked_by``/``blocks`` arrays a card also
    carries (none of them an envelope name, but they are part of the same class)."""
    return {
        "id": 478,
        "ticket_number": "KAN-478",
        "board_id": 5,
        "title": "Ship it",
        "description": None,
        "column": "todo",
        "position": 1,
        "story_points": 1,
        "labels": [{"id": 1, "name": "bug", "color": "#f00"}],
        "links": [{"id": 3, "label": "PR", "url": "https://example.test/pr/1"}],
        "blocked_by": [],
        "blocks": [],
        **extra,
    }


def _template(**extra) -> dict:
    """A ``CardTemplateRead`` — what ``template create`` returns. The ``cards`` array
    holds unsaved card *definitions*: no id, no ticket number."""
    return {
        "id": 1,
        "board_id": 5,
        "name": "Slice",
        "cards": [
            {"title": "API", "column": "todo", "story_points": 3},
            {"title": "UI", "column": "todo"},
        ],
        "created_at": "2026-07-31T00:00:00Z",
        **extra,
    }


def _comment(cid: int, body: str) -> dict:
    return {"id": cid, "body": body, "author_id": None, "created_at": "2026-07-31T00:00:00Z"}


def _notification(nid: int, body: str) -> dict:
    return {
        "id": nid,
        "user_id": "u",
        "board_id": 5,
        "card_id": 7,
        "kind": "needs_human",
        "body": body,
        "read_at": None,
        "created_at": "2026-07-31T00:00:00Z",
    }


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
    file, no ``.mcp.json`` discovery, no ``PANDAN_*``/``KANBAN_*`` from the shell (a
    stray ``PANDAN_MAX_TEXT_CHARS`` would silently move the truncation expectations)."""
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


def without_hints(out: str) -> list[str]:
    """``out`` minus V46's ``help:`` next-step lines (KAN-429) — applied at the
    assertion site, never inside ``run_capture``, so a hint can never hide inside a
    line count this suite is measuring."""
    return [line for line in out.splitlines() if not line.startswith(cli.HINT_PREFIX)]


# --- 0. identity: what already rendered correctly is untouched ---------------
# Asserted BEFORE the intended effects. A "provably cosmetic" change on this project
# once carried two real behaviour changes; the boring test caught them.


@pytest.mark.parametrize(
    ("helper", "payload", "expected"),
    [
        ("_card_line", _card(), "KAN-478\ttodo\tShip it\tpts=1"),
        (
            "_epic_line",
            {"ticket_number": "EPIC-7", "name": "Sharpen", "progress": {
                "percent": 60, "done": 3, "total": 5}},
            "EPIC-7\tSharpen\t60% (3/5)",
        ),
        ("_board_line", {"id": 5, "name": "Pandan Roadmap"}, "5\tPandan Roadmap"),
        # KAN-614. A principal's id is a UUID, not an int — the row is still id-first,
        # tab-separated, one line.
        (
            "_me_line",
            {"id": "9f1d-not-a-card-id", "email": "you@example.test"},
            "9f1d-not-a-card-id\tyou@example.test",
        ),
        ("_label_line", {"id": 1, "name": "bug", "color": "#f00"}, "1\tbug\t#f00"),
        (
            "_view_line",
            {"id": 2, "name": "My WIP", "query": {"column": "todo"}},
            '2\tMy WIP\t{"column": "todo"}',
        ),
        (
            "_cycle_line",
            {"id": 3, "name": "S1", "starts_on": "2026-07-01", "ends_on": "2026-07-14"},
            "3\tS1\t2026-07-01\t2026-07-14",
        ),
        ("_template_line", _template(), "1\tSlice\t2 cards"),
        (
            "_activity_line",
            {"ts": "2026-07-31T00:00:00Z", "actor_label": "jian", "action": "created",
             "summary": "created KAN-3: Fix login"},
            "2026-07-31T00:00:00Z\tjian\tcreated\tcreated KAN-3: Fix login",
        ),
        ("_comment_line", _comment(9, "looks good"), "9\t2026-07-31T00:00:00Z\tlooks good"),
        (
            "_notification_line",
            _notification(4, "KAN-3 needs a human"),
            "4\tneeds_human\tunread\tKAN-3 needs a human",
        ),
        (
            "_link_line",
            {"id": 3, "label": "PR", "url": "https://example.test/pr/1"},
            "3\tPR\thttps://example.test/pr/1",
        ),
        ("_error_row", cli.CliError("nope", code="invalid_input", arg="--board"),
         "error\tinvalid_input\tnope\t--board"),
    ],
)
def test_a_row_of_ordinary_text_renders_byte_identically(helper, payload, expected):
    """Flattening is a no-op on text that has no control characters in it, so every
    row that rendered correctly before still renders **exactly** the same bytes."""
    assert getattr(cli, helper)(payload) == expected


def test_a_description_block_keeps_its_line_breaks():
    """The counterpart invariant: flattening applies to a ROW, never to the
    single-entity ``description:`` block, which is prose on its own lines by design."""
    card = _card(description="para one\n\npara two")
    rendered = cli._card_block(card, limit=LIMIT)
    assert rendered == f"{cli._card_line(card)}\ndescription:\npara one\n\npara two"
    assert "para one\n\npara two" in rendered


# --- 1. KAN-478: a row belongs to the entity the verb returned ---------------


def test_template_create_renders_the_template_and_not_its_card_definitions():
    """The bug: ``'?\\ttodo\\tAPI\\tpts=3'`` — the template's unsaved card definitions
    printed as card rows, with ``?`` standing in for a ticket number they do not have.
    It must render as the template it is, the same line ``template list`` prints."""
    template = _template()
    rendered = cli._humanize(template)
    assert rendered == "1\tSlice\t2 cards"
    assert rendered == cli._template_line(template)
    # The tells, asserted directly: no ticket-less rows, and one line for one entity.
    assert "?" not in rendered
    assert "pts=" not in rendered
    assert len(rendered.splitlines()) == 1


def test_template_create_and_template_list_render_the_same_entity_the_same_way():
    """One template, two verbs, one row shape — the consistency KAN-478 asks for."""
    template = _template()
    assert cli._humanize(template) == cli._humanize({"templates": [template]})


def test_a_single_card_with_labels_still_renders_as_one_card():
    """The original KAN-277 regression, which the unified guard now covers instead of
    the hand-written ``"ticket_number" not in result`` exception it replaced."""
    card = _card()
    assert cli._humanize(card) == cli._card_line(card)
    assert cli._humanize(card) == "KAN-478\ttodo\tShip it\tpts=1"
    assert "(no labels)" not in cli._humanize(card)


@pytest.mark.parametrize("key", cli._LIST_ENVELOPES)
def test_no_single_entity_carrying_an_envelope_array_can_render_as_rows(key):
    """The class guard — the point of the slice, and why a THIRD instance of this trap
    cannot appear silently.

    For **every** envelope name, a single entity that merely carries an array under
    that name must not be treated as a list by any of the three consumers, and must
    not print the array's contents as rows. The rule is the entity's own
    ``id``/``ticket_number``, so this holds for envelope names that do not exist yet."""
    marker = "ROW-MARKER"
    entity = {
        "id": 1,
        "name": "an entity",
        key: [{"id": 99, "title": marker, "name": marker, "body": marker,
               "summary": marker, "url": marker}],
    }
    assert cli._list_envelope(entity) is None
    assert cli._summary_for(entity) is None
    assert cli._project_rows(entity, ["id"]) is None
    rendered = cli._humanize(entity)
    assert len(rendered.splitlines()) == 1
    assert marker not in rendered


@pytest.mark.parametrize("key", cli._LIST_ENVELOPES)
def test_a_real_list_envelope_still_renders_one_row_per_entity(key):
    """The other half — proof the guard above excluded single entities and not lists.
    A genuine envelope (no ``id`` of its own) still prints its rows."""
    rows = [{"id": 1, "name": "a", "title": "a"}, {"id": 2, "name": "b", "title": "b"}]
    envelope = {key: rows}
    assert cli._list_envelope(envelope) == (key, rows)
    assert len(cli._humanize(envelope).splitlines()) == 2
    assert len(cli._project_rows(envelope, ["id"]).splitlines()) == 2


@pytest.mark.parametrize("key", cli._LIST_ENVELOPES)
def test_an_empty_envelope_keeps_its_definitive_zero_state(key):
    """AXI 5 — unchanged by the rewrite of the branch conditions."""
    assert cli._humanize({key: []}) == f"(no {key})"
    assert cli._project_rows({key: []}, ["id"]) == f"(no {key})"


def test_the_three_consumers_agree_on_list_ness_for_every_known_payload():
    """``_humanize``, ``_project_rows`` and ``_summary_for`` read list-ness from the
    one ``_list_envelope``. This pins the agreement over the payload shapes the API
    actually returns, single-entity-with-array shapes first."""
    single_entities = [
        _card(),                                        # CardRead: labels/links/blocked_by
        _template(),                                    # CardTemplateRead: cards
        {"id": 5, "name": "Roadmap", "owner_id": None},  # BoardRead
        {"id": 7, "ticket_number": "EPIC-7", "name": "Sharpen",
         "progress": {"percent": 0, "done": 0, "total": 0}},   # EpicRead
        {"id": 2, "name": "My WIP", "query": {}},              # SavedViewRead
        {"id": 3, "name": "S1", "starts_on": None, "ends_on": None},  # CycleRead
        {"id": 1, "name": "bug", "color": "#f00"},             # LabelRead
        _comment(9, "hi"),                                     # CommentRead
        _notification(4, "hi"),                                # NotificationRead
    ]
    for payload in single_entities:
        assert cli._list_envelope(payload) is None, payload
        assert cli._summary_for(payload) is None, payload
        assert cli._project_rows(payload, ["id"]) is None, payload
        # …and none of them renders as a multi-row list.
        assert len(cli._humanize(payload).splitlines()) == 1, payload

    lists = [
        {"cards": [_card()], "next_cursor": None},
        {"templates": [_template()]},
        {"comments": [_comment(9, "hi")]},
        {"notifications": [_notification(4, "hi")]},
    ]
    for payload in lists:
        key = next(iter(payload))
        assert cli._list_envelope(payload) == (key, payload[key])
        assert cli._summary_for(payload)[0] == key
        assert cli._project_rows(payload, ["id"]) is not None


def test_template_create_prints_the_template_line_end_to_end(monkeypatch, capsys):
    """Through ``run``, because that is what an agent scripting the verb sees."""
    template = _template()
    out = run_capture(
        monkeypatch,
        capsys,
        ["template", "create", "Slice", "--board", "5",
         "--cards", json.dumps(template["cards"])],
        template,
    )
    assert without_hints(out) == ["1\tSlice\t2 cards"]


# --- 2. KAN-485: one row, one line ------------------------------------------


@pytest.mark.parametrize(
    ("helper", "payload"),
    [
        ("_comment_line", _comment(1, NASTY)),
        ("_notification_line", _notification(1, NASTY)),
        ("_card_line", _card(title=NASTY)),
        ("_epic_line", {"ticket_number": "EPIC-7", "name": NASTY}),
        ("_board_line", {"id": 5, "name": NASTY}),
        ("_label_line", {"id": 1, "name": NASTY, "color": NASTY}),
        ("_view_line", {"id": 2, "name": NASTY, "query": {"q": NASTY}}),
        ("_cycle_line", {"id": 3, "name": NASTY}),
        ("_template_line", _template(name=NASTY)),
        ("_activity_line", {"ts": "t", "actor_label": NASTY, "action": "created",
                            "summary": NASTY}),
        ("_link_line", {"id": 3, "label": NASTY, "url": NASTY}),
        ("_warmup_line", {"status": "error", "detail": NASTY}),
        ("_error_row", cli.CliError(NASTY, code="invalid_input")),
    ],
)
def test_every_row_helper_renders_exactly_one_line(helper, payload):
    """The audit, as a test: every helper that prints a row of free text — not just the
    two that were noticed — collapses ``\\n``/``\\r``/``\\t`` so one entity is one line."""
    rendered = getattr(cli, helper)(payload)
    assert len(rendered.splitlines()) == 1
    assert "\n" not in rendered
    assert "\r" not in rendered


def test_the_flattened_cell_is_byte_identical_to_the_fields_path():
    """The two paths cannot drift again: the default row's body cell and
    ``--fields body`` render the same input to the same bytes, because both call
    ``_flatten``."""
    for raw in (NASTY, "a\nb", "a\r\nb", "a\tb", "plain", "", "trailing\n"):
        expected = cli._field_value(raw)
        assert cli._flatten(raw) == expected
        assert cli._comment_line(_comment(1, raw)).split("\t")[2] == expected
        assert cli._notification_line(_notification(1, raw)).split("\t")[3] == expected
        assert cli._project_line({"body": raw}, ["body"]) == expected
        # …and no cell ever gains or loses characters by being flattened.
        assert len(expected) == len(raw)


def test_flattening_happens_before_truncation():
    """Order matters twice over (V45 interaction): a newline near the limit must not
    change how much real text survives, and the size hint must land on THIS row."""
    body = "a\nb" * 400  # 1200 chars, well over the default limit
    rendered = cli._comment_line(_comment(1, body), limit=LIMIT)
    assert len(rendered.splitlines()) == 1
    # Exactly the limit's worth of real characters survived — the same prefix a body
    # with no newlines would have kept, flattened.
    kept = rendered.split("\t")[2]
    assert kept.startswith(cli._flatten(body)[:LIMIT])
    # The hint is on this row and its total is the TRUE original length (flattening is
    # length-preserving, so it cannot inflate or deflate the number).
    assert kept.endswith(cli._truncation_hint(len(body)))
    assert f"{len(body)} chars total" in rendered


@pytest.mark.parametrize(
    ("argv", "envelope", "rows", "expected_summary"),
    [
        (["comment", "list", "7"], "comments",
         [_comment(1, "a\nb"), _comment(2, "c\r\nd\te"), _comment(3, "plain")],
         "3 comments"),
        (["notify", "list"], "notifications",
         [_notification(1, "a\nb"), _notification(2, "c\r\nd"), _notification(3, "e")],
         "3 notifications · 3 unread"),
    ],
)
def test_the_printed_line_count_equals_the_row_count(
    monkeypatch, capsys, argv, envelope, rows, expected_summary
):
    """**The line-count assertion** — the one that goes red when the flatten is
    reverted, and the reason this suite does not assert "the body appears in the
    output" (which passes whether the row spilled or not).

    Three comments with newlines in them must be three rows plus V44's one aggregate
    line, and each row must carry its own id in the first cell."""
    out = run_capture(monkeypatch, capsys, argv, {envelope: rows})
    lines = without_hints(out)
    assert len(lines) == len(rows) + 1  # + the V44 aggregate
    assert lines[-1] == expected_summary
    # Splitting on newline associates each id with its own body, which is the property
    # that actually broke: `lines[i]` is row `i`.
    assert [line.split("\t")[0] for line in lines[:-1]] == [str(r["id"]) for r in rows]


def test_a_card_title_with_a_newline_does_not_add_a_row(monkeypatch, capsys):
    """The same property for the busiest verb — ``list`` — since a title is free text
    the API does not screen for control characters."""
    cards = [_card(title="one\ntwo"), _card(id=2, ticket_number="KAN-2", title="three")]
    out = run_capture(monkeypatch, capsys, ["list", "--board", "5"],
                      {"cards": cards, "next_cursor": None})
    lines = without_hints(out)
    assert len(lines) == 3  # two cards + the aggregate
    assert lines[0] == "KAN-478\ttodo\tone two\tpts=1"
