"""Unit tests for PandanClient — every method against a mocked transport.

No real server: an ``httpx.MockTransport`` captures each outgoing request so we
can assert method/path/params/body/headers, and returns canned responses so we
can assert the client's return shape and error mapping.
"""
from __future__ import annotations

import httpx
import pytest

from pandan_client import PandanApiError, PandanClient
from pandan_client.client import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_TIMEOUT,
)


def make_client(handler, token=None):
    return PandanClient("http://test", token=token, transport=httpx.MockTransport(handler))


def capture(response):
    """A handler that records the request it saw and returns ``response``."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["headers"] = request.headers
        seen["content"] = request.content
        return response

    return handler, seen


# --- identity (KAN-614) ----------------------------------------------------


def test_me_hits_the_board_less_me_route_and_returns_the_body_unchanged():
    handler, seen = capture(
        httpx.Response(200, json={"id": "2b1c-uuid", "email": "you@example.test"})
    )
    out = make_client(handler, token="pandan_pat_test").me()
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/me"
    assert seen["params"] == {}  # no board, no filters — there is nothing to scope
    assert seen["headers"]["authorization"] == "Bearer pandan_pat_test"
    # Returned verbatim: it is a cross-app contract (kaya mirrors the UUID), so this
    # adapter must not wrap it in an envelope or rename its keys.
    assert out == {"id": "2b1c-uuid", "email": "you@example.test"}


def test_me_maps_a_401_to_the_shared_api_error():
    """The whole reason the verb exists: a bad credential comes back 401, which the
    CLI turns into exit 3 — the "did my token work?" answer."""
    handler, _ = capture(httpx.Response(401, json={"detail": "Not authenticated"}))
    with pytest.raises(PandanApiError) as excinfo:
        make_client(handler, token="pandan_pat_nope").me()
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Not authenticated"


# --- boards (V10) ----------------------------------------------------------


def test_list_boards_hits_boards_and_wraps_result():
    handler, seen = capture(httpx.Response(200, json=[{"id": 1, "name": "A"}]))
    out = make_client(handler).list_boards()
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards"
    assert out == {"boards": [{"id": 1, "name": "A"}]}


def test_create_board_posts_name():
    import json

    handler, seen = capture(httpx.Response(201, json={"id": 2, "name": "New"}))
    out = make_client(handler).create_board("New")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/boards"
    assert json.loads(seen["content"]) == {"name": "New"}
    assert out == {"id": 2, "name": "New"}


def test_update_board_patches_name():
    import json

    handler, seen = capture(httpx.Response(200, json={"id": 2, "name": "Renamed"}))
    out = make_client(handler).update_board(2, name="Renamed")
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/boards/2"
    assert json.loads(seen["content"]) == {"name": "Renamed"}
    assert out == {"id": 2, "name": "Renamed"}


def test_get_board_hits_the_id_path():
    handler, seen = capture(httpx.Response(200, json={"id": 4, "name": "B"}))
    out = make_client(handler).get_board(4)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/4"
    assert out == {"id": 4, "name": "B"}


def test_delete_board_sends_delete_and_returns_ack_without_parsing_body():
    handler, seen = capture(httpx.Response(204))  # no JSON body
    out = make_client(handler).delete_board(4)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/boards/4"
    assert out == {"deleted": 4}


# --- reads -----------------------------------------------------------------


def test_list_cards_passes_filters_and_reads_cursor_header():
    handler, seen = capture(
        httpx.Response(200, json=[{"id": 1}], headers={"X-Next-Cursor": "abc"})
    )
    out = make_client(handler).list_cards(column="todo", limit=2)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/cards"
    assert seen["params"] == {"column": "todo", "limit": "2"}
    assert out == {"cards": [{"id": 1}], "next_cursor": "abc"}


def test_list_cards_scopes_by_board_id():
    handler, seen = capture(httpx.Response(200, json=[]))
    make_client(handler).list_cards(board_id=7)
    assert seen["params"] == {"board_id": "7"}


# --- batch read by id / ticket ref (issue #254) ----------------------------


def test_list_cards_sends_ids_and_refs():
    handler, seen = capture(httpx.Response(200, json=[{"id": 12}]))
    make_client(handler).list_cards(ids="12,45", refs="KAN-9")
    assert seen["params"] == {"ids": "12,45", "refs": "KAN-9"}


def test_list_cards_lifts_the_unresolved_header_into_the_envelope():
    """The miss must reach the caller without them knowing the API reports in
    headers — omitting it silently is the one option issue #254 ruled out."""
    handler, _ = capture(
        httpx.Response(
            200,
            json=[{"id": 12}],
            headers={"X-Unresolved-Selectors": "99,KAN-404"},
        )
    )
    out = make_client(handler).list_cards(ids="12,99", refs="KAN-404")
    assert out == {"cards": [{"id": 12}], "unresolved": ["99", "KAN-404"]}


