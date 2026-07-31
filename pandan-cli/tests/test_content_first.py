"""Content-first bare invocation + ``help[]`` next-step hints — V46 (KAN-429).

Two halves, and the tests below are grouped by them:

1. **Bare ``pandan`` prints live state and exits 0** (AXI 8). Before this slice it
   printed argparse's usage block on stderr, one ``error<TAB>usage<TAB>…`` row on
   stdout, and exited **2** — verified by running it from source at ``origin/main``
   (052091a) before any code was written, not assumed from the card. Now it prints
   the tool's own identity + the exact executable, a one-sentence description, then
   the default board's open cards and V44's aggregate. No default board → the board
   list. No token → V43's structured config error, unchanged.
2. **Results carry ``help[]`` next-step hints** (AXI 9) as *templates*: one fixed
   flag carried forward, every runtime value left parameterised. Suppressed under
   ``--format json``/``toon``.

The load-bearing guard is ``test_hints_never_interpolate_an_id_from_the_result``: a
hint that merely *mentions* ``<id>`` proves nothing — the same output could contain a
pre-filled command too — so it asserts both that the literal placeholder survives
**and** that no identifier from the result appears anywhere in a hint line.

``--help`` is pinned against ``tests/help_golden.txt``, generated from the
**unmodified** ``origin/main`` parser before this slice was written — that ordering is
what makes it a regression guard (AXI 10) rather than a restatement of the current
code. The comparison is **word-for-word**, with the usage line additionally pinned to
the byte; ``help_words`` explains why byte-exactness for the whole text would pin the
interpreter's argparse rather than this CLI.

**KAN-492 amended two of V46's decisions**, both of which existed only to keep that
golden green, and neither of which was ever the point of the guard:

* ``overview`` is now **listed** in ``--help`` (it has a ``help=`` kwarg), and the
  golden was regenerated mechanically from the new parser in the same diff. The guard
  is a *change-detector*, not a freeze: it still fails on any drift nobody intended,
  and ``test_no_top_level_verb_is_hidden_from_help`` now additionally makes hiding a
  verb — the thing V46 did to stay green — a test failure in its own right.
* **List verbs carry hints**, because ``_emit`` prints hints *above* V44's aggregate
  instead of below it. V46 withheld them to protect the epilog's ``tail -1`` promise;
  reordering protects the same promise word-for-word and gets the hint back.

**KAN-526 then took the one thing that change cost back** (§2c): a result naming no
entity drops the templates whose ``<id>`` slot has no referent, because `pandan list`
on an empty board was answering ``(no cards)`` and then offering two next steps on
rows it had just said do not exist. The predicate lives in ``_hint_lines``, so
``_emit`` is still a printer, and the ordering above is untouched.
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import shlex

import pytest
from toon_decode import decode

from pandan_cli import __version__, cli, config, context

HELP_GOLDEN = pathlib.Path(__file__).with_name("help_golden.txt")

# argparse wraps help to the terminal width, and `shutil.get_terminal_size` reads
# `COLUMNS` before asking the tty — so the golden is only comparable at a pinned
# width. 80 is the conventional default; CI has no tty at all.
GOLDEN_WIDTH = "80"


def help_words(text: str) -> list[str]:
    """The help text as a word sequence, with all whitespace collapsed.

    The comparison against the golden is **word-for-word**, not byte-for-byte, and
    that was forced by evidence rather than chosen for convenience: argparse decides
    its help column from ``_action_max_length`` and its width from
    ``shutil.get_terminal_size()``, and both are stdlib internals that move between
    interpreter builds. A byte-exact golden captured locally failed in CI purely on
    layout — one space less padding, which pushed ``batch-update``'s help string onto
    its own line — while every word was identical. Pinning bytes would therefore have
    pinned the *interpreter*, not this CLI.

    What survives the collapse is everything the AXI 10 guard is actually about: the
    exact set and order of words, so a newly *visible* subcommand (its name **and**
    its help sentence), a reworded epilog, a dropped line or a changed usage token
    all fail. The usage line's own bytes are asserted separately — that is where
    ``<command> ...`` vs ``[<command> ...]`` lives, i.e. the one layout detail this
    slice could have broken by making the subparsers action optional.
    """
    return text.split()

# A deliberately distinctive id/ticket pair: the hint guard asserts the string "412"
# appears in NO hint line, which is only a real assertion if the number could not
# have come from anywhere else in the fixtures.
CARD_ID = 412
TICKET = f"KAN-{CARD_ID}"


def _card(ticket: str = TICKET, column: str = "todo", *, needs_human: bool = False) -> dict:
    """A realistic ``CardRead`` row (carries ``labels`` — the KAN-277 trap shape)."""
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


BOARD = {"id": CARD_ID, "name": "Roadmap", "owner_id": None}
EPIC = {"id": CARD_ID, "ticket_number": f"EPIC-{CARD_ID}", "name": "Onboarding",
        "description": None}
COMMENT = {"id": CARD_ID, "card_id": CARD_ID, "author_id": 1, "body": "noted"}
PAGE = {"cards": [_card(TICKET, "todo"), _card("KAN-413", "in_progress")], "next_cursor": None}


class FakeClient:
    """Records every call; returns a canned result (or a per-method override)."""

    def __init__(self, result=None, results: dict | None = None, **kwargs) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.kwargs = kwargs  # the constructor kwargs `run()` passed through
        self._result = result
        self._results = results or {}

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, kwargs))
            if name in self._results:
                return self._results[name]
            return self._result

        return call


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch, tmp_path):
    """The hermetic-config fixture the other suites use: an empty XDG dir, no
    ``.mcp.json`` discovery, and **both** env spellings of every key cleared, so a
    developer's own shell can't supply the token the no-token tests need absent."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: None)
    for names in config._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    config._warned.clear()


