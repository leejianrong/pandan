"""Unit tests for the ``pandan`` CLI.

The CLI is a thin adapter, so we mock the shared ``PandanClient`` (patched into
``pandan_cli.cli``) and assert: each subcommand calls the right client method with
the right args, board-id default resolution, ``--json`` vs human output, and exit
codes (success, config errors, and a mapped ``PandanApiError``). A couple of tests
drive the real client over an ``httpx.MockTransport`` to prove the HTTP wiring.
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import subprocess
from typing import NamedTuple

import httpx
import pytest
from pandan_client import PandanApiError

from pandan_cli import build_info, cli, config

# The real find_mcp_json, captured before the autouse fixture patches it out — so
# the test that exercises the upward walk itself can reach the genuine impl.
_REAL_FIND_MCP_JSON = config.find_mcp_json

# A realistic single card carries a ``labels`` array (empty here) and a
# ``story_points`` key — like every ``CardRead`` from the API. The old fixture
# omitted both, which hid KAN-277 (a single card matched the broad list_labels
# branch and printed "(no labels)") and masked KAN-269's ``pts=`` field.
CARD = {
    "ticket_number": "KAN-1",
    "column": "todo",
    "title": "Ship it",
    "id": 1,
    "story_points": None,
    "labels": [],
}
EPIC = {
    "ticket_number": "EPIC-1",
    "name": "Onboarding",
    "description": "d",
    "id": 1,
    # Derived rollup + health (V32, KAN-296) ride the epic payload.
    "progress": {"total": 5, "done": 3, "percent": 60},
    "health": "at_risk",
}
BOARD = {"id": 2, "name": "Roadmap", "owner_id": None}


class FakeClient:
    """Records method calls; returns a canned result or raises a canned error."""

    def __init__(
        self,
        result=None,
        error: Exception | None = None,
        results: dict | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._result = CARD if result is None else result
        self._error = error
        # Optional per-method overrides (e.g. `list_cards` returns a card page while
        # `get_card` returns the single card) — used by the KAN-285 ticket-resolution
        # tests, where one command makes two different client calls.
        self._results = results or {}

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def _call(self, method: str, **kwargs):
        self.calls.append((method, kwargs))
        if self._error is not None:
            raise self._error
        if method in self._results:
            return self._results[method]
        return self._result

    def warmup(self):
        return self._call("warmup")

    def list_cards(self, **kw):
        return self._call("list_cards", **kw)

    def get_card(self, card_id):
        return self._call("get_card", card_id=card_id)

    def create_card(self, title, **kw):
        return self._call("create_card", title=title, **kw)

    def update_card(self, card_id, **kw):
        return self._call("update_card", card_id=card_id, **kw)

    def move_card(self, card_id, column, **kw):
        return self._call("move_card", card_id=card_id, column=column, **kw)

    def delete_card(self, card_id):
        return self._call("delete_card", card_id=card_id)

    def list_boards(self):
        return self._call("list_boards")

    def create_board(self, name):
        return self._call("create_board", name=name)

    def get_board(self, board_id):
        return self._call("get_board", board_id=board_id)

    def update_board(self, board_id, **kw):
        return self._call("update_board", board_id=board_id, **kw)

    def delete_board(self, board_id):
        return self._call("delete_board", board_id=board_id)

    def get_epic(self, epic_id):
        return self._call("get_epic", epic_id=epic_id)

    def create_cards(self, cards):
        return self._call("create_cards", cards=cards)

    def claim_card(self, card_id, assignee):
        return self._call("claim_card", card_id=card_id, assignee=assignee)

    def list_epics(self, **kw):
        return self._call("list_epics", **kw)

    def create_epic(self, name, **kw):
        return self._call("create_epic", name=name, **kw)

    def update_epic(self, epic_id, **kw):
        return self._call("update_epic", epic_id=epic_id, **kw)

    def delete_epic(self, epic_id):
        return self._call("delete_epic", epic_id=epic_id)

    def list_labels(self, board_id):
        return self._call("list_labels", board_id=board_id)

    def create_label(self, board_id, name, color):
        return self._call("create_label", board_id=board_id, name=name, color=color)

    def delete_label(self, label_id):
        return self._call("delete_label", label_id=label_id)

    def dispatch(self, board_id, **kw):
        return self._call("dispatch", board_id=board_id, **kw)

    def next_ready(self, board_id, **kw):
        return self._call("next_ready", board_id=board_id, **kw)

    def flag_needs_human(self, card_id, **kw):
        return self._call("flag_needs_human", card_id=card_id, **kw)

    def resolve_card(self, card_id):
        return self._call("resolve_card", card_id=card_id)

    def board_metrics(self, board_id, **kw):
        return self._call("board_metrics", board_id=board_id, **kw)

    def list_activity(self, board_id, **kw):
        return self._call("list_activity", board_id=board_id, **kw)

    def list_notifications(self, **kw):
        return self._call("list_notifications", **kw)

    def mark_notification_read(self, notification_id):
        return self._call("mark_notification_read", notification_id=notification_id)

    def list_views(self, board_id):
        return self._call("list_views", board_id=board_id)

    def create_view(self, board_id, name, query):
        return self._call("create_view", board_id=board_id, name=name, query=query)

    def delete_view(self, board_id, view_id):
        return self._call("delete_view", board_id=board_id, view_id=view_id)

    def update_cards(self, updates):
        return self._call("update_cards", updates=updates)

    def list_templates(self, board_id):
        return self._call("list_templates", board_id=board_id)

    def create_template(self, board_id, name, cards):
        return self._call("create_template", board_id=board_id, name=name, cards=cards)

    def delete_template(self, board_id, template_id):
        return self._call("delete_template", board_id=board_id, template_id=template_id)

    def apply_template(self, board_id, template_id):
        return self._call("apply_template", board_id=board_id, template_id=template_id)

    def list_cycles(self, board_id):
        return self._call("list_cycles", board_id=board_id)

    def create_cycle(self, board_id, name, **kw):
        return self._call("create_cycle", board_id=board_id, name=name, **kw)

    def delete_cycle(self, board_id, cycle_id):
        return self._call("delete_cycle", board_id=board_id, cycle_id=cycle_id)

    def cycle_metrics(self, board_id, cycle_id):
        return self._call("cycle_metrics", board_id=board_id, cycle_id=cycle_id)

    def add_dependency(self, card_id, blocker_id):
        return self._call("add_dependency", card_id=card_id, blocker_id=blocker_id)

    def remove_dependency(self, card_id, blocker_id):
        return self._call("remove_dependency", card_id=card_id, blocker_id=blocker_id)

    def list_dependencies(self, card_id):
        return self._call("list_dependencies", card_id=card_id)

    def add_link(self, card_id, label, url):
        return self._call("add_link", card_id=card_id, label=label, url=url)

    def remove_link(self, card_id, link_id):
        return self._call("remove_link", card_id=card_id, link_id=link_id)

    def add_comment(self, card_id, body):
        return self._call("add_comment", card_id=card_id, body=body)

    def list_comments(self, card_id):
        return self._call("list_comments", card_id=card_id)


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch, tmp_path):
    """Keep every test hermetic w.r.t. config *discovery*. The suite runs inside the
    repo tree, which has a real ``.mcp.json`` (and a developer may have a real
    ``~/.config/pandan/config.toml``); without this, ``load_config`` would silently
    resolve a token from those and defeat the 'no token → error' tests. Point
    ``XDG_CONFIG_HOME`` at an empty tmp dir and disable ``.mcp.json`` discovery by
    default; tests exercising those sources re-enable them explicitly.

    Also clears **both** env spellings of every key — the deprecated ``KANBAN_*``
    fallback (V40, KAN-423) means a developer's own shell could otherwise supply a
    token and defeat the same tests — and resets the one-shot deprecation-notice
    memo so notice assertions don't depend on test order."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: None)
    for names in config._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    config._warned.clear()


@pytest.fixture
def env(monkeypatch):
    """A valid environment (token set, no default board)."""
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_test")
    monkeypatch.delenv("PANDAN_BOARD_ID", raising=False)
    monkeypatch.delenv("PANDAN_API_URL", raising=False)


def patch_client(monkeypatch, fake: FakeClient) -> FakeClient:
    monkeypatch.setattr(cli, "PandanClient", lambda *a, **k: fake)
    return fake


def data_out(capsys) -> str:
    """stdout with V46's ``help:`` next-step lines removed (KAN-429).

    ``_emit`` prints those for the hinted verbs (``get``/``create``/``move``/``next``/
    ``list``/…) after the result and — since KAN-492 — *before* V44's aggregate. The
    assertions that use this helper are about the row itself, so they read the data
    lines only rather than restating V46's contract, which is pinned in
    ``tests/test_content_first.py``."""
    out = capsys.readouterr().out
    return "\n".join(line for line in out.splitlines() if not line.startswith(cli.HINT_PREFIX))


# ``list``'s own hints (KAN-492), printed between the rows and V44's aggregate. The
# byte-exact ``list`` assertions below splice this in rather than filtering it out with
# ``data_out``, so they keep proving that nothing *else* reached stdout — and that the
# aggregate is still the final line.
LIST_HINTS = "help: pandan get <id>\nhelp: pandan move <id> in_progress\n"


def data_out_lines(out: str) -> list[str]:
    """``out``'s lines minus the ``help:`` hints — for counting *data* lines."""
    return [line for line in out.splitlines() if not line.startswith(cli.HINT_PREFIX)]


class Err(NamedTuple):
    """A parsed structured error (V43, KAN-426): the row's three fields + both streams."""

    code: str
    message: str
    arg: str
    out: str
    err: str


def read_error(capsys) -> Err:
    """Parse the structured error row the CLI prints on **stdout**, asserting there is
    exactly one and that the machine channel is stdout (AXI 6). Errors are no longer
    prose on stderr, so every failure assertion goes through here."""
    captured = capsys.readouterr()
    rows = [line for line in captured.out.splitlines() if line.startswith("error\t")]
    assert len(rows) == 1, f"expected one error row on stdout, got out={captured.out!r}"
    _, code, message, arg = rows[0].split("\t")
    assert "pandan:" not in captured.err  # the old stderr prose is gone
    return Err(code, message, arg, captured.out, captured.err)


# --- --version / -v (top-level, no subcommand) ------------------------------


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_version_flag_prints_version_and_exits_zero(flag, capsys):
    # argparse's action="version" prints to stdout and raises SystemExit(0),
    # short-circuiting before the required subcommand is enforced.
    with pytest.raises(SystemExit) as exc:
        cli.run([flag])
    assert exc.value.code == 0
    # Asserted against the package's own ``__version__`` rather than a literal, so a
    # version bump doesn't need a test edit (it did for 0.3.0 → 0.4.0 at the rebrand).
    from pandan_cli import __version__

    out = capsys.readouterr().out.strip()
    assert out.startswith(f"pandan {__version__} (")
    # The test suite runs from a source checkout, so there is no build stamp and the
    # line must say so rather than look like a release (V50, KAN-435).
    assert out == f"pandan {__version__} ({build_info.SOURCE_LABEL})"


# --- build provenance in --version (V50, KAN-435) ---------------------------


def test_version_string_released_build_shows_commit():
    # Metadata is injected, not built: a unit test must not depend on PyInstaller.
    assert build_info.version_string("0.5.0", "a10eaee") == "pandan 0.5.0 (a10eaee)"
    # A build off an uncommitted tree is flagged as such by stamp_build.py.
    assert build_info.version_string("0.5.0", "a10eaee-dirty") == "pandan 0.5.0 (a10eaee-dirty)"


@pytest.mark.parametrize("sha", [None, "", "   "])
def test_version_string_source_run_is_honest_and_never_claims_a_release(sha):
    # No stamp (or a blank one) must not crash and must not read as a release.
    out = build_info.version_string("0.5.0", sha)
    assert out == "pandan 0.5.0 (source checkout, not a released build)"
    assert "source" in out


def test_version_string_is_ascii_single_line():
    # --version is machine-readable stdout on every platform: no em dashes, one line.
    for sha in ("a10eaee", None):
        out = build_info.version_string("0.5.0", sha)
        out.encode("ascii")  # raises if a non-ASCII char sneaks in
        assert "\n" not in out


def test_declared_version_matches_pyproject():
    # The bump-on-fix guard only checks that the version FILES moved; this catches
    # the half-bump (pyproject bumped, __init__ not — the KAN-46-era drift).
    from pandan_cli import __version__

    pyproject = (pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert declared is not None
    assert declared.group(1) == __version__


def test_build_stamp_is_not_committed():
    # `_build_stamp.py` is generated + git-ignored. If it is ever committed, every
    # source checkout starts reporting itself as a release — the exact confusion
    # V50 exists to remove. (After a local stamped build, delete it.)
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files", "pandan-cli/pandan_cli/_build_stamp.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout.strip() == ""


# --- each command calls the right client method with the right args ---------


def test_list_maps_all_filters(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    code = cli.run(["list", "--board", "3", "--column", "done", "--epic", "5", "--limit", "10"])
    assert code == 0
    assert fake.calls == [
        (
            "list_cards",
            {
                "board_id": 3,
                "ids": None,
                "refs": None,
                "column": "done",
                "epic_id": 5,
                "cycle_id": None,
                "priority": None,
                "label": None,
                "due_before": None,
                "overdue": None,
                "needs_human": None,
                "assignee": None,
                "q": None,
                "sort": None,
                "limit": 10,
            },
        )
    ]


def test_list_maps_card_field_filters(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    code = cli.run(
        ["list", "--priority", "high", "--label", "4", "--due-before", "2026-08-01", "--overdue"]
    )
    assert code == 0
    call = fake.calls[0][1]
    assert call["priority"] == "high"
    assert call["label"] == 4
    assert call["due_before"] == "2026-08-01"
    assert call["overdue"] is True


def test_list_maps_assignee_and_sort(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    code = cli.run(["list", "--assignee", "agent-7", "--sort=-priority,position"])
    assert code == 0
    call = fake.calls[0][1]
    assert call["assignee"] == "agent-7"
    assert call["sort"] == "-priority,position"


def test_list_maps_q_search(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    code = cli.run(["list", "--q", "login flow"])
    assert code == 0
    assert fake.calls[0][1]["q"] == "login flow"


def test_view_list_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"views": []}))
    code = cli.run(["view", "list", "--board", "3"])
    assert code == 0
    assert fake.calls == [("list_views", {"board_id": 3})]


def test_view_create_assembles_query_from_flags(monkeypatch, env):
    fake = patch_client(
        monkeypatch, FakeClient(result={"id": 1, "name": "mine", "query": {}})
    )
    code = cli.run(
        ["view", "create", "mine", "--board", "3", "--priority", "high",
         "--assignee", "me", "--sort=-priority"]
    )
    assert code == 0
    assert fake.calls == [
        (
            "create_view",
            {
                "board_id": 3,
                "name": "mine",
                "query": {"priority": "high", "assignee": "me", "sort": "-priority"},
            },
        )
    ]


def test_view_delete_requires_yes(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    # Without --yes the CLI refuses (config error → exit 1), no client call.
    assert cli.run(["view", "delete", "5", "--board", "3"]) == 1
    assert fake.calls == []
    # With --yes it deletes.
    assert cli.run(["view", "delete", "5", "--board", "3", "--yes"]) == 0
    assert fake.calls == [("delete_view", {"board_id": 3, "view_id": 5})]


# --- batch update + templates (M5 V19 / KAN-252) ---------------------------


def test_batch_update_parses_json_array(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"updated": []}))
    code = cli.run(["batch-update", '[{"id": 1, "assignee": "me"}, {"id": 2, "priority": "high"}]'])
    assert code == 0
    assert fake.calls == [
        (
            "update_cards",
            {"updates": [{"id": 1, "assignee": "me"}, {"id": 2, "priority": "high"}]},
        )
    ]


def test_batch_update_rejects_non_array(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"updated": []}))
    # A JSON object (not an array) is a usage error → exit 1, no client call.
    assert cli.run(["batch-update", '{"id": 1}']) == 1
    assert fake.calls == []


def test_template_list_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"templates": []}))
    assert cli.run(["template", "list", "--board", "3"]) == 0
    assert fake.calls == [("list_templates", {"board_id": 3})]


def test_template_create_parses_cards_json(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"id": 7}))
    code = cli.run(
        ["template", "create", "sprint", "--board", "3", "--cards", '[{"title": "A"}]']
    )
    assert code == 0
    assert fake.calls == [
        ("create_template", {"board_id": 3, "name": "sprint", "cards": [{"title": "A"}]})
    ]


def test_template_apply_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"created": []}))
    assert cli.run(["template", "apply", "7", "--board", "3"]) == 0
    assert fake.calls == [("apply_template", {"board_id": 3, "template_id": 7})]


def test_template_delete_requires_yes(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 7}))
    assert cli.run(["template", "delete", "7", "--board", "3"]) == 1
    assert fake.calls == []
    assert cli.run(["template", "delete", "7", "--board", "3", "--yes"]) == 0
    assert fake.calls == [("delete_template", {"board_id": 3, "template_id": 7})]


# --- cycle subcommands (V33 / KAN-297) -------------------------------------


