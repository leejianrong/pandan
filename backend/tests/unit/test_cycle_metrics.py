"""Unit tests for the cycle burndown / velocity computation (V34, KAN-298).

Pure functions: committed-vs-completed totals, velocity, and the per-day burndown
series, exercised directly with no database. ``app.metrics`` imports only the
stdlib, so a top-level import here touches no engine (the unit job has no DB).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.metrics import compute_cycle_metrics

# A 3-day cycle window: 2026-07-01 .. 2026-07-03 (UTC).
START = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 3, 0, 0, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)


def _card(cid, column, points=None):
    return {"id": cid, "story_points": points, "column": column}


def test_empty_cycle_is_zeroed():
    m = compute_cycle_metrics([], {}, starts_on=START, ends_on=END, now=NOW)
    assert m["committed"] == {"count": 0, "points": 0}
    assert m["completed"] == {"count": 0, "points": 0}
    assert m["velocity"] == 0
    # No estimated work → count unit; a 3-day window still yields 3 flat points.
    assert m["unit"] == "count"
    assert [p["remaining"] for p in m["burndown"]] == [0, 0, 0]
    assert [p["completed"] for p in m["burndown"]] == [0, 0, 0]


def test_committed_completed_and_velocity_by_points():
    cards = [
        _card(1, "done", points=3),
        _card(2, "done", points=5),
        _card(3, "in_progress", points=8),
        _card(4, "todo", points=2),
        _card(5, "todo", points=None),  # unestimated → 0 points, still committed
    ]
    m = compute_cycle_metrics(cards, {}, starts_on=None, ends_on=None, now=NOW)
    assert m["committed"] == {"count": 5, "points": 18}
    assert m["completed"] == {"count": 2, "points": 8}
    assert m["velocity"] == 8
    assert m["unit"] == "points"
    # No dated window → no burndown series.
    assert m["burndown"] == []


def test_burndown_reduces_at_completion_day_by_points():
    # Committed 10 points. Card 1 (3pts) done on day 1; card 2 (7pts) done on day 3.
    cards = [
        _card(1, "done", points=3),
        _card(2, "done", points=7),
    ]
    done_times = {
        1: datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),  # day 0
        2: datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc),  # day 2
    }
    m = compute_cycle_metrics(cards, done_times, starts_on=START, ends_on=END, now=NOW)
    assert m["unit"] == "points"
    assert m["committed"]["points"] == 10
    b = m["burndown"]
    assert [p["date"] for p in b] == ["2026-07-01", "2026-07-02", "2026-07-03"]
    # Day 0: card 1 done (3) → remaining 7; day 1: nothing new → 7; day 2: card 2 → 0.
    assert [p["remaining"] for p in b] == [7, 7, 0]
    assert [p["completed"] for p in b] == [3, 3, 10]
    # Ideal line: 10 → 0 linearly across 3 points.
    assert [p["ideal"] for p in b] == [10.0, 5.0, 0.0]


def test_burndown_uses_count_when_unestimated():
    # No story points anywhere → burn down by card count instead.
    cards = [_card(1, "done"), _card(2, "done"), _card(3, "todo")]
    done_times = {
        1: datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        2: datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    }
    m = compute_cycle_metrics(cards, done_times, starts_on=START, ends_on=END, now=NOW)
    assert m["unit"] == "count"
    assert m["committed"] == {"count": 3, "points": 0}
    assert m["velocity"] == 0  # velocity is points, which are zero here
    assert [p["remaining"] for p in m["burndown"]] == [2, 1, 1]


def test_null_window_yields_empty_burndown_but_keeps_totals():
    cards = [_card(1, "done", points=4), _card(2, "todo", points=1)]
    m = compute_cycle_metrics(cards, {}, starts_on=START, ends_on=None, now=NOW)
    assert m["burndown"] == []
    assert m["committed"]["points"] == 5
    assert m["completed"]["points"] == 4


def test_done_card_missing_transition_falls_back_to_now():
    # A card currently done but with no recorded 'done' transition still counts as
    # completed and lands on the burndown at `now` (so the final day burns down).
    cards = [_card(1, "done", points=6)]
    m = compute_cycle_metrics(cards, {}, starts_on=START, ends_on=END, now=NOW)
    assert m["completed"]["points"] == 6
    # now = day 2 (2026-07-03 12:00) → completed by the last day.
    assert m["burndown"][-1]["remaining"] == 0
    assert m["burndown"][0]["remaining"] == 6  # not yet completed on day 0
