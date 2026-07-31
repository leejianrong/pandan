"""Derived per-epic progress rollup + health signal (V32, KAN-296) — a pure
computation layer, in the spirit of :mod:`app.metrics`.

An epic's *progress* and *health* are **entirely derived** from data already
recorded elsewhere — the epic's ``target_date`` (V31, KAN-295) and the current
state of its child cards (``card.epic_id`` + ``card.column``, minus soft-deleted
rows). There is **no new write path and no migration**: the rollup rides existing
state and is recomputed on every read.

This module is pure (no DB, no I/O) so it unit-tests directly — the router does the
one grouped ``COUNT`` query and hands the totals here.

Progress
--------
``percent = round(done / total * 100)`` over the epic's **non-deleted** child cards,
where ``done`` counts cards in the ``done`` column. An epic with no children is
``0%`` (not a divide-by-zero) — see :func:`compute_rollup`.

Health rule (explicit, and its boundaries are tested)
-----------------------------------------------------
``health`` is a coarse RAG-style signal derived from ``target_date`` vs. the work
still outstanding. Let *remaining* mean "has >=1 unfinished child" (``total > 0 and
done < total``) and *now* be the (tz-aware) reference time:

- **null** — the epic has **no** ``target_date``. Nothing to be on-/off-track
  against, so no signal (the UI renders no pill).
- **on_track** — there is no remaining work (the epic is complete, or empty), **or**
  a ``target_date`` is set and still comfortably in the future.
- **overdue** — there **is** remaining work and ``now >= target_date`` (past the
  target with unfinished cards).
- **at_risk** — there is remaining work and the target is **near**: it hasn't passed
  yet but is within :data:`AT_RISK_WINDOW` from now.

Rationale for the thresholds: without a per-epic start date there's no meaningful
"expected linear burn-down" to compare against, so *near-and-unfinished* is the
honest proxy for "progress behind". The window default of **7 days** is one working
week of runway — enough warning to react. A **complete** epic (100%) is always
``on_track`` regardless of the date: shipped work can't be overdue. An **empty**
epic (no children) likewise has no remaining work, so it is ``on_track`` (never
``at_risk``/``overdue``) when a target is set.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, TypedDict

# How close (before the target) an epic with remaining work is flagged ``at_risk``.
# One working week of runway; see the module docstring for the rationale.
AT_RISK_WINDOW = timedelta(days=7)

Health = Literal["on_track", "at_risk", "overdue"]


class ProgressDict(TypedDict):
    total: int
    done: int
    percent: int


class RollupDict(TypedDict):
    progress: ProgressDict
    health: Health | None


def compute_rollup(
    total: int,
    done: int,
    target_date: datetime | None,
    *,
    now: datetime,
) -> RollupDict:
    """Compute an epic's derived progress + health — pure, no DB.

    ``total`` / ``done`` are counts over the epic's **non-deleted** child cards
    (``done`` = cards in the ``done`` column). ``target_date`` is the epic's optional
    ship date; ``now`` is the (tz-aware) reference clock. See the module docstring
    for the exact health rule and thresholds.
    """
    percent = round(done / total * 100) if total > 0 else 0
    remaining = total > 0 and done < total

    health: Health | None
    if target_date is None:
        health = None
    elif not remaining:
        # Complete (100%) or empty — nothing outstanding to be late on.
        health = "on_track"
    elif now >= target_date:
        health = "overdue"
    elif target_date - now <= AT_RISK_WINDOW:
        health = "at_risk"
    else:
        health = "on_track"

    return {
        "progress": {"total": total, "done": done, "percent": percent},
        "health": health,
    }