def test_cycle_list_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cycles": []}))
    assert cli.run(["cycle", "list", "--board", "3"]) == 0
    assert fake.calls == [("list_cycles", {"board_id": 3})]


def test_cycle_create_passes_name_and_bounds(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"id": 4, "name": "sprint-1"}))
    code = cli.run(
        ["cycle", "create", "sprint-1", "--board", "3",
         "--starts-on", "2026-01-01T00:00:00Z", "--ends-on", "2026-01-14T00:00:00Z"]
    )
    assert code == 0
    assert fake.calls == [
        (
            "create_cycle",
            {
                "board_id": 3,
                "name": "sprint-1",
                "starts_on": "2026-01-01T00:00:00Z",
                "ends_on": "2026-01-14T00:00:00Z",
            },
        )
    ]


def test_cycle_delete_requires_yes(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 4}))
    assert cli.run(["cycle", "delete", "4", "--board", "3"]) == 1
    assert fake.calls == []
    assert cli.run(["cycle", "delete", "4", "--board", "3", "--yes"]) == 0
    assert fake.calls == [("delete_cycle", {"board_id": 3, "cycle_id": 4})]


CYCLE_METRICS = {
    "board_id": 3,
    "cycle_id": 4,
    "generated_at": "2026-07-17T12:00:00Z",
    "starts_on": "2026-07-01T00:00:00Z",
    "ends_on": "2026-07-03T00:00:00Z",
    "committed": {"count": 3, "points": 16},
    "completed": {"count": 2, "points": 11},
    "velocity": 11,
    "unit": "points",
    "burndown": [
        {"date": "2026-07-01", "remaining": 13, "completed": 3, "ideal": 16.0},
        {"date": "2026-07-03", "remaining": 5, "completed": 11, "ideal": 0.0},
    ],
}


def test_cycle_metrics_maps_board_and_cycle(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=CYCLE_METRICS))
    assert cli.run(["cycle", "metrics", "4", "--board", "3"]) == 0
    assert fake.calls == [("cycle_metrics", {"board_id": 3, "cycle_id": 4})]


def test_cycle_metrics_pretty_renders_burndown(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=CYCLE_METRICS))
    assert cli.run(["cycle", "metrics", "4", "--board", "3"]) == 0
    out = capsys.readouterr().out
    assert "velocity:    11 pts done" in out
    assert "committed:   3 stories  16 pts" in out
    assert "2026-07-01\tremaining 13\tideal 16.0" in out


def test_cycle_metrics_json(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=CYCLE_METRICS))
    assert cli.run(["cycle", "metrics", "4", "--board", "3", "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["velocity"] == 11


def test_list_filters_by_cycle(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    assert cli.run(["list", "--cycle", "4"]) == 0
    assert fake.calls[0][1]["cycle_id"] == 4


def test_create_and_update_pass_cycle(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["create", "S", "--cycle", "4"]) == 0
    assert fake.calls[0][1]["cycle_id"] == 4
    assert cli.run(["update", "7", "--cycle", "5"]) == 0
    assert fake.calls[1][1]["cycle_id"] == 5


def test_list_needs_human_filter(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    assert cli.run(["list", "--needs-human"]) == 0
    assert fake.calls[0][1]["needs_human"] is True


def test_needs_human_with_note(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["needs-human", "1", "--note", "decide the region"]) == 0
    assert fake.calls == [
        ("flag_needs_human", {"card_id": 1, "attention_note": "decide the region"})
    ]


def test_needs_human_without_note(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["needs-human", "2"]) == 0
    assert fake.calls == [("flag_needs_human", {"card_id": 2, "attention_note": None})]


METRICS = {
    "board_id": 2,
    "generated_at": "2026-07-17T12:00:00Z",
    "since": None,
    "until": "2026-07-17T12:00:00Z",
    "throughput": 2,
    "cycle_time": {
        "count": 2,
        "avg_seconds": 7200.0,
        "median_seconds": 7200.0,
        "p90_seconds": 10800.0,
    },
    "aging_wip": {
        "count": 1,
        "avg_seconds": 1800.0,
        "max_seconds": 1800.0,
        "items": [
            {
                "card_id": 3,
                "ticket_number": "KAN-3",
                "assignee": "agent-b",
                "age_seconds": 1800.0,
            }
        ],
    },
    "by_assignee": [{"assignee": "agent-a", "throughput": 2, "wip": 0}],
}


def test_metrics_maps_board_and_window(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=METRICS))
    assert cli.run(["metrics", "--board", "2", "--window", "7d"]) == 0
    assert fake.calls == [
        ("board_metrics", {"board_id": 2, "since": None, "window": "7d"})
    ]


def test_metrics_requires_a_board(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=METRICS))
    assert cli.run(["metrics"]) == 1  # no --board, no PANDAN_BOARD_ID → refused
    err = read_error(capsys)
    assert err.code == "board_required"
    assert "board is required" in err.message
    assert err.arg == "--board"


def test_metrics_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=METRICS))
    assert cli.run(["metrics", "--board", "2"]) == 0
    out = capsys.readouterr().out
    assert "throughput:  2 done" in out
    assert "cycle time:" in out
    assert "KAN-3" in out and "agent-b" in out
    assert "agent-a\tdone 2\twip 0" in out


ACTIVITY = [
    {
        "id": 9,
        "board_id": 2,
        "actor_label": "agent-a",
        "action": "moved",
        "summary": "moved KAN-3 to done",
        "ts": "2026-07-17T12:00:00Z",
    }
]


def test_activity_maps_board_and_filters(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"activity": ACTIVITY}))
    code = cli.run(
        ["activity", "--board", "2", "--actor", "agent-a", "--action", "moved", "--limit", "10"]
    )
    assert code == 0
    assert fake.calls == [
        (
            "list_activity",
            {
                "board_id": 2,
                "limit": 10,
                "cursor": None,
                "actor": "agent-a",
                "action": "moved",
            },
        )
    ]


def test_activity_requires_a_board(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"activity": []}))
    assert cli.run(["activity"]) == 1  # no --board, no PANDAN_BOARD_ID → refused
    err = read_error(capsys)
    assert err.code == "board_required"
    assert err.arg == "--board"


def test_activity_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"activity": ACTIVITY}))
    assert cli.run(["activity", "--board", "2"]) == 0
    out = capsys.readouterr().out
    assert "agent-a" in out and "moved" in out and "moved KAN-3 to done" in out


# --- notification inbox (V37, KAN-301) --------------------------------------

NOTIFICATIONS = [
    {"id": 2, "kind": "needs_human", "read_at": None, "body": "KAN-3 needs a human"},
    {"id": 1, "kind": "assigned", "read_at": "2026-07-17T12:00:00Z",
     "body": "KAN-1 assigned to me"},
]


def test_notify_list_calls_client_all(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"notifications": NOTIFICATIONS}))
    assert cli.run(["notify", "list"]) == 0
    # No --board (per-user); unread omitted → None (all).
    assert fake.calls == [("list_notifications", {"unread": None})]


def test_notify_list_unread_flag(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"notifications": []}))
    assert cli.run(["notify", "list", "--unread"]) == 0
    assert fake.calls == [("list_notifications", {"unread": True})]


def test_notify_list_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"notifications": NOTIFICATIONS}))
    assert cli.run(["notify", "list"]) == 0
    out = capsys.readouterr().out
    assert "needs_human" in out and "unread" in out and "KAN-3 needs a human" in out
    assert "read" in out  # the assigned one is read


def test_notify_read_marks_by_id(monkeypatch, env, capsys):
    fake = patch_client(
        monkeypatch,
        FakeClient(result={"id": 2, "kind": "needs_human", "read_at": "2026-07-18T00:00:00Z",
                           "body": "KAN-3 needs a human"}),
    )
    assert cli.run(["notify", "read", "2"]) == 0
    assert fake.calls == [("mark_notification_read", {"notification_id": 2})]
    assert "needs_human" in capsys.readouterr().out


def test_resolve(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["resolve", "7"]) == 0
    assert fake.calls == [("resolve_card", {"card_id": 7})]


def test_get_passes_card_id(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["get", "42"]) == 0
    assert fake.calls == [("get_card", {"card_id": 42})]


def test_create_maps_all_options(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    code = cli.run(
        [
            "create", "My story",
            "--board", "2", "--description", "d",
            "--column", "in_progress", "--points", "5",
            "--assignee", "alice", "--epic", "9",
        ]
    )
    assert code == 0
    assert fake.calls == [
        (
            "create_card",
            {
                "title": "My story",
                "board_id": 2,
                "description": "d",
                "column": "in_progress",
                "story_points": 5,
                "assignee": "alice",
                "epic_id": 9,
                "cycle_id": None,
                "priority": None,
                "due_date": None,
                "label_ids": None,
            },
        )
    ]


def test_create_maps_card_fields(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    code = cli.run(
        [
            "create", "S",
            "--priority", "urgent", "--due", "2026-08-01T00:00:00Z",
            "--label", "1", "--label", "2",
        ]
    )
    assert code == 0
    call = fake.calls[0][1]
    assert call["priority"] == "urgent"
    assert call["due_date"] == "2026-08-01T00:00:00Z"
    assert call["label_ids"] == [1, 2]


def test_update_maps_fields(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    code = cli.run(["update", "7", "--title", "New", "--points", "8", "--assignee", "bob"])
    assert code == 0
    assert fake.calls == [
        (
            "update_card",
            {
                "card_id": 7,
                "title": "New",
                "description": None,
                "story_points": 8,
                "assignee": "bob",
                "epic_id": None,
                "cycle_id": None,
                "priority": None,
                "due_date": None,
                "label_ids": None,
            },
        )
    ]


def test_update_maps_card_fields(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    code = cli.run(["update", "7", "--priority", "low", "--due", "2026-09-01", "--label", "3"])
    assert code == 0
    call = fake.calls[0][1]
    assert call["priority"] == "low"
    assert call["due_date"] == "2026-09-01"
    assert call["label_ids"] == [3]


# --- label subcommands ------------------------------------------------------


def test_label_list_maps_board(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"labels": []}))
    assert cli.run(["label", "list", "--board", "2"]) == 0
    assert fake.calls == [("list_labels", {"board_id": 2})]


def test_label_create_passes_name_and_color(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(result={"id": 1, "board_id": 2, "name": "bug", "color": "#ef4444"}),
    )
    assert cli.run(["label", "create", "bug", "#ef4444", "--board", "2"]) == 0
    assert fake.calls == [
        ("create_label", {"board_id": 2, "name": "bug", "color": "#ef4444"})
    ]


def test_label_delete_requires_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    assert cli.run(["label", "delete", "5"]) == 1  # no --yes → refused
    assert fake.calls == []
    assert cli.run(["label", "delete", "5", "--yes"]) == 0
    assert fake.calls == [("delete_label", {"label_id": 5})]


def test_move_passes_column_and_position(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["move", "7", "done", "--position", "0"]) == 0
    assert fake.calls == [("move_card", {"card_id": 7, "column": "done", "position": 0})]


def test_move_defaults_position_to_none(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["move", "7", "in_progress"]) == 0
    assert fake.calls == [("move_card", {"card_id": 7, "column": "in_progress", "position": None})]


# --- board-id default resolution --------------------------------------------


def test_list_uses_board_env_default(monkeypatch, env):
    monkeypatch.setenv("PANDAN_BOARD_ID", "7")
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    cli.run(["list"])
    assert fake.calls[0][1]["board_id"] == 7


def test_flag_overrides_board_env_default(monkeypatch, env):
    monkeypatch.setenv("PANDAN_BOARD_ID", "7")
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    cli.run(["list", "--board", "3"])
    assert fake.calls[0][1]["board_id"] == 3


# --- delete confirmation guard ----------------------------------------------


def test_delete_requires_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    code = cli.run(["delete", "5"])
    assert code == cli.EXIT_ERROR
    assert fake.calls == []  # never touched the API
    # Stdout is non-empty and self-describing: a scripted sweep sees a REASON, not the
    # silence that used to read as "the verb returned nothing" (M7 stage-3 note).
    err = read_error(capsys)
    assert err.code == "confirmation_required"
    assert err.arg == "--yes"


def test_delete_with_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    assert cli.run(["delete", "5", "--yes"]) == 0
    assert fake.calls == [("delete_card", {"card_id": 5})]
    assert "deleted card 5" in capsys.readouterr().out


# --- --json vs human output -------------------------------------------------


def test_json_output_is_the_envelope_plus_the_summary(monkeypatch, env, capsys):
    """``--json`` is the client envelope verbatim **plus** V44's ``summary`` object
    (KAN-427): the rows are untouched, and the aggregate rides beside them rather
    than as a trailing line a JSON consumer would have to strip."""
    patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    assert cli.run(["list", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["cards"] == [CARD]
    assert parsed == {
        "cards": [CARD],
        "summary": {
            "count": 1, "todo": 1, "in_progress": 0, "done": 0, "needs_human": 0
        },
    }


def test_json_flag_before_subcommand(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient())
    assert cli.run(["--json", "get", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == CARD


def test_human_output_is_concise_line(monkeypatch, env, capsys):
    # CARD has no story_points → rendered pts=- (never the literal "None").
    # The row is followed by `list`'s hints (KAN-492) and then V44's aggregate
    # line (KAN-427) — in that order, so `tail -1` is still the aggregate.
    patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    cli.run(["list"])
    out = capsys.readouterr().out.strip()
    assert out == (
        "KAN-1\ttodo\tShip it\tpts=-\n"
        + LIST_HINTS
        + "1 card · 1 todo · 0 in_progress · 0 done"
    )


def test_human_output_empty_list(monkeypatch, env, capsys):
    """No ``LIST_HINTS`` here on purpose: both of `list`'s hints name an ``<id>``, and
    an empty result has none to name, so KAN-526 drops them. The zero state and the
    aggregate are all that is left — and this stays a whole-stdout pin, so a hint
    creeping back would fail here."""
    patch_client(monkeypatch, FakeClient(result={"cards": []}))
    cli.run(["list"])
    assert capsys.readouterr().out.strip() == (
        "(no cards)\n0 cards · 0 todo · 0 in_progress · 0 done"
    )


def test_create_with_points_shows_points_in_human_output(monkeypatch, env, capsys):
    """KAN-269 regression: `create --points N` human output must show the points (from
    the API's `story_points` field), not null/None. The reporter's null was a jq
    missing-key artifact (`points` is not an API field); the CLI now surfaces it."""
    # Carries labels:[] like a real CardRead — reproduces the KAN-277 trap.
    created = {
        "ticket_number": "KAN-9", "column": "todo", "title": "Estimated",
        "story_points": 5, "labels": [],
    }
    patch_client(monkeypatch, FakeClient(result=created))
    assert cli.run(["create", "Estimated", "--points", "5"]) == 0
    out = capsys.readouterr().out.strip()
    assert "pts=5" in out
    assert "None" not in out
    assert "null" not in out


def test_get_shows_story_points_field(monkeypatch, env, capsys):
    """A single-card `get` renders story_points as pts=N (KAN-269)."""
    # Carries labels:[] like a real CardRead — reproduces the KAN-277 trap.
    card = {
        "ticket_number": "KAN-3", "column": "in_progress", "title": "WIP",
        "story_points": 8, "labels": [],
    }
    patch_client(monkeypatch, FakeClient(result=card))
    assert cli.run(["get", "3"]) == 0
    assert data_out(capsys).strip() == "KAN-3\tin_progress\tWIP\tpts=8"


def test_single_card_with_labels_renders_card_line_not_no_labels(monkeypatch, env, capsys):
    """KAN-277 regression: a single card carries a ``labels`` array, so ``get`` (and
    create/update/move) used to match the broad list_labels branch and print
    ``(no labels)`` instead of the card line (which also masked KAN-269's ``pts=``).
    The fixture MUST carry ``labels`` — that's the exact shape that hid the bug."""
    card = {
        "ticket_number": "KAN-260", "column": "done", "title": "Fix humanize",
        "story_points": 3, "labels": [{"id": 1, "name": "bug", "color": "#f00"}],
    }
    patch_client(monkeypatch, FakeClient(result=card))
    assert cli.run(["get", "260"]) == 0
    out = data_out(capsys).strip()
    assert out == "KAN-260\tdone\tFix humanize\tpts=3"
    assert out != "(no labels)"
    assert "(no labels)" not in out


def test_label_list_renders_labels(monkeypatch, env, capsys):
    """`pandan label list` on a real ``{"labels": [...]}`` response renders one line
    per label (id, name, color) — the legitimate consumer of the labels branch."""
    labels = {"labels": [
        {"id": 1, "name": "bug", "color": "#f00"},
        {"id": 2, "name": "chore", "color": "#0f0"},
    ]}
    patch_client(monkeypatch, FakeClient(result=labels))
    assert cli.run(["label", "list", "--board", "2"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == "1\tbug\t#f00\n2\tchore\t#0f0\n2 labels"


def test_label_list_empty_shows_no_labels(monkeypatch, env, capsys):
    """An empty label-LIST response still yields ``(no labels)`` (KAN-277 must not
    over-correct and break the genuine empty-list case)."""
    patch_client(monkeypatch, FakeClient(result={"labels": []}))
    assert cli.run(["label", "list", "--board", "2"]) == 0
    assert capsys.readouterr().out.strip() == "(no labels)\n0 labels"


# --- exit codes / error mapping ---------------------------------------------


def test_missing_token_is_config_error(monkeypatch, capsys):
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    code = cli.run(["list"])
    assert code == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "config"
    assert "PANDAN_TOKEN" in err.message


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, cli.EXIT_AUTH),
        (403, cli.EXIT_FORBIDDEN),
        (404, cli.EXIT_NOT_FOUND),
        (500, cli.EXIT_ERROR),
    ],
)
def test_api_error_maps_to_exit_code(monkeypatch, env, capsys, status, expected):
    patch_client(monkeypatch, FakeClient(error=PandanApiError(status, "boom")))
    code = cli.run(["get", "1"])
    assert code == expected
    err = read_error(capsys)
    assert err.code == {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(
        status, "api_error"
    )
    assert "boom" in err.message


def test_unexpected_error_is_general(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(error=httpx.ConnectError("down")))
    assert cli.run(["get", "1"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "transport"  # no answer from the API, not a 4xx
    assert "down" in err.message


def test_usage_error_exits_two(env):
    # argparse exits (SystemExit) with code 2 on a bad invocation.
    with pytest.raises(SystemExit) as exc:
        cli.run(["move", "7", "not_a_column"])
    assert exc.value.code == cli.EXIT_USAGE


# --- board subcommands ------------------------------------------------------


def test_board_list_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"boards": [BOARD]}))
    assert cli.run(["board", "list"]) == 0
    assert fake.calls == [("list_boards", {})]


def test_board_create_passes_name(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=BOARD))
    assert cli.run(["board", "create", "Roadmap"]) == 0
    assert fake.calls == [("create_board", {"name": "Roadmap"})]


def test_board_list_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"boards": [BOARD]}))
    cli.run(["board", "list"])
    assert capsys.readouterr().out.strip() == "2\tRoadmap\n1 board"


def test_board_list_empty(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"boards": []}))
    cli.run(["board", "list"])
    assert capsys.readouterr().out.strip() == "(no boards)\n0 boards"


