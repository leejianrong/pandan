"""API tests for the trash lifecycle: list / restore / purge (KAN-20, R5.2).

Builds on KAN-19's soft-delete tombstone. A soft-deleted card/epic:
- shows up under the trash listing (``GET /cards/trash`` / ``GET /epics/trash``),
  and is absent from the live list;
- can be **restored** (``POST .../restore``) — back in the live list with a valid,
  non-colliding position, and gone from the trash;
- can be **purged** (``DELETE .../purge``) — hard-deleted, gone from both lists, and
  a second purge/restore 404s.

Per CLAUDE.md (the PR #17 trap): every ``import app.*`` stays inside a test/fixture
body, never at module top.
"""
from __future__ import annotations

import pytest

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


@pytest.fixture
def client(logged_in_client):
    """/api/v1 is owner-gated (V8): run as the board-owning session user, who owns
    the reset fixture's default board via claim-on-login."""
    return logged_in_client


def _create_card(client, **fields):
    r = client.post("/api/v1/cards", json={"title": "T", **fields})
    assert r.status_code == 201
    return r.json()


def _create_epic(client, **fields):
    r = client.post("/api/v1/epics", json={"name": "E", **fields})
    assert r.status_code == 201
    return r.json()


def _titles_positions(client):
    return {c["title"]: c["position"] for c in client.get("/api/v1/cards").json()}


# --- cards: full round-trip ---------------------------------------------------


def test_card_trash_restore_purge_round_trip(client):
    a = _create_card(client, title="a", column="todo")  # pos 0
    b = _create_card(client, title="b", column="todo")  # pos 1
    c = _create_card(client, title="c", column="todo")  # pos 2

    # Soft-delete the middle card.
    assert client.delete(f"/api/v1/cards/{b['id']}").status_code == 204

    # It's in the trash listing (with deleted_at), absent from the live list.
    trash = client.get("/api/v1/cards/trash").json()
    assert [t["id"] for t in trash] == [b["id"]]
    assert trash[0]["deleted_at"] is not None
    assert b["id"] not in [x["id"] for x in client.get("/api/v1/cards").json()]

    # Restore it → back in the live list, gone from trash.
    r = client.post(f"/api/v1/cards/{b['id']}/restore")
    assert r.status_code == 200
    restored = r.json()
    # Re-appended to the end of its (board, column): the two live siblings (a=0, c=2
    # still occupy those slots, but the ordering count is by *live rows*, so append
    # index = 2 (there are 2 other live cards in todo).
    assert restored["column"] == "todo"
    assert restored["position"] == 2
    assert "deleted_at" not in restored  # normal read stays unchanged (KAN-20)

    live_ids = [x["id"] for x in client.get("/api/v1/cards").json()]
    assert b["id"] in live_ids
    assert client.get("/api/v1/cards/trash").json() == []

    # Restoring a live (not-trashed) card 404s.
    assert client.post(f"/api/v1/cards/{b['id']}/restore").status_code == 404
    # Purging a live (not-trashed) card 404s (purge is trash-only).
    assert client.delete(f"/api/v1/cards/{b['id']}/purge").status_code == 404

    # Delete again, then purge permanently.
    assert client.delete(f"/api/v1/cards/{b['id']}").status_code == 204
    assert client.delete(f"/api/v1/cards/{b['id']}/purge").status_code == 204

    # Gone from BOTH lists; a second purge and a restore both 404.
    assert b["id"] not in [x["id"] for x in client.get("/api/v1/cards").json()]
    assert client.get("/api/v1/cards/trash").json() == []
    assert client.delete(f"/api/v1/cards/{b['id']}/purge").status_code == 404
    assert client.post(f"/api/v1/cards/{b['id']}/restore").status_code == 404

    # Sanity: the untouched siblings are still live.
    assert {a["id"], c["id"]}.issubset(set(live_ids))


def test_restored_card_position_does_not_collide(client):
    # Delete the tail card, add another so the freed slot is reused, then restore —
    # the restored card must land at the end, not collide.
    _create_card(client, title="a", column="todo")  # pos 0
    b = _create_card(client, title="b", column="todo")  # pos 1
    assert client.delete(f"/api/v1/cards/{b['id']}").status_code == 204
    d = _create_card(client, title="d", column="todo")  # reuses index 1 (1 live left)
    assert d["position"] == 1

    restored = client.post(f"/api/v1/cards/{b['id']}/restore").json()
    # Two live cards (a=0, d=1) → append index 2, no collision with d.
    assert restored["position"] == 2
    positions = _titles_positions(client)
    assert positions == {"a": 0, "d": 1, "b": 2}


def test_purge_cascades_card_dependencies(client):
    blocker = _create_card(client, title="blocker")
    blocked = _create_card(client, title="blocked")
    assert (
        client.post(
            f"/api/v1/cards/{blocked['id']}/dependencies",
            json={"blocker_id": blocker["id"]},
        ).status_code
        == 201
    )
    assert client.delete(f"/api/v1/cards/{blocked['id']}").status_code == 204
    assert client.delete(f"/api/v1/cards/{blocked['id']}/purge").status_code == 204

    # The dependency edge is cascade-deleted; the blocker no longer "blocks" anything.
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM card_dependency")).scalar()
    assert n == 0
    refetched = client.get(f"/api/v1/cards/{blocker['id']}").json()
    assert refetched["blocks"] == []


