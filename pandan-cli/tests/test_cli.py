"""Unit tests for the ``kan`` CLI.

The CLI is a thin adapter, so we mock the shared ``KanbanClient`` (patched into
``pandan_cli.cli``) and assert: each subcommand calls the right client method with
the right args, board-id default resolution, ``--json`` vs human output, and exit
codes (success, config errors, and a mapped ``KanbanApiError``). A couple of tests
drive the real client over an ``httpx.MockTransport`` to prove the HTTP wiring.
"""
from __future__ import annotations

import io
import json

import httpx
import pytest
from pandan_client import KanbanApiError

from pandan_cli import cli, config

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
    ``~/.config/kan/config.toml``); without this, ``load_config`` would silently
    resolve a token from those and defeat the 'no token → error' tests. Point
    ``XDG_CONFIG_HOME`` at an empty tmp dir and disable ``.mcp.json`` discovery by
    default; tests exercising those sources re-enable them explicitly."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: None)


@pytest.fixture
def env(monkeypatch):
    """A valid environment (token set, no default board)."""
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_test")
    monkeypatch.delenv("KANBAN_BOARD_ID", raising=False)
    monkeypatch.delenv("KANBAN_API_URL", raising=False)


def patch_client(monkeypatch, fake: FakeClient) -> FakeClient:
    monkeypatch.setattr(cli, "KanbanClient", lambda *a, **k: fake)
    return fake


# --- --version / -v (top-level, no subcommand) ------------------------------


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_version_flag_prints_version_and_exits_zero(flag, capsys):
    # argparse's action="version" prints to stdout and raises SystemExit(0),
    # short-circuiting before the required subcommand is enforced.
    with pytest.raises(SystemExit) as exc:
        cli.run([flag])
    assert exc.value.code == 0
    assert "0.3.0" in capsys.readouterr().out


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
    assert cli.run(["metrics"]) == 1  # no --board, no KANBAN_BOARD_ID → refused
    assert "board is required" in capsys.readouterr().err


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
    assert cli.run(["activity"]) == 1  # no --board, no KANBAN_BOARD_ID → refused
    assert "board is required" in capsys.readouterr().err


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
    monkeypatch.setenv("KANBAN_BOARD_ID", "7")
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    cli.run(["list"])
    assert fake.calls[0][1]["board_id"] == 7


def test_flag_overrides_board_env_default(monkeypatch, env):
    monkeypatch.setenv("KANBAN_BOARD_ID", "7")
    fake = patch_client(monkeypatch, FakeClient(result={"cards": []}))
    cli.run(["list", "--board", "3"])
    assert fake.calls[0][1]["board_id"] == 3


# --- delete confirmation guard ----------------------------------------------


def test_delete_requires_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    code = cli.run(["delete", "5"])
    assert code == cli.EXIT_ERROR
    assert fake.calls == []  # never touched the API
    assert "--yes" in capsys.readouterr().err


def test_delete_with_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 5}))
    assert cli.run(["delete", "5", "--yes"]) == 0
    assert fake.calls == [("delete_card", {"card_id": 5})]
    assert "deleted card 5" in capsys.readouterr().out


# --- --json vs human output -------------------------------------------------