def test_board_list_json(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"boards": [BOARD]}))
    assert cli.run(["board", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "boards": [BOARD],
        "summary": {"count": 1},
    }


# --- KAN-502: the four CLI↔MCP parity gaps ----------------------------------
# ADR 0019 verified that parity ran one way only — every `pandan` verb had an MCP twin,
# not the reverse — and rejected "let the CLI be the surface" on exactly these four:
# `update_board` / `delete_board` (no CLI verb at all), `claim_card` (a chosen card
# needed `move` + `update`) and `create_cards` (N invocations). These close them.
#
# The mechanical both-directions assertion lives in `tests/test_parity.py`; this section
# is the behaviour of each new verb.

# A realistic ``BoardRead``: the outbound-webhook **url + flag are readable, the secret
# is not** (backend/app/schemas.py:478-483 — write-only, like a password). The fixture
# omits it for the same reason the API does, so a test that finds the secret in output
# has found the CLI putting it there.
BOARD_WITH_WEBHOOK = {
    "id": 5,
    "name": "Roadmap",
    "owner_id": None,
    "autosync_enabled": False,
    "autosync_advance_to_done": False,
    "outbound_webhook_url": "https://hooks.example/pandan",
    "outbound_webhook_enabled": True,
    "role": "owner",
    "created_at": "2026-07-31T00:00:00Z",
    "updated_at": "2026-07-31T00:00:00Z",
}

# The literal used by every secret-leak assertion below. Distinctive on purpose — a
# substring search for it cannot accidentally match anything else the CLI prints —
# but built from dictionary words, and NOT bound to a name like ``FAKE_WEBHOOK_KEY``/``TOKEN``.
# The first draft was a high-entropy ``FAKE_WEBHOOK_KEY = "…"`` and CI's gitleaks scan flagged it
# as a ``generic-api-key``, correctly: a random-looking string assigned to a name that
# says "secret" is indistinguishable from the real thing, and this repo's rule is to fix
# such a finding at the source rather than allowlist it (ci.yml:419-420). Low entropy is
# the point, so keep it prose.
FAKE_WEBHOOK_KEY = "not-a-real-webhook-signing-key-for-tests-only"


def test_the_verbs_this_slice_did_not_touch_are_byte_identical(monkeypatch, env, capsys):
    """The identity invariant, asserted BEFORE the new behaviour (and the reason this
    test sits first): adding `get`/`update`/`delete` to the `board` group, a `claim`
    verb and `batch-create` must not have moved a single byte of what the pre-existing
    verbs print. `board list`, `board create` and `create` are the three the new code
    sits closest to — `_humanize`'s board branch and its card-envelope branch, which
    KAN-502 widened to cover `created`."""
    patch_client(monkeypatch, FakeClient(result={"boards": [BOARD]}))
    cli.run(["board", "list"])
    assert capsys.readouterr().out == "2\tRoadmap\n1 board\n"

    patch_client(monkeypatch, FakeClient(result=BOARD))
    cli.run(["board", "create", "Roadmap"])
    assert data_out(capsys) == "2\tRoadmap"

    patch_client(monkeypatch, FakeClient(result=CARD))
    cli.run(["create", "Ship it"])
    assert data_out(capsys) == "KAN-1\ttodo\tShip it\tpts=-"


# --- gap 1a: `board get` ----------------------------------------------------


def test_board_get_calls_client_with_the_numeric_id(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    assert cli.run(["board", "get", "5"]) == 0
    assert fake.calls == [("get_board", {"board_id": 5})]


def test_board_get_human_output_is_the_board_line(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    cli.run(["board", "get", "5"])
    assert capsys.readouterr().out == "5\tRoadmap\n"


# --- gap 1b: `board update` -------------------------------------------------


def test_board_update_sends_only_the_flags_passed(monkeypatch, env):
    """The rename case — the one the packaged skill handed out a `curl` for. Every
    field the caller didn't name must arrive as ``None`` so the client's ``_clean``
    drops it and the PATCH leaves it untouched."""
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    assert cli.run(["board", "update", "5", "--name", "Pandan Roadmap"]) == 0
    assert fake.calls == [
        ("update_board", {
            "board_id": 5,
            "name": "Pandan Roadmap",
            "autosync_enabled": None,
            "autosync_advance_to_done": None,
            "outbound_webhook_url": None,
            "outbound_webhook_secret": None,
            "outbound_webhook_enabled": None,
        }),
    ]


def test_board_update_carries_the_whole_outbound_webhook_trio(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    code = cli.run([
        "board", "update", "5",
        "--outbound-webhook-url", "https://hooks.example/pandan",
        "--outbound-webhook-secret", FAKE_WEBHOOK_KEY,
        "--outbound-webhook-enabled",
    ])
    assert code == 0
    assert fake.calls == [
        ("update_board", {
            "board_id": 5,
            "name": None,
            "autosync_enabled": None,
            "autosync_advance_to_done": None,
            "outbound_webhook_url": "https://hooks.example/pandan",
            "outbound_webhook_secret": FAKE_WEBHOOK_KEY,
            "outbound_webhook_enabled": True,
        }),
    ]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--outbound-webhook-enabled"], True),
        (["--outbound-webhook-disabled"], False),
        (["--name", "x"], None),  # neither flag → leave the setting alone
    ],
)
def test_board_update_enabled_is_a_tri_state(monkeypatch, env, argv, expected):
    """``store_const`` with ``default=None``, not ``store_true``: "off" and "don't
    touch it" are different PATCHes, and a rename must not silently disable delivery."""
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    assert cli.run(["board", "update", "5", *argv]) == 0
    assert fake.calls[0][1]["outbound_webhook_enabled"] is expected


# --- KAN-529: the autosync pair, reachable from NEITHER adapter before this -----
# An API-coverage gap rather than a parity gap: `autosync_enabled` and
# `autosync_advance_to_done` are two of the six `BoardUpdate` fields
# (backend/app/schemas.py:436-443) and KAN-502 shipped only four, so the documented way
# to opt a board into EPIC-10 / ADR 0016 auto-sync stayed a raw `curl` — the exact state
# `pandan board update` was created to end. Landed on both surfaces in one PR so parity
# never goes one-directional in the *other* direction (CLI ⊃ MCP).


@pytest.mark.parametrize(
    ("argv", "field", "expected"),
    [
        (["--autosync-enabled"], "autosync_enabled", True),
        (["--autosync-disabled"], "autosync_enabled", False),
        (["--autosync-advance-to-done"], "autosync_advance_to_done", True),
        (["--no-autosync-advance-to-done"], "autosync_advance_to_done", False),
        # The third state, and the one with teeth: an unrelated update must not carry an
        # opinion about either flag. `store_const(default=None)`, never `store_true` —
        # a default of False would silently DISABLE auto-sync on every board rename.
        (["--name", "x"], "autosync_enabled", None),
        (["--name", "x"], "autosync_advance_to_done", None),
    ],
)
def test_board_update_autosync_flags_are_tri_states(monkeypatch, env, argv, field, expected):
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    assert cli.run(["board", "update", "5", *argv]) == 0
    assert fake.calls[0][1][field] is expected


def test_board_update_autosync_flags_are_independent_of_each_other(monkeypatch, env):
    """The two switches are separate by design (ADR 0016): `advance_to_done` is the
    human-in-the-loop safeguard, so turning the master switch on must not imply it, and
    naming one must leave the other unsent."""
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    assert cli.run(["board", "update", "5", "--autosync-enabled"]) == 0
    call = fake.calls[0][1]
    assert call["autosync_enabled"] is True
    assert call["autosync_advance_to_done"] is None


def test_board_update_autosync_does_not_disturb_the_webhook_trio(monkeypatch, env):
    """Opting into auto-sync must not touch the V38 outbound webhook — including its
    `enabled` flag, whose own tri-state is the KAN-502 property this mirrors."""
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    argv = ["board", "update", "5", "--autosync-enabled", "--autosync-advance-to-done"]
    assert cli.run(argv) == 0
    assert fake.calls == [
        ("update_board", {
            "board_id": 5,
            "name": None,
            "autosync_enabled": True,
            "autosync_advance_to_done": True,
            "outbound_webhook_url": None,
            "outbound_webhook_secret": None,
            "outbound_webhook_enabled": None,
        }),
    ]


def test_board_update_covers_every_boardupdate_field(monkeypatch, env):
    """The card's claim, asserted: `BoardUpdate` has **six** fields
    (backend/app/schemas.py:436-443) and `pandan board update` now reaches all six in one
    invocation. Counts on this project have been wrong before, so this pins the set by
    name rather than by a number in a docstring."""
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    code = cli.run([
        "board", "update", "5",
        "--name", "Pandan Roadmap",
        "--autosync-enabled",
        "--autosync-advance-to-done",
        "--outbound-webhook-url", "https://hooks.example/pandan",
        "--outbound-webhook-secret", FAKE_WEBHOOK_KEY,
        "--outbound-webhook-enabled",
    ])
    assert code == 0
    sent = fake.calls[0][1]
    assert set(sent) - {"board_id"} == {
        "name",
        "autosync_enabled",
        "autosync_advance_to_done",
        "outbound_webhook_url",
        "outbound_webhook_secret",
        "outbound_webhook_enabled",
    }
    assert not any(value is None for value in sent.values())


@pytest.mark.parametrize(
    "argv",
    [
        ["--autosync-enabled", "--autosync-disabled"],
        ["--autosync-advance-to-done", "--no-autosync-advance-to-done"],
    ],
)
def test_board_update_autosync_on_and_off_are_mutually_exclusive(monkeypatch, env, argv):
    with pytest.raises(SystemExit) as exc:
        cli.run(["board", "update", "5", *argv])
    assert exc.value.code == cli.EXIT_USAGE


def test_board_update_reads_the_secret_from_stdin(monkeypatch, env):
    """The documented path: argv is visible in ``ps`` and lands in shell history, so the
    secret goes over stdin exactly like ``config set --token-stdin``."""
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{FAKE_WEBHOOK_KEY}\n"))
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    argv = ["board", "update", "5", "--outbound-webhook-secret-stdin"]
    assert cli.run(argv) == 0
    assert fake.calls[0][1]["outbound_webhook_secret"] == FAKE_WEBHOOK_KEY
    # The value reached the client without ever being an argument.
    assert not any(FAKE_WEBHOOK_KEY in token for token in argv)


def test_board_update_empty_stdin_secret_is_an_error_not_a_no_op(monkeypatch, env, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    assert cli.run(["board", "update", "5", "--outbound-webhook-secret-stdin"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_input"
    assert err.arg == "--outbound-webhook-secret-stdin"
    assert fake.calls == []  # nothing was PATCHed


def test_board_update_secret_flag_and_stdin_are_mutually_exclusive(monkeypatch, env):
    with pytest.raises(SystemExit) as exc:
        cli.run([
            "board", "update", "5",
            "--outbound-webhook-secret", FAKE_WEBHOOK_KEY,
            "--outbound-webhook-secret-stdin",
        ])
    assert exc.value.code == cli.EXIT_USAGE


def test_board_update_with_no_fields_is_a_structured_error(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    assert cli.run(["board", "update", "5"]) == cli.EXIT_ERROR
    assert read_error(capsys).code == "invalid_input"
    assert fake.calls == []


@pytest.mark.parametrize("fmt", [[], ["--format", "json"], ["--format", "toon"]])
def test_board_update_never_prints_the_webhook_secret(monkeypatch, env, capsys, fmt):
    """**The guard that matters most in this slice.** The secret is write-only: the API
    accepts it on PATCH and never returns it (``BoardRead`` omits the field entirely).
    stdout is this CLI's machine channel — piped, redirected, and routinely captured
    into agent transcripts and CI logs — so echoing a credential there is the one
    failure here with consequences beyond ergonomics.

    Checked on **all three** formats, because human output happens to render a board as
    id+name (which would hide a leak by luck, not by design) while ``json``/``toon``
    serialize the whole payload.

    Written so it cannot pass for the wrong reason: it first asserts the secret
    genuinely **reached the client**. Without that, a `board update` that silently
    dropped the flag would satisfy "the secret isn't in the output" perfectly.

    **Mutation record, because one half of it is weaker than it looks.** Making the
    handler merge the secret into its result reddens ``json`` and ``toon`` immediately —
    but leaves ``human`` GREEN, because ``_board_line`` prints a fixed id+name projection
    and drops the extra key. So the human parametrization does not guard the
    result-payload route on its own; it needs the *renderer* to widen too. Both mutations
    applied together redden all three, and the read-side companion test below covers the
    renderer alone. Kept as three cases rather than collapsed to two: a leak added to the
    human branch (a stray print, an error echoing the value) is a real route the
    structured formats would not catch."""
    fake = patch_client(monkeypatch, FakeClient(result=BOARD_WITH_WEBHOOK))
    code = cli.run([
        "board", "update", "5", "--outbound-webhook-secret", FAKE_WEBHOOK_KEY, *fmt
    ])
    assert code == 0
    # Not blind: the flag is wired, so the absence below is a real property.
    assert fake.calls[0][1]["outbound_webhook_secret"] == FAKE_WEBHOOK_KEY
    captured = capsys.readouterr()
    assert FAKE_WEBHOOK_KEY not in captured.out
    assert FAKE_WEBHOOK_KEY not in captured.err
    # And the CLI did print something, so "no output" isn't what passed the test.
    assert captured.out.strip()


def test_board_get_never_prints_a_secret_even_if_the_api_returned_one(monkeypatch, env, capsys):
    """Belt-and-braces on the read side. ``BoardRead`` has no ``outbound_webhook_secret``
    today, so this asserts the CLI's *human* row is a fixed projection (id + name) rather
    than a dump of whatever arrived — the property that keeps a future API field from
    becoming a leak by default. ``--format json`` is deliberately NOT covered: it is
    documented as the client's raw dict, so a server that echoed a secret would show it
    there, and pretending otherwise would be the CLI lying about its own contract."""
    patch_client(
        monkeypatch,
        FakeClient(result={**BOARD_WITH_WEBHOOK, "outbound_webhook_secret": FAKE_WEBHOOK_KEY}),
    )
    assert cli.run(["board", "get", "5"]) == 0
    assert capsys.readouterr().out == "5\tRoadmap\n"


# --- gap 1c: `board delete` -------------------------------------------------


def test_board_delete_refuses_without_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    assert cli.run(["board", "delete", "5"]) == cli.EXIT_ERROR
    assert read_error(capsys).code == "confirmation_required"
    assert fake.calls == []


def test_board_delete_with_yes_reports_the_board_noun(monkeypatch, env, capsys):
    """``noun="board"`` matters: the delete receipt is shape-identical across entities
    (``{"deleted": id}``), so only the noun distinguishes "deleted board 5" from
    "deleted card 5" — and one of those is very much worse to misread."""
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    assert cli.run(["board", "delete", "5", "--yes"]) == 0
    assert fake.calls == [("delete_board", {"board_id": 5})]
    assert capsys.readouterr().out == "deleted board 5\n"


# --- gap 2: `claim` — an atomic claim of a CHOSEN card ----------------------


def test_claim_calls_claim_card_in_one_invocation(monkeypatch, env):
    """One invocation, not `move` + `update`. That pairing is what the CLI required
    before this verb, and nothing made a reader aware they had to run both."""
    fake = patch_client(monkeypatch, FakeClient(result=CARD))
    assert cli.run(["claim", "7", "--assignee", "agent-a"]) == 0
    assert fake.calls == [("claim_card", {"card_id": 7, "assignee": "agent-a"})]


def test_claim_resolves_a_ticket(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(results={"list_cards": {"cards": [CARD]}, "claim_card": CARD}),
    )
    assert cli.run(["claim", "KAN-1", "--assignee", "agent-a"]) == 0
    assert ("claim_card", {"card_id": 1, "assignee": "agent-a"}) in fake.calls


def test_claim_requires_an_assignee(monkeypatch, env):
    """Required, exactly as on the MCP ``claim_card`` tool: the client's ``claim_card``
    PATCHes the assignee it is handed and there is no "the caller" default on that path
    (only ``dispatch``, which ``next --claim`` uses, has one). Failing at argparse is
    better than silently moving the card and assigning it to nobody."""
    with pytest.raises(SystemExit) as exc:
        cli.run(["claim", "7"])
    assert exc.value.code == cli.EXIT_USAGE


def test_claim_prints_the_card_block(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=CARD))
    cli.run(["claim", "7", "--assignee", "agent-a"])
    assert data_out(capsys) == cli._card_block(CARD)


# --- gap 3: `batch-create` — N creates in one round trip --------------------


def _created(n: int) -> dict:
    return {"created": [
        {**CARD, "id": i, "ticket_number": f"KAN-{i}", "title": f"c{i}"}
        for i in range(1, n + 1)
    ]}


def test_batch_create_passes_the_array_through(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=_created(2)))
    payload = '[{"title": "a", "board_id": 5}, {"title": "b", "board_id": 5}]'
    assert cli.run(["batch-create", payload]) == 0
    assert fake.calls == [
        ("create_cards", {"cards": [
            {"title": "a", "board_id": 5},
            {"title": "b", "board_id": 5},
        ]}),
    ]


def test_batch_create_fills_the_board_into_objects_that_omit_it(monkeypatch, env):
    """A card dict with no ``board_id`` lands on your **earliest** board — the exact
    footgun `--board` / PANDAN_BOARD_ID resolution exists to prevent everywhere else.
    An object that names its own board keeps it, so one batch can still span boards."""
    fake = patch_client(monkeypatch, FakeClient(result=_created(2)))
    payload = '[{"title": "a"}, {"title": "b", "board_id": 9}]'
    assert cli.run(["batch-create", payload, "--board", "5"]) == 0
    assert fake.calls[0][1]["cards"] == [
        {"title": "a", "board_id": 5},
        {"title": "b", "board_id": 9},
    ]


def test_batch_create_uses_the_configured_board(monkeypatch, env):
    monkeypatch.setenv("PANDAN_BOARD_ID", "4")
    fake = patch_client(monkeypatch, FakeClient(result=_created(1)))
    assert cli.run(["batch-create", '[{"title": "a"}]']) == 0
    assert fake.calls[0][1]["cards"] == [{"title": "a", "board_id": 4}]


def test_batch_create_reads_stdin_so_a_plan_can_come_from_a_file(monkeypatch, env):
    monkeypatch.setattr("sys.stdin", io.StringIO('[{"title": "from a file", "board_id": 5}]'))
    fake = patch_client(monkeypatch, FakeClient(result=_created(1)))
    assert cli.run(["batch-create", "-"]) == 0
    assert fake.calls[0][1]["cards"] == [{"title": "from a file", "board_id": 5}]


def test_batch_create_prints_one_row_per_created_card_and_an_aggregate(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=_created(2)))
    assert cli.run(["batch-create", '[{"title": "c1"}, {"title": "c2"}]', "--board", "5"]) == 0
    out = capsys.readouterr().out
    assert out == (
        "KAN-1\ttodo\tc1\tpts=-\n"
        "KAN-2\ttodo\tc2\tpts=-\n"
        "2 cards · 2 todo · 0 in_progress · 0 done\n"
    )


def test_batch_create_json_keeps_the_clients_own_created_envelope(monkeypatch, env, capsys):
    """``--format json`` is documented as the client's raw dict, so the envelope stays
    ``created`` rather than being re-labelled ``cards`` for rendering convenience."""
    patch_client(monkeypatch, FakeClient(result=_created(1)))
    assert cli.run(["batch-create", '[{"title": "c1"}]', "--board", "5", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert list(payload["created"][0]["ticket_number"]) == list("KAN-1")
    assert payload["summary"]["count"] == 1


@pytest.mark.parametrize(
    "payload",
    ['{"title": "a"}', '[["title", "a"]]', '[{"description": "no title"}]', '[{"title": ""}]'],
)
def test_batch_create_rejects_a_payload_it_cannot_use(monkeypatch, env, capsys, payload):
    """Shape errors are caught before the first request, because the verb is fail-fast:
    a bad third object must not leave the first two created."""
    fake = patch_client(monkeypatch, FakeClient(result=_created(1)))
    assert cli.run(["batch-create", payload, "--board", "5"]) == cli.EXIT_ERROR
    assert read_error(capsys).code == "invalid_input"
    assert fake.calls == []


def test_batch_create_help_says_it_is_not_atomic(monkeypatch, capsys):
    """The card asks the CLI to *say* that `create_cards` is fail-fast rather than
    transactional, and `--help` is where a caller reads it. `batch-update` promises
    "atomically" two lines below, so the contrast has to be legible."""
    monkeypatch.setenv("COLUMNS", "100")
    with pytest.raises(SystemExit):
        cli.run(["--help"])
    top = capsys.readouterr().out
    assert "NOT" in top and "atomic" in top
    with pytest.raises(SystemExit):
        cli.run(["batch-create", "--help"])
    detail = capsys.readouterr().out
    assert "NOT atomic" in detail


# --- gap 4 (optional in the card): `epic get` ------------------------------


def test_epic_get_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=EPIC))
    assert cli.run(["epic", "get", "1"]) == 0
    assert fake.calls == [("get_epic", {"epic_id": 1})]


def test_epic_get_resolves_a_ticket(monkeypatch, env):
    fake = patch_client(
        monkeypatch, FakeClient(results={"list_epics": {"epics": [EPIC]}, "get_epic": EPIC})
    )
    assert cli.run(["epic", "get", "EPIC-1"]) == 0
    assert ("get_epic", {"epic_id": 1}) in fake.calls


def test_epic_get_rejects_a_card_ticket(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=EPIC))
    assert cli.run(["epic", "get", "KAN-1"]) == cli.EXIT_ERROR
    assert read_error(capsys).code == "invalid_ref"


# --- epic subcommands -------------------------------------------------------


def test_epic_list_maps_board_filter(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"epics": [EPIC]}))
    assert cli.run(["epic", "list", "--board", "3"]) == 0
    assert fake.calls == [("list_epics", {"board_id": 3})]