@pytest.fixture
def token(monkeypatch):
    """A token but **no** default board."""
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_test")


@pytest.fixture
def board(monkeypatch, token):
    """A token **and** a default board (the normal configured state)."""
    monkeypatch.setenv("PANDAN_BOARD_ID", "5")


def patch_client(monkeypatch, result=None, results=None) -> list[FakeClient]:
    """Patch ``cli.PandanClient`` and hand back the list of clients built, so a test
    can assert on the constructor kwargs as well as the calls."""
    built: list[FakeClient] = []

    def build(*args, **kwargs):
        client = FakeClient(result=result, results=results, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(cli, "PandanClient", build)
    return built


def run_ok(monkeypatch, capsys, argv, result=None, results=None) -> str:
    patch_client(monkeypatch, result=result, results=results)
    assert cli.run(argv) == cli.EXIT_OK
    return capsys.readouterr().out


def hints_in(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(cli.HINT_PREFIX)]


# --- 1. bare invocation: content, exit 0 ------------------------------------


def test_bare_invocation_prints_rows_and_exits_zero(monkeypatch, capsys, board):
    """The headline promise. Rows, not usage; exit 0, not 2."""
    patch_client(monkeypatch, result=PAGE)
    assert cli.run([]) == cli.EXIT_OK
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert f"{TICKET}\ttodo\tcard {TICKET}\tpts=3" in lines
    # The pre-slice behaviour, asserted absent in both its parts: the structured
    # usage row on stdout and argparse's usage block on stderr.
    assert not any(line.startswith("error\t") for line in lines)
    assert "usage:" not in captured.err


def test_bare_invocation_leads_with_the_executable_and_a_description(
    monkeypatch, capsys, board
):
    """AXI 8's prefix: which build answered, from where, and what it is for.

    The executable is how to re-invoke *this* pandan (``context._self_argv``), never a
    ``pandan`` on ``$PATH`` — telling those apart is the whole point of printing it."""
    out = run_ok(monkeypatch, capsys, [], result=PAGE)
    first, second, third = out.splitlines()[:3]
    assert first.startswith(f"pandan {__version__} (")
    assert first.endswith(" ".join(context._self_argv()))
    assert second == f"{cli.TOOL_DESCRIPTION} `pandan --help` for usage."
    # The third line names the view, because the rows are a *subset* of one page.
    assert third.endswith("· board 5 · open cards (todo, in_progress):")


def test_bare_invocation_shows_open_cards_only_and_counts_what_it_printed(
    monkeypatch, capsys, board
):
    """"Open" excludes the terminal column, and V44's aggregate still describes the
    rows **actually printed** — the filter is applied before ``_emit``, so a count
    the reader cannot reconcile with the rows above it is impossible."""
    page = {
        "cards": [_card("KAN-1", "todo"), _card("KAN-2", "in_progress"), _card("KAN-3", "done")],
        "next_cursor": None,
    }
    out = run_ok(monkeypatch, capsys, [], result=page)
    assert "KAN-3\t" not in out
    lines = out.splitlines()
    # Since KAN-492 the aggregate is the LAST line here too — hints print above it.
    assert lines[-1] == "2 cards · 1 todo · 1 in_progress · 0 done"
    assert cli.OPEN_COLUMNS == ("todo", "in_progress")


def test_the_keyset_cursor_survives_the_open_filter(monkeypatch, capsys, board):
    """A board bigger than one page must still say so — the filter drops rows, never
    the "there are more" signal."""
    page = {"cards": [_card("KAN-1", "todo")], "next_cursor": "KAN-1"}
    out = run_ok(monkeypatch, capsys, [], result=page)
    assert "(more — next cursor: KAN-1)" in out


def test_bare_invocation_makes_exactly_one_request(monkeypatch, capsys, board):
    built = patch_client(monkeypatch, result=PAGE)
    assert cli.run([]) == cli.EXIT_OK
    assert [name for name, _ in built[0].calls] == ["list_cards"]
    assert built[0].calls[0][1] == {"board_id": 5, "limit": cli.OVERVIEW_FETCH_LIMIT}


def test_no_board_configured_lists_boards(monkeypatch, capsys, token):
    """The spec's second shape: with no default board the actionable content is the
    board list — the thing you need in order to pick one — still exit 0."""
    built = patch_client(monkeypatch, result={"boards": [BOARD]})
    assert cli.run([]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert [name for name, _ in built[0].calls] == ["list_boards"]
    assert "no default board configured · your boards:" in out
    assert "5\tRoadmap" in out or "Roadmap" in out
    assert out.splitlines()[-1] == "1 board"


def test_no_token_is_the_structured_config_error_not_a_traceback(monkeypatch, capsys):
    """The distinction the slice has to get right: *no board* is content (exit 0),
    *no token* is V43's error contract (exit 1, code ``config``) — unchanged from
    every other verb, and emphatically not a stack trace."""

    def boom(*a, **k):  # pragma: no cover - a config failure precedes the client
        raise AssertionError("no client should be built without a token")

    monkeypatch.setattr(cli, "PandanClient", boom)
    assert cli.run([]) == cli.EXIT_ERROR
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line.startswith("error\t")]
    assert len(rows) == 1
    assert rows[0].split("\t")[1] == "config"
    assert cli.ERROR_CODES["config"] == cli.EXIT_ERROR
    assert "Traceback" not in out


def test_pandan_overview_names_the_same_code_path(monkeypatch, capsys, board):
    """The bare rewrite targets a real, and since KAN-492 a *listed*, verb, so the
    front door is reachable by name — which is also how a script asks for it
    explicitly."""
    bare = run_ok(monkeypatch, capsys, [], result=PAGE)
    named = run_ok(monkeypatch, capsys, [cli.OVERVIEW_COMMAND], result=PAGE)
    assert bare == named


# --- 1b. the allow-list: nothing that used to work changed -------------------


@pytest.mark.parametrize(
    "argv",
    [[], ["--json"], ["--full"], ["--format", "toon"], ["--format=json"], ["--full", "--json"]],
)
def test_these_argvs_are_bare(argv):
    assert cli._is_bare_invocation(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["list"],
        ["overview"],
        ["-h"],
        ["--help"],
        ["-v"],
        ["--version"],
        ["--format"],  # a dangling value: argparse must still report it its own way
        ["--nope"],
        ["--json", "list"],
        ["get", "KAN-1"],
    ],
)
def test_these_argvs_are_not_bare(argv):
    """The branch is an allow-list, so every other argv reaches argparse untouched.
    That is what makes "no invocation that used to work changed" a structural claim
    rather than a hope."""
    assert not cli._is_bare_invocation(argv)


