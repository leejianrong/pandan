"""Unit tests for the derived epic rollup (app.epic_rollup) — V32, KAN-296.

Pure function: progress percent + the on_track / at_risk / overdue health rule,
exercised directly with no database. ``app.epic_rollup`` imports only the stdlib,
so a top-level import here touches no engine (the unit job has no DB).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.epic_rollup import AT_RISK_WINDOW, compute_rollup

NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


def _in(**kw) -> datetime:
    return NOW + timedelta(**kw)


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


# --- progress math ----------------------------------------------------------


def test_progress_three_of_five_is_sixty_percent():
    # The card's demo case: 3 done / 5 total = 60%.
    r = compute_rollup(total=5, done=3, target_date=None, now=NOW)
    assert r["progress"] == {"total": 5, "done": 3, "percent": 60}


def test_progress_empty_epic_is_zero_not_divide_by_zero():
    r = compute_rollup(total=0, done=0, target_date=None, now=NOW)
    assert r["progress"] == {"total": 0, "done": 0, "percent": 0}


def test_progress_all_done_is_hundred():
    r = compute_rollup(total=4, done=4, target_date=None, now=NOW)
    assert r["progress"]["percent"] == 100


def test_progress_rounds_to_nearest_int():
    # 1/3 → 33.33 → 33
    assert compute_rollup(3, 1, None, now=NOW)["progress"]["percent"] == 33
    # 2/3 → 66.67 → 67
    assert compute_rollup(3, 2, None, now=NOW)["progress"]["percent"] == 67


# --- health: null when no target_date ---------------------------------------


def test_no_target_date_has_no_health():
    assert compute_rollup(5, 3, None, now=NOW)["health"] is None
    assert compute_rollup(0, 0, None, now=NOW)["health"] is None


# --- health: overdue --------------------------------------------------------


def test_overdue_past_target_with_remaining_work():
    r = compute_rollup(5, 3, target_date=_ago(days=1), now=NOW)
    assert r["health"] == "overdue"


def test_complete_epic_is_on_track_even_past_target():
    # 100% done can't be overdue — shipped work is never late.
    r = compute_rollup(5, 5, target_date=_ago(days=30), now=NOW)
    assert r["health"] == "on_track"


def test_empty_epic_past_target_is_on_track():
    # No children → no remaining work → never overdue/at_risk.
    r = compute_rollup(0, 0, target_date=_ago(days=5), now=NOW)
    assert r["health"] == "on_track"


# --- health: at_risk vs on_track across the window boundary -----------------


def test_on_track_when_target_comfortably_in_future():
    r = compute_rollup(5, 3, target_date=_in(days=30), now=NOW)
    assert r["health"] == "on_track"


def test_at_risk_when_target_near_with_remaining_work():
    r = compute_rollup(5, 3, target_date=_in(days=2), now=NOW)
    assert r["health"] == "at_risk"


def test_boundary_exactly_at_window_edge_is_at_risk():
    # target - now == AT_RISK_WINDOW → within the window (<=), so at_risk.
    r = compute_rollup(5, 3, target_date=NOW + AT_RISK_WINDOW, now=NOW)
    assert r["health"] == "at_risk"


def test_boundary_just_past_window_edge_is_on_track():
    r = compute_rollup(
        5, 3, target_date=NOW + AT_RISK_WINDOW + timedelta(seconds=1), now=NOW
    )
    assert r["health"] == "on_track"


# --- health: the date-boundary transition (overdue at exactly `now`) --------


def test_transition_at_target_date_moment_is_overdue():
    # now == target_date → not "in the future", remaining work → overdue.
    r = compute_rollup(5, 3, target_date=NOW, now=NOW)
    assert r["health"] == "overdue"


def test_transition_one_second_before_target_is_at_risk():
    r = compute_rollup(5, 3, target_date=NOW + timedelta(seconds=1), now=NOW)
    assert r["health"] == "at_risk"