def test_epic_list_uses_board_env_default(monkeypatch, env):
    monkeypatch.setenv("PANDAN_BOARD_ID", "7")
    fake = patch_client(monkeypatch, FakeClient(result={"epics": []}))
    cli.run(["epic", "list"])
    assert fake.calls[0][1]["board_id"] == 7


def test_epic_create_maps_all_options(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=EPIC))
    code = cli.run(
        [
            "epic", "create", "Onboarding", "--board", "2", "--description", "d",
            "--target-date", "2026-09-01T00:00:00Z", "--lead", "ada",
        ]
    )
    assert code == 0
    assert fake.calls == [
        (
            "create_epic",
            {
                "name": "Onboarding", "board_id": 2, "description": "d",
                "target_date": "2026-09-01T00:00:00Z", "lead": "ada",
            },
        )
    ]


def test_epic_update_maps_fields(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result=EPIC))
    assert cli.run(
        [
            "epic", "update", "1", "--name", "New", "--description", "x",
            "--target-date", "2026-12-31T12:00:00Z", "--lead", "grace",
        ]
    ) == 0
    assert fake.calls == [
        (
            "update_epic",
            {
                "epic_id": 1, "name": "New", "description": "x",
                "target_date": "2026-12-31T12:00:00Z", "lead": "grace",
            },
        )
    ]


def test_epic_delete_requires_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 1}))
    code = cli.run(["epic", "delete", "1"])
    assert code == cli.EXIT_ERROR
    assert fake.calls == []  # never touched the API
    err = read_error(capsys)
    assert err.code == "confirmation_required"
    assert err.arg == "--yes"


def test_epic_delete_with_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 1}))
    assert cli.run(["epic", "delete", "1", "--yes"]) == 0
    assert fake.calls == [("delete_epic", {"epic_id": 1})]
    assert "deleted epic 1" in capsys.readouterr().out


def test_epic_list_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"epics": [EPIC]}))
    cli.run(["epic", "list"])
    assert capsys.readouterr().out.strip() == (
        "EPIC-1\tOnboarding\t60% (3/5) [at_risk]\n"
        "1 epic · 3/5 stories done (60%) · 1 at_risk"
    )


def test_epic_single_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=EPIC))
    cli.run(["epic", "create", "Onboarding"])
    # The head line is unchanged; V45 (KAN-428) appends the epic's own description
    # to a **single**-entity render (``EPIC`` carries ``description: "d"``), well
    # under the limit so it prints verbatim with no hint.
    assert data_out(capsys).strip() == (
        "EPIC-1\tOnboarding\t60% (3/5) [at_risk]\ndescription:\nd"
    )


def test_epic_missing_subcommand_is_usage_error(env):
    with pytest.raises(SystemExit) as exc:
        cli.run(["epic"])
    assert exc.value.code == cli.EXIT_USAGE


# --- warmup -----------------------------------------------------------------


def test_warmup_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"status": "ok", "health": {}}))
    assert cli.run(["warmup"]) == cli.EXIT_OK
    assert fake.calls == [("warmup", {})]


def test_warmup_ok_exits_zero(monkeypatch, env):
    patch_client(monkeypatch, FakeClient(result={"status": "ok", "health": {"status": "ok"}}))
    assert cli.run(["warmup"]) == cli.EXIT_OK


@pytest.mark.parametrize(
    "status", ["waking", "error"]
)
def test_warmup_not_ok_exits_nonzero(monkeypatch, env, status):
    patch_client(monkeypatch, FakeClient(result={"status": status, "detail": "not yet"}))
    assert cli.run(["warmup"]) == cli.EXIT_ERROR


def test_warmup_needs_no_token(monkeypatch, capsys):
    # No PANDAN_TOKEN set — warmup hits the public /api/health, so it must not
    # error out on a missing token like the other (auth-required) commands do.
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    monkeypatch.delenv("PANDAN_BOARD_ID", raising=False)
    monkeypatch.delenv("PANDAN_API_URL", raising=False)
    patch_client(monkeypatch, FakeClient(result={"status": "ok", "health": {}}))
    assert cli.run(["warmup"]) == cli.EXIT_OK


def test_warmup_human_output_ok(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"status": "ok", "health": {}}))
    cli.run(["warmup"])
    assert capsys.readouterr().out.strip() == "ok\tAPI is awake"


def test_warmup_human_output_waking(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"status": "waking", "detail": "retry shortly"}))
    cli.run(["warmup"])
    assert capsys.readouterr().out.strip() == "waking\tretry shortly"


def test_warmup_json_output(monkeypatch, env, capsys):
    result = {"status": "ok", "health": {"status": "ok"}}
    patch_client(monkeypatch, FakeClient(result=result))
    assert cli.run(["warmup", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == result


# --- real client over a MockTransport (HTTP wiring) -------------------------


def test_real_client_hits_move_endpoint(monkeypatch, env):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["content"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=CARD)

    from pandan_client import PandanClient

    monkeypatch.setattr(
        cli,
        "PandanClient",
        lambda url, token, **k: PandanClient(
            url, token, transport=httpx.MockTransport(handler)
        ),
    )
    assert cli.run(["move", "7", "done", "--position", "1"]) == 0
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/7/move"
    assert seen["content"] == {"column": "done", "position": 1}
    assert seen["auth"] == "Bearer pandan_pat_test"


def test_real_client_warmup_hits_unversioned_health(monkeypatch):
    # No token in the env: warmup must still reach the unversioned /api/health
    # (not /api/v1/...) and send no Authorization header.
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    monkeypatch.delenv("PANDAN_BOARD_ID", raising=False)
    monkeypatch.delenv("PANDAN_API_URL", raising=False)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"status": "ok"})

    from pandan_client import PandanClient

    monkeypatch.setattr(
        cli,
        "PandanClient",
        lambda url, token, **k: PandanClient(
            url, token, transport=httpx.MockTransport(handler)
        ),
    )
    assert cli.run(["warmup"]) == cli.EXIT_OK
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/health"
    assert seen["auth"] is None


# --- dependency / link / comment subcommands (KAN-270) ----------------------


def test_dep_add_maps_card_and_blocker(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["dep", "add", "7", "--blocked-by", "3"]) == 0
    assert fake.calls == [("add_dependency", {"card_id": 7, "blocker_id": 3})]


def test_dep_rm_maps_card_and_blocker(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["dep", "rm", "7", "--blocked-by", "3"]) == 0
    assert fake.calls == [("remove_dependency", {"card_id": 7, "blocker_id": 3})]


def test_dep_add_requires_blocked_by(env):
    # --blocked-by is required → argparse usage error (exit 2).
    with pytest.raises(SystemExit) as exc:
        cli.run(["dep", "add", "7"])
    assert exc.value.code == cli.EXIT_USAGE


def test_dep_list_calls_client(monkeypatch, env):
    fake = patch_client(
        monkeypatch, FakeClient(result={"card_id": 7, "blocked_by": [3], "blocks": [9]})
    )
    assert cli.run(["dep", "list", "7"]) == 0
    assert fake.calls == [("list_dependencies", {"card_id": 7})]


def test_dep_list_human_output(monkeypatch, env, capsys):
    patch_client(
        monkeypatch, FakeClient(result={"card_id": 7, "blocked_by": [3, 4], "blocks": []})
    )
    assert cli.run(["dep", "list", "7"]) == 0
    out = capsys.readouterr().out
    assert "card 7" in out
    assert "blocked_by:\t3, 4" in out
    assert "blocks:\t(none)" in out


def test_dep_list_json_output(monkeypatch, env, capsys):
    result = {"card_id": 7, "blocked_by": [3], "blocks": []}
    patch_client(monkeypatch, FakeClient(result=result))
    assert cli.run(["dep", "list", "7", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        **result,
        "summary": {"blocked_by": 1, "blocks": 0},
    }


def test_link_add_maps_label_and_url(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    code = cli.run(
        ["link", "add", "7", "--url", "https://github.com/o/r/pull/1", "--label", "PR"]
    )
    assert code == 0
    assert fake.calls == [
        ("add_link", {"card_id": 7, "label": "PR", "url": "https://github.com/o/r/pull/1"})
    ]


def test_link_add_requires_label_and_url(env):
    # Both --url and --label are required (the API's LinkCreate demands both).
    with pytest.raises(SystemExit) as exc:
        cli.run(["link", "add", "7", "--url", "https://x"])
    assert exc.value.code == cli.EXIT_USAGE


def test_dep_add_human_output_shows_edges(monkeypatch, env, capsys):
    # add_dependency returns the refreshed card; the verb projects just its edges.
    patch_client(
        monkeypatch,
        FakeClient(result={"ticket_number": "KAN-7", "blocked_by": [3], "blocks": [], "id": 7}),
    )
    assert cli.run(["dep", "add", "7", "--blocked-by", "3"]) == 0
    out = capsys.readouterr().out
    assert "card 7" in out
    assert "blocked_by:\t3" in out


def test_link_rm_maps_link_id(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["link", "rm", "7", "--link-id", "2"]) == 0
    assert fake.calls == [("remove_link", {"card_id": 7, "link_id": 2})]


def test_link_add_human_output_shows_links(monkeypatch, env, capsys):
    # add_link returns the refreshed card; the verb projects just its links.
    link = {"id": 2, "label": "PR", "url": "https://github.com/o/r/pull/1"}
    patch_client(
        monkeypatch,
        FakeClient(result={"ticket_number": "KAN-7", "links": [link], "labels": [], "id": 7}),
    )
    assert cli.run(["link", "add", "7", "--url", link["url"], "--label", "PR"]) == 0
    out = capsys.readouterr().out
    assert "card 7" in out
    assert "2\tPR\thttps://github.com/o/r/pull/1" in out


def test_comment_add_maps_body(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(result={"id": 1, "body": "looks good", "author_id": None}),
    )
    assert cli.run(["comment", "add", "7", "--body", "looks good"]) == 0
    assert fake.calls == [("add_comment", {"card_id": 7, "body": "looks good"})]


def test_comment_add_human_output(monkeypatch, env, capsys):
    patch_client(
        monkeypatch,
        FakeClient(
            result={
                "id": 1,
                "body": "looks good",
                "author_id": None,
                "created_at": "2026-07-20T00:00:00Z",
            }
        ),
    )
    assert cli.run(["comment", "add", "7", "--body", "looks good"]) == 0
    assert "looks good" in capsys.readouterr().out


def test_comment_list_calls_client(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"comments": []}))
    assert cli.run(["comment", "list", "7"]) == 0
    assert fake.calls == [("list_comments", {"card_id": 7})]