@pytest.mark.parametrize(
    "argv,expected",
    [(["-v"], 0), (["--version"], 0)],
)
def test_version_still_short_circuits_without_a_network_call(monkeypatch, capsys, argv, expected):
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("--version must not touch the network")

    monkeypatch.setattr(cli, "PandanClient", boom)
    with pytest.raises(SystemExit) as exc:
        cli.run(argv)
    assert exc.value.code == expected
    assert capsys.readouterr().out.startswith(f"pandan {__version__} (")


def test_an_unknown_flag_alone_is_still_a_usage_error(monkeypatch, capsys):
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("a usage error must not touch the network")

    monkeypatch.setattr(cli, "PandanClient", boom)
    with pytest.raises(SystemExit) as exc:
        cli.run(["--nope"])
    assert exc.value.code == cli.EXIT_USAGE
    assert capsys.readouterr().out.split("\t")[1] == "usage"


def test_a_dangling_format_value_is_still_argparses_own_error(monkeypatch, capsys):
    """Why the rewrite **prepends**: appended, ``--format`` would swallow the injected
    verb and report a confusing "invalid choice" instead of a missing argument."""
    with pytest.raises(SystemExit) as exc:
        cli.run(["--format"])
    assert exc.value.code == cli.EXIT_USAGE
    row = capsys.readouterr().out.split("\t")
    assert row[1] == "usage"
    assert "expected one argument" in row[2]