def test_no_unresolved_key_when_nothing_missed():
    """Absence is the signal, so the key must not appear as an empty list."""
    handler, _ = capture(httpx.Response(200, json=[{"id": 12}]))
    out = make_client(handler).list_cards(ids="12")
    assert out == {"cards": [{"id": 12}]}
    assert "unresolved" not in out


def test_split_card_selectors_buckets_ids_and_tickets():
    from pandan_client import split_card_selectors

    assert split_card_selectors("KAN-12,45,KAN-9") == ("45", "KAN-12,KAN-9")
    assert split_card_selectors("1,2,3") == ("1,2,3", None)
    assert split_card_selectors("KAN-1") == (None, "KAN-1")
    assert split_card_selectors("") == (None, None)
    # Whitespace around a token is the caller's formatting, not a selector.
    assert split_card_selectors(" 7 , KAN-8 ") == ("7", "KAN-8")


def test_split_card_selectors_does_not_validate_ticket_shape():
    """Validation is the API's 422 to raise; duplicating the rule client-side is
    how the two drift. Anything non-numeric is simply passed through as a ref."""
    from pandan_client import split_card_selectors

    assert split_card_selectors("not-a-ticket") == (None, "not-a-ticket")


def test_list_epics_scopes_by_board_id_and_wraps_result():
    handler, seen = capture(httpx.Response(200, json=[{"id": 3, "name": "E"}]))
    out = make_client(handler).list_epics(board_id=7)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/epics"
    assert seen["params"] == {"board_id": "7"}
    assert out == {"epics": [{"id": 3, "name": "E"}]}


def test_list_epics_without_board_sends_no_params():
    handler, seen = capture(httpx.Response(200, json=[]))
    make_client(handler).list_epics()
    assert seen["params"] == {}


def test_list_cards_without_more_pages_has_no_cursor():
    handler, _ = capture(httpx.Response(200, json=[]))
    out = make_client(handler).list_cards()
    assert out == {"cards": []}
    assert "next_cursor" not in out


def test_get_card_hits_the_id_path():
    handler, seen = capture(httpx.Response(200, json={"id": 7}))
    out = make_client(handler).get_card(7)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/cards/7"
    assert out == {"id": 7}


def test_get_epic_hits_the_id_path():
    handler, seen = capture(httpx.Response(200, json={"id": 3, "name": "E"}))
    out = make_client(handler).get_epic(3)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/epics/3"
    assert out == {"id": 3, "name": "E"}


# --- writes ----------------------------------------------------------------


def test_create_card_posts_only_provided_fields():
    import json

    handler, seen = capture(httpx.Response(201, json={"id": 1, "title": "T"}))
    make_client(handler).create_card("T", column="done")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards"
    # None fields (description, story_points, ...) are dropped, not sent as null.
    assert json.loads(seen["content"]) == {"title": "T", "column": "done"}


def test_create_card_includes_board_id_when_given():
    import json

    handler, seen = capture(httpx.Response(201, json={"id": 1}))
    make_client(handler).create_card("T", board_id=7)
    assert json.loads(seen["content"]) == {"board_id": 7, "title": "T"}


def test_create_epic_posts_name():
    import json

    handler, seen = capture(httpx.Response(201, json={"id": 1, "name": "E"}))
    make_client(handler).create_epic("E")
    assert seen["path"] == "/api/v1/epics"
    assert json.loads(seen["content"]) == {"name": "E"}


