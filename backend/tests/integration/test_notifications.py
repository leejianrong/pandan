"""API tests for the notification store + inbox (V37, KAN-301).

Covers the four emit-on-event call-sites — each fires **exactly one** notification
row for the board owner: (1) a card flagged ``needs_human``, (2) a card newly
``blocked`` by a dependency edge, (3) a linked PR's CI failing (the GitHub
auto-sync webhook path), and (4) a card being assigned — plus the inbox API:
``GET /notifications`` (all vs. unread), ``PATCH /notifications/{id}`` (mark read,
idempotent, flips ``read_at``), and owner-scoping (you never see — or can mark —
another user's notifications; someone else's id 404s).

Recipient design (V37): the recipient is always the **board owner**
(``board.owner_id``), a real ``User`` — which is why owner-scoping is trivial.

Per the suite convention, every ``import app.*`` lives inside a test/fixture body,
not at module top (the PR #17 collection-time trap).
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

CARDS = "/api/v1/cards"
BOARDS = "/api/v1/boards"
NOTIFS = "/api/v1/notifications"
WEBHOOK = "/api/v1/webhooks/github"
SECRET = "shhh-notify-secret"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


@pytest.fixture
def owner(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated; the session user claimed the default
    board on login, so they are its owner and the notification recipient."""
    return logged_in_client