# --- 1c. the network bound --------------------------------------------------


def test_the_bare_call_is_bounded_tighter_than_the_shared_default(monkeypatch, board):
    """A bare invocation is what a human types to *look*, so its worst case matters.

    The shared client defaults to a 35 s read timeout + one retry after a 1 s backoff
    (``pandan-client/pandan_client/client.py:36-39``) — a ~71 s ceiling. The overview
    shortens each attempt and drops the backoff, which is asserted here as a
    *relation* to those defaults rather than a magic number, so a change to either
    side has to be deliberate."""
    from pandan_client import client as shared

    built = patch_client(monkeypatch, result=PAGE)
    assert cli.run([]) == cli.EXIT_OK
    assert built[0].kwargs == {"timeout": cli.OVERVIEW_TIMEOUT, "retry_backoff": 0.0}
    shared_ceiling = 2 * shared.DEFAULT_TIMEOUT + shared.DEFAULT_RETRY_BACKOFF
    assert 2 * cli.OVERVIEW_TIMEOUT < shared_ceiling
    # Still generous enough to span the observed ~30-40s Fly cold wake across the
    # client's two attempts — the reason we bound it rather than fail fast.
    assert 2 * cli.OVERVIEW_TIMEOUT >= 40


def test_no_other_verb_changes_its_transport(monkeypatch, board):
    """``_client_options`` is empty for everything but the overview, so V44/V45/V47's
    verbs keep the batch-friendly cold-start defaults they were built against."""
    built = patch_client(monkeypatch, result=PAGE)
    assert cli.run(["list"]) == cli.EXIT_OK
    assert built[0].kwargs == {}


def test_the_wait_notice_is_stderr_and_tty_only(monkeypatch, capsys):
    """The progress affordance must never reach stdout — that stream is the machine
    channel, and an agent parsing it must not find prose in its data."""

    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    cfg = config.Config(api_url="https://example.test", token="t", board_id=None)
    tty = Tty()
    monkeypatch.setattr(cli.sys, "stderr", tty)
    cli._announce_wait(cfg)
    assert "contacting https://example.test" in tty.getvalue()

    quiet = io.StringIO()  # a pipe: isatty() is False
    monkeypatch.setattr(cli.sys, "stderr", quiet)
    cli._announce_wait(cfg)
    assert quiet.getvalue() == ""


def test_the_wait_notice_never_lands_on_stdout(monkeypatch, capsys, board):
    """End-to-end: under capsys (never a tty) the notice is silent, and stdout stays
    parseable as JSON — the assertion that would fail if it leaked."""
    out = run_ok(monkeypatch, capsys, ["--json"], result=PAGE)
    assert json.loads(out)["tool"]["name"] == "pandan"


# --- 2. help[] hints: templates, never pre-filled ---------------------------

# One invocation per hinted verb: (argv, canned result). Every result carries the
# same distinctive id/ticket (412 / KAN-412), which is what lets the guard below
# assert that no identifier from the result reached a hint.
HINTED: dict[str, tuple[list[str], dict]] = {
    "overview": ([], PAGE),
    "list": (["list"], PAGE),
    "get": (["get", str(CARD_ID)], _card()),
    "create": (["create", "a card", "--board", "5"], _card()),
    "update": (["update", str(CARD_ID), "--points", "3"], _card()),
    "move": (["move", str(CARD_ID), "done"], _card(column="done")),
    "next": (["next", "--board", "5"], {"card": _card()}),
    "needs-human": (["needs-human", str(CARD_ID)], _card(needs_human=True)),
    "resolve": (["resolve", str(CARD_ID)], _card()),
    "comment add": (["comment", "add", str(CARD_ID), "--body", "noted"], COMMENT),
    "board create": (["board", "create", "Roadmap"], BOARD),
    "epic create": (["epic", "create", "Onboarding"], EPIC),
}


def test_the_hint_table_covers_exactly_the_verbs_it_is_wired_to():
    """A key that matches no verb is a dead entry nobody would notice, and a verb
    wired to a tuple that isn't in the table is an untested hint. Walk the real
    parser and pin both directions."""
    wired: dict[str, tuple[str, ...]] = {}

    def walk(parser: argparse.ArgumentParser, prefix: str = "") -> None:
        for action in parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, sub in action.choices.items():
                path = f"{prefix}{name}"
                hints = sub.get_default("hints")
                if hints:
                    wired[path] = hints
                walk(sub, prefix=f"{path} ")

    walk(cli.build_parser())
    assert wired == cli._HINTS