# --- epics: round-trip + story re-association ---------------------------------


def test_epic_trash_restore_purge_round_trip(client):
    epic = _create_epic(client, name="E1")
    assert client.delete(f"/api/v1/epics/{epic['id']}").status_code == 204

    trash = client.get("/api/v1/epics/trash").json()
    assert [t["id"] for t in trash] == [epic["id"]]
    assert trash[0]["deleted_at"] is not None
    assert client.get("/api/v1/epics").json() == []

    r = client.post(f"/api/v1/epics/{epic['id']}/restore")
    assert r.status_code == 200
    assert "deleted_at" not in r.json()  # normal epic read unchanged
    assert [e["id"] for e in client.get("/api/v1/epics").json()] == [epic["id"]]
    assert client.get("/api/v1/epics/trash").json() == []

    # Restore/purge of a live epic 404 (trash-only).
    assert client.post(f"/api/v1/epics/{epic['id']}/restore").status_code == 404
    assert client.delete(f"/api/v1/epics/{epic['id']}/purge").status_code == 404

    assert client.delete(f"/api/v1/epics/{epic['id']}").status_code == 204
    assert client.delete(f"/api/v1/epics/{epic['id']}/purge").status_code == 204
    assert client.get("/api/v1/epics").json() == []
    assert client.get("/api/v1/epics/trash").json() == []
    assert client.delete(f"/api/v1/epics/{epic['id']}/purge").status_code == 404
    assert client.post(f"/api/v1/epics/{epic['id']}/restore").status_code == 404


def test_restoring_epic_reassociates_still_linked_stories(client):
    epic = _create_epic(client, name="E1")
    card = _create_card(client, epic_id=epic["id"])
    assert card["epic_id"] == epic["id"]

    # Soft-delete the epic — KAN-19 keeps the story's epic_id intact (no detach).
    assert client.delete(f"/api/v1/epics/{epic['id']}").status_code == 204
    assert client.get(f"/api/v1/cards/{card['id']}").json()["epic_id"] == epic["id"]

    # Restore the epic → it's live again and the story still resolves it.
    assert client.post(f"/api/v1/epics/{epic['id']}/restore").status_code == 200
    assert [e["id"] for e in client.get("/api/v1/epics").json()] == [epic["id"]]
    assert client.get(f"/api/v1/cards/{card['id']}").json()["epic_id"] == epic["id"]


def test_purging_epic_detaches_its_stories(client):
    epic = _create_epic(client, name="E1")
    card = _create_card(client, epic_id=epic["id"])
    assert client.delete(f"/api/v1/epics/{epic['id']}").status_code == 204
    assert client.delete(f"/api/v1/epics/{epic['id']}/purge").status_code == 204

    # ON DELETE SET NULL fires on a real delete: the story survives, detached.
    refetched = client.get(f"/api/v1/cards/{card['id']}").json()
    assert refetched["epic_id"] is None


# --- activity trail -----------------------------------------------------------


def test_restore_records_a_restored_activity_event(client):
    board_id = 1
    card = _create_card(client, title="a")
    assert client.delete(f"/api/v1/cards/{card['id']}").status_code == 204
    assert client.post(f"/api/v1/cards/{card['id']}/restore").status_code == 200

    feed = client.get(f"/api/v1/boards/{board_id}/activity").json()
    restored = [e for e in feed if e["action"] == "restored"]
    assert len(restored) == 1
    assert restored[0]["entity_type"] == "card"
    assert restored[0]["entity_id"] == card["id"]
    assert (card.get("ref") or card["ticket_number"]) in restored[0]["summary"]


# --- authz gates --------------------------------------------------------------


def test_trash_lifecycle_authz(login_as):
    alice = login_as(*ALICE)  # owns the default board
    card = alice.post("/api/v1/cards", json={"title": "a"}).json()
    epic = alice.post("/api/v1/epics", json={"name": "E"}).json()
    assert alice.delete(f"/api/v1/cards/{card['id']}").status_code == 204
    assert alice.delete(f"/api/v1/epics/{epic['id']}").status_code == 204

    bob = login_as(*BOB)  # owns nothing
    board_id = 1
    # Non-member is 403 on every trash-scoped route.
    assert bob.get("/api/v1/cards/trash", params={"board_id": board_id}).status_code == 403
    assert bob.get("/api/v1/epics/trash", params={"board_id": board_id}).status_code == 403
    assert bob.post(f"/api/v1/cards/{card['id']}/restore").status_code == 403
    assert bob.delete(f"/api/v1/cards/{card['id']}/purge").status_code == 403
    assert bob.post(f"/api/v1/epics/{epic['id']}/restore").status_code == 403
    assert bob.delete(f"/api/v1/epics/{epic['id']}/purge").status_code == 403


def test_trash_lifecycle_requires_auth(client):
    # An unauthenticated client (no cookie / no PAT) is 401 everywhere.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        assert anon.get("/api/v1/cards/trash").status_code == 401
        assert anon.get("/api/v1/epics/trash").status_code == 401
        assert anon.post("/api/v1/cards/1/restore").status_code == 401
        assert anon.delete("/api/v1/cards/1/purge").status_code == 401
        assert anon.post("/api/v1/epics/1/restore").status_code == 401
        assert anon.delete("/api/v1/epics/1/purge").status_code == 401