def test_comment_list_human_output(monkeypatch, env, capsys):
    comment = {
        "id": 5,
        "body": "please rebase",
        "author_id": None,
        "created_at": "2026-07-20T00:00:00Z",
    }
    patch_client(monkeypatch, FakeClient(result={"comments": [comment]}))
    assert cli.run(["comment", "list", "7"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == "5\t2026-07-20T00:00:00Z\tplease rebase\n1 comment"


def test_comment_list_empty_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"comments": []}))
    assert cli.run(["comment", "list", "7"]) == 0
    assert capsys.readouterr().out.strip() == "(no comments)\n0 comments"


# --- config resolution chain (KAN-199) --------------------------------------
# Precedence per value: env > ~/.config/pandan/config.toml > nearest .mcp.json.
# The point is that a PAT can live in a file and never touch the command line.
# (``isolate_config`` autouse fixture keeps the repo's real .mcp.json out of view;
# these tests opt individual sources back in.)


def _write_mcp_json(monkeypatch, tmp_path, env: dict, server: str = "pandan") -> None:
    """Drop a .mcp.json carrying ``env`` under ``server`` and point discovery at it."""
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {server: {"env": env}}}), encoding="utf-8")
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: path)


def test_token_from_config_file_when_env_unset(monkeypatch):
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    config.write_config_file(token="pandan_pat_fromfile", board_id="9")
    cfg = config.load_config()
    assert cfg.token == "pandan_pat_fromfile"
    assert cfg.board_id == 9


def test_token_from_mcp_json_when_env_and_file_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    _write_mcp_json(
        monkeypatch,
        tmp_path,
        {
            "PANDAN_TOKEN": "pandan_pat_frommcp",
            "PANDAN_API_URL": "https://mcp.example",
            "PANDAN_BOARD_ID": 42,  # a JSON number — must be coerced to int 42
        },
    )
    cfg = config.load_config()
    assert cfg.token == "pandan_pat_frommcp"
    assert cfg.api_url == "https://mcp.example"
    assert cfg.board_id == 42


def test_env_overrides_config_file_and_mcp_json(monkeypatch, tmp_path):
    _write_mcp_json(monkeypatch, tmp_path, {"PANDAN_TOKEN": "pandan_pat_mcp", "PANDAN_BOARD_ID": 1})
    config.write_config_file(token="pandan_pat_file", board_id="2")
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_env")
    monkeypatch.setenv("PANDAN_BOARD_ID", "3")
    cfg = config.load_config()
    assert cfg.token == "pandan_pat_env"
    assert cfg.board_id == 3


def test_config_file_overrides_mcp_json(monkeypatch, tmp_path):
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    monkeypatch.delenv("PANDAN_BOARD_ID", raising=False)
    _write_mcp_json(monkeypatch, tmp_path, {"PANDAN_TOKEN": "pandan_pat_mcp", "PANDAN_BOARD_ID": 1})
    config.write_config_file(token="pandan_pat_file", board_id="2")
    cfg = config.load_config()
    assert cfg.token == "pandan_pat_file"
    assert cfg.board_id == 2


def test_missing_token_everywhere_raises(monkeypatch):
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    with pytest.raises(config.ConfigError):
        config.load_config()


def test_warmup_allows_missing_token_everywhere(monkeypatch):
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    cfg = config.load_config(require_token=False)  # warmup path
    assert cfg.token == ""


def test_malformed_sources_are_ignored(monkeypatch, tmp_path):
    """A broken config file / .mcp.json must not crash — it's just skipped, so the
    normal 'token required' error still surfaces rather than a traceback."""
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    config.config_file_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_file_path().write_text("this is not = valid toml [", encoding="utf-8")
    bad = tmp_path / ".mcp.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: bad)
    with pytest.raises(config.ConfigError):
        config.load_config()


def test_write_config_file_is_owner_only_and_merges(monkeypatch):
    p1 = config.write_config_file(api_url="https://a.example", board_id="5")
    assert (p1.stat().st_mode & 0o777) == 0o600
    # A later write of just the token must preserve api_url + board_id.
    config.write_config_file(token="pandan_pat_x")
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    cfg = config.load_config()
    assert cfg.api_url == "https://a.example"
    assert cfg.board_id == 5
    assert cfg.token == "pandan_pat_x"


def test_find_mcp_json_walks_up(monkeypatch, tmp_path):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert _REAL_FIND_MCP_JSON(deep) == tmp_path / ".mcp.json"


def test_config_show_redacts_token(monkeypatch, tmp_path, capsys):
    _write_mcp_json(monkeypatch, tmp_path, {"PANDAN_TOKEN": "pandan_pat_supersecret1234"})
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    assert cli.run(["config", "show"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "pandan_pat_supersecret1234" not in out  # never print the raw token
    assert "1234" in out  # but the last 4 identify it


def test_config_set_token_stdin_never_needs_argv(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("pandan_pat_viastdin\n"))
    assert cli.run(["config", "set", "--token-stdin", "--board-id", "8"]) == cli.EXIT_OK
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    cfg = config.load_config()
    assert cfg.token == "pandan_pat_viastdin"
    assert cfg.board_id == 8


def test_config_set_rejects_non_integer_board_id():
    assert cli.run(["config", "set", "--board-id", "abc"]) == cli.EXIT_ERROR


# --- batch read: list --refs (issue #254) ----------------------------------


def test_list_refs_splits_ids_from_tickets(monkeypatch, env):
    """One mixed list on the CLI, two params on the wire — the caller should not have
    to know which bucket each token belongs in."""
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    assert cli.run(["list", "--board", "3", "--refs", "KAN-12,45,KAN-9"]) == cli.EXIT_OK
    params = fake.calls[0][1]
    assert params["ids"] == "45"
    assert params["refs"] == "KAN-12,KAN-9"


def test_list_without_refs_sends_neither_param(monkeypatch, env):
    """Purely additive: an ordinary list must be unchanged on the wire."""
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    assert cli.run(["list", "--board", "3"]) == cli.EXIT_OK
    params = fake.calls[0][1]
    assert params["ids"] is None and params["refs"] is None


def test_unresolved_selectors_are_printed_not_swallowed(monkeypatch, env, capsys):
    """The header exists so a miss is never silent; the human renderer has to honour
    that or the CLI reintroduces exactly the problem."""
    patch_client(
        monkeypatch,
        FakeClient(result={"cards": [CARD], "unresolved": ["99", "KAN-404"]}),
    )
    assert cli.run(["list", "--board", "3", "--refs", "99,KAN-404"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "(unresolved: 99, KAN-404)" in out


def test_all_selectors_missing_still_reports_them(monkeypatch, env, capsys):
    """The regression this most invites: no rows used to return `(no cards)` early,
    which would drop the one piece of information the caller needs."""
    patch_client(monkeypatch, FakeClient(result={"cards": [], "unresolved": ["KAN-404"]}))
    assert cli.run(["list", "--board", "3", "--refs", "KAN-404"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "(no cards)" in out
    assert "(unresolved: KAN-404)" in out


def test_unresolved_survives_fields_projection(monkeypatch, env, capsys):
    """The regression that shipped: `--fields` returns early from `_humanize` via
    `_project_rows`, so the projected rendering dropped the report entirely — in the
    combination an agent is most likely to use, since `--refs --fields` is the cheap
    read. Found by running it against production, not by the suite."""
    patch_client(
        monkeypatch,
        FakeClient(result={"cards": [CARD], "unresolved": ["KAN-404"]}),
    )
    code = cli.run(
        ["list", "--board", "3", "--refs", "KAN-404", "--fields", "ticket_number,column"]
    )
    assert code == cli.EXIT_OK
    assert "(unresolved: KAN-404)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "--board", "3", "--refs", "KAN-404"],
        ["list", "--board", "3", "--refs", "KAN-404", "--fields", "ticket_number"],
        ["list", "--board", "3", "--refs", "KAN-404", "--full"],
    ],
)
def test_every_human_rendering_path_reports_unresolved(monkeypatch, env, capsys, argv):
    """One case per exit out of `_humanize`. The point is the *set*: a miss must not
    be silent on ANY human path, so a fourth exit added later fails here rather than
    quietly reintroducing the bug above."""
    patch_client(
        monkeypatch,
        FakeClient(result={"cards": [CARD], "unresolved": ["KAN-404"]}),
    )
    assert cli.run(argv) == cli.EXIT_OK
    assert "(unresolved: KAN-404)" in capsys.readouterr().out


def test_structured_output_carries_unresolved(monkeypatch, env, capsys):
    fake_result = {"cards": [], "unresolved": ["KAN-404"]}
    patch_client(monkeypatch, FakeClient(result=fake_result))
    assert cli.run(["list", "--board", "3", "--refs", "KAN-404", "--format", "json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["unresolved"] == ["KAN-404"]


# --- config unset + require_board (issue #277) ------------------------------
# Two independent halves of one report: there was no way to clear a config value
# without hand-editing a 0600 file that also holds a live PAT, and — the sharper
# edge — an absent default board does not make ``--board`` mandatory, it makes the
# target *unpredictable*. A stale default on a read is a confusing answer; the same
# mistake on ``create`` files a card on the wrong board with nothing in the output
# to say so.


def test_config_unset_clears_a_key_without_touching_the_token(monkeypatch, capsys):
    """The whole point of the verb: the file also holds the PAT, so "just delete the
    line" means opening a credential file by hand."""
    monkeypatch.setattr("sys.stdin", io.StringIO("pandan_pat_keepme\n"))
    assert cli.run(["config", "set", "--token-stdin", "--board-id", "8"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.run(["config", "unset", "board_id"]) == cli.EXIT_OK
    assert "board_id\tremoved" in capsys.readouterr().out

    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    cfg = config.load_config()
    assert cfg.board_id is None
    assert cfg.token == "pandan_pat_keepme"  # the neighbouring secret survived


def test_config_unset_distinguishes_cleared_from_never_set(monkeypatch, capsys):
    """"Cleared it" and "it was never there" are different answers to 'why is this
    still pointing at board 5?' — the second means the value comes from the
    environment or .mcp.json, which this verb cannot touch."""
    assert cli.run(["config", "set", "--board-id", "8"]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.run(["config", "unset", "board_id", "max_text_chars"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "board_id\tremoved" in out
    assert "max_text_chars\tnot set" in out


def test_config_unset_warns_when_the_value_still_resolves(monkeypatch, capsys):
    """Clearing the file only unmasks the next source. Reporting OK while the value
    is unchanged is precisely the silent behaviour the issue is about."""
    assert cli.run(["config", "set", "--board-id", "8"]) == cli.EXIT_OK
    capsys.readouterr()
    monkeypatch.setenv("PANDAN_BOARD_ID", "9")
    assert cli.run(["config", "unset", "board_id"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert "board_id\tremoved" in captured.out
    assert "still resolves to 9" in captured.err  # stderr: stdout stays parseable


def test_config_unset_rejects_an_unknown_key(capsys):
    """A typo must not report success having done nothing — that is the same
    failure shape as the silent board fallback."""
    assert cli.run(["config", "unset", "boardid"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_input"
    assert err.arg == "boardid"


def test_require_board_refuses_a_board_scoped_verb_with_no_board(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"cards": []}))
    monkeypatch.setenv("PANDAN_BOARD_ID", "5")
    monkeypatch.setenv("PANDAN_REQUIRE_BOARD", "1")
    assert cli.run(["list"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "board_required"
    assert err.arg == "--board"


def test_require_board_still_allows_an_explicit_board(monkeypatch, env):
    """The switch makes ``--board`` mandatory, not impossible."""
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    monkeypatch.setenv("PANDAN_REQUIRE_BOARD", "true")
    assert cli.run(["list", "--board", "7"]) == cli.EXIT_OK
    assert fake.calls[0][1]["board_id"] == 7


def test_require_board_is_off_by_default(monkeypatch, env):
    """Opt-in: the fallback is genuinely convenient on a single-board account, which
    is where everyone starts. No existing invocation may change behaviour."""
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    monkeypatch.setenv("PANDAN_BOARD_ID", "5")
    assert cli.run(["list"]) == cli.EXIT_OK
    assert fake.calls[0][1]["board_id"] == 5


def test_require_board_rejects_an_unparseable_value(monkeypatch, env, capsys):
    """The one setting whose job is preventing a misfiled write must not read
    ``ture`` as "off" and hand back the exact fallback the user disabled."""
    patch_client(monkeypatch, FakeClient(result={"cards": []}))
    monkeypatch.setenv("PANDAN_REQUIRE_BOARD", "ture")
    assert cli.run(["list"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "config"
    assert "ture" in err.message


def test_require_board_round_trips_through_the_config_file(monkeypatch, capsys):
    """Written as a real TOML bool, not a quoted string, so anything else reading the
    file sees a boolean."""
    assert cli.run(["config", "set", "--require-board"]) == cli.EXIT_OK
    capsys.readouterr()
    assert "require_board = true" in config.config_file_path().read_text(encoding="utf-8")
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_x")
    assert config.load_config().require_board is True

    assert cli.run(["config", "set", "--no-require-board"]) == cli.EXIT_OK
    capsys.readouterr()
    assert config.load_config().require_board is False


def test_require_board_off_in_the_file_is_written_not_dropped(monkeypatch, capsys):
    """``--no-require-board`` must persist ``false`` rather than removing the key: the
    file is the middle source, so a vanished key would fall through to .mcp.json and
    the override would not stick."""
    assert cli.run(["config", "set", "--no-require-board"]) == cli.EXIT_OK
    capsys.readouterr()
    assert "require_board = false" in config.config_file_path().read_text(encoding="utf-8")


# --- next / dispatch (M5 V12, KAN-245) -------------------------------------


def test_next_peeks_by_default(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"card": CARD}))
    code = cli.run(["next", "--board", "3", "--priority", "high", "--label", "4"])
    assert code == 0
    assert fake.calls == [("next_ready", {"board_id": 3, "label": 4, "priority": "high"})]


def test_next_claim_dispatches(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"card": CARD}))
    code = cli.run(["next", "--board", "3", "--claim", "--assignee", "agent-7"])
    assert code == 0
    assert fake.calls == [
        ("dispatch", {"board_id": 3, "assignee": "agent-7", "label": None, "priority": None})
    ]


def test_next_requires_a_board(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"card": CARD}))
    code = cli.run(["next"])
    # No --board and no PANDAN_BOARD_ID → config error, no client call.
    assert code == cli.EXIT_ERROR
    assert fake.calls == []


def test_next_humanizes_empty(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"card": None}))
    code = cli.run(["next", "--board", "3"])
    assert code == 0
    assert data_out(capsys).strip() == "(no card ready)"


# --- KAN-285: id-taking commands accept KAN-/EPIC- tickets (not only DB ids) --
# Every id argument resolves a KAN-<n> / EPIC-<n> ticket (the form the CLI itself
# prints) to its numeric id via a client-side lookup; bare integers still pass
# through unchanged with no extra request. Fixtures carry the full CardRead shape
# (labels/story_points) so they match the real API (the KAN-277 lesson).


def _card(ticket, cid, **extra):
    return {
        "ticket_number": ticket, "id": cid, "column": "todo",
        "title": "t", "story_points": None, "labels": [], **extra,
    }


def _epic(ticket, eid, **extra):
    return {"ticket_number": ticket, "id": eid, "name": "n", "description": None, **extra}


def test_get_accepts_kan_ticket(monkeypatch, env):
    # `get KAN-9` lists cards, matches the ticket → numeric id 42, then GETs it.
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result=_card("KAN-9", 42),
            results={"list_cards": {"cards": [_card("KAN-9", 42)]}},
        ),
    )
    assert cli.run(["get", "KAN-9"]) == 0
    assert fake.calls == [
        ("list_cards", {"board_id": None}),
        ("get_card", {"card_id": 42}),
    ]


def test_get_ticket_is_case_insensitive(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result=_card("KAN-9", 42),
            results={"list_cards": {"cards": [_card("KAN-9", 42)]}},
        ),
    )
    assert cli.run(["get", "kan-9"]) == 0
    assert fake.calls[-1] == ("get_card", {"card_id": 42})


def test_bare_int_card_id_skips_lookup(monkeypatch, env):
    # A bare integer resolves with NO list request — only the target call is made.
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["get", "42"]) == 0
    assert fake.calls == [("get_card", {"card_id": 42})]


def test_move_accepts_kan_ticket(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result=_card("KAN-7", 7),
            results={"list_cards": {"cards": [_card("KAN-7", 7)]}},
        ),
    )
    assert cli.run(["move", "KAN-7", "done"]) == 0
    assert fake.calls == [
        ("list_cards", {"board_id": None}),
        ("move_card", {"card_id": 7, "column": "done", "position": None}),
    ]


def test_delete_accepts_kan_ticket(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(result={"deleted": 7}, results={"list_cards": {"cards": [_card("KAN-7", 7)]}}),
    )
    assert cli.run(["delete", "KAN-7", "--yes"]) == 0
    assert fake.calls == [
        ("list_cards", {"board_id": None}),
        ("delete_card", {"card_id": 7}),
    ]


def test_card_ticket_resolution_pages_the_cursor(monkeypatch, env):
    # A ticket on a later page is still found — the resolver follows next_cursor.
    class Paging:
        def __init__(self):
            self.calls = []
            self._pages = [
                {"cards": [_card("KAN-1", 1)], "next_cursor": "c2"},
                {"cards": [_card("KAN-9", 42)]},
            ]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def list_cards(self, **kw):
            self.calls.append(("list_cards", kw))
            return self._pages.pop(0)

        def get_card(self, card_id):
            self.calls.append(("get_card", {"card_id": card_id}))
            return _card("KAN-9", card_id)

    fake = Paging()
    patch_client(monkeypatch, fake)
    assert cli.run(["get", "KAN-9"]) == 0
    assert fake.calls == [
        ("list_cards", {"board_id": None}),
        ("list_cards", {"board_id": None, "cursor": "c2"}),
        ("get_card", {"card_id": 42}),
    ]


def test_unknown_card_ticket_is_a_clean_error(monkeypatch, env, capsys):
    # V43: a ticket that resolves to nothing is NOT_FOUND (5), the same code the API
    # gives for a numeric id that doesn't exist. It used to be 1.
    fake = patch_client(monkeypatch, FakeClient(results={"list_cards": {"cards": []}}))
    assert cli.run(["get", "KAN-999"]) == cli.EXIT_NOT_FOUND
    err = read_error(capsys)
    assert err.code == "not_found"
    assert "no card found with ticket KAN-999" in err.message
    assert err.arg == "KAN-999"
    assert fake.calls == [("list_cards", {"board_id": None})]


def test_card_id_arg_rejects_epic_ticket(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["get", "EPIC-3"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_ref"  # wrong KIND of ticket, not a missing card
    assert "not a card ticket" in err.message
    assert fake.calls == []  # never lists — the shape is wrong up front


def test_malformed_id_is_usage_error(env):
    # A value that is neither an int nor a KAN-/EPIC- ticket is a usage error (2).
    with pytest.raises(SystemExit) as exc:
        cli.run(["get", "not-an-id"])
    assert exc.value.code == cli.EXIT_USAGE


def test_list_epic_filter_accepts_epic_ticket(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result={"cards": []},
            results={"list_epics": {"epics": [_epic("EPIC-4", 7)]}},
        ),
    )
    assert cli.run(["list", "--epic", "EPIC-4"]) == 0
    assert fake.calls[0] == ("list_epics", {"board_id": None})
    assert fake.calls[1][0] == "list_cards"
    assert fake.calls[1][1]["epic_id"] == 7


def test_update_epic_link_accepts_epic_ticket(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result=_card("KAN-7", 7),
            results={"list_epics": {"epics": [_epic("EPIC-4", 9)]}},
        ),
    )
    assert cli.run(["update", "7", "--epic", "EPIC-4"]) == 0
    assert fake.calls == [
        ("list_epics", {"board_id": None}),
        (
            "update_card",
            {
                "card_id": 7, "title": None, "description": None, "story_points": None,
                "assignee": None, "epic_id": 9, "cycle_id": None, "priority": None,
                "due_date": None, "label_ids": None,
            },
        ),
    ]


def test_epic_update_accepts_epic_ticket(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result=_epic("EPIC-4", 7),
            results={"list_epics": {"epics": [_epic("EPIC-4", 7)]}},
        ),
    )
    assert cli.run(["epic", "update", "EPIC-4", "--name", "New"]) == 0
    assert fake.calls == [
        ("list_epics", {"board_id": None}),
        (
            "update_epic",
            {
                "epic_id": 7, "name": "New", "description": None,
                "target_date": None, "lead": None,
            },
        ),
    ]


def test_epic_arg_rejects_kan_ticket(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["epic", "update", "KAN-3", "--name", "x"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_ref"
    assert "not an epic ticket" in err.message
    assert fake.calls == []


def test_dep_add_resolves_both_card_and_blocker_tickets(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result={"ticket_number": "KAN-7", "blocked_by": [3], "blocks": [], "id": 7},
            results={"list_cards": {"cards": [_card("KAN-7", 7), _card("KAN-3", 3)]}},
        ),
    )
    assert cli.run(["dep", "add", "KAN-7", "--blocked-by", "KAN-3"]) == 0
    # Two lookups (card + blocker), then the add with resolved numeric ids.
    assert fake.calls == [
        ("list_cards", {"board_id": None}),
        ("list_cards", {"board_id": None}),
        ("add_dependency", {"card_id": 7, "blocker_id": 3}),
    ]


# --- KAN-286: `--sort` with a leading-dash value in the space form -----------
# `pandan list --sort -priority,position` used to fail ("expected one argument")
# because argparse read the leading '-' as a flag; only `--sort=...` worked. The
# argv normalizer rewrites `--sort -spec` → `--sort=-spec` so the documented space
# form works, without breaking the equals form.


def test_sort_space_form_with_leading_dash(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    assert cli.run(["list", "--sort", "-priority,position"]) == 0
    assert fake.calls[0][1]["sort"] == "-priority,position"


def test_sort_equals_form_still_works(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    assert cli.run(["list", "--sort=-priority,position"]) == 0
    assert fake.calls[0][1]["sort"] == "-priority,position"


def test_sort_space_form_ascending_value(monkeypatch, env):
    # A plain (ascending) value in the space form was always fine — keep it so.
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    assert cli.run(["list", "--sort", "priority,position"]) == 0
    assert fake.calls[0][1]["sort"] == "priority,position"


def test_sort_normalizer_leaves_real_flags_alone(monkeypatch, env, capsys):
    # `--sort` with a following long flag (not a value) must not swallow the flag:
    # argparse still reports the missing sort value as a usage error.
    with pytest.raises(SystemExit) as exc:
        cli.run(["list", "--sort", "--json"])
    assert exc.value.code == cli.EXIT_USAGE


def test_normalize_sort_argv_only_touches_sort():
    # Unit check on the rewriter: only `--sort -x` is rewritten; nothing else moves.
    assert cli._normalize_sort_argv(["list", "--sort", "-priority", "--json"]) == [
        "list", "--sort=-priority", "--json",
    ]
    assert cli._normalize_sort_argv(["list", "--column", "todo"]) == [
        "list", "--column", "todo",
    ]


# --- KAN-287: `template list` human formatter (not raw JSON) -----------------
# Every other list verb prints a tab-separated human line without --json;
# `template list` used to dump raw JSON always. It now prints `id<TAB>name<TAB>N
# cards` and reserves raw JSON for --json.

# A realistic CardTemplateRead carries id/board_id/name/cards/created_at.
TEMPLATE = {
    "id": 5,
    "board_id": 3,
    "name": "sprint",
    "cards": [{"title": "A"}, {"title": "B"}],
    "created_at": "2026-07-17T12:00:00Z",
}


def test_template_list_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"templates": [TEMPLATE]}))
    assert cli.run(["template", "list", "--board", "3"]) == 0
    assert capsys.readouterr().out.strip() == "5\tsprint\t2 cards\n1 template"


def test_template_list_empty_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"templates": []}))
    assert cli.run(["template", "list", "--board", "3"]) == 0
    assert capsys.readouterr().out.strip() == "(no templates)\n0 templates"