@pytest.mark.parametrize("verb", sorted(HINTED))
def test_every_hinted_verb_prints_its_hints(monkeypatch, capsys, verb, board):
    argv, result = HINTED[verb]
    out = run_ok(monkeypatch, capsys, argv, result=result, results={"get_card": result})
    assert hints_in(out), f"{verb} printed no help[] line"


@pytest.mark.parametrize("verb", sorted(HINTED))
def test_hints_never_interpolate_an_id_from_the_result(monkeypatch, capsys, verb, board):
    """**The guard this slice turns on.** Two assertions, because either alone passes
    for the wrong reason:

    * the literal ``<id>`` placeholder is present — a hint that named a card at all
      must name it as a *slot*;
    * and no identifier from the result appears anywhere in a hint line, so the
      placeholder can't be sitting next to a helpfully pre-filled duplicate.

    ``412`` is checked as a bare substring on purpose: it catches ``KAN-412``,
    ``412``, and ``--board 412`` alike.
    """
    argv, result = HINTED[verb]
    out = run_ok(monkeypatch, capsys, argv, result=result, results={"get_card": result})
    lines = hints_in(out)
    # The rows above really did carry the identifier — otherwise "absent from the
    # hints" would be trivially true and this test would prove nothing.
    assert str(CARD_ID) in out
    for line in lines:
        assert str(CARD_ID) not in line, f"{verb} pre-filled an id into {line!r}"
        assert TICKET not in line
    if any("<id>" in template for template in cli._HINTS[verb]):
        assert any("<id>" in line for line in lines)


@pytest.mark.parametrize("verb", sorted(cli._HINTS))
def test_every_hint_template_is_a_command_that_actually_parses(verb, capsys):
    """A hint the CLI would reject is worse than no hint — it teaches a wrong shape
    and an agent will run it. Substitute a plausible value for each placeholder and
    feed the result to the real parser; argparse must accept it.

    This is not hypothetical: it caught ``pandan comment add <id> "…"`` in the first
    draft of the table, where the body is actually ``--body``.
    """
    fill = {"<id>": "1", "<title>": "x", "…": "x", "N": "1", cli._HINT_BOARD_SLOT: ""}
    for template in cli._HINTS[verb]:
        rendered = template
        for slot, value in fill.items():
            rendered = rendered.replace(slot, value)
        argv = shlex.split(rendered)
        assert argv[0] == "pandan"
        cli.build_parser().parse_args(argv[1:])  # SystemExit here = a bad hint
    capsys.readouterr()


def test_the_hint_table_itself_bakes_in_no_identifier():
    """A structural companion to the runtime guard: nothing in the table is a literal
    value, so a hint cannot be born pre-filled. Placeholders only — ``<id>``,
    ``<title>``, ``N``, ``"…"``, and the ``{board}`` carry slot."""
    for verb, templates in cli._HINTS.items():
        for template in templates:
            assert template.startswith("pandan "), (verb, template)
            bare = template.replace(cli._HINT_BOARD_SLOT, "")
            assert not any(char.isdigit() for char in bare), (verb, template)


@pytest.mark.parametrize("fmt", [["--json"], ["--format", "json"], ["--format", "toon"]])
def test_hints_are_absent_under_the_structured_formats(monkeypatch, capsys, fmt, board):
    """Suppression is mechanical — the hints print inside ``_emit``'s human branch —
    and the reason is that stdout must stay parseable, which is what is asserted."""
    out = run_ok(monkeypatch, capsys, ["get", str(CARD_ID), *fmt], result=_card())
    assert cli.HINT_PREFIX not in out
    payload = decode(out) if fmt[-1] == "toon" else json.loads(out)
    assert payload["ticket_number"] == TICKET


def test_an_explicit_board_flag_is_carried_forward(monkeypatch, capsys, token):
    """"Fixed flags carried forward": a hint that would target the wrong board is
    worse than no hint, so an explicitly named ``--board`` rides along — and only
    onto the templates that declare the slot."""
    out = run_ok(monkeypatch, capsys, [cli.OVERVIEW_COMMAND, "--board", "7"], result=PAGE)
    lines = hints_in(out)
    assert f"{cli.HINT_PREFIX} pandan list --column todo --board 7" in lines
    assert f"{cli.HINT_PREFIX} pandan next --claim --board 7" in lines
    # `get` takes no --board, and its template carries no slot, so it stays clean.
    assert f"{cli.HINT_PREFIX} pandan get <id>" in lines


