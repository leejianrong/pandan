"""KAN-501: the read tools narrow their result and truncate long free text.

Read in the order written — the first section is the one that would catch a
regression the rest cannot. ADR 0019's own postmortem: a "provably cosmetic" schema
change contained two real behaviour changes, and the boring invariant test ("every
property name and required set is preserved") caught them, not the clever one. So
here the boring test comes first: **with no arguments, a read returns exactly what
the API returned.** Only then is narrowing asserted.

Every behavioural test drives the **production tool function** through a mocked
transport, not the helper in isolation. A test that only exercises
``shaping.project`` proves the helper works, not that ``list_cards`` calls it — and
the seam is where this slice could silently fail.

**KAN-517 (§3b) is the second pass**, over the nine reads KAN-501 documented as
deliberately left raw. It measured all nine against the real board and extended
three; the other six are pinned as *still unshaped*, because "shape everything for
symmetry" is the trade ADR 0019 explicitly rejected.
"""
from __future__ import annotations

import copy
import json

import httpx
import pytest
from pandan_client import PandanClient

from pandan_mcp import server, shaping

# A card exactly as the live API returns one: all 22 keys, verified against a real
# capture from board 5 (see scripts/measure_read_payload_tokens.py). 22 keys × 125
# rows, most of them null, is the 48k-token payload this slice exists to shrink.
CARD = {
    "id": 10,
    "ticket_number": "KAN-10",
    "title": "Wire the fields argument",
    "description": "x" * 1200,
    "column": "todo",
    "position": 3,
    "story_points": 3,
    "assignee": None,
    "epic_id": None,
    "cycle_id": None,
    "board_id": 5,
    "priority": "high",
    "due_date": None,
    "needs_human": False,
    "attention_note": None,
    "blocked": False,
    "blocked_by": [],
    "blocks": [],
    "labels": [],
    "links": [{"id": 1, "label": "PR", "url": "https://example.test/" + "p" * 900}],
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-02T00:00:00Z",
}


def _client(monkeypatch, response, seen=None):
    """Point the server's client at a MockTransport returning ``response``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["params"] = dict(request.url.params)
        return response

    monkeypatch.setattr(
        server, "_client", PandanClient("http://test", transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(server, "_default_board_id", None)


def _cards_response(*cards, headers=None):
    return httpx.Response(200, json=list(cards), headers=headers or {})


def _keyshape(value):
    """A payload's key structure, recursively — values stripped away. Two payloads
    with the same keyshape are the same *contract* however their values differ."""
    if isinstance(value, dict):
        return {key: _keyshape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_keyshape(item) for item in value]
    return None


# --- 1. the identity invariants (assert these before anything clever) --------


def test_a_default_read_is_unchanged_key_for_key(monkeypatch):
    """No ``fields``: the response carries exactly the API's keys, at every depth.

    This is the guard against the whole slice being a silent breaking change. It is
    deliberately about *keys*, because truncation legitimately changes a value.
    """
    _client(monkeypatch, _cards_response(CARD))
    out = server.list_cards()
    assert _keyshape(out) == _keyshape({"cards": [CARD]})


def test_a_default_read_changes_no_value_except_the_truncated_text(monkeypatch):
    """Every non-free-text value is passed through untouched — including the two
    long strings V45's allow-list deliberately protects (a link ``url`` here, a
    ``next_cursor`` below)."""
    _client(monkeypatch, _cards_response(CARD))
    row = server.list_cards()["cards"][0]
    for key, value in CARD.items():
        if key == "description":
            continue
        assert row[key] == value, f"{key} was altered by shaping"
    assert row["links"][0]["url"] == CARD["links"][0]["url"]


def test_full_returns_the_payload_completely_untouched(monkeypatch):
    """``full=true`` is the escape hatch, and it must be exact — not "nearly the
    original". Compared with ``==`` on the whole payload, not field by field."""
    _client(monkeypatch, _cards_response(CARD))
    assert server.list_cards(full=True) == {"cards": [CARD]}


def test_shaping_never_mutates_its_input():
    """The tools hand ``shape`` the client's own dict; shaping must copy, not edit
    in place, or a caller holding the payload sees it change under them."""
    original = copy.deepcopy(CARD)
    shaping.shape({"cards": [CARD]}, fields=["title"])
    assert CARD == original