def test_template_list_json_carries_the_rows_verbatim(monkeypatch, env, capsys):
    result = {"templates": [TEMPLATE]}
    patch_client(monkeypatch, FakeClient(result=result))
    assert cli.run(["template", "list", "--board", "3", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {**result, "summary": {"count": 1}}


# --- KAN-288: `label create` accepts --color as well as the positional --------
# The signature was `label create <name> <color>` (color a required positional);
# docs/users expected a --color flag. Color is now optional either way — the
# positional still works, --color works, --color wins if both are given, and
# omitting both falls back to a neutral default.


def test_label_create_color_positional_still_works(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(result={"id": 1, "board_id": 2, "name": "bug", "color": "#ef4444"}),
    )
    assert cli.run(["label", "create", "bug", "#ef4444", "--board", "2"]) == 0
    assert fake.calls == [
        ("create_label", {"board_id": 2, "name": "bug", "color": "#ef4444"})
    ]


def test_label_create_color_flag(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(result={"id": 1, "board_id": 2, "name": "bug", "color": "#ef4444"}),
    )
    assert cli.run(["label", "create", "bug", "--color", "#ef4444", "--board", "2"]) == 0
    assert fake.calls == [
        ("create_label", {"board_id": 2, "name": "bug", "color": "#ef4444"})
    ]


def test_label_create_color_flag_wins_over_positional(monkeypatch, env):
    fake = patch_client(
        monkeypatch,
        FakeClient(result={"id": 1, "board_id": 2, "name": "bug", "color": "#111111"}),
    )
    assert cli.run(
        ["label", "create", "bug", "#000000", "--color", "#111111", "--board", "2"]
    ) == 0
    assert fake.calls == [
        ("create_label", {"board_id": 2, "name": "bug", "color": "#111111"})
    ]


def test_label_create_default_color_when_omitted(monkeypatch, env):
    label = {"id": 1, "board_id": 2, "name": "bug", "color": cli.DEFAULT_LABEL_COLOR}
    fake = patch_client(monkeypatch, FakeClient(result=label))
    assert cli.run(["label", "create", "bug", "--board", "2"]) == 0
    assert fake.calls == [
        ("create_label", {"board_id": 2, "name": "bug", "color": cli.DEFAULT_LABEL_COLOR})
    ]


# --- rebrand: PANDAN_* wins, KANBAN_* is a deprecated fallback (V40, KAN-423) --
# Precedence is per *value*, so a half-migrated environment resolves correctly
# instead of one stale var poisoning the whole config. The notice goes to stderr
# because stdout is machine-readable (--json is piped into jq).


def test_pandan_env_wins_over_kanban_env(monkeypatch, capsys):
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_new")
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_old")
    monkeypatch.setenv("PANDAN_API_URL", "https://new.example")
    monkeypatch.setenv("KANBAN_API_URL", "https://old.example")
    monkeypatch.setenv("PANDAN_BOARD_ID", "5")
    monkeypatch.setenv("KANBAN_BOARD_ID", "9")

    cfg = config.load_config()

    assert cfg.token == "pandan_pat_new"
    assert cfg.api_url == "https://new.example"
    assert cfg.board_id == 5
    # Nothing resolved from a deprecated name, so nothing is warned about.
    assert capsys.readouterr().err == ""


def test_kanban_env_alone_still_resolves_and_warns(monkeypatch, capsys):
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_old")
    monkeypatch.setenv("KANBAN_API_URL", "https://old.example")
    monkeypatch.setenv("KANBAN_BOARD_ID", "9")

    cfg = config.load_config()

    assert cfg.token == "kanban_pat_old"
    assert cfg.api_url == "https://old.example"
    assert cfg.board_id == 9
    err = capsys.readouterr().err
    for name in ("KANBAN_TOKEN", "KANBAN_API_URL", "KANBAN_BOARD_ID"):
        assert name in err
        assert name.replace("KANBAN_", "PANDAN_") in err
    assert "deprecated" in err


def test_deprecation_notice_is_emitted_once_per_process(monkeypatch, capsys):
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_old")
    config.load_config()
    first = capsys.readouterr().err
    config.load_config()
    assert first.count("KANBAN_TOKEN") == 1
    assert capsys.readouterr().err == ""  # second resolve stays quiet


def test_mixed_env_resolves_per_value(monkeypatch):
    """A half-migrated env: new token, old board id. Both must land."""
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_new")
    monkeypatch.setenv("KANBAN_BOARD_ID", "9")
    cfg = config.load_config()
    assert cfg.token == "pandan_pat_new"
    assert cfg.board_id == 9


def test_no_token_from_either_spelling_is_a_config_error(monkeypatch, capsys):
    assert cli.run(["list"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "config"
    assert "PANDAN_TOKEN is required" in err.message
    assert "pandan_pat_" in err.message


def test_mcp_json_pandan_server_key_is_read(monkeypatch, tmp_path):
    _write_mcp_json(monkeypatch, tmp_path, {"PANDAN_TOKEN": "pandan_pat_mcp"})
    assert config.load_config().token == "pandan_pat_mcp"


def test_mcp_json_falls_back_to_legacy_server_key_and_env_names(monkeypatch, tmp_path):
    """A live pre-rebrand .mcp.json — `kanban` server key, `KANBAN_*` env — still works."""
    _write_mcp_json(
        monkeypatch,
        tmp_path,
        {"KANBAN_TOKEN": "kanban_pat_mcp", "KANBAN_BOARD_ID": 3},
        server="kanban",
    )
    cfg = config.load_config()
    assert cfg.token == "kanban_pat_mcp"
    assert cfg.board_id == 3


def test_mcp_json_prefers_pandan_server_over_kanban(monkeypatch, tmp_path):
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "kanban": {"env": {"KANBAN_TOKEN": "kanban_pat_old"}},
                    "pandan": {"env": {"PANDAN_TOKEN": "pandan_pat_new"}},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: path)
    assert config.load_config().token == "pandan_pat_new"


# --- rebrand: config directory migration (V40, KAN-423) ----------------------


def test_legacy_config_dir_is_migrated_on_read(capsys):
    """``~/.config/kan/config.toml`` is copied to ``~/.config/pandan/`` on first use."""
    legacy = config.legacy_config_file_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        '[kan]\ntoken = "kanban_pat_legacydir"\nboard_id = 4\n', encoding="utf-8"
    )

    cfg = config.load_config()

    assert cfg.token == "kanban_pat_legacydir"
    assert cfg.board_id == 4
    new = config.config_file_path()
    assert new.is_file()
    assert legacy.is_file()  # left in place, so an old binary keeps working
    assert new.stat().st_mode & 0o777 == 0o600
    assert str(new) in capsys.readouterr().err  # one-line notice, on stderr


def test_existing_new_config_is_not_overwritten_by_the_legacy_one():
    config.write_config_file(token="pandan_pat_current")
    legacy = config.legacy_config_file_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('[kan]\ntoken = "kanban_pat_stale"\n', encoding="utf-8")

    assert config.load_config().token == "pandan_pat_current"


def test_write_config_file_renders_the_pandan_table():
    path = config.write_config_file(token="pandan_pat_x", board_id="2")
    body = path.read_text(encoding="utf-8")
    assert body.startswith("[pandan]")
    # And it round-trips through the reader.
    assert config.load_config().token == "pandan_pat_x"


# --- V42 / KAN-425: `--fields` projection on list verbs (AXI 2) ---------------
# The default row stays minimal (4 fields for a card); `--fields a,b,c` widens it
# on demand. The vocabulary is the row's own `--json` keys plus the aliases
# `ticket` / `pts` / `points`, so it can't drift from the API. `--fields` shapes the
# HUMAN row only — `--json` carries the rows verbatim (plus V44's `summary`).
#
# Every expected human output below also carries V44's trailing aggregate line
# (KAN-427): a projection changes which columns print, never the count of rows.

# V44's aggregate for the two-card page these tests share, spelled out once.
FCARD_SUMMARY_LINE = "2 cards · 1 todo · 0 in_progress · 1 done · 1 needs-human\n"

# Two realistic CardRead rows (all the keys the API returns, so the field
# vocabulary under test is the real one).
FCARD_A = {
    "ticket_number": "KAN-7", "id": 7, "board_id": 5, "column": "todo",
    "title": "Ship it", "description": "long body", "story_points": 3,
    "assignee": "agent:v42", "epic_id": 4, "cycle_id": None, "priority": "high",
    "due_date": None, "needs_human": False, "attention_note": None,
    "labels": [{"id": 1, "name": "bug", "color": "#f00"}],
    "blocked_by": [3, 9], "blocks": [], "blocked": False, "links": [],
    "position": 0, "created_at": "2026-07-30T00:00:00Z",
    "updated_at": "2026-07-30T00:00:00Z",
}
FCARD_B = {
    **FCARD_A,
    "ticket_number": "KAN-8", "id": 8, "column": "done", "title": "Next",
    "story_points": None, "assignee": None, "priority": "none",
    "labels": [], "blocked_by": [], "needs_human": True,
}


def test_default_row_is_byte_identical_without_fields(monkeypatch, env, capsys):
    """The 4-field default row is the contract `--fields` must not disturb: with the
    flag absent, the rows are byte-for-byte what they were before V42 (V44 appends
    its aggregate line after them)."""
    patch_client(monkeypatch, FakeClient(result={"cards": [FCARD_A, FCARD_B]}))
    assert cli.run(["list"]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "KAN-7\ttodo\tShip it\tpts=3\n"
        "KAN-8\tdone\tNext\tpts=-\n"
        + LIST_HINTS
        + FCARD_SUMMARY_LINE
    )


def test_fields_projects_exactly_the_named_columns(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"cards": [FCARD_A, FCARD_B]}))
    assert cli.run(["list", "--fields", "ticket,title,assignee,priority"]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "KAN-7\tShip it\tagent:v42\thigh\n"
        "KAN-8\tNext\t-\tnone\n"          # a null assignee renders `-`, never "None"
        + LIST_HINTS
        + FCARD_SUMMARY_LINE
    )