def test_a_board_from_the_environment_is_not_carried_forward(monkeypatch, capsys, board):
    """PANDAN_BOARD_ID resolves the same way for the next command, so spelling it out
    would be noise — and would read as though the flag were required."""
    out = run_ok(monkeypatch, capsys, [], result=PAGE)
    assert hints_in(out) == [
        f"{cli.HINT_PREFIX} pandan list --column todo",
        f"{cli.HINT_PREFIX} pandan next --claim",
        f"{cli.HINT_PREFIX} pandan get <id>",
    ]


# --- 2b. the hints did not disturb V44's contract ---------------------------


@pytest.mark.parametrize(
    "argv,result,expected,hinted",
    [
        (["list"], PAGE, "2 cards · 1 todo · 1 in_progress · 0 done", True),
        (["board", "list"], {"boards": [BOARD]}, "1 board", False),
        (["epic", "list"], {"epics": []}, "0 epics · 0/0 stories done (0%)", False),
        (["comment", "list", str(CARD_ID)], {"comments": []}, "0 comments", False),
    ],
)
def test_a_list_verb_still_ends_with_its_aggregate(
    monkeypatch, capsys, argv, result, expected, hinted, board
):
    """V44's promise — restated in the parser epilog as "Every list verb ends with a
    pre-computed aggregate" — is a ``tail -1`` contract, and it is the reason V46
    withheld hints from every list verb.

    KAN-492 keeps the promise a different way: ``_emit`` prints hints **above** the
    aggregate, so ``list`` can carry the tool's most useful hint
    (``pandan move <id> in_progress``) while ``tail -1`` still returns the counts. The
    ``hinted`` column is what makes this a real assertion rather than a filter — for
    ``list`` the hints must be *present* and the aggregate must *still* be last; for
    the others the exclusion is asserted as before."""
    out = run_ok(monkeypatch, capsys, argv, result=result, results={"get_card": _card()})
    assert out.splitlines()[-1] == expected
    assert bool(hints_in(out)) is hinted
    if hinted:
        # The hints really are above it — not merely absent from the final line.
        assert out.splitlines()[-2].startswith(cli.HINT_PREFIX)


@pytest.mark.parametrize("argv", [[], ["list"]])
def test_the_hints_print_above_the_aggregate_not_after_it(monkeypatch, capsys, argv, board):
    """The ordering KAN-492 reversed, pinned for both aggregate-bearing hinted verbs.

    V46 printed the aggregate first and the hints after it, which is why a hinted list
    verb would have broken the ``tail -1`` contract. Asserted as a *relation* between
    the two line positions, plus "nothing but the aggregate after the last hint", so
    the guard fails whichever way the order drifts."""
    out = run_ok(monkeypatch, capsys, argv, result=PAGE)
    lines = out.splitlines()
    aggregate = next(i for i, line in enumerate(lines) if line.startswith("2 cards · "))
    last_hint = max(i for i, line in enumerate(lines) if line.startswith(cli.HINT_PREFIX))
    assert last_hint < aggregate
    assert aggregate == len(lines) - 1  # the aggregate is the final line, i.e. `tail -1`


# --- 2c. an empty result drops the hints that name a row (KAN-526) -----------
#
# Letting list verbs carry hints created a state that could not exist before KAN-492:
# `pandan list` on an empty board printed `(no cards)` and then two next steps on rows
# it had just said do not exist. KAN-526 drops a hint whose `<id>` slot has no referent
# — and only that hint, which is why the answer differs per verb without a per-verb
# rule. Below: the per-verb table, the drop, the survivors, and the control that keeps
# the drop from becoming a blanket suppression.

# Every hinted verb → the client result for its *empty* state, or ``None`` when the
# verb has no empty state at all. ``None`` is the answer for every single-entity verb:
# `get`/`update`/`move`/`claim`/`needs-human`/`resolve` return one card or raise (404 →
# exit 5, no hints printed), and `create`/`comment add`/`board create`/`epic create`
# return the thing they just made. Only the two aggregate-bearing verbs and `next` can
# report nothing — and `next` is the one the KAN-526 card did not name.
EMPTY_RESULTS: dict[str, dict | None] = {
    "overview": {"cards": [], "next_cursor": None},
    "list": {"cards": [], "next_cursor": None},
    "next": {"card": None},
    "get": None,
    "create": None,
    "update": None,
    "move": None,
    "claim": None,
    "needs-human": None,
    "resolve": None,
    "comment add": None,
    "board create": None,
    "epic create": None,
}
CAN_BE_EMPTY = sorted(verb for verb, result in EMPTY_RESULTS.items() if result is not None)