def test_create_epic_includes_board_id_when_given():
    import json

    handler, seen = capture(httpx.Response(201, json={"id": 1, "name": "E"}))
    make_client(handler).create_epic("E", board_id=7)
    assert json.loads(seen["content"]) == {"board_id": 7, "name": "E"}


def test_create_epic_includes_project_fields_when_given():
    import json

    # V31 (KAN-295): target_date + lead pass through the body when supplied.
    handler, seen = capture(httpx.Response(201, json={"id": 1, "name": "E"}))
    make_client(handler).create_epic(
        "E", target_date="2026-09-01T00:00:00Z", lead="ada"
    )
    assert json.loads(seen["content"]) == {
        "name": "E",
        "target_date": "2026-09-01T00:00:00Z",
        "lead": "ada",
    }


def test_update_card_patches_provided_fields():
    import json

    handler, seen = capture(httpx.Response(200, json={"id": 3}))
    make_client(handler).update_card(3, title="new")
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/cards/3"
    assert json.loads(seen["content"]) == {"title": "new"}


def test_update_epic_patches_only_provided_fields():
    import json

    handler, seen = capture(httpx.Response(200, json={"id": 3, "name": "E"}))
    make_client(handler).update_epic(3, name="E")
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/epics/3"
    # None fields (description) are dropped, not sent as null.
    assert json.loads(seen["content"]) == {"name": "E"}


def test_update_epic_includes_project_fields_when_given():
    import json

    handler, seen = capture(httpx.Response(200, json={"id": 3, "name": "E"}))
    make_client(handler).update_epic(3, target_date="2026-12-31T12:00:00Z", lead="grace")
    assert json.loads(seen["content"]) == {
        "target_date": "2026-12-31T12:00:00Z",
        "lead": "grace",
    }


def test_delete_epic_sends_delete_and_returns_ack_without_parsing_body():
    handler, seen = capture(httpx.Response(204))  # no JSON body
    out = make_client(handler).delete_epic(8)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/epics/8"
    assert out == {"deleted": 8}


def test_move_card_posts_to_move_with_column_and_position():
    import json

    handler, seen = capture(httpx.Response(200, json={"id": 5, "column": "done"}))
    make_client(handler).move_card(5, "done", position=0)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/5/move"
    assert json.loads(seen["content"]) == {"column": "done", "position": 0}


def test_delete_card_sends_delete_and_returns_ack_without_parsing_body():
    handler, seen = capture(httpx.Response(204))  # no JSON body
    out = make_client(handler).delete_card(9)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/cards/9"
    assert out == {"deleted": 9}


# --- card-to-card dependencies (KAN-28 API / KAN-31) -----------------------


def test_add_dependency_posts_blocker_id_and_returns_card():
    import json

    handler, seen = capture(
        httpx.Response(201, json={"id": 5, "blocked_by": [2], "blocks": []})
    )
    out = make_client(handler).add_dependency(5, 2)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/5/dependencies"
    assert json.loads(seen["content"]) == {"blocker_id": 2}
    # The whole (now-blocked) card body is returned unchanged.
    assert out == {"id": 5, "blocked_by": [2], "blocks": []}


def test_remove_dependency_deletes_edge_and_returns_card_body():
    # The DELETE responds with the refreshed card body (not 204), so it is parsed.
    handler, seen = capture(
        httpx.Response(200, json={"id": 5, "blocked_by": [], "blocks": []})
    )
    out = make_client(handler).remove_dependency(5, 2)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/cards/5/dependencies/2"
    assert out == {"id": 5, "blocked_by": [], "blocks": []}


def test_list_dependencies_reads_card_and_shapes_arrays():
    handler, seen = capture(
        httpx.Response(200, json={"id": 5, "title": "T", "blocked_by": [2, 3], "blocks": [9]})
    )
    out = make_client(handler).list_dependencies(5)
    # No dedicated endpoint — it reads the card itself.
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/cards/5"
    assert out == {"card_id": 5, "blocked_by": [2, 3], "blocks": [9]}


def test_list_dependencies_defaults_missing_arrays_to_empty():
    # A card body without the arrays (e.g. before KAN-29/KAN-28 fields are present)
    # yields empty lists rather than KeyErrors.
    handler, _ = capture(httpx.Response(200, json={"id": 5, "title": "T"}))
    out = make_client(handler).list_dependencies(5)
    assert out == {"card_id": 5, "blocked_by": [], "blocks": []}


