"""Integration tests for the planning-interval metrics rollup (M8 V57, KAN-978).

The endpoint sums each member cycle's already-computed committed/completed/
velocity dict (``cycle_metrics_dict``, shared with ``routers/cycles.py``) rather
than deriving anything of its own from the activity feed, so these tests exercise
the rollup arithmetic and its board-scoping/authz — not burndown derivation,
which ``test_cycle_metrics.py`` already covers per-cycle. Per the suite
convention, every ``import app.*`` lives inside a test/fixture body."""
from __future__ import annotations

import pytest

CARDS = "/api/v1/cards"
BOARDS = "/api/v1/boards"


@pytest.fixture
def client(logged_in_client):
    return logged_in_client


def _board_id(client) -> int:
    return client.get(BOARDS).json()[0]["id"]


def _cycles(board_id: int) -> str:
    return f"{BOARDS}/{board_id}/cycles"


def _pis(board_id: int) -> str:
    return f"{BOARDS}/{board_id}/planning-intervals"


def _create_card(client, title, **fields):
    r = client.post(CARDS, json={"title": title, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _move(client, card_id, column):
    r = client.post(f"{CARDS}/{card_id}/move", json={"column": column})
    assert r.status_code == 200, r.text
    return r.json()


def _pi_metrics(client, board_id, pi_id):
    r = client.get(f"{_pis(board_id)}/{pi_id}/metrics")
    assert r.status_code == 200, r.text
    return r.json()


# --- rollup arithmetic --------------------------------------------------------


def test_empty_planning_interval_is_zeroed(client):
    board_id = _board_id(client)
    pi = client.post(_pis(board_id), json={"name": "empty"}).json()
    m = _pi_metrics(client, board_id, pi["id"])
    assert m["board_id"] == board_id
    assert m["planning_interval_id"] == pi["id"]
    assert m["cycle_count"] == 0
    assert m["committed"] == {"count": 0, "points": 0}
    assert m["completed"] == {"count": 0, "points": 0}
    assert m["velocity"] == 0
    assert m["unit"] == "count"
    assert "burndown" not in m


def test_planning_interval_with_no_cycles_but_not_empty_is_still_zeroed(client):
    """A planning interval with cycles assigned to OTHER planning intervals
    (or none) contributes nothing — the rollup only sums its own members."""
    board_id = _board_id(client)
    pi = client.post(_pis(board_id), json={"name": "target"}).json()
    other_pi = client.post(_pis(board_id), json={"name": "other"}).json()
    client.post(
        _cycles(board_id),
        json={"name": "elsewhere", "planning_interval_id": other_pi["id"]},
    )
    client.post(_cycles(board_id), json={"name": "unassigned"})
    m = _pi_metrics(client, board_id, pi["id"])
    assert m["cycle_count"] == 0
    assert m["committed"] == {"count": 0, "points": 0}


def test_rollup_sums_across_member_cycles(client):
    board_id = _board_id(client)
    pi = client.post(_pis(board_id), json={"name": "Q4"}).json()
    sprint1 = client.post(
        _cycles(board_id), json={"name": "Sprint 1", "planning_interval_id": pi["id"]}
    ).json()
    sprint2 = client.post(
        _cycles(board_id), json={"name": "Sprint 2", "planning_interval_id": pi["id"]}
    ).json()

    # Sprint 1: committed 8, completed 3 (done).
    a = _create_card(client, "A", story_points=3, cycle_id=sprint1["id"])
    _create_card(client, "B", story_points=5, cycle_id=sprint1["id"])
    _move(client, a["id"], "in_progress")
    _move(client, a["id"], "done")

    # Sprint 2: committed 13, completed 13 (both done).
    c = _create_card(client, "C", story_points=5, cycle_id=sprint2["id"])
    d = _create_card(client, "D", story_points=8, cycle_id=sprint2["id"])
    for card in (c, d):
        _move(client, card["id"], "in_progress")
        _move(client, card["id"], "done")

    m = _pi_metrics(client, board_id, pi["id"])
    assert m["cycle_count"] == 2
    assert m["committed"] == {"count": 4, "points": 21}
    assert m["completed"] == {"count": 3, "points": 16}
    assert m["velocity"] == 16
    assert m["unit"] == "points"


def test_rollup_falls_back_to_count_unit_when_unestimated(client):
    board_id = _board_id(client)
    pi = client.post(_pis(board_id), json={"name": "Q4"}).json()
    sprint = client.post(
        _cycles(board_id), json={"name": "Sprint 1", "planning_interval_id": pi["id"]}
    ).json()
    card = _create_card(client, "A", cycle_id=sprint["id"])  # no story_points
    _move(client, card["id"], "in_progress")
    _move(client, card["id"], "done")

    m = _pi_metrics(client, board_id, pi["id"])
    assert m["unit"] == "count"
    assert m["committed"] == {"count": 1, "points": 0}


# --- authz + scoping ----------------------------------------------------------


def test_pi_metrics_requires_authentication(client):
    from fastapi.testclient import TestClient

    from app.main import app

    board_id = _board_id(client)
    pi = client.post(_pis(board_id), json={"name": "s"}).json()
    with TestClient(app) as anon:
        r = anon.get(f"{_pis(board_id)}/{pi['id']}/metrics")
    assert r.status_code == 401, r.text


def test_pi_metrics_denied_to_non_member(client, login_as):
    board_id = _board_id(client)
    pi = client.post(_pis(board_id), json={"name": "s"}).json()
    stranger = login_as("stranger-pim@example.com", "gh-stranger-pim")
    r = stranger.get(f"{_pis(board_id)}/{pi['id']}/metrics")
    assert r.status_code == 403, r.text


def test_pi_metrics_unknown_is_404(client):
    board_id = _board_id(client)
    assert client.get(f"{_pis(board_id)}/999999/metrics").status_code == 404


def test_pi_metrics_cross_board_is_404(client):
    board_id = _board_id(client)
    other = client.post(BOARDS, json={"name": "Other"}).json()
    pi = client.post(_pis(board_id), json={"name": "s"}).json()
    r = client.get(f"{_pis(other['id'])}/{pi['id']}/metrics")
    assert r.status_code == 404, r.text
