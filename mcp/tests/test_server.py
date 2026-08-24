"""Smoke tests for the MCP server wiring + board-scoping (V10)."""
from __future__ import annotations

import asyncio
import json

import httpx
from pandan_client import PandanClient

# The expected tool-name set is the V49 freeze, and it lives in exactly one place:
# ``tests/test_schema.py``. Bare tool names are the Python function names, which the
# rebrand does NOT touch — the agent-visible identifier is ``mcp__<server>__<tool>``
# and the ``<server>`` part comes from the client's ``mcpServers`` key in
# ``.mcp.json`` (V40 changed it ``kanban`` → ``pandan``), which is not visible from
# inside the server.
from test_schema import FROZEN_TOOLS as EXPECTED_TOOLS

from pandan_mcp import server
from pandan_mcp.server import mcp


def _tools():
    return asyncio.run(mcp.list_tools())


def test_server_advertises_exactly_the_expected_tools():
    assert {tool.name for tool in _tools()} == EXPECTED_TOOLS


def test_every_tool_has_a_description_and_schema():
    for tool in _tools():
        assert tool.description, f"{tool.name} is missing a description"
        assert tool.input_schema, f"{tool.name} is missing an input schema"


def test_create_card_schema_marks_title_required():
    create_card = next(t for t in _tools() if t.name == "create_card")
    assert create_card.input_schema["required"] == ["title"]


# --- board-scoping default resolution (V10) --------------------------------


def _stub_client(monkeypatch, default_board_id):
    """Point the server's lazily-built client at a MockTransport and set the
    PANDAN_BOARD_ID default, capturing the outgoing request."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        seen["content"] = request.content
        return httpx.Response(201, json={"id": 1})

    client = PandanClient("http://test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_default_board_id", default_board_id)
    return seen


def test_create_card_falls_back_to_default_board(monkeypatch):
    seen = _stub_client(monkeypatch, default_board_id=7)
    server.create_card("T")
    assert json.loads(seen["content"]) == {"board_id": 7, "title": "T"}


def test_per_call_board_id_overrides_the_default(monkeypatch):
    seen = _stub_client(monkeypatch, default_board_id=7)
    server.create_card("T", board_id=3)
    assert json.loads(seen["content"]) == {"board_id": 3, "title": "T"}


def test_no_board_id_and_no_default_sends_none(monkeypatch):
    seen = _stub_client(monkeypatch, default_board_id=None)
    server.list_cards()
    assert seen["params"] == {}


# --- dependency tools (KAN-31) ---------------------------------------------


def _capture_client(monkeypatch, response):
    """Point the server's client at a MockTransport returning ``response`` and
    capture the outgoing method/path/content."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["content"] = request.content
        return response

    client = PandanClient("http://test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_default_board_id", None)
    return seen


def test_add_dependency_posts_blocker_id(monkeypatch):
    seen = _capture_client(
        monkeypatch, httpx.Response(201, json={"id": 5, "blocked_by": [2], "blocks": []})
    )
    out = server.add_dependency(5, 2)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/5/dependencies"
    assert json.loads(seen["content"]) == {"blocker_id": 2}
    assert out == {"id": 5, "blocked_by": [2], "blocks": []}


def test_remove_dependency_deletes_edge_path(monkeypatch):
    seen = _capture_client(
        monkeypatch, httpx.Response(200, json={"id": 5, "blocked_by": [], "blocks": []})
    )
    out = server.remove_dependency(5, 2)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/cards/5/dependencies/2"
    assert out == {"id": 5, "blocked_by": [], "blocks": []}


def test_list_dependencies_shapes_card_arrays(monkeypatch):
    seen = _capture_client(
        monkeypatch,
        httpx.Response(200, json={"id": 5, "title": "T", "blocked_by": [2, 3], "blocks": [9]}),
    )
    out = server.list_dependencies(5)
    # Reads the card itself — no dedicated endpoint.
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/cards/5"
    assert out == {"card_id": 5, "blocked_by": [2, 3], "blocks": [9]}


# --- work-link + comment tools (KAN-34) ------------------------------------


