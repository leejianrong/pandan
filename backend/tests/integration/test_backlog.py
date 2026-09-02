"""API tests for the backlog (M8 V56, KAN-977).

The backlog itself is *derived* (``cycle_id IS NULL``, SHAPING D8) — there is no
stored "backlog" state to test beyond the ``backlog`` list filter. ``parked`` is
the one real column this slice adds: a plain, independent boolean marking a card
*deliberately* parked, distinct from simply not yet scheduled. Covers: the
default, create/update, the null-rejection guard, and both list filters
(``backlog``/``parked``) alone and combined.

Per the suite convention, any app-module imports go inside test bodies, not at
module top (the PR #17 trap).
"""
from __future__ import annotations

import pytest

CARDS = "/api/v1/cards"


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these tests run as the
    board-owning session user (claim-on-login gives them the default board, id=1)."""
    return logged_in_client


def _card(client, title="T", **fields):
    r = client.post(CARDS, json={"title": title, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _cycles(board_id: int = 1) -> str:
    return f"/api/v1/boards/{board_id}/cycles"


def _cycle(client, name="Sprint 1"):
    r = client.post(_cycles(), json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


# --- the parked column --------------------------------------------------------


def test_parked_defaults_to_false(client):
    card = _card(client, "unparked")
    assert card["parked"] is False


def test_create_with_parked_true(client):
    card = _card(client, "parked-from-birth", parked=True)
    assert card["parked"] is True


def test_update_toggles_parked(client):
    card = _card(client, "toggle")
    updated = client.patch(f"{CARDS}/{card['id']}", json={"parked": True})
    assert updated.status_code == 200
    assert updated.json()["parked"] is True
    unparked = client.patch(f"{CARDS}/{card['id']}", json={"parked": False})
    assert unparked.status_code == 200
    assert unparked.json()["parked"] is False


def test_update_rejects_explicit_null_parked(client):
    # A NOT NULL boolean has no "clear to null" meaning — same guard as
    # CycleUpdate.name / LabelUpdate.
    card = _card(client, "no-null")
    r = client.patch(f"{CARDS}/{card['id']}", json={"parked": None})
    assert r.status_code == 422


def test_update_omitting_parked_leaves_it_unchanged(client):
    card = _card(client, "leave-alone", parked=True)
    updated = client.patch(f"{CARDS}/{card['id']}", json={"title": "renamed"})
    assert updated.status_code == 200
    assert updated.json()["parked"] is True


# --- list filters -------------------------------------------------------------


def test_filter_backlog(client):
    cycle = _cycle(client)
    _card(client, "scheduled", cycle_id=cycle["id"])
    _card(client, "unscheduled")
    r = client.get(CARDS, params={"backlog": "true"})
    assert {c["title"] for c in r.json()} == {"unscheduled"}
    r = client.get(CARDS, params={"backlog": "false"})
    assert {c["title"] for c in r.json()} == {"scheduled"}


def test_filter_parked(client):
    _card(client, "parked", parked=True)
    _card(client, "unparked", parked=False)
    r = client.get(CARDS, params={"parked": "true"})
    assert {c["title"] for c in r.json()} == {"parked"}
    r = client.get(CARDS, params={"parked": "false"})
    assert {c["title"] for c in r.json()} == {"unparked"}


def test_filter_backlog_and_parked_combine(client):
    # The two axes are independent (SHAPING/SLICES V56): scheduled-but-parked and
    # unscheduled-but-not-parked must not satisfy backlog=true&parked=true.
    cycle = _cycle(client)
    _card(client, "scheduled-parked", cycle_id=cycle["id"], parked=True)
    _card(client, "unscheduled-parked", parked=True)
    _card(client, "unscheduled-unparked", parked=False)
    r = client.get(CARDS, params={"backlog": "true", "parked": "true"})
    assert {c["title"] for c in r.json()} == {"unscheduled-parked"}
