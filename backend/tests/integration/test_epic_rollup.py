"""API tests for the derived epic progress rollup + health signal (V32, KAN-296).

Derived (no writes, no migration): each epic read/list carries a ``progress``
rollup (done / total non-deleted child cards + percent) and a ``health`` signal
(on_track / at_risk / overdue, or null when the epic has no target_date). Covers
the rollup math over seeded child cards, the empty-epic 0% case, soft-deleted
children being excluded, and the health rule across the target-date boundary.

Uses only the HTTP client — per the suite convention any app-module imports go
inside test bodies, not at module top.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these run as the board-owning
    session user (claim-on-login owns the reset fixture's default board)."""
    return logged_in_client


def _create_epic(client, **fields):
    return client.post("/api/v1/epics", json={"name": "E", **fields})


def _create_card(client, epic_id, column="todo"):
    return client.post(
        "/api/v1/cards", json={"title": "T", "epic_id": epic_id, "column": column}
    )


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# --- progress rollup math ---------------------------------------------------


def test_rollup_three_of_five_done_is_sixty_percent(client):
    epic = _create_epic(client, name="Launch").json()
    for _ in range(3):
        _create_card(client, epic["id"], column="done")
    for _ in range(2):
        _create_card(client, epic["id"], column="todo")
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["progress"] == {"total": 5, "done": 3, "percent": 60}


def test_empty_epic_reads_zero_progress(client):
    epic = _create_epic(client, name="Empty").json()
    # Both on create and on read the rollup is present and zeroed (no crash).
    assert epic["progress"] == {"total": 0, "done": 0, "percent": 0}
    fetched = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert fetched["progress"] == {"total": 0, "done": 0, "percent": 0}


def test_all_children_done_is_hundred_percent(client):
    epic = _create_epic(client, name="Shipped").json()
    for _ in range(3):
        _create_card(client, epic["id"], column="done")
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["progress"]["percent"] == 100


def test_soft_deleted_children_excluded_from_rollup(client):
    epic = _create_epic(client, name="WithTrash").json()
    keep = _create_card(client, epic["id"], column="done").json()
    gone = _create_card(client, epic["id"], column="todo").json()
    # Soft-delete the todo child: it must drop out of both total and done.
    assert client.delete(f"/api/v1/cards/{gone['id']}").status_code == 204
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["progress"] == {"total": 1, "done": 1, "percent": 100}
    assert keep["id"] != gone["id"]


def test_rollup_present_on_list(client):
    epic = _create_epic(client, name="Listed").json()
    _create_card(client, epic["id"], column="done")
    _create_card(client, epic["id"], column="todo")
    listed = client.get("/api/v1/epics").json()
    row = next(e for e in listed if e["id"] == epic["id"])
    assert row["progress"] == {"total": 2, "done": 1, "percent": 50}
    assert "health" in row


# --- health signal ----------------------------------------------------------


def test_no_target_date_has_null_health(client):
    epic = _create_epic(client, name="NoDate").json()
    _create_card(client, epic["id"], column="todo")
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["health"] is None


def test_overdue_when_past_target_with_remaining_work(client):
    past = datetime.now(timezone.utc) - timedelta(days=2)
    epic = _create_epic(client, name="Late", target_date=_iso(past)).json()
    _create_card(client, epic["id"], column="done")
    _create_card(client, epic["id"], column="todo")  # remaining work
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["health"] == "overdue"


def test_at_risk_when_target_near_with_remaining_work(client):
    soon = datetime.now(timezone.utc) + timedelta(days=2)
    epic = _create_epic(client, name="Soon", target_date=_iso(soon)).json()
    for _ in range(3):
        _create_card(client, epic["id"], column="done")
    for _ in range(2):
        _create_card(client, epic["id"], column="todo")
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    # The card's demo: 60% done, deadline near → at_risk.
    assert body["progress"]["percent"] == 60
    assert body["health"] == "at_risk"


def test_on_track_when_target_comfortably_in_future(client):
    later = datetime.now(timezone.utc) + timedelta(days=30)
    epic = _create_epic(client, name="Plenty", target_date=_iso(later)).json()
    _create_card(client, epic["id"], column="done")
    _create_card(client, epic["id"], column="todo")
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["health"] == "on_track"


def test_complete_epic_on_track_even_past_target(client):
    past = datetime.now(timezone.utc) - timedelta(days=10)
    epic = _create_epic(client, name="DoneLate", target_date=_iso(past)).json()
    _create_card(client, epic["id"], column="done")
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["progress"]["percent"] == 100
    assert body["health"] == "on_track"


def test_empty_epic_past_target_is_on_track(client):
    past = datetime.now(timezone.utc) - timedelta(days=10)
    epic = _create_epic(client, name="EmptyLate", target_date=_iso(past)).json()
    body = client.get(f"/api/v1/epics/{epic['id']}").json()
    assert body["health"] == "on_track"


def test_health_transitions_across_the_date_boundary(client):
    """Same remaining work, health flips as the target moves across `now`:
    far future → on_track, near future → at_risk, past → overdue."""
    epic = _create_epic(client, name="Boundary").json()
    _create_card(client, epic["id"], column="done")
    _create_card(client, epic["id"], column="todo")  # keeps remaining work

    def health_for(delta: timedelta) -> str:
        target = datetime.now(timezone.utc) + delta
        client.patch(
            f"/api/v1/epics/{epic['id']}", json={"target_date": _iso(target)}
        )
        return client.get(f"/api/v1/epics/{epic['id']}").json()["health"]

    assert health_for(timedelta(days=60)) == "on_track"
    assert health_for(timedelta(days=1)) == "at_risk"
    assert health_for(timedelta(days=-1)) == "overdue"