def test_env_zero_disables_truncation_globally(monkeypatch):
    """``PANDAN_MAX_TEXT_CHARS=0`` is the deployment-wide form of ``full=true``."""
    monkeypatch.setenv(shaping.ENV_MAX_TEXT_CHARS, "0")
    _client(monkeypatch, _cards_response(CARD))
    assert server.list_cards() == {"cards": [CARD]}


def test_a_junk_text_limit_falls_back_to_the_default(monkeypatch):
    """An output-shaping preference must never be able to fail a board read."""
    monkeypatch.setenv(shaping.ENV_MAX_TEXT_CHARS, "not-a-number")
    assert shaping.max_text_chars() == shaping.DEFAULT_MAX_TEXT_CHARS
    monkeypatch.setenv(shaping.ENV_MAX_TEXT_CHARS, "-5")
    assert shaping.max_text_chars() == shaping.DEFAULT_MAX_TEXT_CHARS


# --- 2. narrowing, through the real tools -----------------------------------


def test_a_narrowed_list_returns_only_the_requested_fields(monkeypatch):
    _client(monkeypatch, _cards_response(CARD, {**CARD, "id": 11}))
    out = server.list_cards(fields=["ticket_number", "title", "column"])
    assert [list(row) for row in out["cards"]] == [
        ["ticket_number", "title", "column"],
        ["ticket_number", "title", "column"],
    ]
    assert out["cards"][0] == {
        "ticket_number": "KAN-10",
        "title": CARD["title"],
        "column": "todo",
    }


def test_narrowing_uses_the_canonical_key_for_an_alias(monkeypatch):
    """``ticket``/``pts`` are accepted (the CLI's vocabulary) but the payload keeps
    the API's own names, so a consumer reading ``.ticket_number`` still works."""
    _client(monkeypatch, _cards_response(CARD))
    assert server.list_cards(fields=["ticket", "pts"])["cards"][0] == {
        "ticket_number": "KAN-10",
        "story_points": 3,
    }


def test_a_comma_joined_element_is_split(monkeypatch):
    """An agent porting the CLI's ``--fields ticket,title`` habit sends one element
    containing a comma. Do the obvious thing rather than erroring on a field called
    ``ticket,title``."""
    _client(monkeypatch, _cards_response(CARD))
    assert list(server.list_cards(fields=["ticket_number,title"])["cards"][0]) == [
        "ticket_number",
        "title",
    ]


def test_narrowing_preserves_the_pagination_cursor(monkeypatch):
    """``next_cursor`` is how the caller pages. Narrowing must not eat it, and
    truncation must never cut it however long it gets."""
    cursor = "c" * 900
    _client(monkeypatch, _cards_response(CARD, headers={"X-Next-Cursor": cursor}))
    out = server.list_cards(fields=["title"])
    assert out["next_cursor"] == cursor
    assert list(out) == ["cards", "next_cursor"]


def test_a_single_card_read_narrows_its_own_keys(monkeypatch):
    _client(monkeypatch, httpx.Response(200, json=CARD))
    assert server.get_card(10, fields=["ticket_number", "column"]) == {
        "ticket_number": "KAN-10",
        "column": "todo",
    }


def test_a_single_object_is_never_mistaken_for_a_row_envelope(monkeypatch):
    """**The trap this slice's envelope detection exists for**, and the reason the
    detection checks the payload's *shape* and not only its keys' names.

    A card already carries two inline arrays (``labels``, ``links``); the day one of
    them is named like an envelope — a ``comments`` array inlined on a card is the
    obvious candidate, and ``list_dependencies`` already reshapes card reads — a
    name-only rule would read ``get_card``'s result as a page of rows and narrow the
    wrong objects. An envelope is exactly one row list plus at most a
    ``next_cursor``; anything with keys of its own is a single object.

    **This test's first draft was blind.** It asserted only that a real card isn't an
    envelope, which passes for the wrong reason — ``labels`` isn't in
    ``_ROW_ENVELOPES`` at all, so the sibling-key check never ran. Deleting that
    check left the suite green. The third assertion is the one that fails.
    """
    _client(monkeypatch, httpx.Response(200, json=CARD))
    assert server.get_card(10, fields=["title", "labels"]) == {
        "title": CARD["title"],
        "labels": [],
    }
    assert shaping._envelope(CARD) is None
    # The sibling-key check itself: an envelope NAME plus keys of its own is a
    # single object, not a page. Remove the check and this line goes red.
    assert shaping._envelope({"id": 1, "title": "T", "comments": [{"id": 2}]}) is None
    assert shaping._envelope({"cards": [CARD]}) == "cards"
    assert shaping._envelope({"cards": [CARD], "next_cursor": "x"}) == "cards"
    assert shaping._envelope({"cards": "not-a-list"}) is None


