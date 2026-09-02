"""Unit tests for the derived-metrics computation (app.metrics) — M5 V17, KAN-250.

Pure functions: summary parsing + the throughput / cycle-time / aging / per-assignee
math, exercised directly with no database. ``app.metrics`` imports only the stdlib,
so a top-level import here touches no engine (the unit job has no DB).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.metrics import _assignee_class, compute_metrics, move_target, parse_move_target

NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


# --- parse_move_target ------------------------------------------------------


def test_parse_cross_column_move_returns_destination():
    assert parse_move_target("moved KAN-3 from todo to in_progress") == "in_progress"
    assert parse_move_target("moved KAN-3 from in_progress to done") == "done"
    assert parse_move_target("moved KAN-9 from done to todo") == "todo"


def test_parse_dispatch_summary_is_in_progress():
    # dispatch always claims a todo card into in_progress; assignee text varies.
    assert parse_move_target("dispatched KAN-3 to agent-a@example.com") == "in_progress"
    assert parse_move_target("dispatched KAN-3 to done") == "in_progress"


def test_parse_same_column_reorder_is_not_a_transition():
    assert parse_move_target("moved KAN-3 to done") is None
    assert parse_move_target("moved KAN-3 to in_progress") is None


def test_parse_unrecognised_summary_is_none():
    assert parse_move_target("created KAN-3: Fix login") is None
    assert parse_move_target("moved KAN-3 from todo to sideways") is None


# --- move_target (structured fields, with a NULL-summary fallback) ----------


def test_move_target_reads_structured_cross_column():
    # A genuine transition: to_column set and differs from from_column. The summary
    # is ignored when the structured fields are present.
    assert move_target("todo", "in_progress", "ignored") == "in_progress"
    assert move_target("in_progress", "done", "ignored") == "done"


def test_move_target_structured_same_column_is_not_a_transition():
    # from == to is a same-column reorder, not a transition.
    assert move_target("done", "done", "moved KAN-3 to done") is None


def test_move_target_structured_ignores_invalid_column():
    assert move_target("todo", "sideways", "ignored") is None


def test_move_target_falls_back_to_summary_when_structured_is_null():
    # Legacy rows (pre-KAN-260) have NULL from/to; fall back to summary parsing so no
    # historical metric regresses.
    assert move_target(None, None, "moved KAN-3 from todo to in_progress") == "in_progress"
    assert move_target(None, None, "dispatched KAN-3 to agent-a@example.com") == "in_progress"
    assert move_target(None, None, "moved KAN-3 to done") is None
    assert move_target(None, None, "created KAN-3: Fix login") is None


# --- compute_metrics --------------------------------------------------------


def _card(
    cid, column, *, ticket=None, assignee=None, story_points=None,
    created_at=None, deleted=False,
):
    return {
        "id": cid,
        "ticket_number": ticket or f"KAN-{cid}",
        "column": column,
        "assignee": assignee,
        "story_points": story_points,
        "created_at": created_at or _ago(hours=1),
        "deleted": deleted,
    }


def test_empty_board_is_all_zeros_and_nulls():
    m = compute_metrics([], [], now=NOW, since=None)
    assert m["throughput"] == 0
    assert m["cycle_time"] == {
        "count": 0,
        "avg_seconds": None,
        "median_seconds": None,
        "p90_seconds": None,
    }
    assert m["aging_wip"]["count"] == 0
    assert m["aging_wip"]["avg_seconds"] is None
    assert m["aging_wip"]["max_seconds"] is None
    assert m["aging_wip"]["items"] == []
    assert m["by_assignee"] == []
    assert m["by_assignee_class"] == []


def test_throughput_counts_distinct_cards_done_in_period():
    transitions = [
        (1, "in_progress", _ago(hours=3)),
        (1, "done", _ago(hours=2)),
        (2, "done", _ago(hours=1)),
        (3, "done", _ago(days=10)),  # outside a 7-day window
    ]
    cards = [_card(1, "done"), _card(2, "done"), _card(3, "done")]
    all_time = compute_metrics(transitions, cards, now=NOW, since=None)
    assert all_time["throughput"] == 3
    windowed = compute_metrics(transitions, cards, now=NOW, since=_ago(days=7))
    assert windowed["throughput"] == 2


def test_cycle_time_is_first_in_progress_to_done():
    # Card 1: 2h cycle; card 2: 4h cycle. avg 3h, median 3h, p90 = 4h (nearest-rank).
    transitions = [
        (1, "in_progress", _ago(hours=4)),
        (1, "done", _ago(hours=2)),
        (2, "in_progress", _ago(hours=6)),
        (2, "done", _ago(hours=2)),
    ]
    cards = [_card(1, "done"), _card(2, "done")]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    assert m["cycle_time"]["count"] == 2
    assert m["cycle_time"]["avg_seconds"] == 3 * 3600
    assert m["cycle_time"]["median_seconds"] == 3 * 3600
    assert m["cycle_time"]["p90_seconds"] == 4 * 3600


def test_cycle_time_excludes_done_cards_that_never_hit_in_progress():
    # Card straight from todo to done (no in_progress) counts for throughput but
    # not cycle time.
    transitions = [(1, "done", _ago(hours=1))]
    cards = [_card(1, "done")]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    assert m["throughput"] == 1
    assert m["cycle_time"]["count"] == 0
    assert m["cycle_time"]["avg_seconds"] is None


def test_aging_wip_measures_from_last_in_progress_entry():
    transitions = [
        (1, "in_progress", _ago(hours=5)),
        (1, "done", _ago(hours=4)),
        (1, "in_progress", _ago(hours=2)),  # bounced back; last entry wins
    ]
    cards = [_card(1, "in_progress", assignee="agent-a")]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    assert m["aging_wip"]["count"] == 1
    item = m["aging_wip"]["items"][0]
    assert item["card_id"] == 1
    assert item["age_seconds"] == 2 * 3600
    assert m["aging_wip"]["max_seconds"] == 2 * 3600


def test_aging_wip_falls_back_to_created_at_without_a_move():
    # A card currently in_progress with no recorded move (e.g. created there).
    cards = [_card(1, "in_progress", created_at=_ago(hours=3))]
    m = compute_metrics([], cards, now=NOW, since=None)
    assert m["aging_wip"]["items"][0]["age_seconds"] == 3 * 3600


def test_aging_wip_ignores_soft_deleted_cards():
    cards = [_card(1, "in_progress", deleted=True), _card(2, "in_progress")]
    m = compute_metrics([], cards, now=NOW, since=None)
    assert m["aging_wip"]["count"] == 1
    assert m["aging_wip"]["items"][0]["card_id"] == 2


def test_by_assignee_breakdown():
    transitions = [
        (1, "done", _ago(hours=1)),
        (2, "done", _ago(hours=1)),
        (3, "in_progress", _ago(hours=1)),
    ]
    cards = [
        _card(1, "done", assignee="agent-a"),
        _card(2, "done", assignee="agent-a"),
        _card(3, "in_progress", assignee="agent-b"),
        _card(4, "in_progress", assignee=None),
    ]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    by = {row["assignee"]: row for row in m["by_assignee"]}
    assert by["agent-a"] == {"assignee": "agent-a", "throughput": 2, "wip": 0}
    assert by["agent-b"] == {"assignee": "agent-b", "throughput": 0, "wip": 1}
    assert by[None] == {"assignee": None, "throughput": 0, "wip": 1}
    # Unassigned sorts last.
    assert m["by_assignee"][-1]["assignee"] is None


# --- by_assignee_class: observed throughput (M8 V60, KAN-981) ---------------


def test_assignee_class_classifies_agent_human_and_unassigned():
    assert _assignee_class("agent:claude") == "agent"
    assert _assignee_class("agent:") == "agent"
    assert _assignee_class("someone@example.com") == "human"
    # No colon: not the agent: prefix, so it's just an (unusual) human name.
    assert _assignee_class("agent-a") == "human"
    assert _assignee_class(None) == "unassigned"


def test_by_assignee_class_is_a_ratio_of_sums_not_an_average_of_ratios():
    # One big/slow card (12pts/6days = 2 pts/day) and one small/fast card
    # (1pt/1day = 1 pt/day). An average of per-card ratios would read 1.5 pts/day;
    # the ratio-of-sums this function actually computes reads 13pts/7days ≈ 1.857 —
    # the big card isn't outvoted by the fast one.
    transitions = [
        (1, "in_progress", _ago(days=6)),
        (1, "done", NOW),
        (2, "in_progress", _ago(days=1)),
        (2, "done", NOW),
    ]
    cards = [
        _card(1, "done", assignee="agent:claude", story_points=12),
        _card(2, "done", assignee="agent:claude", story_points=1),
    ]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    agent = next(r for r in m["by_assignee_class"] if r["assignee_class"] == "agent")
    assert agent["n"] == 2
    assert agent["points_per_day"] == 13 / 7


def test_by_assignee_class_splits_agent_human_unassigned_and_omits_the_rest():
    transitions = [
        (1, "in_progress", _ago(days=1)),
        (1, "done", NOW),
        (2, "in_progress", _ago(days=2)),
        (2, "done", NOW),
        (3, "in_progress", _ago(days=1)),
        (3, "done", NOW),
    ]
    cards = [
        _card(1, "done", assignee="agent:claude", story_points=6),
        _card(2, "done", assignee="alice@example.com", story_points=4),
        # No story_points at all: excluded from the rate but not throughput.
        _card(3, "done", assignee="agent:claude", story_points=None),
    ]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    by_class = {row["assignee_class"]: row for row in m["by_assignee_class"]}
    assert by_class["agent"] == {"assignee_class": "agent", "points_per_day": 6.0, "n": 1}
    assert by_class["human"] == {"assignee_class": "human", "points_per_day": 2.0, "n": 1}
    # No unassigned/eligible card in this fixture — the class is omitted, not zeroed.
    assert "unassigned" not in by_class
    # Sample size still one card, even though card 3 contributed no points.
    assert m["throughput"] == 3


def test_by_assignee_class_excludes_cards_without_a_recorded_cycle_time():
    # Straight todo → done (no in_progress): eligible for throughput, not the rate,
    # mirroring cycle_time's own exclusion rule exactly.
    transitions = [(1, "done", _ago(hours=1))]
    cards = [_card(1, "done", assignee="agent:claude", story_points=5)]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    assert m["throughput"] == 1
    assert m["by_assignee_class"] == []


def test_by_assignee_class_unassigned_bucket():
    transitions = [(1, "in_progress", _ago(days=1)), (1, "done", NOW)]
    cards = [_card(1, "done", assignee=None, story_points=3)]
    m = compute_metrics(transitions, cards, now=NOW, since=None)
    assert m["by_assignee_class"] == [
        {"assignee_class": "unassigned", "points_per_day": 3.0, "n": 1}
    ]