def test_fields_accepts_the_raw_api_key_and_its_alias(monkeypatch, env, capsys):
    """`ticket`/`pts` are aliases of `ticket_number`/`story_points`; both spellings
    work and both print the BARE value (the `pts=` label belongs to the default row)."""
    one_card = LIST_HINTS + "1 card · 1 todo · 0 in_progress · 0 done\n"
    patch_client(monkeypatch, FakeClient(result={"cards": [FCARD_A]}))
    assert cli.run(["list", "--fields", "ticket_number,pts"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "KAN-7\t3\n" + one_card
    patch_client(monkeypatch, FakeClient(result={"cards": [FCARD_A]}))
    assert cli.run(["list", "--fields", "ticket,story_points,points"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "KAN-7\t3\t3\n" + one_card


def test_fields_are_case_insensitive_and_tolerate_spaces(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"cards": [FCARD_A]}))
    assert cli.run(["list", "--fields", " Ticket , TITLE "]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "KAN-7\tShip it\n" + LIST_HINTS + "1 card · 1 todo · 0 in_progress · 0 done\n"
    )


def test_fields_renders_scalars_lists_and_nulls_compactly(monkeypatch, env, capsys):
    """One projected row is always ONE line: booleans as true/false, an object list
    by its most identifying key (a label's name), an int list comma-joined, an empty
    list and a null both `-`."""
    patch_client(monkeypatch, FakeClient(result={"cards": [FCARD_A, FCARD_B]}))
    argv = ["list", "--fields", "needs_human,labels,blocked_by,due_date"]
    assert cli.run(argv) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "false\tbug\t3,9\t-\n"
        "true\t-\t-\t-\n"
        + LIST_HINTS
        + FCARD_SUMMARY_LINE
    )


def test_fields_keeps_a_projected_row_on_one_line(monkeypatch, env, capsys):
    """A description with a newline/tab in it must not break the row format."""
    card = {**FCARD_A, "description": "line one\nline two\twith tab"}
    patch_client(monkeypatch, FakeClient(result={"cards": [card]}))
    assert cli.run(["list", "--fields", "ticket,description"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "KAN-7\tline one line two with tab"
    # One row + `list`'s two hints + V44's aggregate — the embedded newline did not
    # split the row. Counted on the hint-free output so the number stays about the row.
    assert len(data_out_lines(out)) == 2


def test_fields_unknown_name_is_a_clean_error_naming_the_field(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"cards": [FCARD_A]}))
    # V43 folded this into the structured shape: same content, now a machine code +
    # the offending field in its own column, on stdout. Exit code unchanged (1) — the
    # CLI (not argparse) rejected a runtime-validated value.
    assert cli.run(["list", "--fields", "ticket,nope"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "unknown_field"
    assert err.arg == "nope"  # the offending field, isolated in its own column
    assert "unknown --fields name 'nope'" in err.message
    assert "for card rows" in err.message  # which row type it applied to
    assert "available:" in err.message and "ticket" in err.message  # what IS valid


def test_fields_rejects_an_empty_list_as_a_usage_error(env):
    # A syntactically empty flag value is argparse's business → exit 2, before any
    # request. (An unknown *name* needs the rows, so it's a runtime error → exit 1.)
    for value in ("", "  ", ",,"):
        with pytest.raises(SystemExit) as exc:
            cli.run(["list", "--fields", value])
        assert exc.value.code == cli.EXIT_USAGE


def test_fields_preserves_the_definitive_empty_state(monkeypatch, env, capsys):
    # AXI 5: an empty result still says so explicitly, projection or not — and V44's
    # aggregate states the zero a second, machine-parseable way. No `LIST_HINTS`:
    # KAN-526 drops the `<id>` hints on an empty result (see test_human_output_empty_list).
    patch_client(monkeypatch, FakeClient(result={"cards": []}))
    assert cli.run(["list", "--fields", "ticket,title"]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "(no cards)\n0 cards · 0 todo · 0 in_progress · 0 done\n"
    )


def test_fields_preserves_the_next_cursor_hint(monkeypatch, env, capsys):
    patch_client(
        monkeypatch, FakeClient(result={"cards": [FCARD_A], "next_cursor": "abc123"})
    )
    assert cli.run(["list", "--fields", "ticket"]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "KAN-7\n(more — next cursor: abc123)\n"
        + LIST_HINTS
        + "1 card · 1 todo · 0 in_progress · 0 done\n"
    )


def test_fields_does_not_touch_json_output(monkeypatch, env, capsys):
    """`--json` carries the client's rows verbatim plus V44's `summary` key — so a
    projection there would reshape a documented machine contract. `--fields` is
    human-row-only, and the two are independent."""
    page = {"cards": [FCARD_A, FCARD_B]}
    patch_client(monkeypatch, FakeClient(result=page))
    assert cli.run(["list", "--json"]) == cli.EXIT_OK
    plain = capsys.readouterr().out
    patch_client(monkeypatch, FakeClient(result=page))
    assert cli.run(["list", "--json", "--fields", "ticket"]) == cli.EXIT_OK
    assert capsys.readouterr().out == plain
    parsed = json.loads(plain)
    assert parsed["cards"] == page["cards"]
    assert set(parsed) == {"cards", "summary"}


def test_fields_is_not_offered_on_single_entity_verbs(env):
    # `--fields` is a LIST-row projection; on `get` (one entity, full payload) it is
    # an unrecognized argument, not a silently ignored flag.
    with pytest.raises(SystemExit) as exc:
        cli.run(["get", "KAN-7", "--fields", "title"])
    assert exc.value.code == cli.EXIT_USAGE


@pytest.mark.parametrize(
    "argv,result,expected",
    [
        (
            ["epic", "list", "--fields", "ticket,name"],
            {"epics": [{"ticket_number": "EPIC-4", "id": 4, "name": "M7", "lead": None}]},
            # This fixture predates V32's `progress`, so the rollup degrades to 0/0
            # rather than raising — an older API is a supported shape.
            "EPIC-4\tM7\n1 epic · 0/0 stories done (0%)\n",
        ),
        (
            ["board", "list", "--fields", "id,name"],
            {"boards": [{"id": 5, "name": "Roadmap", "owner_id": 1}]},
            "5\tRoadmap\n1 board\n",
        ),
        (
            ["label", "list", "--board", "5", "--fields", "name,color"],
            {"labels": [{"id": 1, "name": "bug", "color": "#f00"}]},
            "bug\t#f00\n1 label\n",
        ),
        (
            ["view", "list", "--board", "5", "--fields", "id,name"],
            {"views": [{"id": 2, "name": "Mine", "query": {"column": "todo"}}]},
            "2\tMine\n1 view\n",
        ),
        (
            ["cycle", "list", "--board", "5", "--fields", "name,starts_on"],
            {"cycles": [{"id": 3, "name": "S1", "starts_on": "2026-07-01", "ends_on": None}]},
            "S1\t2026-07-01\n1 cycle\n",
        ),
        (
            ["template", "list", "--board", "5", "--fields", "id,name"],
            {"templates": [{"id": 4, "name": "Slice", "cards": [{"title": "a"}]}]},
            "4\tSlice\n1 template\n",
        ),
        (
            ["comment", "list", "7", "--fields", "id,body"],
            {"comments": [{"id": 9, "body": "hi", "author_id": None, "created_at": "t"}]},
            "9\thi\n1 comment\n",
        ),
        (
            ["activity", "--board", "5", "--fields", "action,summary"],
            {"activity": [{"ts": "t", "actor_label": "me", "action": "moved", "summary": "s"}]},
            "moved\ts\n1 activity row\n",
        ),
        (
            ["notify", "list", "--fields", "id,kind"],
            {"notifications": [{"id": 1, "kind": "mention", "body": "b", "read_at": None}]},
            "1\tmention\n1 notification · 1 unread\n",
        ),
    ],
    ids=["epic", "board", "label", "view", "cycle", "template", "comment", "activity", "notify"],
)
def test_fields_works_on_every_list_verb(monkeypatch, env, capsys, argv, result, expected):
    patch_client(monkeypatch, FakeClient(result=result))
    assert cli.run(argv) == cli.EXIT_OK
    assert capsys.readouterr().out == expected


def test_list_help_distinguishes_fields_from_sort_keys(capsys):
    """`list --help` used to carry a bare `Fields:` line that was `--sort`'s key
    vocabulary — mistaken for a projection flag more than once (M7 shaping note).
    The help must now name --fields as the projection and label --sort's list as
    SORT keys."""
    with pytest.raises(SystemExit):
        cli.run(["list", "--help"])
    # argparse re-wraps help text, so compare on whitespace-normalised output.
    out = " ".join(capsys.readouterr().out.split())
    assert "--fields" in out
    assert "Sort keys: position" in out
    assert "Fields: position" not in out


# --- V42 / KAN-425: identifier round-trip regression tests -------------------
# The CLI must accept every identifier it PRINTS (KAN-285, commit a10eaee; source
# `_id_or_ticket_arg` / `_parse_id_or_ticket` in cli.py). That behaviour had no
# test, which is why a ten-day-old fix was later mistaken for a live defect (the
# reporter was on a stale 0.3.0 binary). These tests close the loop for real: run a
# list verb, take the identifier out of the PRINTED row, feed it back verbatim.


def _printed_identifier(monkeypatch, capsys, list_argv, page):
    """Run a list verb and return the identifier from column 0 of its first printed
    row — i.e. exactly the string a human/agent would copy off the screen."""
    patch_client(monkeypatch, FakeClient(result=page))
    assert cli.run(list_argv) == cli.EXIT_OK
    return capsys.readouterr().out.splitlines()[0].split("\t")[0]


_CARD_PAGE = {"cards": [_card("KAN-7", 7)]}
_EPIC_PAGE = {"epics": [_epic("EPIC-4", 9)]}

# Every card-id-taking verb (enumerated from cli.py's `type=_id_or_ticket_arg`
# arguments, not from a doc). `{ref}` is substituted with the printed ticket.
_CARD_REF_VERBS = [
    (["get", "{ref}"], "get_card"),
    (["update", "{ref}", "--title", "x"], "update_card"),
    (["move", "{ref}", "done"], "move_card"),
    (["delete", "{ref}", "--yes"], "delete_card"),
    (["needs-human", "{ref}"], "flag_needs_human"),
    (["resolve", "{ref}"], "resolve_card"),
    (["dep", "add", "{ref}", "--blocked-by", "{ref}"], "add_dependency"),
    (["dep", "rm", "{ref}", "--blocked-by", "{ref}"], "remove_dependency"),
    (["dep", "list", "{ref}"], "list_dependencies"),
    (["link", "add", "{ref}", "--url", "https://e.example/1", "--label", "PR"], "add_link"),
    (["link", "rm", "{ref}", "--link-id", "3"], "remove_link"),
    (["comment", "add", "{ref}", "--body", "note"], "add_comment"),
    (["comment", "list", "{ref}"], "list_comments"),
]


@pytest.mark.parametrize(
    "argv_template,method", _CARD_REF_VERBS, ids=[" ".join(a[:2]) for a, _ in _CARD_REF_VERBS]
)
def test_card_verbs_round_trip_the_printed_ticket(
    monkeypatch, env, capsys, argv_template, method
):
    ref = _printed_identifier(monkeypatch, capsys, ["list"], _CARD_PAGE)
    assert ref == "KAN-7"  # what `list` prints in column 0
    fake = patch_client(
        monkeypatch, FakeClient(result=_card("KAN-7", 7), results={"list_cards": _CARD_PAGE})
    )
    argv = [ref if tok == "{ref}" else tok for tok in argv_template]
    assert cli.run(argv) == cli.EXIT_OK
    hits = [call for call in fake.calls if call[0] == method]
    assert hits, f"{method} was never called; calls={fake.calls}"
    assert hits[-1][1]["card_id"] == 7  # the printed ticket resolved to the numeric id


_EPIC_REF_VERBS = [
    (["epic", "update", "{ref}", "--name", "x"], "update_epic", "epic_id"),
    (["epic", "delete", "{ref}", "--yes"], "delete_epic", "epic_id"),
    (["list", "--epic", "{ref}"], "list_cards", "epic_id"),
    (["create", "T", "--epic", "{ref}"], "create_card", "epic_id"),
    (["update", "7", "--epic", "{ref}"], "update_card", "epic_id"),
]


@pytest.mark.parametrize(
    "argv_template,method,kwarg",
    _EPIC_REF_VERBS,
    ids=[" ".join(a[:2]) for a, _, _ in _EPIC_REF_VERBS],
)
def test_epic_ref_verbs_round_trip_the_printed_ticket(
    monkeypatch, env, capsys, argv_template, method, kwarg
):
    ref = _printed_identifier(monkeypatch, capsys, ["epic", "list"], _EPIC_PAGE)
    assert ref == "EPIC-4"  # what `epic list` prints in column 0
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result=_epic("EPIC-4", 9),
            results={"list_epics": _EPIC_PAGE, "list_cards": _CARD_PAGE},
        ),
    )
    argv = [ref if tok == "{ref}" else tok for tok in argv_template]
    assert cli.run(argv) == cli.EXIT_OK
    hits = [call for call in fake.calls if call[0] == method]
    assert hits, f"{method} was never called; calls={fake.calls}"
    assert hits[-1][1][kwarg] == 9


def test_view_create_round_trips_the_printed_epic_ticket(monkeypatch, env, capsys):
    # `view create --epic` stores the resolved numeric id inside the view's query.
    ref = _printed_identifier(monkeypatch, capsys, ["epic", "list"], _EPIC_PAGE)
    fake = patch_client(
        monkeypatch,
        FakeClient(
            result={"id": 1, "name": "V", "query": {}},
            results={"list_epics": _EPIC_PAGE},
        ),
    )
    assert cli.run(["view", "create", "V", "--board", "5", "--epic", ref]) == cli.EXIT_OK
    assert fake.calls[-1][1]["query"]["epic_id"] == 9


# The numeric-id entities have no ticket, so their round-trip is the printed integer
# in column 0 of their own list verb — same contract, different identifier form.
_NUMERIC_ID_ROUNDTRIPS = [
    (["label", "list", "--board", "5"], {"labels": [{"id": 11, "name": "bug", "color": "#f00"}]},
     ["label", "delete", "{ref}", "--yes"], "delete_label", "label_id"),
    (["view", "list", "--board", "5"], {"views": [{"id": 12, "name": "V", "query": {}}]},
     ["view", "delete", "{ref}", "--board", "5", "--yes"], "delete_view", "view_id"),
    (["cycle", "list", "--board", "5"],
     {"cycles": [{"id": 13, "name": "S1", "starts_on": None, "ends_on": None}]},
     ["cycle", "delete", "{ref}", "--board", "5", "--yes"], "delete_cycle", "cycle_id"),
    (["cycle", "list", "--board", "5"],
     {"cycles": [{"id": 13, "name": "S1", "starts_on": None, "ends_on": None}]},
     ["cycle", "metrics", "{ref}", "--board", "5"], "cycle_metrics", "cycle_id"),
    (["template", "list", "--board", "5"], {"templates": [{"id": 14, "name": "T", "cards": []}]},
     ["template", "apply", "{ref}", "--board", "5"], "apply_template", "template_id"),
    (["template", "list", "--board", "5"], {"templates": [{"id": 14, "name": "T", "cards": []}]},
     ["template", "delete", "{ref}", "--board", "5", "--yes"], "delete_template", "template_id"),
    (["notify", "list"],
     {"notifications": [{"id": 15, "kind": "mention", "body": "b", "read_at": None}]},
     ["notify", "read", "{ref}"], "mark_notification_read", "notification_id"),
    (["board", "list"], {"boards": [{"id": 16, "name": "B", "owner_id": 1}]},
     ["list", "--board", "{ref}"], "list_cards", "board_id"),
]


@pytest.mark.parametrize(
    "list_argv,page,argv_template,method,kwarg",
    _NUMERIC_ID_ROUNDTRIPS,
    ids=[" ".join(t[:2]) for _, _, t, _, _ in _NUMERIC_ID_ROUNDTRIPS],
)
def test_numeric_id_verbs_round_trip_the_printed_id(
    monkeypatch, env, capsys, list_argv, page, argv_template, method, kwarg
):
    ref = _printed_identifier(monkeypatch, capsys, list_argv, page)
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    argv = [ref if tok == "{ref}" else tok for tok in argv_template]
    assert cli.run(argv) == cli.EXIT_OK
    hits = [call for call in fake.calls if call[0] == method]
    assert hits, f"{method} was never called; calls={fake.calls}"
    assert hits[-1][1][kwarg] == int(ref)


def test_link_rm_round_trips_the_printed_link_id(monkeypatch, env, capsys):
    # `link add` prints `card <id>` then `id  label  url` per link; the link id in
    # column 0 of that row is what `link rm --link-id` takes.
    link = {"id": 21, "label": "PR", "url": "https://e.example/1"}
    patch_client(
        monkeypatch,
        FakeClient(
            result={"ticket_number": "KAN-7", "id": 7, "links": [link], "labels": []},
            results={"list_cards": _CARD_PAGE},
        ),
    )
    argv = ["link", "add", "7", "--url", link["url"], "--label", "PR"]
    assert cli.run(argv) == cli.EXIT_OK
    printed_link_id = capsys.readouterr().out.splitlines()[1].split("\t")[0]
    assert printed_link_id == "21"
    fake = patch_client(monkeypatch, FakeClient(result={"card_id": 7, "links": []}))
    assert cli.run(["link", "rm", "7", "--link-id", printed_link_id]) == cli.EXIT_OK
    assert fake.calls[-1] == ("remove_link", {"card_id": 7, "link_id": 21})


# --- V42 / KAN-425: ref-parsing cases ---------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("42", (42, None)),
        (" 42 ", (42, None)),            # surrounding whitespace is stripped
        ("KAN-9", (None, "KAN-9")),
        ("kan-9", (None, "KAN-9")),      # mixed case normalises upward
        ("Kan-9", (None, "KAN-9")),
        ("EPIC-3", (None, "EPIC-3")),
        ("epic-3", (None, "EPIC-3")),
    ],
)
def test_parse_id_or_ticket_accepts_ints_and_either_case(raw, expected):
    assert cli._parse_id_or_ticket(raw) == expected