def test_an_absent_field_projects_as_null_not_a_missing_key(monkeypatch):
    """The projection is rectangular: every row answers to every requested key, so a
    caller can index them uniformly. (Validation has already established the name
    exists on at least one row.)"""
    _client(monkeypatch, _cards_response(CARD, {"id": 11, "title": "sparse"}))
    rows = server.list_cards(fields=["title", "priority"])["cards"]
    assert rows[1] == {"title": "sparse", "priority": None}


def test_metrics_narrows_to_whole_sections(monkeypatch):
    """An aggregate is not rows — ``fields`` there picks top-level sections, which is
    the useful unit (``aging_wip``/``by_assignee`` grow with the board)."""
    report = {
        "board_id": 5,
        "throughput": {"done": 12},
        "cycle_time": {"avg_seconds": 3600},
        "aging_wip": [{"card_id": 1, "seconds": 99}],
        "by_assignee": [{"assignee": "a", "completed": 3}],
    }
    _client(monkeypatch, httpx.Response(200, json=report))
    assert server.metrics(board_id=5, fields=["throughput", "cycle_time"]) == {
        "throughput": {"done": 12},
        "cycle_time": {"avg_seconds": 3600},
    }


def test_an_unknown_field_errors_and_lists_the_valid_names(monkeypatch):
    """A wrong guess must cost one cheap error that teaches the vocabulary, not a
    page of rows full of nulls."""
    _client(monkeypatch, _cards_response(CARD))
    with pytest.raises(ValueError) as excinfo:
        server.list_cards(fields=["titel"])
    message = str(excinfo.value)
    assert "titel" in message
    assert "title" in message and "ticket_number" in message


def test_every_shaped_tool_narrows(monkeypatch):
    """One assertion per shaped read, so a tool that was given the argument but not
    wired to it cannot hide behind ``list_cards`` passing."""
    epic = {"id": 1, "ticket_number": "EPIC-1", "name": "E", "description": "d", "lead": None}
    row = {"id": 1, "ts": "2026-07-01T00:00:00Z", "action": "created", "summary": "s"}
    comment = {"id": 1, "body": "b", "author_id": 2, "created_at": "2026-07-01T00:00:00Z"}

    _client(monkeypatch, httpx.Response(200, json=[epic]))
    assert server.list_epics(fields=["name"]) == {"epics": [{"name": "E"}]}

    _client(monkeypatch, httpx.Response(200, json=[row]))
    assert server.activity(board_id=5, fields=["action"]) == {"activity": [{"action": "created"}]}

    _client(monkeypatch, httpx.Response(200, json=[comment]))
    assert server.list_comments(1, fields=["body"]) == {"comments": [{"body": "b"}]}

    _client(monkeypatch, httpx.Response(200, json={"velocity": 8, "burndown": [1, 2, 3]}))
    assert server.cycle_metrics(4, board_id=5, fields=["velocity"]) == {"velocity": 8}


# --- 3. truncation, and the true total --------------------------------------


def test_truncation_reports_the_true_total(monkeypatch):
    """The number in the hint is the length of the **original** text, measured before
    the cut — a hint claiming a wrong size is worse than no hint. Asserted against
    the real length, never against a re-derived one."""
    _client(monkeypatch, _cards_response(CARD))
    description = server.list_cards()["cards"][0]["description"]
    assert f"{len(CARD['description'])} chars total" in description
    assert description.startswith(CARD["description"][: shaping.DEFAULT_MAX_TEXT_CHARS])
    assert len(description) < len(CARD["description"])


def test_the_kept_prefix_is_exactly_the_limit(monkeypatch):
    monkeypatch.setenv(shaping.ENV_MAX_TEXT_CHARS, "40")
    _client(monkeypatch, _cards_response(CARD))
    kept = server.list_cards()["cards"][0]["description"].split("…")[0]
    assert len(kept) == 40