# --- card work-links (KAN-32 API / KAN-34) ---------------------------------


def test_add_link_posts_label_and_url_and_returns_card():
    import json

    handler, seen = capture(
        httpx.Response(201, json={"id": 5, "links": [{"id": 1, "label": "PR", "url": "u"}]})
    )
    out = make_client(handler).add_link(5, "PR", "https://example/pr/1")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/5/links"
    assert json.loads(seen["content"]) == {"label": "PR", "url": "https://example/pr/1"}
    # The whole card body (with refreshed links) is returned unchanged.
    assert out == {"id": 5, "links": [{"id": 1, "label": "PR", "url": "u"}]}


def test_remove_link_deletes_link_and_returns_card_body():
    # The DELETE responds with the refreshed card body (not 204), so it is parsed.
    handler, seen = capture(httpx.Response(200, json={"id": 5, "links": []}))
    out = make_client(handler).remove_link(5, 2)
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/cards/5/links/2"
    assert out == {"id": 5, "links": []}


# --- card notes / comments (KAN-33 API / KAN-34) ---------------------------


def test_add_comment_posts_body_and_returns_comment():
    import json

    handler, seen = capture(
        httpx.Response(201, json={"id": 3, "body": "hi", "author_id": None})
    )
    out = make_client(handler).add_comment(5, "hi")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/cards/5/comments"
    assert json.loads(seen["content"]) == {"body": "hi"}
    assert out == {"id": 3, "body": "hi", "author_id": None}


def test_list_comments_reads_and_wraps_result():
    handler, seen = capture(httpx.Response(200, json=[{"id": 3, "body": "hi"}]))
    out = make_client(handler).list_comments(5)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/cards/5/comments"
    assert out == {"comments": [{"id": 3, "body": "hi"}]}


# --- health / warmup (KAN-39) ----------------------------------------------


def test_health_hits_unversioned_api_health_not_v1():
    handler, seen = capture(httpx.Response(200, json={"status": "ok"}))
    out = make_client(handler).health()
    assert seen["method"] == "GET"
    # /api/health, NOT /api/v1/api/health — the /api/v1 prefix is bypassed.
    assert seen["path"] == "/api/health"
    assert out == {"status": "ok"}


def test_warmup_returns_ok_when_healthy():
    handler, _ = capture(httpx.Response(200, json={"status": "ok"}))
    out = make_client(handler).warmup()
    assert out == {"status": "ok", "health": {"status": "ok"}}


def test_warmup_returns_waking_on_transport_error_without_raising():
    # Two connection failures: the GET retries once then gives up; warmup swallows
    # it into a soft "waking" status rather than raising (a cold, still-waking box).
    handler, calls = flaky(
        [httpx.ConnectError("still waking"), httpx.ConnectError("still waking")],
        httpx.Response(200, json={"status": "ok"}),
    )
    out = retry_client(handler).warmup()
    assert out["status"] == "waking"
    assert calls["count"] == 2  # original + one retry, then soft-return


def test_warmup_returns_error_on_http_error_response():
    handler, _ = capture(httpx.Response(503, json={"detail": "unavailable"}))
    out = make_client(handler).warmup()
    assert out["status"] == "error"
    assert "503" in out["detail"]


# --- claim_card (KAN-38) ---------------------------------------------------