def _card(client, title="T", **fields):
    r = client.post(CARDS, json={"title": title, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _notification_rows(kind=None):
    """Read notification rows straight from the DB (oldest-first), optionally
    filtered by kind. Returns a list of ORM ``Notification`` objects."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Notification

    with SessionLocal() as db:
        query = select(Notification).order_by(Notification.id)
        if kind is not None:
            query = query.where(Notification.kind == kind)
        return list(db.scalars(query).all())


# --- (1) needs_human --------------------------------------------------------


def test_needs_human_emits_exactly_one_notification(owner):
    card = _card(owner)
    r = owner.post(f"{CARDS}/{card['id']}/needs-human", json={"attention_note": "pick auth"})
    assert r.status_code == 200, r.text

    rows = _notification_rows(kind="needs_human")
    assert len(rows) == 1
    assert rows[0].card_id == card["id"]
    assert card["ticket_number"] in rows[0].body


def test_needs_human_reflag_does_not_emit_a_second(owner):
    card = _card(owner)
    owner.post(f"{CARDS}/{card['id']}/needs-human", json={})
    owner.post(f"{CARDS}/{card['id']}/needs-human", json={"attention_note": "again"})
    # Only the transition into needs-human emits — the second flag is a no-op.
    assert len(_notification_rows(kind="needs_human")) == 1


# --- (2) blocked ------------------------------------------------------------


def test_new_blocking_dependency_emits_exactly_one_notification(owner):
    blocked = _card(owner, title="blocked")
    blocker = _card(owner, title="blocker")  # default column todo → active blocker
    r = owner.post(
        f"{CARDS}/{blocked['id']}/dependencies", json={"blocker_id": blocker["id"]}
    )
    assert r.status_code == 201, r.text

    rows = _notification_rows(kind="blocked")
    assert len(rows) == 1
    assert rows[0].card_id == blocked["id"]
    assert blocker["ticket_number"] in rows[0].body


def test_second_blocker_on_already_blocked_card_does_not_re_emit(owner):
    blocked = _card(owner, title="blocked")
    b1 = _card(owner, title="b1")
    b2 = _card(owner, title="b2")
    owner.post(f"{CARDS}/{blocked['id']}/dependencies", json={"blocker_id": b1["id"]})
    owner.post(f"{CARDS}/{blocked['id']}/dependencies", json={"blocker_id": b2["id"]})
    # The card was already blocked when b2 was added → no second notification.
    assert len(_notification_rows(kind="blocked")) == 1


def test_done_blocker_does_not_block_and_does_not_emit(owner):
    blocked = _card(owner, title="blocked")
    blocker = _card(owner, title="blocker")
    # Move the blocker to done first — it no longer blocks, so no transition.
    owner.post(f"{CARDS}/{blocker['id']}/move", json={"column": "done"})
    owner.post(f"{CARDS}/{blocked['id']}/dependencies", json={"blocker_id": blocker["id"]})
    assert _notification_rows(kind="blocked") == []


# --- (3) ci_failed (GitHub auto-sync webhook) -------------------------------


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _send_webhook(client, event: str, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        WEBHOOK,
        content=body,
        headers={"X-GitHub-Event": event, "X-Hub-Signature-256": _sign(body)},
    )


def test_ci_failure_webhook_emits_exactly_one_notification(owner, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    card = _card(owner)  # first card of the test → KAN-1 (sequences reset per test)
    board_id = owner.get(BOARDS).json()[0]["id"]
    # The webhook only acts on autosync-enabled boards.
    assert owner.patch(f"{BOARDS}/{board_id}", json={"autosync_enabled": True}).status_code == 200

    ticket = card["ticket_number"]
    payload = {
        "check_suite": {
            "head_branch": f"feat/{ticket.lower()}-work",
            "status": "completed",
            "conclusion": "failure",
        }
    }
    assert _send_webhook(owner, "check_suite", payload).status_code == 200

    rows = _notification_rows(kind="ci_failed")
    assert len(rows) == 1
    assert rows[0].card_id == card["id"]
    assert ticket in rows[0].body


def test_ci_success_webhook_emits_nothing(owner, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    card = _card(owner)
    board_id = owner.get(BOARDS).json()[0]["id"]
    owner.patch(f"{BOARDS}/{board_id}", json={"autosync_enabled": True})

    payload = {
        "check_suite": {
            "head_branch": f"feat/{card['ticket_number'].lower()}-work",
            "status": "completed",
            "conclusion": "success",
        }
    }
    assert _send_webhook(owner, "check_suite", payload).status_code == 200
    assert _notification_rows(kind="ci_failed") == []


# --- (4) assigned -----------------------------------------------------------


def test_assigning_a_card_emits_exactly_one_notification(owner):
    card = _card(owner)
    r = owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
    assert r.status_code == 200, r.text

    rows = _notification_rows(kind="assigned")
    assert len(rows) == 1
    assert rows[0].card_id == card["id"]
    assert "agent:foo" in rows[0].body


def test_reassigning_same_assignee_does_not_re_emit(owner):
    card = _card(owner)
    owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
    owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})  # no change
    assert len(_notification_rows(kind="assigned")) == 1


def test_editing_other_fields_does_not_emit_assigned(owner):
    card = _card(owner)
    owner.patch(f"{CARDS}/{card['id']}", json={"title": "renamed"})
    assert _notification_rows(kind="assigned") == []


# --- inbox API: list / mark-read --------------------------------------------


def test_list_returns_own_notifications_newest_first(owner):
    c1 = _card(owner, title="one")
    c2 = _card(owner, title="two")
    owner.post(f"{CARDS}/{c1['id']}/needs-human", json={})
    owner.post(f"{CARDS}/{c2['id']}/needs-human", json={})

    rows = owner.get(NOTIFS).json()
    assert len(rows) == 2
    # Newest-first (descending id): c2's notification precedes c1's.
    assert rows[0]["card_id"] == c2["id"]
    assert rows[1]["card_id"] == c1["id"]
    assert rows[0]["read_at"] is None


def test_mark_read_flips_read_at_and_unread_filter(owner):
    card = _card(owner)
    owner.post(f"{CARDS}/{card['id']}/needs-human", json={})
    nid = owner.get(NOTIFS).json()[0]["id"]

    # Unread filter shows it; then mark it read.
    assert len(owner.get(NOTIFS, params={"unread": True}).json()) == 1
    r = owner.patch(f"{NOTIFS}/{nid}")
    assert r.status_code == 200, r.text
    assert r.json()["read_at"] is not None

    # It drops out of the unread list but stays in the full list.
    assert owner.get(NOTIFS, params={"unread": True}).json() == []
    assert len(owner.get(NOTIFS).json()) == 1


def test_mark_read_is_idempotent(owner):
    card = _card(owner)
    owner.post(f"{CARDS}/{card['id']}/needs-human", json={})
    nid = owner.get(NOTIFS).json()[0]["id"]

    first = owner.patch(f"{NOTIFS}/{nid}").json()["read_at"]
    second = owner.patch(f"{NOTIFS}/{nid}").json()["read_at"]
    assert first is not None and second == first  # timestamp untouched on re-mark


# --- owner-scoping ----------------------------------------------------------


def test_notifications_are_owner_scoped(login_as):
    alice = login_as(*ALICE)  # first login claims the default board → alice owns it
    bob = login_as(*BOB)

    card = _card(alice)
    alice.post(f"{CARDS}/{card['id']}/needs-human", json={})

    # Alice sees her notification; Bob (a different user) sees none of it.
    alice_rows = alice.get(NOTIFS).json()
    assert len(alice_rows) == 1
    assert bob.get(NOTIFS).json() == []

    # Bob cannot mark Alice's notification read — 404 (never reveal it exists).
    nid = alice_rows[0]["id"]
    assert bob.patch(f"{NOTIFS}/{nid}").status_code == 404
    # And Alice's stays unread.
    assert alice.get(NOTIFS).json()[0]["read_at"] is None


def test_notifications_require_auth(client):
    assert client.get(NOTIFS).status_code == 401