@pytest.mark.parametrize("raw", ["#KAN-1", "KAN 1", "KAN-", "-5", "KAN-1x", "TASK-1", ""])
def test_malformed_refs_are_usage_errors_before_any_request(monkeypatch, env, raw):
    """A value that is neither a bare int nor a KAN-/EPIC- ticket is rejected by
    argparse (exit 2) with no network call.

    `#KAN-1` is in this list deliberately: the leading `#` is NOT accepted today
    (the CLI never prints that form). Pinned as current behaviour rather than
    changed — accepting it would be a one-line regex tweak, but it is not what
    KAN-425 asks for, so it's raised in the PR body instead of assumed."""
    fake = patch_client(monkeypatch, FakeClient())
    with pytest.raises(SystemExit) as exc:
        cli.run(["get", raw])
    assert exc.value.code == cli.EXIT_USAGE
    assert fake.calls == []


def test_id_or_ticket_arg_rejects_malformed_values_with_a_naming_message():
    with pytest.raises(argparse.ArgumentTypeError) as exc:
        cli._id_or_ticket_arg("#KAN-1")
    assert "#KAN-1" in str(exc.value)  # the message quotes the offending value


@pytest.mark.parametrize(
    "argv",
    [
        ["get", "KAN-4242"],
        ["update", "KAN-4242", "--title", "x"],
        ["move", "KAN-4242", "done"],
        ["delete", "KAN-4242", "--yes"],
        ["comment", "list", "KAN-4242"],
    ],
    ids=["get", "update", "move", "delete", "comment-list"],
)
def test_unresolvable_card_ref_is_not_found(monkeypatch, env, capsys, argv):
    """A well-formed ticket that matches nothing fails cleanly on every verb that
    resolves a ref — with **EXIT_NOT_FOUND (5)** as of V43 / KAN-426, matching the
    server-side 404 the numeric form produces (see the agreement test below)."""
    fake = patch_client(monkeypatch, FakeClient(results={"list_cards": {"cards": []}}))
    assert cli.run(argv) == cli.EXIT_NOT_FOUND
    err = read_error(capsys)
    assert err.code == "not_found"
    assert "no card found with ticket KAN-4242" in err.message
    assert [c[0] for c in fake.calls] == ["list_cards"]  # never reached the verb's call


def test_unresolvable_epic_ref_is_not_found(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(results={"list_epics": {"epics": []}}))
    assert cli.run(["epic", "update", "EPIC-4242", "--name", "x"]) == cli.EXIT_NOT_FOUND
    err = read_error(capsys)
    assert err.code == "not_found"
    assert "no epic found with ticket EPIC-4242" in err.message
    assert [c[0] for c in fake.calls] == ["list_epics"]


@pytest.mark.parametrize(
    "argv,message",
    [
        (["get", "EPIC-3"], "not a card ticket"),
        (["move", "EPIC-3", "done"], "not a card ticket"),
        (["comment", "add", "EPIC-3", "--body", "x"], "not a card ticket"),
        (["dep", "add", "KAN-7", "--blocked-by", "EPIC-3"], "not a card ticket"),
        (["epic", "delete", "KAN-3", "--yes"], "not an epic ticket"),
        (["list", "--epic", "KAN-3"], "not an epic ticket"),
    ],
    ids=["get", "move", "comment-add", "dep-blocker", "epic-delete", "list-epic-filter"],
)
def test_wrong_entity_ticket_is_rejected_up_front(monkeypatch, env, capsys, argv, message):
    """An EPIC- ticket handed to a card verb (or vice versa) is caught by shape
    before any lookup — the mismatch is knowable without a request."""
    fake = patch_client(monkeypatch, FakeClient(results={"list_cards": _CARD_PAGE}))
    assert cli.run(argv) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_ref"
    assert message in err.message
    assert "add_dependency" not in [c[0] for c in fake.calls]


# --- V43 / KAN-426: the error contract (AXI 6) -------------------------------
# Three things are pinned here, because all three are a published contract:
#   1. the SIX exit codes and their meanings (scripts branch on them — never renumber),
#   2. the machine `code` vocabulary and its code→exit mapping,
#   3. the *stream* and *shape*: one row on stdout, JSON under --json, human extras
#      (argparse usage, the KANBAN_* notice) on stderr.


def test_exit_code_scheme_is_pinned_by_literal_numbers():
    """Deliberately literal. These numbers are a scripting contract documented in
    pandan-cli/README.md §"Exit codes"; renumbering silently breaks callers, so the
    test states the numbers rather than re-deriving them from the module."""
    assert cli.EXIT_OK == 0
    assert cli.EXIT_ERROR == 1
    assert cli.EXIT_USAGE == 2
    assert cli.EXIT_AUTH == 3
    assert cli.EXIT_FORBIDDEN == 4
    assert cli.EXIT_NOT_FOUND == 5
    # HTTP status → exit code, the mapping verified against prod (401→3, 403→4, 404→5).
    assert cli._STATUS_EXIT == {401: 3, 403: 4, 404: 5}


def test_error_code_vocabulary_is_pinned():
    """Every machine code and the exit code it maps to. Entries may be ADDED (a new
    failure class), never renamed or remapped."""
    assert cli.ERROR_CODES == {
        "usage": 2,
        "config": 1,
        "board_required": 1,
        "confirmation_required": 1,
        "invalid_input": 1,
        "invalid_ref": 1,
        "unknown_field": 1,
        "no_token": 1,
        "unauthorized": 3,
        "forbidden": 4,
        "not_found": 5,
        "api_error": 1,
        "transport": 1,
        "unexpected": 1,
    }
    # The 1-vs-2 rule: only argparse's own rejection is a usage error.
    assert [c for c, code in cli.ERROR_CODES.items() if code == 2] == ["usage"]


def test_cli_error_derives_its_exit_code_and_rejects_an_unknown_code():
    err = cli.CliError("nope", code="not_found", arg="KAN-1")
    assert (err.exit_code, err.code, err.arg, err.status) == (5, "not_found", "KAN-1", None)
    with pytest.raises(KeyError):  # a typo'd code is a programming error, not a silent 1
        cli.CliError("x", code="no_such_code")


# --- one case per failure class: stream, shape, exit code --------------------


def test_unknown_flag_is_structured_on_stdout_and_keeps_usage_on_stderr(env, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["list", "--nope"])
    assert exc.value.code == cli.EXIT_USAGE
    captured = capsys.readouterr()
    # Machine channel: stdout carries the parseable row…
    row = captured.out.strip().split("\t")
    assert row[0] == "error" and row[1] == "usage"
    assert "--nope" in row[2]
    # …while the human usage block stays on stderr (AXI 10 — --help is unaffected).
    # (`unrecognized arguments` is raised by the TOP-level parser once the subparser
    # has consumed what it understands, so this is the top-level usage line.)
    assert captured.err.startswith("usage: pandan")


def test_invalid_enum_value_is_a_usage_error_on_stdout(env, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["move", "7", "not_a_column"])
    assert exc.value.code == cli.EXIT_USAGE
    out = capsys.readouterr().out
    assert out.startswith("error\tusage\t")
    assert "not_a_column" in out


def test_missing_required_option_is_a_usage_error_on_stdout(env, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["comment", "add", "7"])  # --body is required
    assert exc.value.code == cli.EXIT_USAGE
    assert capsys.readouterr().out.startswith("error\tusage\t")


def test_invalid_json_payload_is_invalid_input(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient())
    assert cli.run(["batch-update", "{not json"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_input"
    assert "invalid JSON" in err.message


def test_wrong_shape_json_payload_names_the_argument(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient())
    assert cli.run(["batch-update", '{"id": 1}']) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_input"
    assert err.arg == "JSON"


def test_success_prints_no_error_row_and_nothing_on_stderr(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    assert cli.run(["list"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert "error\t" not in captured.out
    assert captured.err == ""


def test_warmup_still_reports_a_status_not_an_error(monkeypatch, env, capsys):
    """The one documented nonzero exit that is NOT an error row: a still-waking API is
    a *status* (`waking  <detail>`) with exit 1, so `until pandan warmup; do …` keeps
    working. Pinned so the error contract doesn't silently swallow it."""
    patch_client(monkeypatch, FakeClient(result={"status": "waking", "detail": "call again"}))
    assert cli.run(["warmup"]) == cli.EXIT_ERROR
    out = capsys.readouterr().out
    assert out.startswith("waking\t")
    assert "error\t" not in out


# --- the real defect: one failure, one exit code, whatever the identifier form ---


@pytest.mark.parametrize(
    "numeric_argv,ticket_argv",
    [
        (["get", "999999"], ["get", "KAN-999999"]),
        (["update", "999999", "--title", "x"], ["update", "KAN-999999", "--title", "x"]),
        (["move", "999999", "done"], ["move", "KAN-999999", "done"]),
        (["delete", "999999", "--yes"], ["delete", "KAN-999999", "--yes"]),
        (["comment", "list", "999999"], ["comment", "list", "KAN-999999"]),
        (["dep", "list", "999999"], ["dep", "list", "KAN-999999"]),
        (["needs-human", "999999"], ["needs-human", "KAN-999999"]),
        (["resolve", "999999"], ["resolve", "KAN-999999"]),
    ],
    ids=["get", "update", "move", "delete", "comment-list", "dep-list", "needs-human", "resolve"],
)
def test_both_identifier_forms_of_a_missing_card_agree(
    monkeypatch, env, capsys, numeric_argv, ticket_argv
):
    """The KAN-426 defect: `get 999999` (404 server-side) exited 5 while
    `get KAN-999999` (resolved client-side, found nothing) exited 1 — the same logical
    failure reported two ways, which defeats branching on the exit code. Both forms now
    exit 5 with code `not_found`, on every verb that resolves a ref."""
    # Numeric: the API answers 404.
    patch_client(monkeypatch, FakeClient(error=PandanApiError(404, "Card not found")))
    numeric_exit = cli.run(numeric_argv)
    numeric_err = read_error(capsys)
    # Ticket: resolution happens client-side and matches nothing.
    patch_client(monkeypatch, FakeClient(results={"list_cards": {"cards": []}}))
    ticket_exit = cli.run(ticket_argv)
    ticket_err = read_error(capsys)

    assert numeric_exit == ticket_exit == cli.EXIT_NOT_FOUND
    assert numeric_err.code == ticket_err.code == "not_found"


def test_both_identifier_forms_of_a_missing_epic_agree(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(error=PandanApiError(404, "Epic not found")))
    numeric_exit = cli.run(["epic", "update", "999999", "--name", "x"])
    assert read_error(capsys).code == "not_found"
    patch_client(monkeypatch, FakeClient(results={"list_epics": {"epics": []}}))
    ticket_exit = cli.run(["epic", "update", "EPIC-999999", "--name", "x"])
    assert read_error(capsys).code == "not_found"
    assert numeric_exit == ticket_exit == cli.EXIT_NOT_FOUND


def test_a_missing_blocker_ref_is_also_not_found(monkeypatch, env, capsys):
    # `--blocked-by` resolves a ref too — the fix is in the resolver, so it covers
    # every call site, not just the positional card argument.
    patch_client(
        monkeypatch, FakeClient(results={"list_cards": {"cards": [_card("KAN-7", 7)]}})
    )
    assert cli.run(["dep", "add", "KAN-7", "--blocked-by", "KAN-4242"]) == cli.EXIT_NOT_FOUND
    assert read_error(capsys).arg == "KAN-4242"


# --- --json error shape ------------------------------------------------------


def read_json_error(capsys) -> dict:
    """The `--json` error object from stdout (and stderr carries no prose)."""
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "pandan:" not in captured.err
    return payload["error"]


def test_json_error_carries_code_message_arg_status_and_exit_code(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(error=PandanApiError(403, "not yours")))
    assert cli.run(["list", "--json"]) == cli.EXIT_FORBIDDEN
    err = read_json_error(capsys)
    assert err == {
        "code": "forbidden",
        "message": "403: that board isn't yours — call list_boards to see the boards "
        "you can use (not yours)",
        "arg": None,
        "status": 403,
        "exit_code": 4,
    }


def test_json_error_keys_are_always_present_even_when_null(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(results={"list_cards": {"cards": []}}))
    assert cli.run(["get", "KAN-4242", "--json"]) == cli.EXIT_NOT_FOUND
    err = read_json_error(capsys)
    assert set(err) == {"code", "message", "arg", "status", "exit_code"}
    assert err["status"] is None       # client-side failure: no HTTP status
    assert err["arg"] == "KAN-4242"    # …but the offending ref is named
    assert err["exit_code"] == 5


@pytest.mark.parametrize(
    "argv",
    [["--json", "list", "--nope"], ["list", "--json", "--nope"]],
    ids=["json-before-verb", "json-after-verb"],
)
def test_usage_errors_are_json_too_when_json_is_requested(env, capsys, argv):
    """An argparse failure happens before there's a parsed namespace, so the render
    mode is read straight off argv — both flag positions must work."""
    with pytest.raises(SystemExit) as exc:
        cli.run(argv)
    assert exc.value.code == cli.EXIT_USAGE
    err = json.loads(capsys.readouterr().out)["error"]
    assert err["code"] == "usage" and err["exit_code"] == 2


def test_error_row_is_one_line_even_for_a_multiline_message(capsys):
    cli._set_error_format(cli.FORMAT_HUMAN)
    code = cli._print_error(cli.CliError("line one\nline\ttwo", code="unexpected"))
    out = capsys.readouterr().out
    assert code == cli.EXIT_ERROR
    assert len(out.splitlines()) == 1
    assert out == "error\tunexpected\tline one line two\t-\n"


def test_help_is_unaffected_and_prints_human_usage_to_stdout(capsys):
    # AXI 10: --help stays human text on stdout, exit 0, and is not an error.
    with pytest.raises(SystemExit) as exc:
        cli.run(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: pandan")
    assert "error\t" not in out
    # The epilog documents the contract the tests above pin.
    normalised = " ".join(out.split())
    assert "Exit codes: 0 ok, 1 error, 2 usage, 3 unauthorized, 4 forbidden, 5 not found" in (
        normalised
    )
    assert "error<TAB>code<TAB>message<TAB>arg" in normalised


# --- never prompt when stdin isn't a tty (AXI 6) -----------------------------


def _explode_getpass(*a, **k):
    raise AssertionError("getpass must never be reached without a tty")


def test_login_never_prompts_when_stdin_is_not_a_tty(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", _explode_getpass)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # nothing piped in
    assert cli.run(["login"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "no_token"
    assert "terminal" in err.message  # says how to supply it instead


def test_login_reads_a_piped_token_without_prompting(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", _explode_getpass)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr("sys.stdin", io.StringIO("pandan_pat_piped\n"))
    assert cli.run(["login"]) == cli.EXIT_OK
    assert "saved token" in capsys.readouterr().out
    monkeypatch.delenv("PANDAN_TOKEN", raising=False)
    assert config.load_config().token == "pandan_pat_piped"


def test_login_prompts_only_when_stdin_is_a_tty(monkeypatch, capsys):
    prompted: list[str] = []

    def fake_getpass(prompt=""):
        prompted.append(prompt)
        return "pandan_pat_typed"

    monkeypatch.setattr("getpass.getpass", fake_getpass)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    assert cli.run(["login"]) == cli.EXIT_OK
    assert prompted and "PAT" in prompted[0]
    assert "saved token" in capsys.readouterr().out


def test_token_stdin_never_prompts_even_on_a_tty(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", _explode_getpass)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)  # a tty, but --token-stdin wins
    monkeypatch.setattr("sys.stdin", io.StringIO("pandan_pat_explicit\n"))
    assert cli.run(["login", "--token-stdin"]) == cli.EXIT_OK
    assert "saved token" in capsys.readouterr().out


def test_stdin_is_tty_is_false_for_a_detached_stdin(monkeypatch):
    class Detached:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr("sys.stdin", Detached())
    assert cli._stdin_is_tty() is False


def test_config_set_errors_are_structured(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert cli.run(["config", "set", "--token-stdin"]) == cli.EXIT_ERROR
    assert read_error(capsys).code == "no_token"
    assert cli.run(["config", "set"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_input"
    assert "nothing to set" in err.message


def test_config_set_rejects_non_integer_board_id_structured(capsys):
    assert cli.run(["config", "set", "--board-id", "abc"]) == cli.EXIT_ERROR
    err = read_error(capsys)
    assert err.code == "invalid_input"
    assert err.arg == "--board-id"