def test_truncation_cuts_characters_not_bytes(monkeypatch):
    """The board's own text is full of ``·``/``—``/``→``. Slicing a ``str`` is by code
    point, so a cut can never split a multi-byte character and the result is always
    valid UTF-8."""
    monkeypatch.setenv(shaping.ENV_MAX_TEXT_CHARS, "5")
    text = "→→→→→→→→→→"
    _client(monkeypatch, _cards_response({**CARD, "description": text}))
    out = server.list_cards()["cards"][0]["description"]
    assert out.startswith("→→→→→…")
    assert "10 chars total" in out  # characters, not the 30 bytes
    out.encode("utf-8")  # valid UTF-8 by construction


def test_truncation_reaches_every_free_text_field(monkeypatch):
    """The allow-list is the point: ``description``/``body``/``attention_note``/an
    activity row's ``summary``, and nothing else."""
    monkeypatch.setenv(shaping.ENV_MAX_TEXT_CHARS, "10")
    long = "y" * 50

    _client(monkeypatch, _cards_response({**CARD, "attention_note": long}))
    assert "50 chars total" in server.list_cards()["cards"][0]["attention_note"]

    _client(monkeypatch, httpx.Response(200, json=[{"id": 1, "body": long}]))
    assert "50 chars total" in server.list_comments(1)["comments"][0]["body"]

    _client(monkeypatch, httpx.Response(200, json=[{"id": 1, "summary": long}]))
    assert "50 chars total" in server.activity(board_id=5)["activity"][0]["summary"]


def test_a_short_value_is_returned_identical(monkeypatch):
    """No ellipsis, no hint, same string — truncation is invisible below the limit."""
    _client(monkeypatch, _cards_response({**CARD, "description": "short"}))
    assert server.list_cards()["cards"][0]["description"] == "short"


def test_narrowed_text_is_still_truncated(monkeypatch):
    """``fields=["description"]`` must not be a way to put a 3.4k-char body back on
    the wire: the two knobs compose, they do not cancel."""
    _client(monkeypatch, _cards_response(CARD))
    out = server.list_cards(fields=["description"])["cards"][0]["description"]
    assert f"{len(CARD['description'])} chars total" in out


def test_full_defeats_truncation_on_a_narrowed_read(monkeypatch):
    _client(monkeypatch, _cards_response(CARD))
    out = server.list_cards(fields=["description"], full=True)
    assert out == {"cards": [{"description": CARD["description"]}]}


# --- 3b. KAN-517: the second pass over the reads KAN-501 left alone ----------

#: An epic whose description is over the 500-char cut, so the two reads below have
#: something to disagree about. 651 chars is the real length of EPIC-8 on board 5.
EPIC = {
    "id": 8,
    "ticket_number": "EPIC-8",
    "name": "M4: Board as an Agent-PM Surface",
    "description": "d" * 651,
    "board_id": 5,
    "health": "on_track",
    "progress": {"done": 3, "total": 9},
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-02T00:00:00Z",
}

#: A notification exactly as the inbox returns one. The inbox has no ``limit`` and
#: no cursor (backend/app/routers/notifications.py:32-44 takes only ``unread``), so
#: it returns the caller's whole history — 127 rows / ~14,300 tokens when measured,
#: and only ever growing. That, not its row width, is why it is shaped.
NOTIFICATION = {
    "id": 128,
    "user_id": "c5e6f334-e548-4719-8f43-8460fe1940c9",
    "board_id": 18,
    "card_id": 570,
    "kind": "blocked",
    "body": "KAN-570 is now blocked by KAN-569",
    "read_at": None,
    "created_at": "2026-07-31T18:04:03.968852Z",
}

BOARD = {
    "id": 5,
    "name": "Pandan Roadmap",
    "owner_id": "c5e6f334-e548-4719-8f43-8460fe1940c9",
    "autosync_enabled": False,
    "autosync_advance_to_done": False,
    "outbound_webhook_url": None,
    "outbound_webhook_enabled": False,
    "role": "owner",
    "created_at": "2026-07-09T08:39:42.126980Z",
    "updated_at": "2026-07-30T19:50:43.403347Z",
}


