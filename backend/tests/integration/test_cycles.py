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
