"""Integration tests for fleet reporting / metrics — M5 V17, KAN-250.

Drives real card moves over the HTTP client (so genuine ``activity`` rows exist),
then backdates those activity timestamps to known values so the derived numbers —
throughput, cycle time, aging WIP, per-assignee — are deterministic. Also covers
the empty-board (all zeros) and authz (READ-gated) paths.

Per the suite convention, every ``import app.*`` lives inside a test/fixture body
(never module top) so the throwaway-DB fixture repoints DATABASE_URL first.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

CARDS = "/api/v1/cards"
BOARDS = "/api/v1/boards"


@pytest.fixture
def client(logged_in_client):
    """/api/v1 is owner-gated (V8): run as the board-owning session user, who owns
    the reset fixture's default board via claim-on-login."""
    return logged_in_client


def _board_id(client) -> int:
    return client.get(BOARDS).json()[0]["id"]


def _create(client, title, **fields):
    r = client.post(CARDS, json={"title": title, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _move(client, card_id, column):
    r = client.post(f"{CARDS}/{card_id}/move", json={"column": column})
    assert r.status_code == 200, r.text
    return r.json()


def _set_activity_ts(card_id: int, target_column: str, ts: datetime) -> None:
    """Backdate the ``moved``-to-``target_column`` activity row for a card so cycle
    time / aging are deterministic (the move endpoint stamps ts server-side)."""
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE activity SET ts = :ts WHERE entity_id = :cid "
                "AND action = 'moved' AND summary LIKE :suffix"
            ),
            {"ts": ts, "cid": card_id, "suffix": f"%to {target_column}"},
        )


def _metrics(client, board_id, **params):
    r = client.get(f"{BOARDS}/{board_id}/metrics", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# --- empty / quiet board -----------------------------------------------------


def test_empty_board_returns_zeroed_metrics(client):
    board_id = _board_id(client)
    m = _metrics(client, board_id)
    assert m["board_id"] == board_id
    assert m["throughput"] == 0
    assert m["cycle_time"] == {
        "count": 0,
        "avg_seconds": None,
        "median_seconds": None,
        "p90_seconds": None,
    }
    assert m["aging_wip"] == {
        "count": 0,
        "avg_seconds": None,
        "max_seconds": None,
        "items": [],
    }
    assert m["by_assignee"] == []
    assert m["by_assignee_class"] == []
    assert m["since"] is None
    assert m["until"] is not None


# --- the full derivation over seeded activity --------------------------------


def test_metrics_derived_from_seeded_activity(client):
    board_id = _board_id(client)
    now = datetime.now(timezone.utc)

    # Card A: in_progress → done, 1h cycle. Card B: in_progress → done, 3h cycle.
    # Both assigned to agent-a. Card C: in_progress only (still WIP), agent-b, ~30m.
    a = _create(client, "A", assignee="agent-a")
    b = _create(client, "B", assignee="agent-a")
    c = _create(client, "C", assignee="agent-b")

    for card in (a, b, c):
        _move(client, card["id"], "in_progress")
    _move(client, a["id"], "done")
    _move(client, b["id"], "done")

    _set_activity_ts(a["id"], "in_progress", now - timedelta(hours=2))
    _set_activity_ts(a["id"], "done", now - timedelta(hours=1))
    _set_activity_ts(b["id"], "in_progress", now - timedelta(hours=4))
    _set_activity_ts(b["id"], "done", now - timedelta(hours=1))
    _set_activity_ts(c["id"], "in_progress", now - timedelta(minutes=30))

    m = _metrics(client, board_id)

    # Throughput: A + B reached done.
    assert m["throughput"] == 2

    # Cycle time: [1h, 3h] → avg 2h, median 2h, p90 = 3h (nearest-rank).
    assert m["cycle_time"]["count"] == 2
    assert m["cycle_time"]["avg_seconds"] == 2 * 3600
    assert m["cycle_time"]["median_seconds"] == 2 * 3600
    assert m["cycle_time"]["p90_seconds"] == 3 * 3600

    # Aging WIP: only card C is still in_progress, ~30 minutes (server clock, so
    # allow a small tolerance for test execution time).
    assert m["aging_wip"]["count"] == 1
    item = m["aging_wip"]["items"][0]
    assert item["ticket_number"] == c["ticket_number"]
    # The board-local ref rides along (M8 V54, KAN-975) so the dashboard's aging bars
    # can label a card the same way every other surface does. It is rendered from the
    # board's key rather than stored, exactly as `CardRead.ref` is — so it must match
    # what the card read itself reports, not merely be non-null.
    assert item["ref"] == c["ref"]
    assert item["ref"] is not None
    assert item["assignee"] == "agent-b"
    assert 1770 <= item["age_seconds"] <= 1860  # ~1800s

    # Per-assignee: agent-a completed 2, agent-b holds 1 in progress.
    by = {row["assignee"]: row for row in m["by_assignee"]}
    assert by["agent-a"] == {"assignee": "agent-a", "throughput": 2, "wip": 0}
    assert by["agent-b"] == {"assignee": "agent-b", "throughput": 0, "wip": 1}


# --- observed throughput by assignee class (M8 V60, KAN-981) ----------------


def test_metrics_by_assignee_class_end_to_end(client):
    board_id = _board_id(client)
    now = datetime.now(timezone.utc)

    # Agent card: 5 pts over a 1-day cycle → 5.0 pts/day.
    agent_card = _create(client, "A", assignee="agent:claude", story_points=5)
    # Human card: 8 pts over a 2-day cycle → 4.0 pts/day.
    human_card = _create(client, "B", assignee="alice@example.com", story_points=8)
    # Unassigned card, still done, no story points: counts for throughput, not the rate.
    bare_card = _create(client, "C", assignee=None, story_points=None)

    for card in (agent_card, human_card, bare_card):
        _move(client, card["id"], "in_progress")
        _move(client, card["id"], "done")

    _set_activity_ts(agent_card["id"], "in_progress", now - timedelta(days=1))
    _set_activity_ts(agent_card["id"], "done", now)
    _set_activity_ts(human_card["id"], "in_progress", now - timedelta(days=2))
    _set_activity_ts(human_card["id"], "done", now)
    _set_activity_ts(bare_card["id"], "in_progress", now - timedelta(days=1))
    _set_activity_ts(bare_card["id"], "done", now)

    m = _metrics(client, board_id)
    assert m["throughput"] == 3

    by_class = {row["assignee_class"]: row for row in m["by_assignee_class"]}
    assert by_class["agent"] == {"assignee_class": "agent", "points_per_day": 5.0, "n": 1}
    assert by_class["human"] == {"assignee_class": "human", "points_per_day": 4.0, "n": 1}
    # The unassigned card has no story_points, so it's excluded from the rate
    # entirely (like cycle_time excludes a never-in-progress card) — no zeroed
    # "unassigned" bucket appears.
    assert "unassigned" not in by_class


def test_move_records_structured_transition_columns(client):
    """A real move todo→in_progress→done writes structured from_column/to_column on
    the ``moved`` activity rows (KAN-260), and metrics derived from them are correct."""
    from sqlalchemy import text

    from app.db import engine

    board_id = _board_id(client)
    now = datetime.now(timezone.utc)

    card = _create(client, "structured")
    _move(client, card["id"], "in_progress")
    _move(client, card["id"], "done")

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT from_column, to_column FROM activity "
                "WHERE entity_id = :cid AND action = 'moved' ORDER BY ts"
            ),
            {"cid": card["id"]},
        ).all()
    assert [(r.from_column, r.to_column) for r in rows] == [
        ("todo", "in_progress"),
        ("in_progress", "done"),
    ]

    # Metrics still derive correctly from the structured fields.
    _set_activity_ts(card["id"], "in_progress", now - timedelta(hours=2))
    _set_activity_ts(card["id"], "done", now - timedelta(hours=1))
    m = _metrics(client, board_id)
    assert m["throughput"] == 1
    assert m["cycle_time"]["count"] == 1
    assert m["cycle_time"]["avg_seconds"] == 1 * 3600