def test_get_epic_and_list_epics_agree_about_the_same_epic(monkeypatch):
    """**The asymmetry KAN-517 exists to fix, pinned as an equality.**

    Before this slice ``list_epics`` truncated an epic's description and ``get_epic``
    did not: the cheap listing was bounded and the targeted read was not, which is
    backwards. Asserted as *the two reads return the same string*, not as "get_epic
    truncates" — an equality cannot drift back apart in either direction, and it is
    the same internal-consistency shape that made KAN-485 a bug rather than a taste.
    """
    _client(monkeypatch, httpx.Response(200, json=[EPIC]))
    listed = server.list_epics()["epics"][0]["description"]

    _client(monkeypatch, httpx.Response(200, json=EPIC))
    fetched = server.get_epic(8)["description"]

    assert fetched == listed
    # …and that the agreed-on value is really the truncated one, so the equality
    # cannot be satisfied by both reads quietly going back to returning it whole.
    assert fetched != EPIC["description"]
    assert f"{len(EPIC['description'])} chars total" in fetched


def test_get_epic_full_returns_the_epic_completely_untouched(monkeypatch):
    """Truncation is only safe because there is a way back to the whole text."""
    _client(monkeypatch, httpx.Response(200, json=EPIC))
    assert server.get_epic(8, full=True) == EPIC


def test_a_default_get_epic_is_unchanged_key_for_key(monkeypatch):
    _client(monkeypatch, httpx.Response(200, json=EPIC))
    assert _keyshape(server.get_epic(8)) == _keyshape(EPIC)


def test_the_inbox_narrows_and_keeps_its_envelope(monkeypatch):
    _client(monkeypatch, httpx.Response(200, json=[NOTIFICATION, {**NOTIFICATION, "id": 129}]))
    out = server.list_notifications(fields=["id", "kind", "body"])
    assert out == {
        "notifications": [
            {"id": 128, "kind": "blocked", "body": NOTIFICATION["body"]},
            {"id": 129, "kind": "blocked", "body": NOTIFICATION["body"]},
        ]
    }


def test_the_inbox_truncates_a_long_body_and_full_restores_it(monkeypatch):
    """``body`` is an unbounded ``Text`` column (backend/app/models.py:693) even though
    today's generated one-liners never reach the cut — so the escape hatch is not
    decoration."""
    long_body = {**NOTIFICATION, "body": "n" * 900}
    _client(monkeypatch, httpx.Response(200, json=[long_body]))
    assert "900 chars total" in server.list_notifications()["notifications"][0]["body"]
    _client(monkeypatch, httpx.Response(200, json=[long_body]))
    assert server.list_notifications(full=True) == {"notifications": [long_body]}


def test_a_default_inbox_read_is_unchanged_key_for_key(monkeypatch):
    _client(monkeypatch, httpx.Response(200, json=[NOTIFICATION]))
    assert server.list_notifications() == {"notifications": [NOTIFICATION]}


def test_the_board_list_narrows(monkeypatch):
    """8 real boards cost 1,157 tokens; ``["id","name"]`` costs 181. Six of a board
    row's ten keys are autosync/webhook settings a discovery call never reads."""
    _client(monkeypatch, httpx.Response(200, json=[BOARD, {**BOARD, "id": 6}]))
    assert server.list_boards(fields=["id", "name"]) == {
        "boards": [{"id": 5, "name": "Pandan Roadmap"}, {"id": 6, "name": "Pandan Roadmap"}]
    }


def test_a_default_board_list_is_unchanged_key_for_key(monkeypatch):
    _client(monkeypatch, httpx.Response(200, json=[BOARD]))
    assert server.list_boards() == {"boards": [BOARD]}


def test_the_two_new_envelope_names_are_shape_checked_like_the_others(monkeypatch):
    """Adding a name to ``_ROW_ENVELOPES`` is not free: any payload carrying that key
    now *could* be read as a page of rows. The sibling-key check is what stops it, so
    assert it for the new names specifically — a single object that merely mentions
    ``boards``/``notifications`` must still be a single object."""
    assert shaping._envelope({"notifications": [NOTIFICATION]}) == "notifications"
    assert shaping._envelope({"boards": [BOARD]}) == "boards"
    assert shaping._envelope({"id": 1, "name": "u", "notifications": [NOTIFICATION]}) is None
    assert shaping._envelope({"id": 1, "name": "u", "boards": [BOARD]}) is None
    assert shaping._envelope({"boards": "not-a-list"}) is None


