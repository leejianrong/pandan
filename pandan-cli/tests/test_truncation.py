"""Content truncation with size hints + ``--full`` — the V45 (KAN-428) contract.

The slice's audit found the card's own description was stale in **both** directions,
and this suite is written against what the CLI actually did:

* Human ``get`` printed a **one-line** card summary with **no description at all**.
  That is an *under*-disclosure, so V45 **adds** the description (truncated).
* ``comment list`` and every ``--json`` / ``--format toon`` payload emitted **full
  bodies untruncated** — a ``get`` on a 3.4k-character card description was the
  single most expensive call an agent could make. So V45 **truncates** those.

Four promises, and they are the whole slice:

1. **Under the limit, nothing changes.** No ellipsis, no hint, no reshaping — and a
   card with no description renders byte-identically to before the slice.
2. **Over the limit, the hint's total is TRUE.** ``(truncated, N chars total …)``
   where ``N`` is ``len(original)`` — asserted against the original, never against
   the truncated text and never against a byte count.
3. **``--full`` restores the whole body everywhere it applies** — human rows *and*
   the structured formats, which is what makes truncating a machine payload safe.
4. **Characters, never bytes.** A multi-byte character cannot be split in half.

Plus the two things truncation must NOT touch: a load-bearing string under some
other key (``next_cursor``, ``url``), and V44's ``summary`` aggregate.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from toon_decode import decode

from pandan_cli import cli, config

LIMIT = config.DEFAULT_MAX_TEXT_CHARS

# A description comfortably over the default limit. Deliberately built from ASCII so
# the char/byte distinction is isolated to the multi-byte tests below.
LONG = "x" * 1200
SHORT = "a short description"

# Multi-byte text, from the characters this project's own board descriptions are full
# of (see any KAN- card: `·`, `—`, `→`). One character each, several bytes each.
MULTIBYTE_UNIT = "a·b—c→d✓"
# Long enough to be cut well inside the string rather than at its very end.
MULTIBYTE = MULTIBYTE_UNIT * 400


def _card(**extra) -> dict:
    """A realistic ``CardRead``: carries ``labels`` (the KAN-277 trap shape) and the
    keys the single-card render reads."""
    return {
        "id": 478,
        "ticket_number": "KAN-478",
        "board_id": 5,
        "title": "Ship it",
        "column": "todo",
        "story_points": 1,
        "labels": [],
        **extra,
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
    file, no ``.mcp.json`` discovery, no ``PANDAN_*``/``KANBAN_*`` from the shell — the
    last one matters doubly here, since ``PANDAN_MAX_TEXT_CHARS`` in a developer's
    shell would silently change every expectation below."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: None)
    for names in config._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    config._warned.clear()
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_test")


def run_capture(monkeypatch, capsys, argv, result, *, exit_code=cli.EXIT_OK) -> str:
    monkeypatch.setattr(cli, "PandanClient", lambda *a, **k: FakeClient(result))
    assert cli.run(argv) == exit_code
    return capsys.readouterr().out
def without_hints(out: str) -> str:
    """``out`` minus V46's ``help:`` next-step lines (KAN-429), which ``_emit`` appends
    after the result on the decision-point verbs (``get``/``create``/``move``/…).

    Applied at the assertion site and deliberately **not** inside ``run_capture``:
    every "stdout still parses as JSON/TOON" check in this suite must stay able to
    catch a hint leaking into a structured format. The hints themselves are pinned in
    ``tests/test_content_first.py``."""
    return "".join(f"{line}\n" for line in out.splitlines() if not line.startswith(cli.HINT_PREFIX))


def hint(total: int) -> str:
    return f"(truncated, {total} chars total — use --full to see complete body)"


# --- 1. the primitive ------------------------------------------------------


def test_under_the_limit_is_returned_unchanged_and_reports_no_truncation():
    text = "y" * LIMIT  # exactly at the limit is NOT over it
    assert cli._truncate_text(text, LIMIT) == (text, None)
    assert cli._truncate_text("", LIMIT) == ("", None)
    # `_truncate_inline` therefore adds nothing at all — no ellipsis, no hint.
    assert cli._truncate_inline(text, LIMIT) == text
    assert "truncated" not in cli._truncate_inline(text, LIMIT)


def test_over_the_limit_keeps_exactly_the_limit_and_reports_the_true_total():
    text = "y" * 1000
    kept, total = cli._truncate_text(text, LIMIT)
    assert len(kept) == LIMIT
    assert kept == text[:LIMIT]
    # The total is the ORIGINAL length, not the kept length. This is the assertion
    # the slice is really about: a hint claiming a wrong size is worse than no hint.
    assert total == 1000
    assert total == len(text)
    assert total != len(kept)


@pytest.mark.parametrize("limit", [0, -1])
def test_a_non_positive_limit_disables_truncation(limit):
    # 0 is the documented "off" value (PANDAN_MAX_TEXT_CHARS=0 / what --full becomes).
    assert cli._truncate_text(LONG, limit) == (LONG, None)
    assert cli._truncate_inline(LONG, limit) == LONG


def test_full_collapses_to_a_zero_limit():
    # One concept downstream: no line helper has to know the flag exists.
    assert cli._text_limit(full=True, limit=LIMIT) == 0
    assert cli._text_limit(full=False, limit=LIMIT) == LIMIT


# --- 2. human `get`: the ADDED description (the audit correction) -----------


def test_get_with_no_description_renders_exactly_the_pre_v45_one_line_summary(
    monkeypatch, capsys
):
    """The under-disclosure fix must not become an over-disclosure: a card with no
    description prints the same single line it always did."""
    card = _card()
    out = run_capture(monkeypatch, capsys, ["get", "478"], card)
    assert without_hints(out) == cli._card_line(card) + "\n"
    assert without_hints(out) == "KAN-478\ttodo\tShip it\tpts=1\n"
    assert "description" not in out


@pytest.mark.parametrize("description", [None, ""])
def test_get_with_an_empty_description_renders_unchanged(monkeypatch, capsys, description):
    out = run_capture(monkeypatch, capsys, ["get", "478"], _card(description=description))
    assert without_hints(out) == "KAN-478\ttodo\tShip it\tpts=1\n"


def test_get_now_shows_a_short_description_verbatim_with_no_hint(monkeypatch, capsys):
    """This is the half the card's text missed entirely: before V45 human ``get``
    showed NO description, so there was nothing to truncate — there was nothing at
    all. Under the limit it prints byte-for-byte."""
    out = run_capture(monkeypatch, capsys, ["get", "478"], _card(description=SHORT))
    assert without_hints(out) == f"KAN-478\ttodo\tShip it\tpts=1\ndescription:\n{SHORT}\n"
    assert "truncated" not in out


def test_get_truncates_a_long_description_and_the_total_is_true(monkeypatch, capsys):
    out = run_capture(monkeypatch, capsys, ["get", "478"], _card(description=LONG))
    lines = out.splitlines()
    # The head line is untouched — the row contract other slices rely on.
    assert lines[0] == "KAN-478\ttodo\tShip it\tpts=1"
    assert lines[1] == "description:"
    assert lines[2] == LONG[:LIMIT]
    assert len(lines[2]) == LIMIT
    assert lines[3] == hint(len(LONG))
    assert lines[3] == hint(1200)
    # The whole body is genuinely NOT in the output — the point of the slice.
    assert LONG not in out
    assert len(out) < len(LONG)


def test_full_restores_the_whole_description_in_human_get(monkeypatch, capsys):
    out = run_capture(monkeypatch, capsys, ["get", "478", "--full"], _card(description=LONG))
    assert without_hints(out) == f"KAN-478\ttodo\tShip it\tpts=1\ndescription:\n{LONG}\n"
    assert "truncated" not in out


def test_full_works_before_the_subcommand_too(monkeypatch, capsys):
    # Registered on the shared `common` parent, like --format/--json (V47).
    out = run_capture(monkeypatch, capsys, ["--full", "get", "478"], _card(description=LONG))
    assert LONG in out
    assert "truncated" not in out


def test_a_single_epic_shows_its_description_the_same_way(monkeypatch, capsys):
    epic = {
        "id": 67,
        "ticket_number": "EPIC-67",
        "name": "Sharpen",
        "description": LONG,
        "progress": {"total": 2, "done": 1, "percent": 50},
        "health": None,
    }
    out = run_capture(monkeypatch, capsys, ["epic", "update", "67", "--name", "Sharpen"], epic)
    lines = out.splitlines()
    assert lines[0] == "EPIC-67\tSharpen\t50% (1/2)"
    assert lines[2] == LONG[:LIMIT]
    assert lines[3] == hint(1200)


def test_a_list_row_never_grows_a_description_block(monkeypatch, capsys):
    """A hundred-card `list` must stay a hundred lines: the description block is a
    SINGLE-entity affordance. Without this guard, `list` on the real board would
    print 118 cards × 500 characters."""
    result = {"cards": [_card(description=LONG), _card(description=SHORT)], "next_cursor": None}
    out = run_capture(monkeypatch, capsys, ["list"], result)
    rows = [line for line in out.splitlines() if not line.startswith("2 cards")]
    assert rows == ["KAN-478\ttodo\tShip it\tpts=1"] * 2
    assert "description" not in out
    assert "truncated" not in out


# --- 3. `comment list`: the TRUNCATED body ---------------------------------


def test_comment_list_leaves_a_short_body_byte_identical(monkeypatch, capsys):
    comment = {"id": 5, "created_at": "2026-07-20T00:00:00Z", "body": "please rebase"}
    out = run_capture(monkeypatch, capsys, ["comment", "list", "7"], {"comments": [comment]})
    assert out == "5\t2026-07-20T00:00:00Z\tplease rebase\n1 comment\n"


def test_comment_list_truncates_a_long_body_with_a_true_total(monkeypatch, capsys):
    comment = {"id": 5, "created_at": "2026-07-20T00:00:00Z", "body": LONG}
    out = run_capture(monkeypatch, capsys, ["comment", "list", "7"], {"comments": [comment]})
    body_cell = out.splitlines()[0].split("\t")[2]
    assert body_cell == f"{LONG[:LIMIT]}… {hint(1200)}"
    assert LONG not in out
    # V44's aggregate still lands last and is unaffected.
    assert out.splitlines()[-1] == "1 comment"


def test_comment_list_full_restores_every_body(monkeypatch, capsys):
    comments = [
        {"id": 5, "created_at": "t", "body": LONG},
        {"id": 6, "created_at": "t", "body": LONG + "tail"},
    ]
    out = run_capture(
        monkeypatch, capsys, ["comment", "list", "7", "--full"], {"comments": comments}
    )
    assert out.count(LONG) == 2
    assert "truncated" not in out


def test_a_notification_body_truncates_too(monkeypatch, capsys):
    row = {"id": 3, "kind": "mention", "read_at": None, "body": LONG}
    out = run_capture(monkeypatch, capsys, ["notify", "list"], {"notifications": [row]})
    assert out.splitlines()[0] == f"3\tmention\tunread\t{LONG[:LIMIT]}… {hint(1200)}"


def test_a_fields_projection_of_a_text_column_truncates(monkeypatch, capsys):
    """``--fields ticket,description`` was the other way to put an unbounded body on a
    TSV row, and it keys off the SAME allow-list the structured payload uses."""
    result = {"cards": [_card(description=LONG)], "next_cursor": None}
    out = run_capture(monkeypatch, capsys, ["list", "--fields", "ticket,description"], result)
    assert out.splitlines()[0] == f"KAN-478\t{LONG[:LIMIT]}… {hint(1200)}"


# --- 4. the structured formats -------------------------------------------


def _payload(monkeypatch, capsys, argv, result) -> dict:
    return json.loads(run_capture(monkeypatch, capsys, argv, result))


def test_json_get_truncates_the_description_and_touches_nothing_else(monkeypatch, capsys):
    card = _card(description=LONG, attention_note=None)
    payload = _payload(monkeypatch, capsys, ["get", "478", "--json"], card)
    # Still a plain string — a consumer's `.description` keeps its type and only
    # gets shorter. Promoting it to an object would break every existing caller.
    assert isinstance(payload["description"], str)
    assert payload["description"] == f"{LONG[:LIMIT]}… {hint(1200)}"
    # Every OTHER key is verbatim, and no key was added or dropped.
    assert payload.keys() == card.keys()
    assert {k: v for k, v in payload.items() if k != "description"} == {
        k: v for k, v in card.items() if k != "description"
    }


def test_json_full_is_the_raw_result_again(monkeypatch, capsys):
    card = _card(description=LONG)
    payload = _payload(monkeypatch, capsys, ["get", "478", "--json", "--full"], card)
    assert payload == card


def test_toon_and_json_truncate_identically(monkeypatch, capsys):
    """The V47 round-trip contract must survive V45: one shared serializer means the
    two structured formats cannot cut different amounts of text."""
    card = _card(description=LONG)
    as_json = _payload(monkeypatch, capsys, ["get", "478", "--json"], card)
    as_toon = run_capture(monkeypatch, capsys, ["get", "478", "--format", "toon"], card)
    assert decode(as_toon) == as_json
    assert "truncated" in as_toon


def test_every_text_field_truncates_wherever_it_is_nested(monkeypatch, capsys):
    result = {
        "comments": [
            {"id": 1, "created_at": "t", "body": LONG, "author_id": 2},
            {"id": 2, "created_at": "t", "body": SHORT, "author_id": 2},
        ]
    }
    payload = _payload(monkeypatch, capsys, ["comment", "list", "7", "--json"], result)
    assert payload["comments"][0]["body"].endswith(hint(1200))
    assert payload["comments"][1]["body"] == SHORT  # under the limit: verbatim


def test_attention_note_is_in_the_allow_list(monkeypatch, capsys):
    card = _card(needs_human=True, attention_note=LONG)
    payload = _payload(monkeypatch, capsys, ["get", "478", "--json"], card)
    assert payload["attention_note"] == f"{LONG[:LIMIT]}… {hint(1200)}"


# --- 5. what truncation must NOT touch -----------------------------------


def test_a_load_bearing_string_under_another_key_is_never_truncated(monkeypatch, capsys):
    """The reason this is an allow-list and not "any long string": a keyset
    ``next_cursor`` truncated by even one character silently breaks pagination, and a
    cut ``url`` is not a URL. A ``title`` is short in practice but is not prose we
    are entitled to elide either."""
    result = {
        "cards": [_card(title=LONG, links=[{"id": 1, "label": "PR", "url": LONG}])],
        "next_cursor": LONG,
    }
    payload = _payload(monkeypatch, capsys, ["list", "--json"], result)
    assert payload["next_cursor"] == LONG
    assert payload["cards"][0]["title"] == LONG
    assert payload["cards"][0]["links"][0]["url"] == LONG


def test_the_text_field_allow_list_excludes_the_load_bearing_keys():
    # Pinned, so a later slice widening the list has to think about these by name.
    for key in ("next_cursor", "url", "title", "name", "ticket_number", "query"):
        assert key not in cli._TEXT_FIELDS
    assert cli._TEXT_FIELDS == {"description", "body", "attention_note", "summary"}


def test_v44s_summary_aggregate_is_untouched_by_truncation(monkeypatch, capsys):
    """The aggregate is attached AFTER truncation, so its counts are structurally out
    of the truncator's reach — even though an activity row's own ``summary`` *string*
    is a member of the allow-list."""
    result = {"cards": [_card(description=LONG), _card(column="done")], "next_cursor": None}
    payload = _payload(monkeypatch, capsys, ["list", "--json"], result)
    assert payload["summary"] == {
        "count": 2,
        "todo": 1,
        "in_progress": 0,
        "done": 1,
        "needs_human": 0,
    }
    assert "truncated" not in json.dumps(payload["summary"])
    # ...while an activity row's `summary` string still truncates.
    activity = {"activity": [{"ts": "t", "actor_label": "a", "action": "x", "summary": LONG}]}
    rows = _payload(monkeypatch, capsys, ["activity", "--board", "5", "--json"], activity)
    assert rows["activity"][0]["summary"].endswith(hint(1200))
    assert rows["summary"] == {"count": 1}


def test_the_aggregate_is_never_handed_to_the_truncator_at_all(monkeypatch):
    """Pins the ORDERING, which the value assertions above cannot: V44's aggregate is
    attached *after* truncation, so it is out of reach structurally.

    Found by mutation testing — reversing the order leaves every other assertion in
    this file green, because the aggregate holds only integers and
    ``_truncate_payload`` skips non-strings. That makes the ordering a promise with no
    observable consequence *today*, and exactly the kind that rots silently: the day
    a summary carries a string (a cycle name, a filter echo) it would be cut, and the
    hint would claim a character total for a field nobody was truncating on purpose.
    ``summary`` is itself in ``_TEXT_FIELDS`` (an activity row's is prose), so the
    collision is real and not hypothetical."""
    seen: list[Any] = []
    real = cli._truncate_payload

    def spy(value, limit):
        seen.append(value)
        return real(value, limit)

    monkeypatch.setattr(cli, "_truncate_payload", spy)
    result = {"cards": [_card(description=LONG)], "next_cursor": None}
    payload = cli._structured_payload(result, limit=LIMIT)

    assert payload["summary"]["count"] == 1
    assert seen, "the truncator was not called at all"
    # The top-level call saw the raw client result — no `summary` key in sight.
    assert "summary" not in seen[0]
    assert seen[0] is result


# --- 6. multi-byte safety ------------------------------------------------


def test_a_multibyte_character_is_never_split_in_half():
    """Truncating by BYTES is the classic bug here. Slicing a ``str`` cuts by code
    point, so the result is always valid UTF-8 with no replacement characters."""
    kept, total = cli._truncate_text(MULTIBYTE, LIMIT)
    assert len(kept) == LIMIT
    assert kept == MULTIBYTE[:LIMIT]
    # Valid UTF-8 that survives a strict round trip — a byte-split prefix would not.
    assert kept.encode("utf-8").decode("utf-8") == kept
    assert "�" not in kept
    # The cut landed strictly inside the string, so this is not a vacuous pass.
    assert len(kept) < len(MULTIBYTE)
    assert kept[-1] in MULTIBYTE_UNIT


def test_the_reported_total_is_characters_not_bytes():
    """The number in the hint is a character count. Under the multi-byte text this
    differs from the byte count, so a byte-based implementation would be caught."""
    _, total = cli._truncate_text(MULTIBYTE, LIMIT)
    assert total == len(MULTIBYTE) == 3200
    # Each `a·b—c→d✓` unit is 8 characters but 15 bytes (1+2+1+3+1+3+1+3).
    assert len(MULTIBYTE.encode("utf-8")) == 6000
    assert total != len(MULTIBYTE.encode("utf-8"))


def test_multibyte_survives_the_whole_human_and_json_path(monkeypatch, capsys):
    card = _card(description=MULTIBYTE)
    out = run_capture(monkeypatch, capsys, ["get", "478"], card)
    assert out.splitlines()[2] == MULTIBYTE[:LIMIT]
    assert "�" not in out
    assert out.splitlines()[3] == hint(3200)

    payload = _payload(monkeypatch, capsys, ["get", "478", "--json"], card)
    assert payload["description"] == f"{MULTIBYTE[:LIMIT]}… {hint(3200)}"


# --- 7. the limit is configurable ----------------------------------------


def test_the_limit_comes_from_the_env_var(monkeypatch, capsys):
    monkeypatch.setenv("PANDAN_MAX_TEXT_CHARS", "10")
    out = run_capture(monkeypatch, capsys, ["get", "478"], _card(description=LONG))
    assert out.splitlines()[2] == LONG[:10]
    assert out.splitlines()[3] == hint(1200)


def test_zero_disables_truncation_entirely(monkeypatch, capsys):
    monkeypatch.setenv("PANDAN_MAX_TEXT_CHARS", "0")
    out = run_capture(monkeypatch, capsys, ["get", "478"], _card(description=LONG))
    assert LONG in out
    assert "truncated" not in out


def test_the_limit_comes_from_the_config_file(monkeypatch, capsys, tmp_path):
    path = config.config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[pandan]\ntoken = "pandan_pat_file"\nmax_text_chars = 12\n')
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    out = run_capture(monkeypatch, capsys, ["get", "478"], _card(description=LONG))
    assert out.splitlines()[2] == LONG[:12]


@pytest.mark.parametrize("bad", ["abc", "-1", "5.5"])
def test_a_bad_limit_is_a_clean_config_error(monkeypatch, capsys, bad):
    monkeypatch.setenv("PANDAN_MAX_TEXT_CHARS", bad)
    out = run_capture(
        monkeypatch, capsys, ["get", "478"], _card(), exit_code=cli.EXIT_ERROR
    )
    row = out.splitlines()[0].split("\t")
    assert row[0] == "error"
    assert row[1] == "config"
    assert "PANDAN_MAX_TEXT_CHARS" in row[2]


def test_config_set_preserves_a_hand_written_limit(tmp_path, monkeypatch):
    """``max_text_chars`` has no ``config set`` flag (you set the env var or edit the
    file), so the file-merge path has to preserve a key it cannot write — otherwise
    `pandan config set --board-id 5` would silently delete the user's limit."""
    path = config.config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[pandan]\ntoken = "pandan_pat_file"\nmax_text_chars = 42\n')
    config.write_config_file(board_id="9")
    assert "max_text_chars = 42" in path.read_text()
    assert config.load_config().max_text_chars == 42
    assert config.load_config().board_id == 9


def test_config_show_reports_the_effective_limit(capsys):
    assert cli.run(["config", "show"]) == cli.EXIT_OK
    assert f"max_text_chars\t{LIMIT}" in capsys.readouterr().out


def test_the_default_limit_is_a_positive_number():
    # A default of 0 would ship the slice inert; a negative one is rejected upstream.
    assert config.DEFAULT_MAX_TEXT_CHARS > 0
    assert config.load_config(require_token=False).max_text_chars == LIMIT