def test_the_empty_result_table_covers_every_hinted_verb():
    """Enumerated against the real hint table, so a verb that grows hints later cannot
    skip the question "and what does this print when it finds nothing?"."""
    assert set(EMPTY_RESULTS) == set(cli._HINTS)


@pytest.mark.parametrize(
    "result,empty",
    [
        ({"cards": [], "next_cursor": None}, True),
        ({"cards": [_card()], "next_cursor": None}, False),
        ({"boards": []}, True),
        ({"card": None}, True),  # next / dispatch found nothing ready
        ({"card": _card()}, False),
        (_card(), False),  # a single card is one entity, never "empty"
        (BOARD, False),
        (COMMENT, False),
        ({"deleted": CARD_ID}, False),  # a receipt names the thing it deleted
    ],
)
def test_names_no_entity_recognises_exactly_the_empty_shapes(result, empty):
    """The predicate is an *enumeration*, not a falsiness test — a general "is this
    falsy" rule would strip hints off shapes it had never seen. Both directions are
    asserted so it can neither over- nor under-fire."""
    assert cli._names_no_entity(result) is empty


@pytest.mark.parametrize("verb", CAN_BE_EMPTY)
def test_an_empty_result_drops_every_hint_that_names_a_row(monkeypatch, capsys, verb, board):
    """Two runs, because the empty assertion alone would pass for a verb that never
    had an ``<id>`` hint in the first place: the populated run proves the hints being
    dropped genuinely exist, then the empty run proves every one of them is gone and
    that nothing new appeared in their place."""
    argv, populated_result = HINTED[verb]
    populated = hints_in(
        run_ok(monkeypatch, capsys, argv, result=populated_result,
               results={"get_card": populated_result})
    )
    assert [line for line in populated if "<id>" in line], f"{verb} has no <id> hint"

    empty = hints_in(run_ok(monkeypatch, capsys, argv, result=EMPTY_RESULTS[verb]))
    assert all("<id>" not in line for line in empty), f"{verb} kept a hint about no rows"
    assert set(empty) <= set(populated)  # survivors only; the drop invents nothing


@pytest.mark.parametrize("verb", sorted(HINTED))
def test_a_populated_result_still_prints_the_whole_hint_table(
    monkeypatch, capsys, verb, board
):
    """The control on KAN-526: suppression is conditional, never blanket. Every hinted
    verb with rows prints one line per template — so a predicate that quietly started
    returning True fails here for all thirteen rather than passing as 'fewer hints'."""
    argv, result = HINTED[verb]
    out = run_ok(monkeypatch, capsys, argv, result=result, results={"get_card": result})
    assert len(hints_in(out)) == len(cli._HINTS[verb])


def test_an_empty_overview_keeps_the_hints_that_are_not_about_rows(monkeypatch, capsys, board):
    """The per-verb difference the KAN-526 card asked for, and it falls out of the
    predicate rather than a table: an empty board is exactly when `overview`'s two
    board-level hints are most useful, so they stay, and only `pandan get <id>` — the
    one with nothing to point at — goes."""
    out = run_ok(monkeypatch, capsys, [], result={"cards": [], "next_cursor": None})
    assert hints_in(out) == [
        f"{cli.HINT_PREFIX} pandan list --column todo",
        f"{cli.HINT_PREFIX} pandan next --claim",
    ]
    assert "(no cards)" in out  # the AXI 5 zero state is untouched by the drop


def test_an_empty_list_is_the_zero_state_and_the_aggregate_and_nothing_else(
    monkeypatch, capsys, board
):
    """The symptom KAN-526 was filed for, pinned as whole stdout. Both of `list`'s
    hints name an ``<id>``, so an empty result keeps neither — and the two lines that
    are contracts (AXI 5's prose zero, V44's ``tail -1`` aggregate) both survive."""
    out = run_ok(monkeypatch, capsys, ["list"], result={"cards": [], "next_cursor": None})
    assert out.splitlines() == ["(no cards)", "0 cards · 0 todo · 0 in_progress · 0 done"]


def test_an_empty_next_is_the_zero_state_and_nothing_else(monkeypatch, capsys, board):
    """`next` is the case the card did not name and the one an agent hits most: polling
    a drained board used to answer "(no card ready)" and then suggest moving a card.
    It has no aggregate to redeem it either, so the whole of stdout is one line."""
    out = run_ok(monkeypatch, capsys, ["next", "--board", "5"], result={"card": None})
    assert out.splitlines() == ["(no card ready)"]


# --- 3. `--help` is unchanged (AXI 10 regression guard) ----------------------


