"""API tests for the epic project fields target_date + lead (V31, KAN-295).

Additive, back-compatible fields on the epic entity: an optional ``target_date``
(timestamptz) and an optional free-text ``lead``. Covers set/read/clear for each,
plus back-compat (an epic created without them reads NULL). Uses only the HTTP
client — per the suite convention any app-module imports go inside test bodies.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these run as the board-owning
    session user (claim-on-login owns the reset fixture's default board)."""
    return logged_in_client


def _create_epic(client, **fields):
    return client.post("/api/v1/epics", json={"name": "E", **fields})


# --- back-compat: existing epics read NULL ---------------------------------


def test_epic_without_project_fields_reads_null(client):
    body = _create_epic(client, name="Legacy").json()
    assert body["target_date"] is None
    assert body["lead"] is None
    # And the read path exposes both keys.
    fetched = client.get(f"/api/v1/epics/{body['id']}").json()
    assert fetched["target_date"] is None
    assert fetched["lead"] is None


# --- set on create ---------------------------------------------------------


def test_create_epic_with_project_fields(client):
    r = _create_epic(
        client, name="Q3 Launch", target_date="2026-09-01T00:00:00Z", lead="ada"
    )
    assert r.status_code == 201
    body = r.json()
    assert body["lead"] == "ada"
    assert body["target_date"] is not None
    assert body["target_date"].startswith("2026-09-01")


# --- set via update --------------------------------------------------------


def test_patch_sets_project_fields(client):
    epic = _create_epic(client, name="Before").json()
    assert epic["target_date"] is None and epic["lead"] is None
    r = client.patch(
        f"/api/v1/epics/{epic['id']}",
        json={"target_date": "2026-12-31T12:00:00Z", "lead": "grace"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["lead"] == "grace"
    assert body["target_date"].startswith("2026-12-31")


# --- clear via update ------------------------------------------------------


def test_patch_clears_project_fields(client):
    epic = _create_epic(
        client, name="Full", target_date="2026-09-01T00:00:00Z", lead="ada"
    ).json()
    assert epic["target_date"] is not None and epic["lead"] == "ada"
    r = client.patch(
        f"/api/v1/epics/{epic['id']}", json={"target_date": None, "lead": None}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["target_date"] is None
    assert body["lead"] is None


def test_patch_project_fields_independently(client):
    """Only the fields actually sent are applied (exclude_unset): setting lead
    alone leaves an existing target_date untouched."""
    epic = _create_epic(
        client, name="Partial", target_date="2026-09-01T00:00:00Z", lead="ada"
    ).json()
    r = client.patch(f"/api/v1/epics/{epic['id']}", json={"lead": "bob"})
    assert r.status_code == 200
    body = r.json()
    assert body["lead"] == "bob"
    # target_date left as-is (not cleared, since it wasn't in the PATCH body).
    assert body["target_date"] is not None
    assert body["target_date"].startswith("2026-09-01")


# --- validation ------------------------------------------------------------


def test_create_epic_rejects_over_long_lead(client):
    assert _create_epic(client, name="ok", lead="x" * 256).status_code == 422


def test_create_epic_rejects_bad_target_date(client):
    assert _create_epic(client, name="ok", target_date="not-a-date").status_code == 422
