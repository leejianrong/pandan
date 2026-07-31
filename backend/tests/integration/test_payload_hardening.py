"""Payload-hardening tests (V28, KAN-292).

Covers the additive limits from the ticket:
- An over-large request body → **413** (the Content-Length ceiling middleware in
  ``app.main``), rejected before the route runs.
- An over-long string field → **422** (per-field ``max_length`` in ``schemas.py``).
- An over-large batch / template array → **422** (array-length caps).
- Representative normal payloads are unaffected (well under every cap).

Per the suite convention, all ``app`` imports live inside test/fixture bodies so the
``_database`` fixture's ``DATABASE_URL`` override lands first (the PR #17 trap)."""
from __future__ import annotations

import pytest

CARDS = "/api/v1/cards"
BATCH = "/api/v1/cards/batch"
TEMPLATES = "/api/v1/boards/1/templates"


@pytest.fixture
def client(logged_in_client):
    """Run as the board-owning session user (/api/v1 is owner-gated, V8)."""
    return logged_in_client


# --- body-size ceiling ------------------------------------------------------


def test_oversized_body_rejected_413(client, monkeypatch):
    """A request whose Content-Length exceeds the ceiling is rejected 413 before the
    route runs. We lower the ceiling at runtime (the middleware reads the module
    global live) so the test stays fast rather than shipping megabytes."""
    from app import main

    monkeypatch.setattr(main, "MAX_REQUEST_BODY_BYTES", 500)
    # A body comfortably over 500 bytes — the 413 fires on Content-Length, before
    # any per-field validation (the description is itself under its max_length).
    resp = client.post(CARDS, json={"title": "x", "description": "y" * 2_000})
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


def test_normal_body_under_ceiling_passes(client):
    """A normal create is kilobytes — far below the (default ~2 MB) ceiling."""
    resp = client.post(CARDS, json={"title": "a normal card", "description": "hello"})
    assert resp.status_code == 201


# --- string caps ------------------------------------------------------------


def test_overlong_title_rejected_422(client):
    from app.schemas import MAX_TITLE_LEN

    resp = client.post(CARDS, json={"title": "t" * (MAX_TITLE_LEN + 1)})
    assert resp.status_code == 422


def test_overlong_description_rejected_422(client):
    from app.schemas import MAX_DESCRIPTION_LEN

    resp = client.post(
        CARDS, json={"title": "ok", "description": "d" * (MAX_DESCRIPTION_LEN + 1)}
    )
    assert resp.status_code == 422


def test_title_at_cap_passes(client):
    from app.schemas import MAX_TITLE_LEN

    resp = client.post(CARDS, json={"title": "t" * MAX_TITLE_LEN})
    assert resp.status_code == 201


# --- array caps -------------------------------------------------------------


def test_batch_over_cap_rejected_422(client):
    """A batch larger than MAX_BATCH_ITEMS is rejected before any card is fetched
    (so it's a cap 422, not a per-id 404 — distinct ids avoid the duplicate check)."""
    from app.schemas import MAX_BATCH_ITEMS

    payload = [{"id": i, "assignee": "x"} for i in range(1, MAX_BATCH_ITEMS + 2)]
    resp = client.patch(BATCH, json=payload)
    assert resp.status_code == 422
    assert str(MAX_BATCH_ITEMS) in resp.json()["detail"]


def test_normal_batch_passes(client):
    a = client.post(CARDS, json={"title": "a"}).json()
    b = client.post(CARDS, json={"title": "b"}).json()
    resp = client.patch(
        BATCH, json=[{"id": a["id"], "assignee": "z"}, {"id": b["id"], "assignee": "z"}]
    )
    assert resp.status_code == 200


def test_template_cards_over_cap_rejected_422(client):
    from app.schemas import MAX_TEMPLATE_CARDS

    cards = [{"title": f"c{i}"} for i in range(MAX_TEMPLATE_CARDS + 1)]
    resp = client.post(TEMPLATES, json={"name": "big", "cards": cards})
    assert resp.status_code == 422


def test_normal_template_passes(client):
    resp = client.post(
        TEMPLATES, json={"name": "small", "cards": [{"title": "one"}, {"title": "two"}]}
    )
    assert resp.status_code == 201
