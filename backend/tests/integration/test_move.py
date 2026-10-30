"""API tests for POST /api/v1/cards/{id}/move (move & reorder, R2)."""
from __future__ import annotations

import pytest


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these board tests run as the
    board-owning session user, shadowing conftest's unauthenticated ``client``.
    Claim-on-login makes this user own the reset fixture's default board."""
    return logged_in_client


def _create(client, title, column="todo"):
    return client.post("/api/v1/cards", json={"title": title, "column": column}).json()


def test_move_to_another_column_appends(client):
    a = _create(client, "A", "todo")
    r = client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "in_progress"})
    assert r.status_code == 200
    body = r.json()
    assert body["column"] == "in_progress"
    assert body["position"] == 0


def test_move_between_columns_renumbers_source(client):
    a = _create(client, "A", "todo")  # pos 0
    b = _create(client, "B", "todo")  # pos 1
    c = _create(client, "C", "todo")  # pos 2
    client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "done"})
    cards = {x["id"]: x for x in client.get("/api/v1/cards").json()}
    assert cards[a["id"]]["column"] == "done"
    assert cards[a["id"]]["position"] == 0
    assert cards[b["id"]]["position"] == 0  # source renumbered 0..n
    assert cards[c["id"]]["position"] == 1


def test_move_into_empty_column_lands_at_zero(client):
    a = _create(client, "A", "todo")
    r = client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "done", "position": 0})
    assert r.status_code == 200
    assert r.json()["column"] == "done"
    assert r.json()["position"] == 0


def test_move_unknown_card_returns_404(client):
    r = client.post("/api/v1/cards/999999/move", json={"column": "done"})
    assert r.status_code == 404


def test_move_rejects_unknown_column_422(client):
    a = _create(client, "A", "todo")
    r = client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "backlog"})
    assert r.status_code == 422


def test_move_rejects_negative_position_422(client):
    a = _create(client, "A", "todo")
    r = client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "todo", "position": -1})
    assert r.status_code == 422


def test_reorder_within_column(client):
    a = _create(client, "A", "todo")  # pos 0
    b = _create(client, "B", "todo")  # pos 1
    c = _create(client, "C", "todo")  # pos 2
    # Move C to the front of todo.
    client.post(f"/api/v1/cards/{c['id']}/move", json={"column": "todo", "position": 0})
    cards = {x["id"]: x for x in client.get("/api/v1/cards").json()}
    assert cards[c["id"]]["position"] == 0
    assert cards[a["id"]]["position"] == 1
    assert cards[b["id"]]["position"] == 2


def test_move_position_beyond_range_clamps_to_end(client):
    a = _create(client, "A", "todo")  # pos 0
    b = _create(client, "B", "todo")  # pos 1
    # Move A within todo to an out-of-range index -> clamps after B.
    client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "todo", "position": 99})
    cards = {x["id"]: x for x in client.get("/api/v1/cards").json()}
    assert cards[b["id"]]["position"] == 0
    assert cards[a["id"]]["position"] == 1


def test_move_to_specific_index_in_other_column(client):
    x = _create(client, "X", "done")  # done pos 0
    y = _create(client, "Y", "done")  # done pos 1
    a = _create(client, "A", "todo")  # todo pos 0
    # Move A into done at index 1 (between X and Y).
    client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "done", "position": 1})
    cards = {c["id"]: c for c in client.get("/api/v1/cards").json()}
    assert cards[x["id"]]["position"] == 0
    assert cards[a["id"]]["position"] == 1
    assert cards[y["id"]]["position"] == 2


def test_done_at_stamped_on_move_to_done_and_cleared_on_move_out(client):
    a = _create(client, "A", "todo")
    assert a["done_at"] is None
    r = client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "done"}).json()
    assert r["done_at"] is not None
    r = client.post(f"/api/v1/cards/{a['id']}/move", json={"column": "todo"}).json()
    assert r["done_at"] is None


def test_done_at_survives_edit_and_orders_done_by_completion(client):
    first = _create(client, "first", "todo")
    second = _create(client, "second", "todo")
    for c in (first, second):
        client.post(f"/api/v1/cards/{c['id']}/move", json={"column": "done"})
    # Editing the older done card bumps updated_at but must not change done_at.
    before = client.get(f"/api/v1/cards/{first['id']}").json()["done_at"]
    client.patch(f"/api/v1/cards/{first['id']}", json={"title": "first, edited"})
    assert client.get(f"/api/v1/cards/{first['id']}").json()["done_at"] == before
    rows = client.get("/api/v1/cards?column=done&sort=-done_at").json()
    assert [c["id"] for c in rows][:2] == [second["id"], first["id"]]


def test_card_created_directly_in_done_has_done_at(client):
    assert _create(client, "born done", "done")["done_at"] is not None