def test_dispatch_records_structured_transition_columns(client):
    """Dispatch claims a todo card into in_progress and records from=todo, to=in_progress."""
    from sqlalchemy import text

    from app.db import engine

    board_id = _board_id(client)
    card = _create(client, "to-dispatch")
    r = client.post(f"{BOARDS}/{board_id}/dispatch", json={"assignee": "agent-a"})
    assert r.status_code == 200, r.text

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT from_column, to_column FROM activity "
                "WHERE entity_id = :cid AND action = 'moved'"
            ),
            {"cid": card["id"]},
        ).one()
    assert (row.from_column, row.to_column) == ("todo", "in_progress")


def test_since_window_scopes_throughput(client):
    board_id = _board_id(client)
    now = datetime.now(timezone.utc)

    recent = _create(client, "recent")
    old = _create(client, "old")
    for card in (recent, old):
        _move(client, card["id"], "in_progress")
        _move(client, card["id"], "done")
    _set_activity_ts(recent["id"], "done", now - timedelta(days=1))
    _set_activity_ts(old["id"], "done", now - timedelta(days=30))

    all_time = _metrics(client, board_id)
    assert all_time["throughput"] == 2

    windowed = _metrics(client, board_id, window="7d")
    assert windowed["throughput"] == 1
    assert windowed["since"] is not None


def test_bad_window_is_422(client):
    board_id = _board_id(client)
    r = client.get(f"{BOARDS}/{board_id}/metrics", params={"window": "soon"})
    assert r.status_code == 422, r.text


# --- authz (READ-gated) ------------------------------------------------------


def test_metrics_requires_authentication(client):
    """No cookie / no PAT → 401 (a bare TestClient carries no session)."""
    from fastapi.testclient import TestClient

    from app.main import app

    board_id = _board_id(client)
    with TestClient(app) as anon:
        r = anon.get(f"{BOARDS}/{board_id}/metrics")
    assert r.status_code == 401, r.text


def test_metrics_denied_to_non_owner(client, login_as):
    """A different user who neither owns nor is a member of the board → 403."""
    board_id = _board_id(client)
    other = login_as("stranger@example.com", "gh-stranger")
    r = other.get(f"{BOARDS}/{board_id}/metrics")
    assert r.status_code == 403, r.text


def test_metrics_unknown_board_is_404(client):
    r = client.get(f"{BOARDS}/999999/metrics")
    assert r.status_code == 404, r.text