def record_requests(response):
    """A handler that records *every* request it sees (claim/batch issue several)."""
    seen = {"requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        content = request.content
        seen["requests"].append(
            {
                "method": request.method,
                "path": request.url.path,
                "body": _json.loads(content) if content else None,
            }
        )
        return response

    return handler, seen


def test_claim_card_moves_to_in_progress_then_patches_assignee():
    handler, seen = record_requests(httpx.Response(200, json={"id": 5, "assignee": "me"}))
    out = make_client(handler).claim_card(5, "me")
    reqs = seen["requests"]
    assert len(reqs) == 2
    # First a move to in_progress ...
    assert reqs[0]["method"] == "POST"
    assert reqs[0]["path"] == "/api/v1/cards/5/move"
    assert reqs[0]["body"] == {"column": "in_progress"}
    # ... then a PATCH of the assignee.
    assert reqs[1]["method"] == "PATCH"
    assert reqs[1]["path"] == "/api/v1/cards/5"
    assert reqs[1]["body"] == {"assignee": "me"}
    # Returns the PATCH response (final state).
    assert out == {"id": 5, "assignee": "me"}


# --- create_cards (KAN-40) -------------------------------------------------


def test_create_cards_issues_one_post_per_card_and_returns_created_list():
    handler, seen = record_requests(httpx.Response(201, json={"id": 1}))
    out = make_client(handler).create_cards(
        [{"title": "A"}, {"title": "B", "column": "done"}]
    )
    reqs = seen["requests"]
    assert len(reqs) == 2
    assert all(r["method"] == "POST" and r["path"] == "/api/v1/cards" for r in reqs)
    assert reqs[0]["body"] == {"title": "A"}
    assert reqs[1]["body"] == {"title": "B", "column": "done"}
    assert out == {"created": [{"id": 1}, {"id": 1}]}


def test_create_cards_empty_list_makes_no_requests():
    handler, seen = record_requests(httpx.Response(201, json={"id": 1}))
    out = make_client(handler).create_cards([])
    assert seen["requests"] == []
    assert out == {"created": []}


def test_create_cards_fail_fast_leaves_earlier_creates_applied():
    # Second card is rejected (422). The loop stops there and the error propagates;
    # the first POST already happened (documented non-atomic behaviour).
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(201, json={"id": 1})
        return httpx.Response(422, json={"detail": "bad story_points"})

    with pytest.raises(PandanApiError) as excinfo:
        make_client(handler).create_cards([{"title": "A"}, {"title": "B", "story_points": 4}])
    assert excinfo.value.status_code == 422
    assert calls["count"] == 2  # first created, second rejected — no third attempt


# --- batch update + templates (M5 V19 / KAN-252) ---------------------------


def test_update_cards_issues_one_atomic_patch():
    handler, seen = record_requests(
        httpx.Response(200, json=[{"id": 1, "assignee": "a"}, {"id": 2, "assignee": "a"}])
    )
    out = make_client(handler).update_cards(
        [{"id": 1, "assignee": "a"}, {"id": 2, "assignee": "a"}]
    )
    reqs = seen["requests"]
    # A *single* server call (atomic), unlike create_cards' client-side loop.
    assert len(reqs) == 1
    assert reqs[0]["method"] == "PATCH"
    assert reqs[0]["path"] == "/api/v1/cards/batch"
    assert reqs[0]["body"] == [{"id": 1, "assignee": "a"}, {"id": 2, "assignee": "a"}]
    assert out == {"updated": [{"id": 1, "assignee": "a"}, {"id": 2, "assignee": "a"}]}


def test_list_templates_reads_board_templates():
    handler, seen = record_requests(httpx.Response(200, json=[{"id": 7, "name": "sprint"}]))
    out = make_client(handler).list_templates(3)
    assert seen["requests"][0]["path"] == "/api/v1/boards/3/templates"
    assert out == {"templates": [{"id": 7, "name": "sprint"}]}


def test_create_template_posts_name_and_cards():
    handler, seen = record_requests(httpx.Response(201, json={"id": 7}))
    make_client(handler).create_template(3, "sprint", [{"title": "A"}, {"title": "B"}])
    req = seen["requests"][0]
    assert req["method"] == "POST"
    assert req["path"] == "/api/v1/boards/3/templates"
    assert req["body"] == {"name": "sprint", "cards": [{"title": "A"}, {"title": "B"}]}


def test_apply_template_posts_to_apply_and_returns_created():
    handler, seen = record_requests(httpx.Response(201, json=[{"id": 10}, {"id": 11}]))
    out = make_client(handler).apply_template(3, 7)
    req = seen["requests"][0]
    assert req["method"] == "POST"
    assert req["path"] == "/api/v1/boards/3/templates/7/apply"
    assert out == {"created": [{"id": 10}, {"id": 11}]}


def test_delete_template_issues_delete():
    handler, seen = record_requests(httpx.Response(204))
    out = make_client(handler).delete_template(3, 7)
    req = seen["requests"][0]
    assert req["method"] == "DELETE"
    assert req["path"] == "/api/v1/boards/3/templates/7"
    assert out == {"deleted": 7}


# --- cycles / iterations (V33) ---------------------------------------------


def test_list_cycles_reads_board_cycles():
    handler, seen = record_requests(httpx.Response(200, json=[{"id": 4, "name": "sprint-1"}]))
    out = make_client(handler).list_cycles(3)
    assert seen["requests"][0]["path"] == "/api/v1/boards/3/cycles"
    assert out == {"cycles": [{"id": 4, "name": "sprint-1"}]}


def test_create_cycle_posts_name_and_bounds():
    handler, seen = record_requests(httpx.Response(201, json={"id": 4}))
    make_client(handler).create_cycle(
        3, "sprint-1", starts_on="2026-01-01T00:00:00Z", ends_on="2026-01-14T00:00:00Z"
    )
    req = seen["requests"][0]
    assert req["method"] == "POST"
    assert req["path"] == "/api/v1/boards/3/cycles"
    assert req["body"] == {
        "name": "sprint-1",
        "starts_on": "2026-01-01T00:00:00Z",
        "ends_on": "2026-01-14T00:00:00Z",
    }


def test_create_cycle_omits_unset_bounds():
    handler, seen = record_requests(httpx.Response(201, json={"id": 4}))
    make_client(handler).create_cycle(3, "sprint-1")
    assert seen["requests"][0]["body"] == {"name": "sprint-1"}


def test_get_cycle_reads_one():
    handler, seen = record_requests(httpx.Response(200, json={"id": 4}))
    make_client(handler).get_cycle(3, 4)
    req = seen["requests"][0]
    assert req["method"] == "GET"
    assert req["path"] == "/api/v1/boards/3/cycles/4"


def test_delete_cycle_issues_delete():
    handler, seen = record_requests(httpx.Response(204))
    out = make_client(handler).delete_cycle(3, 4)
    req = seen["requests"][0]
    assert req["method"] == "DELETE"
    assert req["path"] == "/api/v1/boards/3/cycles/4"
    assert out == {"deleted": 4}


def test_list_cards_sends_cycle_id_filter():
    handler, seen = capture(httpx.Response(200, json=[]))
    make_client(handler).list_cards(cycle_id=4)
    assert seen["params"]["cycle_id"] == "4"


def test_create_card_sends_cycle_id():
    handler, seen = capture(httpx.Response(201, json={"id": 1}))
    make_client(handler).create_card("T", cycle_id=4)
    import json as _json

    assert _json.loads(seen["content"])["cycle_id"] == 4


def test_update_card_sends_cycle_id():
    handler, seen = capture(httpx.Response(200, json={"id": 1}))
    make_client(handler).update_card(1, cycle_id=4)
    import json as _json

    assert _json.loads(seen["content"])["cycle_id"] == 4


# --- auth + error mapping --------------------------------------------------


def test_token_is_sent_as_bearer_header():
    handler, seen = capture(httpx.Response(201, json={"id": 1}))
    make_client(handler, token="s3cret").create_card("T")
    assert seen["headers"]["authorization"] == "Bearer s3cret"


def test_no_token_means_no_authorization_header():
    handler, seen = capture(httpx.Response(200, json=[]))
    make_client(handler).list_cards()
    assert "authorization" not in seen["headers"]


def test_401_raises_with_friendly_hint_and_raw_detail():
    handler, _ = capture(httpx.Response(401, json={"detail": "authentication required"}))
    with pytest.raises(PandanApiError) as excinfo:
        make_client(handler).create_card("T")
    assert excinfo.value.status_code == 401
    # The raw server detail is preserved ...
    assert excinfo.value.detail == "authentication required"
    # ... and the agent-facing message frames it as a token problem (V10).
    assert "401" in str(excinfo.value)
    assert "PANDAN_TOKEN" in str(excinfo.value)


def test_403_raises_with_wrong_board_hint():
    handler, _ = capture(
        httpx.Response(403, json={"detail": "you do not have access to this board"})
    )
    with pytest.raises(PandanApiError) as excinfo:
        make_client(handler).create_card("T", board_id=99)
    assert excinfo.value.status_code == 403
    assert "list_boards" in str(excinfo.value)


def test_error_without_json_body_falls_back_to_status():
    handler, _ = capture(httpx.Response(500, text="Internal Server Error"))
    with pytest.raises(PandanApiError) as excinfo:
        make_client(handler).get_card(1)
    assert excinfo.value.status_code == 500


# --- cold-start timeout + single retry (KAN-25) ----------------------------


def retry_client(handler, token=None):
    """A client whose retry sleep is disabled so tests don't actually wait."""
    return PandanClient(
        "http://test",
        token=token,
        transport=httpx.MockTransport(handler),
        retry_backoff=0,
    )


def flaky(errors, success):
    """A handler that raises the given ``errors`` in turn, then returns ``success``.

    Records how many times the transport was invoked so tests can assert the
    retry actually re-sent the request.
    """
    calls = {"count": 0}
    queue = list(errors)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if queue:
            raise queue.pop(0)
        return success

    return handler, calls


def test_timeout_defaults_are_generous_for_a_cold_start():
    # The documented defaults: short connect, generous read to ride the wake.
    assert DEFAULT_TIMEOUT == 35.0
    assert DEFAULT_CONNECT_TIMEOUT == 5.0
    client = PandanClient("http://test")
    assert client._client.timeout.read == 35.0
    assert client._client.timeout.connect == 5.0


def test_timeout_is_caller_configurable():
    client = PandanClient("http://test", timeout=60.0, connect_timeout=2.0)
    assert client._client.timeout.read == 60.0
    assert client._client.timeout.connect == 2.0


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.RemoteProtocolError("server disconnected / TLS UNEXPECTED_EOF"),
    ],
)
def test_connection_error_retries_once_then_succeeds_for_any_method(error):
    # A connection/handshake failure never reached the server, so even a write
    # (POST) is safely retried. The retry returns the 201.
    handler, calls = flaky([error], httpx.Response(201, json={"id": 1}))
    out = retry_client(handler).create_card("T")
    assert out == {"id": 1}
    assert calls["count"] == 2  # original + one retry