def test_help_text_is_word_for_word_unchanged_from_the_golden(monkeypatch, capsys):
    """Content-first must not cost the usage text. The golden was captured from
    ``origin/main`` before V46 existed, so any drift in the help *surface* — a newly
    visible subcommand, a reworded epilog, a dropped line — fails here.

    **It is a change-detector, not a freeze** (KAN-492). V46 read it as the latter and
    shipped ``overview`` unlisted to keep it green, which inverted the disclosure
    principle the AXI 10 guard exists to serve. A deliberate help change may therefore
    regenerate the golden — mechanically, from the parser, in the *same* diff, with the
    resulting one-line delta shown in the PR — and the guard keeps its teeth because
    every *other* verb's line, the whole epilog and the usage text are still pinned,
    and because the companion test below forbids the specific dodge V46 took.

    Compared word-for-word rather than byte-for-byte; see ``help_words`` for why
    (argparse's column layout tracks the interpreter, not this CLI). KAN-492 did not
    re-tighten that: the usage line stays the only byte-pinned part."""
    monkeypatch.setenv("COLUMNS", GOLDEN_WIDTH)
    with pytest.raises(SystemExit) as exc:
        cli.run(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert help_words(out) == help_words(HELP_GOLDEN.read_text(encoding="utf-8"))


def test_the_usage_line_is_byte_identical(monkeypatch, capsys):
    """The usage line is the one part of the help text whose *bytes* are worth pinning:
    it is a single line, it never wraps at 80 columns, and it is what a reader copies.

    It is **not** a proxy for the subparsers action staying ``required=True``. An
    earlier version of this test claimed it was, on the theory that `required=False`
    renders ``[<command> ...]``; a mutation test flipped the flag and this stayed green,
    because a positional with ``nargs=PARSER`` is never bracketed. The real reason the
    flag stays put is in ``build_parser``'s comment, and it is not a help-text reason."""
    monkeypatch.setenv("COLUMNS", GOLDEN_WIDTH)
    with pytest.raises(SystemExit):
        cli.run(["--help"])
    first = capsys.readouterr().out.splitlines()[0]
    assert first == "usage: pandan [-h] [-v] <command> ..."
    assert first == HELP_GOLDEN.read_text(encoding="utf-8").splitlines()[0]


def test_help_still_prints_usage_and_makes_no_network_call(monkeypatch, capsys):
    """The bare-invocation branch must not swallow ``--help``: it prints usage, and it
    never reaches for a client (a hard failure if it tried)."""

    def boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("--help must not touch the network")

    monkeypatch.setattr(cli, "PandanClient", boom)
    monkeypatch.setenv("COLUMNS", GOLDEN_WIDTH)
    with pytest.raises(SystemExit) as exc:
        cli.run(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: pandan [-h] [-v] <command> ...")
    # Usage, not board state.
    assert "open cards" not in out


def test_no_top_level_verb_is_hidden_from_help(monkeypatch, capsys):
    """**The guard KAN-492 adds, and the reason the golden can be regenerated safely.**

    V46's ``overview`` worked but was invisible: ``add_parser`` builds the choices
    pseudo-action only ``if 'help' in kwargs``, so omitting ``help=`` registers a
    working verb that ``--help`` never mentions. That is the opposite of what AXI's
    disclosure principles ask for, and it happened as a side effect of protecting the
    golden. This asserts the property directly — every verb argparse will *accept* is
    a verb ``--help`` *lists* — so the trade can't be made again silently, and so
    "regenerate the golden" can never mean "hide the thing that changed".

    Checked two ways, because either alone passes for the wrong reason: the name must
    appear in the subcommand block, and argparse must have built a help entry for it
    (a verb merely mentioned in the epilog would satisfy the first)."""
    monkeypatch.setenv("COLUMNS", GOLDEN_WIDTH)
    with pytest.raises(SystemExit):
        cli.run(["--help"])
    out = capsys.readouterr().out
    # Exactly four spaces: that is the subcommand-entry indent. A wrapped help string
    # continues at 18 and the epilog's own lists start at 2, so neither can smuggle a
    # verb name into this set (`metrics`'s wrap contributes "aging", not a verb).
    listed = {
        line.split()[0]
        for line in out.splitlines()
        if line.startswith("    ") and not line.startswith("     ")
    }

    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert sub.choices, "no subcommands found — the walk itself broke"
    for name in sub.choices:
        assert name in listed, f"{name!r} is a working verb that --help does not list"
    # The pseudo-actions argparse renders from `help=` — one per verb, none missing.
    assert {action.dest for action in sub._choices_actions} == set(sub.choices)
    # And the verb this test was written for is one of them.
    assert cli.OVERVIEW_COMMAND in listed