def test_add_link_posts_label_and_url(monkeypatch):
    seen = _capture_client(
        monkeypatch,
        httpx.Response(201, json={"id": 5, "links": [{"id": 1, "label": "PR", "url": "u"}]}),
    )
    out = server.add_link(5, "PR", "https://example/pr/1")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/5/links"
    assert json.loads(seen["content"]) == {"label": "PR", "url": "https://example/pr/1"}
    assert out == {"id": 5, "links": [{"id": 1, "label": "PR", "url": "u"}]}


def test_remove_link_deletes_link_path(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(200, json={"id": 5, "links": []}))
    out = server.remove_link(5, 2)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/cards/5/links/2"
    assert out == {"id": 5, "links": []}


def test_add_comment_posts_body(monkeypatch):
    seen = _capture_client(
        monkeypatch, httpx.Response(201, json={"id": 3, "body": "hi", "author_id": None})
    )
    out = server.add_comment(5, "hi")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/5/comments"
    assert json.loads(seen["content"]) == {"body": "hi"}
    assert out == {"id": 3, "body": "hi", "author_id": None}


def test_list_comments_reads_and_wraps(monkeypatch):
    seen = _capture_client(
        monkeypatch, httpx.Response(200, json=[{"id": 3, "body": "hi"}])
    )
    out = server.list_comments(5)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/cards/5/comments"
    assert out == {"comments": [{"id": 3, "body": "hi"}]}


# --- dispatch + next tools (M5 V12, KAN-245) -------------------------------


def test_dispatch_posts_to_board_dispatch(monkeypatch):
    seen = _capture_client(
        monkeypatch, httpx.Response(200, json={"id": 5, "column": "in_progress"})
    )
    out = server.dispatch(board_id=3, assignee="agent-7")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/boards/3/dispatch"
    assert json.loads(seen["content"]) == {"assignee": "agent-7"}
    assert out == {"card": {"id": 5, "column": "in_progress"}}


def test_next_peeks_board_next(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(200, json={"id": 9, "column": "todo"}))
    out = server.next_ready(board_id=3, priority="high")
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/next"
    assert out == {"card": {"id": 9, "column": "todo"}}


def test_dispatch_requires_a_board(monkeypatch):
    _capture_client(monkeypatch, httpx.Response(204))
    import pytest

    with pytest.raises(ValueError):
        server.dispatch()


# --- saved-view + sort tools (M5 V14, KAN-247) -----------------------------