def test_get_read_timeout_retries_once_then_succeeds():
    # GET is idempotent, so a ReadTimeout is safe to retry.
    handler, calls = flaky(
        [httpx.ReadTimeout("read timed out")], httpx.Response(200, json={"id": 7})
    )
    out = retry_client(handler).get_card(7)
    assert out == {"id": 7}
    assert calls["count"] == 2


def test_post_read_timeout_does_not_retry_and_raises():
    # A write that timed out on read MIGHT have applied server-side; with LWW and
    # no idempotency keys we must not risk a double POST — so no retry.
    handler, calls = flaky(
        [httpx.ReadTimeout("read timed out")], httpx.Response(201, json={"id": 1})
    )
    with pytest.raises(httpx.ReadTimeout):
        retry_client(handler).create_card("T")
    assert calls["count"] == 1  # sent once, never retried


def test_patch_read_timeout_does_not_retry_and_raises():
    handler, calls = flaky(
        [httpx.ReadTimeout("read timed out")], httpx.Response(200, json={"id": 3})
    )
    with pytest.raises(httpx.ReadTimeout):
        retry_client(handler).update_card(3, title="new")
    assert calls["count"] == 1


def test_delete_read_timeout_does_not_retry_and_raises():
    handler, calls = flaky([httpx.ReadTimeout("read timed out")], httpx.Response(204))
    with pytest.raises(httpx.ReadTimeout):
        retry_client(handler).delete_card(9)
    assert calls["count"] == 1


