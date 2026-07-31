"""Integration tests for cycle burndown / velocity metrics — V34, KAN-298.

Seeds a cycle + cards + real card moves (so genuine ``activity`` rows exist),
backdates the ``done`` activity timestamps to known values so the burndown is
deterministic, and asserts committed/completed/velocity + the per-day series.
Also covers the empty cycle (zeroed), the no-window case, and authz (READ-gated:
401 / 403 / 404 including a cross-board cycle id).

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


def _cycles(board_id: int) -> str:
    return f"{BOARDS}/{board_id}/cycles"


def _create_card(client, title, **fields):
    r = client.post(CARDS, json={"title": title, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _move(client, card_id, column):
    r = client.post(f"{CARDS}/{card_id}/move", json={"column": column})
    assert r.status_code == 200, r.text
    return r.json()


def _set_done_ts(card_id: int, ts: datetime) -> None:
    """Backdate a card's ``moved``-to-``done`` activity row so the burndown is
    deterministic (the move endpoint stamps ts server-side)."""
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE activity SET ts = :ts WHERE entity_id = :cid "
                "AND action = 'moved' AND summary LIKE :suffix"
            ),
            {"ts": ts, "cid": card_id, "suffix": "%to done"},
        )


def _metrics(client, board_id, cycle_id):
    r = client.get(f"{_cycles(board_id)}/{cycle_id}/metrics")
    assert r.status_code == 200, r.text
    return r.json()


# --- empty cycle -------------------------------------------------------------


def test_empty_cycle_is_zeroed(client):
    board_id = _board_id(client)
    cycle = client.post(
        _cycles(board_id),
        json={
            "name": "empty",
            "starts_on": "2026-07-01T00:00:00Z",
            "ends_on": "2026-07-03T00:00:00Z",
        },
    ).json()
    m = _metrics(client, board_id, cycle["id"])
    assert m["board_id"] == board_id
    assert m["cycle_id"] == cycle["id"]
    assert m["committed"] == {"count": 0, "points": 0}
    assert m["completed"] == {"count": 0, "points": 0}
    assert m["velocity"] == 0
    assert m["unit"] == "count"
    # 3-day window still yields a (flat, zeroed) series.
    assert [p["remaining"] for p in m["burndown"]] == [0, 0, 0]


# --- full derivation over seeded, backdated activity -------------------------


def test_metrics_derived_from_seeded_activity(client):
    board_id = _board_id(client)
    # Window: today-2d .. today, so backdated completions fall inside it.
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cycle = client.post(
        _cycles(board_id),
        json={
            "name": "sprint",
            "starts_on": start.isoformat(),
            "ends_on": end.isoformat(),
        },
    ).json()

    # Committed 16 points: A(3) done, B(8) done, C(5) still in progress.
    a = _create_card(client, "A", story_points=3, cycle_id=cycle["id"])
    b = _create_card(client, "B", story_points=8, cycle_id=cycle["id"])
    c = _create_card(client, "C", story_points=5, cycle_id=cycle["id"])
    # A card NOT in the cycle must be excluded entirely.
    _create_card(client, "outsider", story_points=13)

    for card in (a, b, c):
        _move(client, card["id"], "in_progress")
    _move(client, a["id"], "done")
    _move(client, b["id"], "done")

    # A done on day 0, B done on day 2 (the last day).
    _set_done_ts(a["id"], start + timedelta(hours=9))
    _set_done_ts(b["id"], end + timedelta(hours=9))

    m = _metrics(client, board_id, cycle["id"])
    assert m["committed"] == {"count": 3, "points": 16}
    assert m["completed"] == {"count": 2, "points": 11}
    assert m["velocity"] == 11
    assert m["unit"] == "points"

    b_series = m["burndown"]
    assert [p["date"] for p in b_series] == [
        start.date().isoformat(),
        (start + timedelta(days=1)).date().isoformat(),
        end.date().isoformat(),
    ]
    # Committed total 16; A(3) burns on day 0, B(8) on day 2.
    assert [p["remaining"] for p in b_series] == [13, 13, 5]
    assert [p["completed"] for p in b_series] == [3, 3, 11]
    assert b_series[0]["ideal"] == 16.0
    assert b_series[-1]["ideal"] == 0.0


def test_null_window_keeps_totals_but_empty_burndown(client):
    board_id = _board_id(client)
    cycle = client.post(_cycles(board_id), json={"name": "no-dates"}).json()
    card = _create_card(client, "S", story_points=5, cycle_id=cycle["id"])
    _move(client, card["id"], "in_progress")
    _move(client, card["id"], "done")
    m = _metrics(client, board_id, cycle["id"])
    assert m["burndown"] == []
    assert m["committed"]["points"] == 5
    assert m["completed"]["points"] == 5
    assert m["velocity"] == 5


def test_soft_deleted_cards_excluded(client):
    board_id = _board_id(client)
    cycle = client.post(_cycles(board_id), json={"name": "s"}).json()
    keep = _create_card(client, "keep", story_points=2, cycle_id=cycle["id"])
    gone = _create_card(client, "gone", story_points=8, cycle_id=cycle["id"])
    assert client.delete(f"{CARDS}/{gone['id']}").status_code == 204
    m = _metrics(client, board_id, cycle["id"])
    assert m["committed"] == {"count": 1, "points": 2}
    _ = keep


# --- authz (READ-gated) ------------------------------------------------------


def test_metrics_requires_authentication(client):
    from fastapi.testclient import TestClient

    from app.main import app

    board_id = _board_id(client)
    cycle = client.post(_cycles(board_id), json={"name": "s"}).json()
    with TestClient(app) as anon:
        r = anon.get(f"{_cycles(board_id)}/{cycle['id']}/metrics")
    assert r.status_code == 401, r.text


def test_metrics_denied_to_non_member(client, login_as):
    board_id = _board_id(client)
    cycle = client.post(_cycles(board_id), json={"name": "s"}).json()
    stranger = login_as("stranger@example.com", "gh-stranger")
    r = stranger.get(f"{_cycles(board_id)}/{cycle['id']}/metrics")
    assert r.status_code == 403, r.text


def test_metrics_unknown_cycle_is_404(client):
    board_id = _board_id(client)
    assert client.get(f"{_cycles(board_id)}/999999/metrics").status_code == 404


def test_metrics_cross_board_cycle_is_404(client):
    board_id = _board_id(client)
    other = client.post(BOARDS, json={"name": "Other"}).json()
    cycle = client.post(_cycles(board_id), json={"name": "s"}).json()
    # The cycle addressed under a different (owned) board 404s — never reachable.
    r = client.get(f"{_cycles(other['id'])}/{cycle['id']}/metrics")
    assert r.status_code == 404, r.text