def test_list_cards_passes_sort_and_assignee(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    client = PandanClient("http://test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_default_board_id", None)
    server.list_cards(board_id=3, sort="-priority", assignee="agent-7")
    assert seen["params"] == {"board_id": "3", "sort": "-priority", "assignee": "agent-7"}


def test_create_view_posts_name_and_query(monkeypatch):
    seen = _capture_client(
        monkeypatch,
        httpx.Response(201, json={"id": 1, "name": "mine", "query": {"assignee": "a"}}),
    )
    out = server.create_view("mine", {"assignee": "a"}, board_id=3)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/boards/3/views"
    assert json.loads(seen["content"]) == {"name": "mine", "query": {"assignee": "a"}}
    assert out == {"id": 1, "name": "mine", "query": {"assignee": "a"}}


def test_create_view_defaults_query_to_empty(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(201, json={"id": 1}))
    server.create_view("all", board_id=3)
    assert json.loads(seen["content"]) == {"name": "all", "query": {}}


def test_list_views_reads_board_views(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(200, json=[{"id": 1}]))
    out = server.list_views(board_id=3)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/views"
    assert out == {"views": [{"id": 1}]}


def test_delete_view_deletes_path(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(204))
    out = server.delete_view(5, board_id=3)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/boards/3/views/5"
    assert out == {"deleted": 5}


def test_view_tools_require_a_board(monkeypatch):
    _capture_client(monkeypatch, httpx.Response(200, json=[]))
    import pytest

    with pytest.raises(ValueError):
        server.list_views()
    with pytest.raises(ValueError):
        server.create_view("x")


# --- activity feed tool (M5 V16, KAN-261) ----------------------------------


def _capture_get(monkeypatch, response):
    """Point the server's client at a MockTransport returning ``response`` and
    capture the outgoing method/path/query-params."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return response

    client = PandanClient("http://test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_default_board_id", None)
    return seen


def test_list_notifications_reads_inbox(monkeypatch):
    seen = _capture_get(
        monkeypatch, httpx.Response(200, json=[{"id": 1, "kind": "needs_human"}])
    )
    out = server.list_notifications()
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/notifications"
    assert seen["params"] == {}  # not board-scoped; unread defaults off → no param
    assert out == {"notifications": [{"id": 1, "kind": "needs_human"}]}


def test_list_notifications_passes_unread_filter(monkeypatch):
    seen = _capture_get(monkeypatch, httpx.Response(200, json=[]))
    server.list_notifications(unread=True)
    assert seen["params"] == {"unread": "true"}


def test_mark_read_patches_notification_by_id(monkeypatch):
    seen = _capture_get(
        monkeypatch, httpx.Response(200, json={"id": 5, "read_at": "2026-01-01T00:00:00Z"})
    )
    out = server.mark_read(5)
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/notifications/5"
    assert out["read_at"] == "2026-01-01T00:00:00Z"


def test_activity_reads_board_feed(monkeypatch):
    seen = _capture_get(monkeypatch, httpx.Response(200, json=[{"id": 1, "action": "created"}]))
    out = server.activity(board_id=3)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/activity"
    assert out == {"activity": [{"id": 1, "action": "created"}]}


def test_activity_passes_actor_and_action_filters(monkeypatch):
    seen = _capture_get(monkeypatch, httpx.Response(200, json=[]))
    server.activity(board_id=3, actor="agent-7", action="moved", limit=5)
    assert seen["params"] == {
        "actor": "agent-7",
        "action": "moved",
        "limit": "5",
    }


def test_activity_requires_a_board(monkeypatch):
    _capture_get(monkeypatch, httpx.Response(200, json=[]))
    import pytest

    with pytest.raises(ValueError):
        server.activity()


# --- batch update + templates tools (M5 V19, KAN-252) ----------------------


def test_update_cards_patches_batch(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(200, json=[{"id": 1}, {"id": 2}]))
    out = server.update_cards([{"id": 1, "assignee": "a"}, {"id": 2, "priority": "high"}])
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/cards/batch"
    assert json.loads(seen["content"]) == [
        {"id": 1, "assignee": "a"},
        {"id": 2, "priority": "high"},
    ]
    assert out == {"updated": [{"id": 1}, {"id": 2}]}


def test_create_template_posts_name_and_cards(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(201, json={"id": 7}))
    server.create_template("sprint", [{"title": "A"}], board_id=3)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/boards/3/templates"
    assert json.loads(seen["content"]) == {"name": "sprint", "cards": [{"title": "A"}]}


def test_list_templates_reads_board_templates(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(200, json=[{"id": 7}]))
    out = server.list_templates(board_id=3)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/templates"
    assert out == {"templates": [{"id": 7}]}


def test_apply_template_posts_to_apply(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(201, json=[{"id": 10}]))
    out = server.apply_template(7, board_id=3)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/boards/3/templates/7/apply"
    assert out == {"created": [{"id": 10}]}


def test_delete_template_deletes_path(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(204))
    out = server.delete_template(7, board_id=3)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/boards/3/templates/7"
    assert out == {"deleted": 7}


def test_template_tools_require_a_board(monkeypatch):
    _capture_client(monkeypatch, httpx.Response(200, json=[]))
    import pytest

    with pytest.raises(ValueError):
        server.list_templates()
    with pytest.raises(ValueError):
        server.apply_template(7)


# --- cycle tools (V33, KAN-297) --------------------------------------------


def test_list_cycles_reads_board_cycles(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(200, json=[{"id": 4}]))
    out = server.list_cycles(board_id=3)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/cycles"
    assert out == {"cycles": [{"id": 4}]}


def test_create_cycle_posts_name_and_bounds(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(201, json={"id": 4}))
    server.create_cycle("sprint-1", starts_on="2026-01-01T00:00:00Z", board_id=3)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/boards/3/cycles"
    assert json.loads(seen["content"]) == {
        "name": "sprint-1",
        "starts_on": "2026-01-01T00:00:00Z",
    }


def test_delete_cycle_deletes_path(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(204))
    out = server.delete_cycle(4, board_id=3)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/boards/3/cycles/4"
    assert out == {"deleted": 4}


def test_cycle_metrics_reads_metrics_path(monkeypatch):
    seen = _capture_client(
        monkeypatch, httpx.Response(200, json={"velocity": 8, "unit": "points"})
    )
    out = server.cycle_metrics(4, board_id=3)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/cycles/4/metrics"
    assert out == {"velocity": 8, "unit": "points"}


def test_cycle_tools_require_a_board(monkeypatch):
    _capture_client(monkeypatch, httpx.Response(200, json=[]))
    import pytest

    with pytest.raises(ValueError):
        server.list_cycles()
    with pytest.raises(ValueError):
        server.create_cycle("x")
    with pytest.raises(ValueError):
        server.cycle_metrics(4)


def test_list_cards_passes_cycle_id(monkeypatch):
    seen = _capture_get(monkeypatch, httpx.Response(200, json=[]))
    server.list_cards(board_id=3, cycle_id=4)
    assert seen["params"] == {"board_id": "3", "cycle_id": "4"}


def test_create_card_passes_cycle_id(monkeypatch):
    seen = _capture_client(monkeypatch, httpx.Response(201, json={"id": 1}))
    server.create_card("T", board_id=3, cycle_id=4)
    assert json.loads(seen["content"]) == {"board_id": 3, "title": "T", "cycle_id": 4}


# --- update_board: the autosync pair (KAN-529) + the board key (V51) --------
# `autosync_enabled` / `autosync_advance_to_done` are two of the `BoardUpdate` fields
# and were reachable from NEITHER adapter, so opting a board into EPIC-10 / ADR 0016
# auto-sync meant a raw `curl`. `key` (V51, KAN-972) is the newest. All were added as
# tool ARGUMENTS, which ADR 0019's freeze permits — it freezes the tool *count*,
# pinned by `tests/test_schema.py`, which arguments do not move.

_BOARD_READ = {"id": 5, "name": "Roadmap", "autosync_enabled": True}


def test_update_board_still_requires_only_board_id():
    """Identity invariant first: the new arguments are optional, so no existing caller
    becomes invalid. Asserted before any behaviour, because a widened `required` set is
    a silent breaking change to every agent already calling this tool."""
    update_board = next(t for t in _tools() if t.name == "update_board")
    assert update_board.input_schema["required"] == ["board_id"]


def test_update_board_advertises_every_boardupdate_field():
    """Every existing argument must survive verbatim — a rename would break callers as
    surely as a removal — and each new one must appear alongside them.

    The set is pinned **by name, never by a count**, which this test has now been
    right about twice: KAN-529 took it to six, and V51 (KAN-972) added ``key`` for
    seven. Both times the assertion was what noticed, which is why the name of this
    test no longer contains a number."""
    update_board = next(t for t in _tools() if t.name == "update_board")
    assert set(update_board.input_schema["properties"]) == {
        "board_id",
        "name",
        "key",
        "autosync_enabled",
        "autosync_advance_to_done",
        "outbound_webhook_url",
        "outbound_webhook_secret",
        "outbound_webhook_enabled",
    }


def test_update_board_sends_only_the_autosync_flags_passed(monkeypatch):
    """The property that matters: an omitted flag must not reach the wire at all, or an
    unrelated rename would silently flip a board's auto-sync opt-in. `_clean` drops
    `None` only — this goes through the real `PandanClient`, so it tests the client's
    whitelist too (it enumerates fields; it does not forward `**kwargs`)."""
    seen = _capture_client(monkeypatch, httpx.Response(200, json=_BOARD_READ))
    server.update_board(5, autosync_enabled=True)
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/boards/5"
    assert json.loads(seen["content"]) == {"autosync_enabled": True}


def test_update_board_sends_an_explicit_false(monkeypatch):
    """`False` is a value, not an omission — opting back out must be expressible.
    `_clean` filters on `is not None` precisely so this survives."""
    seen = _capture_client(monkeypatch, httpx.Response(200, json=_BOARD_READ))
    server.update_board(5, autosync_enabled=False, autosync_advance_to_done=False)
    assert json.loads(seen["content"]) == {
        "autosync_enabled": False,
        "autosync_advance_to_done": False,
    }


def test_update_board_rename_carries_no_autosync_opinion(monkeypatch):
    """The KAN-502 rename case, re-asserted now that two more fields exist."""
    seen = _capture_client(monkeypatch, httpx.Response(200, json=_BOARD_READ))
    server.update_board(5, name="Pandan Roadmap")
    assert json.loads(seen["content"]) == {"name": "Pandan Roadmap"}