def test_only_one_retry_then_the_error_propagates():
    # Two consecutive transport failures: original + one retry, then it gives up.
    handler, calls = flaky(
        [httpx.ConnectError("boom"), httpx.ConnectError("boom again")],
        httpx.Response(200, json={"id": 1}),
    )
    with pytest.raises(httpx.ConnectError):
        retry_client(handler).list_cards()
    assert calls["count"] == 2


def test_http_error_response_is_not_retried():
    # A 404 is an error *response*, not a cold start — no retry, still maps to
    # PandanApiError (no regression to the existing error mapping).
    handler, calls = flaky([], httpx.Response(404, json={"detail": "not found"}))
    with pytest.raises(PandanApiError) as excinfo:
        retry_client(handler).get_card(1)
    assert excinfo.value.status_code == 404
    assert calls["count"] == 1


def test_403_response_is_not_retried():
    handler, calls = flaky([], httpx.Response(403, json={"detail": "not your board"}))
    with pytest.raises(PandanApiError) as excinfo:
        retry_client(handler).create_card("T", board_id=99)
    assert excinfo.value.status_code == 403
    assert calls["count"] == 1


# --- dispatch + fleet-safe claim (M5 V12, KAN-245) -------------------------


def test_dispatch_posts_body_and_wraps_card():
    import json

    handler, seen = capture(httpx.Response(200, json={"id": 5, "column": "in_progress"}))
    out = make_client(handler).dispatch(3, assignee="agent-7", priority="high")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/boards/3/dispatch"
    assert json.loads(seen["content"]) == {"assignee": "agent-7", "priority": "high"}
    assert out == {"card": {"id": 5, "column": "in_progress"}}


