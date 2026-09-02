"""Unit tests for the planning-interval rollup computation (M8 V57, KAN-978).

Pure: sums committed/completed/velocity across member-cycle metrics dicts already
shaped like ``compute_cycle_metrics``'s return value. ``app.metrics`` imports only
the stdlib, so a top-level import here touches no engine (the unit job has no DB).
"""
from __future__ import annotations

from app.metrics import compute_planning_interval_metrics


def _cycle_metrics(committed_count, committed_points, completed_count, completed_points):
    return {
        "committed": {"count": committed_count, "points": committed_points},
        "completed": {"count": completed_count, "points": completed_points},
        "velocity": completed_points,
        "unit": "points" if committed_points > 0 else "count",
        "burndown": [],
    }


def test_no_member_cycles_is_zeroed():
    m = compute_planning_interval_metrics([])
    assert m["committed"] == {"count": 0, "points": 0}
    assert m["completed"] == {"count": 0, "points": 0}
    assert m["velocity"] == 0
    assert m["unit"] == "count"
    assert "burndown" not in m


def test_sums_across_member_cycles():
    members = [
        _cycle_metrics(2, 8, 1, 3),
        _cycle_metrics(2, 13, 2, 13),
    ]
    m = compute_planning_interval_metrics(members)
    assert m["committed"] == {"count": 4, "points": 21}
    assert m["completed"] == {"count": 3, "points": 16}
    assert m["velocity"] == 16
    assert m["unit"] == "points"


def test_unit_is_count_only_when_no_member_has_estimated_work():
    members = [_cycle_metrics(1, 0, 1, 0), _cycle_metrics(2, 0, 0, 0)]
    m = compute_planning_interval_metrics(members)
    assert m["unit"] == "count"
    assert m["committed"] == {"count": 3, "points": 0}


def test_unit_is_points_if_any_single_member_has_estimated_work():
    members = [_cycle_metrics(1, 0, 0, 0), _cycle_metrics(1, 5, 1, 5)]
    m = compute_planning_interval_metrics(members)
    assert m["unit"] == "points"
    assert m["committed"] == {"count": 2, "points": 5}


def test_velocity_sums_member_velocities_directly():
    """A member cycle's own ``velocity`` is already its completed points — the
    rollup must not recompute it from completed.points (which would coincide
    here but is a distinct field the rollup could accidentally read instead)."""
    members = [_cycle_metrics(1, 3, 1, 3), _cycle_metrics(1, 5, 1, 5)]
    m = compute_planning_interval_metrics(members)
    assert m["velocity"] == 8
