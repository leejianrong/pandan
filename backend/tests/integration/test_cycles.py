"""API tests for cycles / iterations (V33, KAN-297).

Covers the board-scoped cycle CRUD (mirroring the saved-views router), assigning
and unassigning a card to a cycle via ``PATCH /cards/{id}``, the ``cycle_id``
filter on ``GET /cards``, and board-scoping/auth (cross-board id → 404, non-member
403). Per the suite convention, any app-module imports go inside test bodies, not at
module top (the PR #17 trap)."""
from __future__ import annotations

import pytest


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these tests run as the
    board-owning session user (shadows conftest's unauthenticated ``client``).
    Claim-on-login makes this user own the reset fixture's default board (id=1)."""
    return logged_in_client


CARDS = "/api/v1/cards"


def _create_card(client, **fields):
    return client.post(CARDS, json={"title": "T", **fields}).json()


def _cycles(board_id: int) -> str:
    return f"/api/v1/boards/{board_id}/cycles"


# --- cycle CRUD -------------------------------------------------------------


def test_create_list_get_delete_cycle(client):
    created = client.post(
        _cycles(1),
        json={
            "name": "Sprint 1",
            "starts_on": "2026-01-01T00:00:00Z",
            "ends_on": "2026-01-14T00:00:00Z",
        },
    )
    assert created.status_code == 201
    cycle = created.json()
    assert cycle["board_id"] == 1
    assert cycle["name"] == "Sprint 1"
    assert cycle["starts_on"] is not None
    assert cycle["ends_on"] is not None

    listed = client.get(_cycles(1))
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [cycle["id"]]

    got = client.get(f"{_cycles(1)}/{cycle['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Sprint 1"

    deleted = client.delete(f"{_cycles(1)}/{cycle['id']}")
    assert deleted.status_code == 204
    assert client.get(_cycles(1)).json() == []


def test_create_cycle_bounds_optional(client):
    cycle = client.post(_cycles(1), json={"name": "Backlog cycle"}).json()
    assert cycle["starts_on"] is None
    assert cycle["ends_on"] is None


def test_create_cycle_rejects_blank_name(client):
    assert client.post(_cycles(1), json={"name": "  "}).status_code == 422


def test_get_missing_cycle_is_404(client):
    assert client.get(f"{_cycles(1)}/9999").status_code == 404


# --- assign / unassign a card to a cycle ------------------------------------


def test_assign_and_unassign_card_to_cycle(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    card = _create_card(client, title="story")
    assert card["cycle_id"] is None

    # Assign via PATCH (a field edit, not /move).
    assigned = client.patch(f"{CARDS}/{card['id']}", json={"cycle_id": cycle["id"]})
    assert assigned.status_code == 200
    assert assigned.json()["cycle_id"] == cycle["id"]

    # Unassign by clearing with null.
    cleared = client.patch(f"{CARDS}/{card['id']}", json={"cycle_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["cycle_id"] is None


def test_create_card_with_cycle(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    card = _create_card(client, title="story", cycle_id=cycle["id"])
    assert card["cycle_id"] == cycle["id"]


def test_assign_nonexistent_cycle_is_422(client):
    card = _create_card(client, title="story")
    assert client.patch(f"{CARDS}/{card['id']}", json={"cycle_id": 9999}).status_code == 422


def test_deleting_cycle_detaches_its_cards(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    card = _create_card(client, title="story", cycle_id=cycle["id"])
    assert client.delete(f"{_cycles(1)}/{cycle['id']}").status_code == 204
    # SET NULL: the card survives, detached (not cascaded away).
    got = client.get(f"{CARDS}/{card['id']}")
    assert got.status_code == 200
    assert got.json()["cycle_id"] is None


# --- cycle_id filter --------------------------------------------------------


def test_filter_cards_by_cycle(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    in_cycle = _create_card(client, title="in", cycle_id=cycle["id"])
    _create_card(client, title="out")
    r = client.get(CARDS, params={"cycle_id": cycle["id"]})
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [in_cycle["id"]]


# --- board-scoping + authz --------------------------------------------------


def test_cycles_are_board_scoped(client):
    other = client.post("/api/v1/boards", json={"name": "Other"}).json()
    c1 = client.post(_cycles(1), json={"name": "on-1"}).json()
    client.post(_cycles(other["id"]), json={"name": "on-2"})
    assert [c["name"] for c in client.get(_cycles(1)).json()] == ["on-1"]
    assert [c["name"] for c in client.get(_cycles(other["id"])).json()] == ["on-2"]
    # c1 addressed under the wrong board 404s (cross-board id not reachable).
    assert client.get(f"{_cycles(other['id'])}/{c1['id']}").status_code == 404
    assert client.delete(f"{_cycles(other['id'])}/{c1['id']}").status_code == 404


def test_cannot_assign_card_to_cross_board_cycle(client):
    # A cycle on another board can't be linked to a card on board 1.
    other = client.post("/api/v1/boards", json={"name": "Other"}).json()
    other_cycle = client.post(_cycles(other["id"]), json={"name": "elsewhere"}).json()
    card = _create_card(client, title="story")  # on board 1
    r = client.patch(f"{CARDS}/{card['id']}", json={"cycle_id": other_cycle["id"]})
    assert r.status_code == 422


def test_non_member_cannot_touch_a_board_cycle(client, login_as):
    cycle = client.post(_cycles(1), json={"name": "private"}).json()
    stranger = login_as("stranger@example.com", "gh-stranger")
    assert stranger.get(_cycles(1)).status_code == 403
    assert stranger.post(_cycles(1), json={"name": "nope"}).status_code == 403
    assert stranger.get(f"{_cycles(1)}/{cycle['id']}").status_code == 403
    assert stranger.delete(f"{_cycles(1)}/{cycle['id']}").status_code == 403


def test_cycles_on_unknown_board_is_404(client):
    assert client.get(_cycles(9999)).status_code == 404
    assert client.post(_cycles(9999), json={"name": "x"}).status_code == 404


# --- PATCH: the non-destructive edit (V55, KAN-976) -------------------------


def test_update_cycle_renames_and_recorrects_bounds(client):
    cycle = client.post(
        _cycles(1),
        json={
            "name": "Sprint 1",
            "starts_on": "2026-01-01T00:00:00Z",
            "ends_on": "2026-01-14T00:00:00Z",
        },
    ).json()

    r = client.patch(
        f"{_cycles(1)}/{cycle['id']}",
        json={"name": "Sprint 12", "ends_on": "2026-09-05T00:00:00Z"},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["id"] == cycle["id"]
    assert updated["name"] == "Sprint 12"
    assert updated["ends_on"].startswith("2026-09-05")
    # Unsent fields are untouched (exclude_unset), not reset to null.
    assert updated["starts_on"] == cycle["starts_on"]

    assert client.get(f"{_cycles(1)}/{cycle['id']}").json()["name"] == "Sprint 12"


def test_update_cycle_keeps_its_cards(client):
    """The reason the endpoint exists. Before V55 the only way to fix a cycle's
    name was delete-and-recreate, which detaches every story in it."""
    cycle = client.post(_cycles(1), json={"name": "typo"}).json()
    card = _create_card(client, title="story", cycle_id=cycle["id"])

    client.patch(f"{_cycles(1)}/{cycle['id']}", json={"name": "fixed"})

    assert client.get(f"{CARDS}/{card['id']}").json()["cycle_id"] == cycle["id"]
    listed = client.get(f"{CARDS}?cycle_id={cycle['id']}").json()
    assert [c["id"] for c in listed] == [card["id"]]


def test_update_cycle_can_unschedule_bounds(client):
    """``starts_on``/``ends_on`` are genuinely nullable — a cycle with no bounds is
    already valid (create makes both optional), so an explicit null means unschedule."""
    cycle = client.post(
        _cycles(1),
        json={
            "name": "Sprint 1",
            "starts_on": "2026-01-01T00:00:00Z",
            "ends_on": "2026-01-14T00:00:00Z",
        },
    ).json()
    updated = client.patch(
        f"{_cycles(1)}/{cycle['id']}", json={"starts_on": None, "ends_on": None}
    ).json()
    assert updated["starts_on"] is None
    assert updated["ends_on"] is None
    assert updated["name"] == "Sprint 1"


def test_update_cycle_empty_body_is_a_noop(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    r = client.patch(f"{_cycles(1)}/{cycle['id']}", json={})
    assert r.status_code == 200
    assert r.json()["name"] == "Sprint 1"


def test_update_cycle_rejects_null_or_blank_name(client):
    """``name`` is not clearable. A null must be a clean 422 and not a NOT NULL
    violation at COMMIT — the trap LabelUpdate documents (V61)."""
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    assert (
        client.patch(f"{_cycles(1)}/{cycle['id']}", json={"name": None}).status_code
        == 422
    )
    assert (
        client.patch(f"{_cycles(1)}/{cycle['id']}", json={"name": "  "}).status_code
        == 422
    )
    assert client.get(f"{_cycles(1)}/{cycle['id']}").json()["name"] == "Sprint 1"


def test_update_missing_or_cross_board_cycle_is_404(client):
    other = client.post("/api/v1/boards", json={"name": "Other"}).json()
    cycle = client.post(_cycles(1), json={"name": "on-1"}).json()
    assert client.patch(f"{_cycles(1)}/9999", json={"name": "x"}).status_code == 404
    r = client.patch(f"{_cycles(other['id'])}/{cycle['id']}", json={"name": "x"})
    assert r.status_code == 404
    assert client.get(f"{_cycles(1)}/{cycle['id']}").json()["name"] == "on-1"


def test_non_member_cannot_update_a_cycle(client, login_as):
    cycle = client.post(_cycles(1), json={"name": "private"}).json()
    stranger = login_as("stranger2@example.com", "gh-stranger2")
    r = stranger.patch(f"{_cycles(1)}/{cycle['id']}", json={"name": "mine now"})
    assert r.status_code == 403
    assert client.get(f"{_cycles(1)}/{cycle['id']}").json()["name"] == "private"


# --- generate: a run of cycles in one call (M8 V58, KAN-979) ----------------


def _generate(client, board_id, **fields):
    return client.post(f"{_cycles(board_id)}/generate", json=fields)


def test_generate_creates_a_run_of_back_to_back_cycles(client):
    r = _generate(
        client,
        1,
        start="2026-09-07",
        length_days=14,
        count=6,
        name_template="Sprint {n}",
    )
    assert r.status_code == 201
    cycles = r.json()
    assert [c["name"] for c in cycles] == [f"Sprint {n}" for n in range(1, 7)]
    assert cycles[0]["starts_on"].startswith("2026-09-07")
    assert cycles[0]["ends_on"].startswith("2026-09-21")
    # Contiguous: each window's end is the next window's start.
    for prev, nxt in zip(cycles, cycles[1:]):
        assert prev["ends_on"] == nxt["starts_on"]

    listed = client.get(_cycles(1)).json()
    assert len(listed) == 6


def test_generate_rejects_overlap_with_existing_cycle_and_creates_none(client):
    existing = client.post(
        _cycles(1),
        json={
            "name": "Sprint 3",
            "starts_on": "2026-10-05T00:00:00Z",
            "ends_on": "2026-10-19T00:00:00Z",
        },
    ).json()

    r = _generate(
        client,
        1,
        start="2026-09-07",
        length_days=14,
        count=6,
        name_template="Sprint {n}",
    )
    assert r.status_code == 422
    assert str(existing["id"]) in r.json()["detail"]
    assert "Sprint 3" in r.json()["detail"]

    # All-or-nothing: the batch was rejected, so nothing besides the pre-existing
    # cycle exists.
    listed = client.get(_cycles(1)).json()
    assert [c["name"] for c in listed] == ["Sprint 3"]


def test_generate_is_all_or_nothing_when_only_a_later_cycle_collides(client):
    # The 4th generated window (2026-10-19..2026-11-02) collides; the first
    # three would not have, but nothing should be created regardless.
    client.post(
        _cycles(1),
        json={
            "name": "existing",
            "starts_on": "2026-10-25T00:00:00Z",
            "ends_on": "2026-11-01T00:00:00Z",
        },
    )
    r = _generate(
        client,
        1,
        start="2026-09-07",
        length_days=14,
        count=6,
        name_template="Sprint {n}",
    )
    assert r.status_code == 422
    listed = client.get(_cycles(1)).json()
    assert [c["name"] for c in listed] == ["existing"]


def test_generate_ignores_undated_existing_cycles(client):
    client.post(_cycles(1), json={"name": "undated"})
    r = _generate(
        client,
        1,
        start="2026-09-07",
        length_days=14,
        count=2,
        name_template="Sprint {n}",
    )
    assert r.status_code == 201
    listed = client.get(_cycles(1)).json()
    assert len(listed) == 3


def test_generate_with_planning_interval(client):
    pi = client.post(
        "/api/v1/boards/1/planning-intervals", json={"name": "PI-1"}
    ).json()
    r = _generate(
        client,
        1,
        start="2026-09-07",
        length_days=14,
        count=2,
        name_template="Sprint {n}",
        planning_interval_id=pi["id"],
    )
    assert r.status_code == 201
    assert all(c["planning_interval_id"] == pi["id"] for c in r.json())


def test_generate_rejects_nonexistent_planning_interval(client):
    r = _generate(
        client,
        1,
        start="2026-09-07",
        length_days=14,
        count=2,
        name_template="Sprint {n}",
        planning_interval_id=9999,
    )
    assert r.status_code == 422
    assert client.get(_cycles(1)).json() == []


def test_generate_rejects_bad_count(client):
    assert (
        _generate(
            client,
            1,
            start="2026-09-07",
            length_days=14,
            count=0,
            name_template="Sprint {n}",
        ).status_code
        == 422
    )
    assert (
        _generate(
            client,
            1,
            start="2026-09-07",
            length_days=14,
            count=53,
            name_template="Sprint {n}",
        ).status_code
        == 422
    )


def test_generate_rejects_nonpositive_length_days(client):
    assert (
        _generate(
            client,
            1,
            start="2026-09-07",
            length_days=0,
            count=2,
            name_template="Sprint {n}",
        ).status_code
        == 422
    )


def test_generate_rejects_blank_name_template(client):
    assert (
        _generate(
            client,
            1,
            start="2026-09-07",
            length_days=14,
            count=2,
            name_template="   ",
        ).status_code
        == 422
    )


def test_generate_rejects_invalid_name_template_placeholder(client):
    r = _generate(
        client,
        1,
        start="2026-09-07",
        length_days=14,
        count=2,
        name_template="Sprint {oops}",
    )
    assert r.status_code == 422
    assert client.get(_cycles(1)).json() == []


def test_generate_on_unknown_board_is_404(client):
    r = _generate(
        client,
        9999,
        start="2026-09-07",
        length_days=14,
        count=2,
        name_template="Sprint {n}",
    )
    assert r.status_code == 404


def test_non_member_cannot_generate_cycles(client, login_as):
    stranger = login_as("stranger3@example.com", "gh-stranger3")
    r = _generate(
        stranger,
        1,
        start="2026-09-07",
        length_days=14,
        count=2,
        name_template="Sprint {n}",
    )
    assert r.status_code == 403
    assert client.get(_cycles(1)).json() == []


# --- close: explicit close + rollover (M8 V59, KAN-980) ---------------------


def _close(client, board_id, cycle_id, rollover_to):
    return client.post(
        f"{_cycles(board_id)}/{cycle_id}/close", json={"rollover_to": rollover_to}
    )


def test_close_stamps_closed_at_and_freezes_committed_completed(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    _create_card(
        client, title="done story", cycle_id=cycle["id"], column="done", story_points=5
    )
    _create_card(
        client, title="wip story", cycle_id=cycle["id"], column="in_progress",
        story_points=3,
    )

    r = _close(client, 1, cycle["id"], None)
    assert r.status_code == 200
    body = r.json()
    assert body["closed_at"] is not None
    assert body["rolled_over_count"] == 1
    assert body["rollover_to"] is None

    got = client.get(f"{_cycles(1)}/{cycle['id']}").json()
    assert got["closed_at"] is not None
    assert got["frozen_committed"] == {"count": 2, "points": 8}
    assert got["frozen_completed"] == {"count": 1, "points": 5}


def test_close_moves_unfinished_cards_to_target_cycle_leaves_done_alone(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    target = client.post(_cycles(1), json={"name": "Sprint 2"}).json()
    done_card = _create_card(client, title="done", cycle_id=cycle["id"], column="done")
    wip_card = _create_card(
        client, title="wip", cycle_id=cycle["id"], column="in_progress"
    )

    r = _close(client, 1, cycle["id"], target["id"])
    assert r.status_code == 200
    assert r.json()["rolled_over_count"] == 1
    assert r.json()["rollover_to"] == target["id"]

    assert client.get(f"{CARDS}/{done_card['id']}").json()["cycle_id"] == cycle["id"]
    assert client.get(f"{CARDS}/{wip_card['id']}").json()["cycle_id"] == target["id"]


def test_close_with_null_rollover_moves_unfinished_to_backlog(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    wip_card = _create_card(
        client, title="wip", cycle_id=cycle["id"], column="in_progress"
    )
    _close(client, 1, cycle["id"], None)
    assert client.get(f"{CARDS}/{wip_card['id']}").json()["cycle_id"] is None


def test_close_leaves_deleted_cards_alone(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    card = _create_card(client, title="wip", cycle_id=cycle["id"], column="in_progress")
    assert client.delete(f"{CARDS}/{card['id']}").status_code == 204
    r = _close(client, 1, cycle["id"], None)
    assert r.json()["rolled_over_count"] == 0


def test_cycle_metrics_after_close_reports_frozen_numbers_and_empty_burndown(client):
    cycle = client.post(
        _cycles(1),
        json={
            "name": "Sprint 1",
            "starts_on": "2026-01-01T00:00:00Z",
            "ends_on": "2026-01-14T00:00:00Z",
        },
    ).json()
    _create_card(
        client, title="done", cycle_id=cycle["id"], column="done", story_points=5
    )
    wip = _create_card(
        client, title="wip", cycle_id=cycle["id"], column="in_progress", story_points=3
    )

    before = client.get(f"{_cycles(1)}/{cycle['id']}/metrics").json()
    assert before["committed"] == {"count": 2, "points": 8}
    assert before["burndown"]  # non-empty: a dated window

    other = client.post(_cycles(1), json={"name": "Sprint 2"}).json()
    _close(client, 1, cycle["id"], other["id"])

    after = client.get(f"{_cycles(1)}/{cycle['id']}/metrics").json()
    # Frozen at close time — still 2/8 committed even though `wip` has since left.
    assert after["committed"] == {"count": 2, "points": 8}
    assert after["completed"] == {"count": 1, "points": 5}
    assert after["velocity"] == 5
    assert after["burndown"] == []

    # Rollover really did move the card out.
    assert client.get(f"{CARDS}/{wip['id']}").json()["cycle_id"] == other["id"]


def test_close_rejects_rollover_to_a_closed_cycle(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    other = client.post(_cycles(1), json={"name": "Sprint 2"}).json()
    _close(client, 1, other["id"], None)  # close the target first

    r = _close(client, 1, cycle["id"], other["id"])
    assert r.status_code == 422
    assert client.get(f"{_cycles(1)}/{cycle['id']}").json()["closed_at"] is None


def test_close_rejects_rollover_to_a_cross_board_cycle(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    other_board = client.post("/api/v1/boards", json={"name": "Other"}).json()
    other_cycle = client.post(_cycles(other_board["id"]), json={"name": "elsewhere"}).json()

    r = _close(client, 1, cycle["id"], other_cycle["id"])
    assert r.status_code == 422


def test_close_rejects_rollover_to_a_nonexistent_cycle(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    assert _close(client, 1, cycle["id"], 9999).status_code == 422


def test_close_rejects_rollover_to_itself(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    assert _close(client, 1, cycle["id"], cycle["id"]).status_code == 422


def test_close_requires_rollover_to_field(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    r = client.post(f"{_cycles(1)}/{cycle['id']}/close", json={})
    assert r.status_code == 422


def test_closing_an_already_closed_cycle_is_409(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    assert _close(client, 1, cycle["id"], None).status_code == 200
    r = _close(client, 1, cycle["id"], None)
    assert r.status_code == 409


def test_close_missing_or_cross_board_cycle_is_404(client):
    other = client.post("/api/v1/boards", json={"name": "Other"}).json()
    cycle = client.post(_cycles(1), json={"name": "on-1"}).json()
    assert _close(client, 1, 9999, None).status_code == 404
    r = _close(client, other["id"], cycle["id"], None)
    assert r.status_code == 404


def test_non_member_cannot_close_a_cycle(client, login_as):
    cycle = client.post(_cycles(1), json={"name": "private"}).json()
    stranger = login_as("stranger4@example.com", "gh-stranger4")
    r = _close(stranger, 1, cycle["id"], None)
    assert r.status_code == 403
    assert client.get(f"{_cycles(1)}/{cycle['id']}").json()["closed_at"] is None