def test_json_output_is_raw(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    assert cli.run(["list", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed == {"cards": [CARD]}


def test_json_flag_before_subcommand(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient())
    assert cli.run(["--json", "get", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == CARD


def test_human_output_is_concise_line(monkeypatch, env, capsys):
    # CARD has no story_points → rendered pts=- (never the literal "None").
    patch_client(monkeypatch, FakeClient(result={"cards": [CARD]}))
    cli.run(["list"])
    out = capsys.readouterr().out.strip()
    assert out == "KAN-1\ttodo\tShip it\tpts=-"


def test_human_output_empty_list(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"cards": []}))
    cli.run(["list"])
    assert capsys.readouterr().out.strip() == "(no cards)"


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
    assert capsys.readouterr().out.strip() == "KAN-3\tin_progress\tWIP\tpts=8"


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
    out = capsys.readouterr().out.strip()
    assert out == "KAN-260\tdone\tFix humanize\tpts=3"
    assert out != "(no labels)"
    assert "(no labels)" not in out


def test_label_list_renders_labels(monkeypatch, env, capsys):
    """`kan label list` on a real ``{"labels": [...]}`` response renders one line
    per label (id, name, color) — the legitimate consumer of the labels branch."""
    labels = {"labels": [
        {"id": 1, "name": "bug", "color": "#f00"},
        {"id": 2, "name": "chore", "color": "#0f0"},
    ]}
    patch_client(monkeypatch, FakeClient(result=labels))
    assert cli.run(["label", "list", "--board", "2"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == "1\tbug\t#f00\n2\tchore\t#0f0"


def test_label_list_empty_shows_no_labels(monkeypatch, env, capsys):
    """An empty label-LIST response still yields ``(no labels)`` (KAN-277 must not
    over-correct and break the genuine empty-list case)."""
    patch_client(monkeypatch, FakeClient(result={"labels": []}))
    assert cli.run(["label", "list", "--board", "2"]) == 0
    assert capsys.readouterr().out.strip() == "(no labels)"


# --- exit codes / error mapping ---------------------------------------------


def test_missing_token_is_config_error(monkeypatch, capsys):
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    code = cli.run(["list"])
    assert code == cli.EXIT_ERROR
    assert "KANBAN_TOKEN" in capsys.readouterr().err


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
    patch_client(monkeypatch, FakeClient(error=KanbanApiError(status, "boom")))
    code = cli.run(["get", "1"])
    assert code == expected
    assert "kan:" in capsys.readouterr().err


def test_unexpected_error_is_general(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(error=httpx.ConnectError("down")))
    assert cli.run(["get", "1"]) == cli.EXIT_ERROR
    assert "kan:" in capsys.readouterr().err


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
    assert capsys.readouterr().out.strip() == "2\tRoadmap"


def test_board_list_empty(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"boards": []}))
    cli.run(["board", "list"])
    assert capsys.readouterr().out.strip() == "(no boards)"


def test_board_list_json(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"boards": [BOARD]}))
    assert cli.run(["board", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"boards": [BOARD]}


# --- epic subcommands -------------------------------------------------------


def test_epic_list_maps_board_filter(monkeypatch, env):
    fake = patch_client(monkeypatch, FakeClient(result={"epics": [EPIC]}))
    assert cli.run(["epic", "list", "--board", "3"]) == 0
    assert fake.calls == [("list_epics", {"board_id": 3})]


def test_epic_list_uses_board_env_default(monkeypatch, env):
    monkeypatch.setenv("KANBAN_BOARD_ID", "7")
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
    assert "--yes" in capsys.readouterr().err


def test_epic_delete_with_yes(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient(result={"deleted": 1}))
    assert cli.run(["epic", "delete", "1", "--yes"]) == 0
    assert fake.calls == [("delete_epic", {"epic_id": 1})]
    assert "deleted epic 1" in capsys.readouterr().out


def test_epic_list_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"epics": [EPIC]}))
    cli.run(["epic", "list"])
    assert capsys.readouterr().out.strip() == "EPIC-1\tOnboarding\t60% (3/5) [at_risk]"


def test_epic_single_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result=EPIC))
    cli.run(["epic", "create", "Onboarding"])
    assert capsys.readouterr().out.strip() == "EPIC-1\tOnboarding\t60% (3/5) [at_risk]"


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
    # No KANBAN_TOKEN set — warmup hits the public /api/health, so it must not
    # error out on a missing token like the other (auth-required) commands do.
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    monkeypatch.delenv("KANBAN_BOARD_ID", raising=False)
    monkeypatch.delenv("KANBAN_API_URL", raising=False)
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

    from pandan_client import KanbanClient

    monkeypatch.setattr(
        cli,
        "KanbanClient",
        lambda url, token, **k: KanbanClient(
            url, token, transport=httpx.MockTransport(handler)
        ),
    )
    assert cli.run(["move", "7", "done", "--position", "1"]) == 0
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/7/move"
    assert seen["content"] == {"column": "done", "position": 1}
    assert seen["auth"] == "Bearer kanban_pat_test"


def test_real_client_warmup_hits_unversioned_health(monkeypatch):
    # No token in the env: warmup must still reach the unversioned /api/health
    # (not /api/v1/...) and send no Authorization header.
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    monkeypatch.delenv("KANBAN_BOARD_ID", raising=False)
    monkeypatch.delenv("KANBAN_API_URL", raising=False)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"status": "ok"})

    from pandan_client import KanbanClient

    monkeypatch.setattr(
        cli,
        "KanbanClient",
        lambda url, token, **k: KanbanClient(
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
    assert json.loads(capsys.readouterr().out) == result


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
    assert out == "5\t2026-07-20T00:00:00Z\tplease rebase"


def test_comment_list_empty_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"comments": []}))
    assert cli.run(["comment", "list", "7"]) == 0
    assert capsys.readouterr().out.strip() == "(no comments)"


# --- config resolution chain (KAN-199) --------------------------------------
# Precedence per value: env > ~/.config/kan/config.toml > nearest .mcp.json.
# The point is that a PAT can live in a file and never touch the command line.
# (``isolate_config`` autouse fixture keeps the repo's real .mcp.json out of view;
# these tests opt individual sources back in.)


def _write_mcp_json(monkeypatch, tmp_path, env: dict) -> None:
    """Drop a .mcp.json carrying ``env`` and point discovery at it."""
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {"kanban": {"env": env}}}), encoding="utf-8")
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: path)


def test_token_from_config_file_when_env_unset(monkeypatch):
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    config.write_config_file(token="kanban_pat_fromfile", board_id="9")
    cfg = config.load_config()
    assert cfg.token == "kanban_pat_fromfile"
    assert cfg.board_id == 9


