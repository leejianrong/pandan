"""API tests for planning intervals (M8 V57, KAN-978).

Mirrors ``test_cycles.py``: board-scoped CRUD, PATCH shipping from day one
(unlike cycles, which shipped without one), assigning a cycle to a planning
interval via ``PATCH /boards/{id}/cycles/{cid}`` and the ``planning_interval_id``
filter on ``GET /boards/{id}/cycles``, plus board-scoping/auth. Per the suite
convention, any app-module imports go inside test bodies, not at module top
(the PR #17 trap)."""
from __future__ import annotations

import pytest


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these tests run as the
    board-owning session user. Claim-on-login makes this user own the reset
    fixture's default board (id=1)."""
    return logged_in_client


CARDS = "/api/v1/cards"


def _pis(board_id: int) -> str:
    return f"/api/v1/boards/{board_id}/planning-intervals"


def _cycles(board_id: int) -> str:
    return f"/api/v1/boards/{board_id}/cycles"


# --- planning interval CRUD --------------------------------------------------


def test_create_list_get_delete_planning_interval(client):
    created = client.post(
        _pis(1),
        json={
            "name": "Q4 Planning",
            "starts_on": "2026-10-01T00:00:00Z",
            "ends_on": "2026-12-31T00:00:00Z",
        },
    )
    assert created.status_code == 201
    pi = created.json()
    assert pi["board_id"] == 1
    assert pi["name"] == "Q4 Planning"
    assert pi["starts_on"] is not None
    assert pi["ends_on"] is not None

    listed = client.get(_pis(1))
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [pi["id"]]

    got = client.get(f"{_pis(1)}/{pi['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Q4 Planning"

    deleted = client.delete(f"{_pis(1)}/{pi['id']}")
    assert deleted.status_code == 204
    assert client.get(_pis(1)).json() == []


def test_create_planning_interval_bounds_optional(client):
    pi = client.post(_pis(1), json={"name": "Backlog PI"}).json()
    assert pi["starts_on"] is None
    assert pi["ends_on"] is None


def test_create_planning_interval_rejects_blank_name(client):
    assert client.post(_pis(1), json={"name": "  "}).status_code == 422


def test_get_missing_planning_interval_is_404(client):
    assert client.get(f"{_pis(1)}/9999").status_code == 404


# --- assign / unassign a cycle to a planning interval ------------------------


def test_assign_and_unassign_cycle_to_planning_interval(client):
    pi = client.post(_pis(1), json={"name": "Q4 Planning"}).json()
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    assert cycle["planning_interval_id"] is None

    assigned = client.patch(
        f"{_cycles(1)}/{cycle['id']}", json={"planning_interval_id": pi["id"]}
    )
    assert assigned.status_code == 200
    assert assigned.json()["planning_interval_id"] == pi["id"]

    cleared = client.patch(
        f"{_cycles(1)}/{cycle['id']}", json={"planning_interval_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["planning_interval_id"] is None


def test_create_cycle_with_planning_interval(client):
    pi = client.post(_pis(1), json={"name": "Q4 Planning"}).json()
    cycle = client.post(
        _cycles(1), json={"name": "Sprint 1", "planning_interval_id": pi["id"]}
    ).json()
    assert cycle["planning_interval_id"] == pi["id"]


def test_assign_nonexistent_planning_interval_is_422(client):
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()
    assert (
        client.patch(
            f"{_cycles(1)}/{cycle['id']}", json={"planning_interval_id": 9999}
        ).status_code
        == 422
    )
    assert (
        client.post(
            _cycles(1), json={"name": "Sprint 2", "planning_interval_id": 9999}
        ).status_code
        == 422
    )


def test_deleting_planning_interval_detaches_its_cycles(client):
    pi = client.post(_pis(1), json={"name": "Q4 Planning"}).json()
    cycle = client.post(
        _cycles(1), json={"name": "Sprint 1", "planning_interval_id": pi["id"]}
    ).json()
    assert client.delete(f"{_pis(1)}/{pi['id']}").status_code == 204
    # SET NULL: the cycle survives, detached (not cascaded away).
    got = client.get(f"{_cycles(1)}/{cycle['id']}")
    assert got.status_code == 200
    assert got.json()["planning_interval_id"] is None


# --- planning_interval_id filter on list_cycles ------------------------------


def test_filter_cycles_by_planning_interval(client):
    pi = client.post(_pis(1), json={"name": "Q4 Planning"}).json()
    in_pi = client.post(
        _cycles(1), json={"name": "in", "planning_interval_id": pi["id"]}
    ).json()
    client.post(_cycles(1), json={"name": "out"})
    r = client.get(_cycles(1), params={"planning_interval_id": pi["id"]})
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [in_pi["id"]]


# --- board-scoping + authz ---------------------------------------------------


def test_planning_intervals_are_board_scoped(client):
    other = client.post("/api/v1/boards", json={"name": "Other"}).json()
    p1 = client.post(_pis(1), json={"name": "on-1"}).json()
    client.post(_pis(other["id"]), json={"name": "on-2"})
    assert [p["name"] for p in client.get(_pis(1)).json()] == ["on-1"]
    assert [p["name"] for p in client.get(_pis(other["id"])).json()] == ["on-2"]
    assert client.get(f"{_pis(other['id'])}/{p1['id']}").status_code == 404
    assert client.delete(f"{_pis(other['id'])}/{p1['id']}").status_code == 404


def test_cannot_assign_cycle_to_cross_board_planning_interval(client):
    other = client.post("/api/v1/boards", json={"name": "Other"}).json()
    other_pi = client.post(_pis(other["id"]), json={"name": "elsewhere"}).json()
    cycle = client.post(_cycles(1), json={"name": "Sprint 1"}).json()  # on board 1
    r = client.patch(
        f"{_cycles(1)}/{cycle['id']}", json={"planning_interval_id": other_pi["id"]}
    )
    assert r.status_code == 422


def test_non_member_cannot_touch_a_board_planning_interval(client, login_as):
    pi = client.post(_pis(1), json={"name": "private"}).json()
    stranger = login_as("stranger-pi@example.com", "gh-stranger-pi")
    assert stranger.get(_pis(1)).status_code == 403
    assert stranger.post(_pis(1), json={"name": "nope"}).status_code == 403
    assert stranger.get(f"{_pis(1)}/{pi['id']}").status_code == 403
    assert stranger.delete(f"{_pis(1)}/{pi['id']}").status_code == 403


def test_planning_intervals_on_unknown_board_is_404(client):
    assert client.get(_pis(9999)).status_code == 404
    assert client.post(_pis(9999), json={"name": "x"}).status_code == 404


# --- PATCH: ships from day one -----------------------------------------------


def test_update_planning_interval_renames_and_recorrects_bounds(client):
    pi = client.post(
        _pis(1),
        json={
            "name": "Q4 Planning",
            "starts_on": "2026-10-01T00:00:00Z",
            "ends_on": "2026-12-31T00:00:00Z",
        },
    ).json()

    r = client.patch(
        f"{_pis(1)}/{pi['id']}",
        json={"name": "Q4 2026", "ends_on": "2026-12-15T00:00:00Z"},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["id"] == pi["id"]
    assert updated["name"] == "Q4 2026"
    assert updated["ends_on"].startswith("2026-12-15")
    assert updated["starts_on"] == pi["starts_on"]

    assert client.get(f"{_pis(1)}/{pi['id']}").json()["name"] == "Q4 2026"


def test_update_planning_interval_keeps_its_cycles(client):
    pi = client.post(_pis(1), json={"name": "typo"}).json()
    cycle = client.post(
        _cycles(1), json={"name": "Sprint 1", "planning_interval_id": pi["id"]}
    ).json()

    client.patch(f"{_pis(1)}/{pi['id']}", json={"name": "fixed"})

    assert client.get(f"{_cycles(1)}/{cycle['id']}").json()["planning_interval_id"] == pi["id"]
    listed = client.get(f"{_cycles(1)}?planning_interval_id={pi['id']}").json()
    assert [c["id"] for c in listed] == [cycle["id"]]


def test_update_planning_interval_can_unschedule_bounds(client):
    pi = client.post(
        _pis(1),
        json={
            "name": "Q4 Planning",
            "starts_on": "2026-10-01T00:00:00Z",
            "ends_on": "2026-12-31T00:00:00Z",
        },
    ).json()
    updated = client.patch(
        f"{_pis(1)}/{pi['id']}", json={"starts_on": None, "ends_on": None}
    ).json()
    assert updated["starts_on"] is None
    assert updated["ends_on"] is None
    assert updated["name"] == "Q4 Planning"


def test_update_planning_interval_empty_body_is_a_noop(client):
    pi = client.post(_pis(1), json={"name": "Q4 Planning"}).json()
    r = client.patch(f"{_pis(1)}/{pi['id']}", json={})
    assert r.status_code == 200
    assert r.json()["name"] == "Q4 Planning"


def test_update_planning_interval_rejects_null_or_blank_name(client):
    pi = client.post(_pis(1), json={"name": "Q4 Planning"}).json()
    assert (
        client.patch(f"{_pis(1)}/{pi['id']}", json={"name": None}).status_code == 422
    )
    assert (
        client.patch(f"{_pis(1)}/{pi['id']}", json={"name": "  "}).status_code == 422
    )
    assert client.get(f"{_pis(1)}/{pi['id']}").json()["name"] == "Q4 Planning"


def test_update_missing_or_cross_board_planning_interval_is_404(client):
    other = client.post("/api/v1/boards", json={"name": "Other"}).json()
    pi = client.post(_pis(1), json={"name": "on-1"}).json()
    assert client.patch(f"{_pis(1)}/9999", json={"name": "x"}).status_code == 404
    r = client.patch(f"{_pis(other['id'])}/{pi['id']}", json={"name": "x"})
    assert r.status_code == 404
    assert client.get(f"{_pis(1)}/{pi['id']}").json()["name"] == "on-1"


def test_non_member_cannot_update_a_planning_interval(client, login_as):
    pi = client.post(_pis(1), json={"name": "private"}).json()
    stranger = login_as("stranger2-pi@example.com", "gh-stranger2-pi")
    r = stranger.patch(f"{_pis(1)}/{pi['id']}", json={"name": "mine now"})
    assert r.status_code == 403
    assert client.get(f"{_pis(1)}/{pi['id']}").json()["name"] == "private"