def test_dispatch_204_returns_no_card():
    handler, seen = capture(httpx.Response(204))
    out = make_client(handler).dispatch(3)
    assert seen["method"] == "POST"
    assert out == {"card": None}


def test_next_ready_gets_and_wraps_card():
    handler, seen = capture(httpx.Response(200, json={"id": 9, "column": "todo"}))
    out = make_client(handler).next_ready(3, label=2)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/next"
    assert seen["params"] == {"label": "2"}
    assert out == {"card": {"id": 9, "column": "todo"}}


def test_next_ready_204_returns_no_card():
    handler, seen = capture(httpx.Response(204))
    out = make_client(handler).next_ready(3)
    assert out == {"card": None}


# --- fleet reporting / metrics (M5 V17, KAN-250) ---------------------------


def test_board_metrics_gets_and_returns_body():
    body = {"board_id": 3, "throughput": 2, "cycle_time": {"count": 0}}
    handler, seen = capture(httpx.Response(200, json=body))
    out = make_client(handler).board_metrics(3, window="7d")
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/metrics"
    assert seen["params"] == {"window": "7d"}
    assert out == body


def test_board_metrics_omits_unset_params():
    handler, seen = capture(httpx.Response(200, json={"board_id": 3}))
    make_client(handler).board_metrics(3)
    assert seen["params"] == {}


# --- activity feed (M5 V16, KAN-261) ---------------------------------------


def test_list_activity_gets_board_feed_and_wraps_result():
    handler, seen = capture(httpx.Response(200, json=[{"id": 1, "action": "created"}]))
    out = make_client(handler).list_activity(3)
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/boards/3/activity"
    assert seen["params"] == {}
    assert out == {"activity": [{"id": 1, "action": "created"}]}


def test_list_activity_passes_actor_action_and_reads_cursor_header():
    handler, seen = capture(
        httpx.Response(200, json=[{"id": 1}], headers={"X-Next-Cursor": "abc"})
    )
    out = make_client(handler).list_activity(
        3, actor="agent-7", action="moved", limit=2
    )
    assert seen["params"] == {"actor": "agent-7", "action": "moved", "limit": "2"}
    assert out == {"activity": [{"id": 1}], "next_cursor": "abc"}


# --- notification inbox (V37 API / KAN-301) ---------------------------------


def test_list_notifications_gets_inbox_and_wraps_result():
    handler, seen = capture(
        httpx.Response(200, json=[{"id": 1, "kind": "needs_human", "read_at": None}])
    )
    out = make_client(handler).list_notifications()
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/notifications"
    assert seen["params"] == {}  # unread omitted → no query param
    assert out == {"notifications": [{"id": 1, "kind": "needs_human", "read_at": None}]}


def test_list_notifications_passes_unread_filter():
    handler, seen = capture(httpx.Response(200, json=[]))
    make_client(handler).list_notifications(unread=True)
    assert seen["params"] == {"unread": "true"}


def test_mark_notification_read_patches_by_id():
    handler, seen = capture(
        httpx.Response(200, json={"id": 5, "kind": "assigned", "read_at": "2026-01-01T00:00:00Z"})
    )
    out = make_client(handler).mark_notification_read(5)
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/notifications/5"
    assert out["read_at"] == "2026-01-01T00:00:00Z"