def test_token_from_mcp_json_when_env_and_file_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    _write_mcp_json(
        monkeypatch,
        tmp_path,
        {
            "KANBAN_TOKEN": "kanban_pat_frommcp",
            "KANBAN_API_URL": "https://mcp.example",
            "KANBAN_BOARD_ID": 42,  # a JSON number — must be coerced to int 42
        },
    )
    cfg = config.load_config()
    assert cfg.token == "kanban_pat_frommcp"
    assert cfg.api_url == "https://mcp.example"
    assert cfg.board_id == 42


def test_env_overrides_config_file_and_mcp_json(monkeypatch, tmp_path):
    _write_mcp_json(monkeypatch, tmp_path, {"KANBAN_TOKEN": "kanban_pat_mcp", "KANBAN_BOARD_ID": 1})
    config.write_config_file(token="kanban_pat_file", board_id="2")
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_env")
    monkeypatch.setenv("KANBAN_BOARD_ID", "3")
    cfg = config.load_config()
    assert cfg.token == "kanban_pat_env"
    assert cfg.board_id == 3


def test_config_file_overrides_mcp_json(monkeypatch, tmp_path):
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    monkeypatch.delenv("KANBAN_BOARD_ID", raising=False)
    _write_mcp_json(monkeypatch, tmp_path, {"KANBAN_TOKEN": "kanban_pat_mcp", "KANBAN_BOARD_ID": 1})
    config.write_config_file(token="kanban_pat_file", board_id="2")
    cfg = config.load_config()
    assert cfg.token == "kanban_pat_file"
    assert cfg.board_id == 2


def test_missing_token_everywhere_raises(monkeypatch):
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    with pytest.raises(config.ConfigError):
        config.load_config()


def test_warmup_allows_missing_token_everywhere(monkeypatch):
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    cfg = config.load_config(require_token=False)  # warmup path
    assert cfg.token == ""


def test_malformed_sources_are_ignored(monkeypatch, tmp_path):
    """A broken config file / .mcp.json must not crash — it's just skipped, so the
    normal 'token required' error still surfaces rather than a traceback."""
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
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
    config.write_config_file(token="kanban_pat_x")
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    cfg = config.load_config()
    assert cfg.api_url == "https://a.example"
    assert cfg.board_id == 5
    assert cfg.token == "kanban_pat_x"


def test_find_mcp_json_walks_up(monkeypatch, tmp_path):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert _REAL_FIND_MCP_JSON(deep) == tmp_path / ".mcp.json"


def test_config_show_redacts_token(monkeypatch, tmp_path, capsys):
    _write_mcp_json(monkeypatch, tmp_path, {"KANBAN_TOKEN": "kanban_pat_supersecret1234"})
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    assert cli.run(["config", "show"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "kanban_pat_supersecret1234" not in out  # never print the raw token
    assert "1234" in out  # but the last 4 identify it


def test_config_set_token_stdin_never_needs_argv(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("kanban_pat_viastdin\n"))
    assert cli.run(["config", "set", "--token-stdin", "--board-id", "8"]) == cli.EXIT_OK
    monkeypatch.delenv("KANBAN_TOKEN", raising=False)
    cfg = config.load_config()
    assert cfg.token == "kanban_pat_viastdin"
    assert cfg.board_id == 8


def test_config_set_rejects_non_integer_board_id():
    assert cli.run(["config", "set", "--board-id", "abc"]) == cli.EXIT_ERROR


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
    # No --board and no KANBAN_BOARD_ID → config error, no client call.
    assert code == cli.EXIT_ERROR
    assert fake.calls == []


def test_next_humanizes_empty(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"card": None}))
    code = cli.run(["next", "--board", "3"])
    assert code == 0
    assert capsys.readouterr().out.strip() == "(no card ready)"


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
    fake = patch_client(monkeypatch, FakeClient(results={"list_cards": {"cards": []}}))
    assert cli.run(["get", "KAN-999"]) == cli.EXIT_ERROR
    assert "no card found with ticket KAN-999" in capsys.readouterr().err
    assert fake.calls == [("list_cards", {"board_id": None})]


def test_card_id_arg_rejects_epic_ticket(monkeypatch, env, capsys):
    fake = patch_client(monkeypatch, FakeClient())
    assert cli.run(["get", "EPIC-3"]) == cli.EXIT_ERROR
    assert "not a card ticket" in capsys.readouterr().err
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
    assert "not an epic ticket" in capsys.readouterr().err
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
# `kan list --sort -priority,position` used to fail ("expected one argument")
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
    assert capsys.readouterr().out.strip() == "5\tsprint\t2 cards"


def test_template_list_empty_human_output(monkeypatch, env, capsys):
    patch_client(monkeypatch, FakeClient(result={"templates": []}))
    assert cli.run(["template", "list", "--board", "3"]) == 0
    assert capsys.readouterr().out.strip() == "(no templates)"


def test_template_list_json_is_still_raw(monkeypatch, env, capsys):
    result = {"templates": [TEMPLATE]}
    patch_client(monkeypatch, FakeClient(result=result))
    assert cli.run(["template", "list", "--board", "3", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == result


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
