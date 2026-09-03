"""API tests for the epic colour field (M8 V63, KAN-984, issue #278).

Additive, back-compatible field on the epic entity: an optional ``color`` drawn
from the same seven-token palette as ``label.color`` (V62, KAN-983) and validated
the same way (``app.palette.is_valid_label_color``) — see ``test_palette.py`` for
the palette's own sync/perceptual-distance coverage, not repeated here. Covers
set/read/clear, back-compat (an epic created without one reads NULL), and that
validation rejects the same things label.color rejects. Uses only the HTTP
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


def test_epic_without_color_reads_null(client):
    body = _create_epic(client, name="Legacy").json()
    assert body["color"] is None
    fetched = client.get(f"/api/v1/epics/{body['id']}").json()
    assert fetched["color"] is None


# --- set on create ----------------------------------------------------------


def test_create_epic_with_palette_token_color(client):
    r = _create_epic(client, name="Checkout Revamp", color="fuchsia")
    assert r.status_code == 201
    assert r.json()["color"] == "fuchsia"


def test_create_epic_with_hex_color(client):
    """The hex branch exists for the same reason label.color has one — see
    palette.py — even though the SPA only ever offers the seven tokens."""
    r = _create_epic(client, name="Checkout Revamp", color="#0ea5e9")
    assert r.status_code == 201
    assert r.json()["color"] == "#0ea5e9"


def test_create_epic_rejects_unknown_color(client):
    r = _create_epic(client, name="Checkout Revamp", color="banana")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("palette token" in str(e.get("msg", e)) for e in detail)


# --- set / clear via update --------------------------------------------------


def test_patch_sets_color(client):
    epic = _create_epic(client, name="Before").json()
    assert epic["color"] is None
    r = client.patch(f"/api/v1/epics/{epic['id']}", json={"color": "sky"})
    assert r.status_code == 200
    assert r.json()["color"] == "sky"


def test_patch_clears_color(client):
    """Unlike label.color (LabelUpdate rejects an explicit null outright), an
    epic's color is genuinely optional — null is a real, permanent value here."""
    epic = _create_epic(client, name="Colored", color="pink").json()
    assert epic["color"] == "pink"
    r = client.patch(f"/api/v1/epics/{epic['id']}", json={"color": None})
    assert r.status_code == 200
    assert r.json()["color"] is None


def test_patch_color_independently_of_other_fields(client):
    """Only the fields actually sent are applied (exclude_unset): setting color
    alone leaves an existing name untouched, and vice versa."""
    epic = _create_epic(client, name="Partial", color="cyan").json()
    r = client.patch(f"/api/v1/epics/{epic['id']}", json={"name": "Renamed"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renamed"
    assert body["color"] == "cyan"  # not sent, so left as-is


def test_patch_rejects_unknown_color(client):
    epic = _create_epic(client, name="E").json()
    r = client.patch(f"/api/v1/epics/{epic['id']}", json={"color": "banana"})
    assert r.status_code == 422
    # And the rejected PATCH must not have applied any part of itself.
    assert client.get(f"/api/v1/epics/{epic['id']}").json()["color"] is None