def test_the_envelope_set_is_exactly_the_envelopes_a_shaped_tool_returns():
    """A decision guard, not a correctness one — the sibling of the V49 tool freeze.

    ``_ROW_ENVELOPES`` is a *name* rule, so an entry no shaped tool ever produces can
    only mis-classify somebody else's payload. KAN-517 measured the nine reads
    KAN-501 left raw and added exactly two; ``labels``/``views``/``templates``/
    ``cycles`` measured 7–68 tokens against the real account and were deliberately
    left out. If you are adding one, measure the payload first.
    """
    assert shaping._ROW_ENVELOPES == {
        "cards", "epics", "activity", "comments", "notifications", "boards",
    }


# --- 4. the advertised schema -----------------------------------------------

#: The reads KAN-501 shapes. ``metrics``/``cycle_metrics`` get ``fields`` but not
#: ``full``: they carry no free-text field, so a truncation escape hatch there would
#: be resident tokens advertising a no-op.
#:
#: KAN-517 measured the nine reads left raw and extended exactly three of them, each
#: with the *smallest* argument set that pays for itself: ``list_notifications``
#: (14,326 tokens, unpaginated) gets both, ``list_boards`` (1,157 → 181) gets
#: ``fields`` only — a board has no free text — and ``get_epic`` gets ``full`` only,
#: because its payload is ~200 tokens and the thing wrong with it was never breadth,
#: it was that it disagreed with ``list_epics`` about truncation.
SHAPED_WITH_FULL = (
    "list_cards", "get_card", "list_epics", "activity", "list_comments",
    "list_notifications",
)
SHAPED_FIELDS_ONLY = ("metrics", "cycle_metrics", "list_boards")
SHAPED_TRUNCATION_ONLY = ("get_epic",)


def _schema(name):
    import asyncio

    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    return tools[name].input_schema


def test_the_shaped_tools_advertise_fields_and_full():
    for name in SHAPED_WITH_FULL:
        properties = _schema(name)["properties"]
        assert properties["fields"] == {
            "default": None,
            "items": {"type": "string"},
            "type": ["array", "null"],
        }, f"{name} advertises an unexpected `fields` schema"
        assert properties["full"] == {"default": False, "type": "boolean"}
    for name in SHAPED_FIELDS_ONLY:
        properties = _schema(name)["properties"]
        assert "fields" in properties
        assert "full" not in properties, f"{name} has no free text — `full` is dead weight"
    for name in SHAPED_TRUNCATION_ONLY:
        properties = _schema(name)["properties"]
        assert properties["full"] == {"default": False, "type": "boolean"}
        assert "fields" not in properties, (
            f"{name} was given `fields`; KAN-517 measured its payload at ~200 tokens, "
            "which does not pay for the resident schema. Measure before you widen it."
        )


def test_the_unshaped_reads_stay_unshaped():
    """The other side of the same decision. KAN-517's answer for these six was *no*,
    on measured payloads of 7–474 tokens against a real board — an argument each
    would cost ~+60 resident to bound a payload that is not expensive, which is the
    opposite of the trade ADR 0019 endorsed. Shaping one is a decision; make it with
    numbers, not for symmetry.
    """
    unshaped = ("next", "dispatch", "list_labels", "list_views", "list_templates",
                "list_cycles")
    # The loop below is a claim about a set, so prove the set is the one measured
    # before believing what it says: six names, each of which must resolve to a real
    # tool (``_schema`` raises otherwise).
    assert len(unshaped) == 6
    for name in unshaped:
        properties = _schema(name)["properties"]
        assert "fields" not in properties and "full" not in properties, (
            f"{name} grew a shaping argument — measure its payload first "
            "(scripts/measure_read_payload_tokens.py) and say what it saves."
        )


def test_the_new_arguments_are_optional_everywhere():
    """KAN-501 adds arguments; it must not make an existing call newly invalid."""
    for name in SHAPED_WITH_FULL + SHAPED_FIELDS_ONLY + SHAPED_TRUNCATION_ONLY:
        required = _schema(name).get("required", [])
        assert "fields" not in required and "full" not in required


def test_the_shaped_schemas_are_still_valid_json():
    for name in SHAPED_WITH_FULL + SHAPED_FIELDS_ONLY + SHAPED_TRUNCATION_ONLY:
        json.dumps(_schema(name))
