"""Shared card sort grammar (M5 V14, KAN-247).

The *filter* half of the query grammar lives inline in ``routers/cards.py``
(``list_cards``); this module owns the *sort* half so the SQL ordering has one
authoritative definition. The sortable field names + parsing live in
``schemas.py`` (``CARD_SORT_FIELDS`` / ``parse_sort_spec``, plain strings, no SQL)
so the ``CardQuery`` validator and this builder never disagree on what's valid;
here we map each validated field to the SQL expression to ``ORDER BY``.

``priority`` sorts by *rank* (none→urgent) via the same ``priority_rank_case`` the
dispatch selection uses, not alphabetically — so ``sort=-priority`` really is
"urgent first", matching agents' expectations.
"""
from __future__ import annotations

from typing import Any

from .models import Card
from .ordering import priority_rank_case
from .schemas import parse_sort_spec


def _sort_expressions() -> dict[str, Any]:
    """Public sort-field name → the SQL expression to order by. Built fresh per
    call because ``priority_rank_case()`` constructs a new ``CASE`` each time."""
    return {
        "position": Card.position,
        "priority": priority_rank_case(),
        "due_date": Card.due_date,
        "created_at": Card.created_at,
        "updated_at": Card.updated_at,
        "done_at": Card.done_at,
        "story_points": Card.story_points,
        "assignee": Card.assignee,
        "title": Card.title,
        "column": Card.column,
        "id": Card.id,
    }


def sort_order_by(sort: str) -> list[Any]:
    """The ``ORDER BY`` clauses for a validated ``sort`` spec.

    Each key becomes ``expr.asc()``/``expr.desc()`` with ``NULLS LAST`` in either
    direction (so cards missing the field always sink, never jump the top of a
    descending sort). A stable ``id ASC`` tiebreaker is appended unless ``id`` is
    already a key, so paging/ordering is deterministic. Raises ``ValueError`` on a
    bad field (via ``parse_sort_spec``) — the router maps that to a 422.
    """
    exprs = _sort_expressions()
    clauses: list[Any] = []
    seen: set[str] = set()
    for field, descending in parse_sort_spec(sort):
        col = exprs[field]
        ordered = col.desc() if descending else col.asc()
        clauses.append(ordered.nulls_last())
        seen.add(field)
    if "id" not in seen:
        clauses.append(Card.id.asc())
    return clauses
