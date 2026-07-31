"""API tests for the signed outbound webhook (V38, KAN-302).

Covers the whole slice end-to-end against a real Postgres + a real local HTTP
receiver:

- **signature correctness** — an opted-in board fires a signed POST on
  notification-create; a receiver recomputing the HMAC over the raw body with the
  board's secret matches the ``X-Hub-Signature-256`` header, and the payload carries
  the notification fields.
- **opt-in gating** — disabled (or no URL) fires **no** POST.
- **failure is non-fatal** — a dead/500 target does not break or roll back the
  mutation, and the notification row still persists.
- **write-only secret** — ``outbound_webhook_secret`` is accepted on PATCH but never
  returned in a board read (``outbound_webhook_url`` + ``enabled`` are).

The outbound POST is dispatched synchronously in the request thread (an
``after_commit`` session event), so by the time a mutation's response returns the
receiver has already captured the delivery — no polling/sleeping needed.

Per the suite convention, every ``import app.*`` lives inside a test/fixture body.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

CARDS = "/api/v1/cards"
BOARDS = "/api/v1/boards"
SECRET = "outbound-board-secret"


# --- a local HTTP receiver --------------------------------------------------


class _Receiver:
    """A tiny threaded HTTP server that captures the POSTs it receives.

    ``status`` controls the response code (500 to exercise the failure path)."""

    def __init__(self, status: int = 200):
        self.requests: list[dict] = []
        self._status = status
        received = self.requests
        resp_status = status

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                received.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "raw": raw,
                    }
                )
                self.send_response(resp_status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):  # silence the default stderr logging
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hook"

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def receiver():
    r = _Receiver()
    try:
        yield r
    finally:
        r.close()


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """Disable the per-board min-interval throttle so deliveries are deterministic
    across tests (board id resets to 1 each test, so a >0 interval would coalesce)."""
    monkeypatch.setenv("OUTBOUND_WEBHOOK_MIN_INTERVAL", "0")
    monkeypatch.setenv("OUTBOUND_WEBHOOK_TIMEOUT", "3")


@pytest.fixture
def owner(logged_in_client):
    """The session user owns the default board (claimed on login) — the recipient."""
    return logged_in_client


def _card(client, title="T", **fields):
    r = client.post(CARDS, json={"title": title, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _configure_webhook(client, board_id, **fields):
    r = client.patch(f"{BOARDS}/{board_id}", json=fields)
    assert r.status_code == 200, r.text
    return r.json()


def _notification_rows():
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Notification

    with SessionLocal() as db:
        return list(db.scalars(select(Notification).order_by(Notification.id)).all())


# --- signature correctness --------------------------------------------------


def test_enabled_board_fires_a_correctly_signed_post(owner, receiver):
    board_id = owner.get(BOARDS).json()[0]["id"]
    _configure_webhook(
        owner,
        board_id,
        outbound_webhook_url=receiver.url,
        outbound_webhook_secret=SECRET,
        outbound_webhook_enabled=True,
    )
    card = _card(owner)

    # Assigning a card emits exactly one "assigned" notification → one signed POST.
    r = owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
    assert r.status_code == 200, r.text

    assert len(receiver.requests) == 1
    req = receiver.requests[0]
    raw = req["raw"]

    # Signature: what the receiver recomputes must equal the header we sent.
    expected = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert req["headers"]["x-hub-signature-256"] == expected
    assert req["headers"]["content-type"] == "application/json"
    assert req["headers"]["x-kanban-event"] == "notification.created"

    # Payload shape.
    payload = json.loads(raw)
    assert payload["event"] == "notification.created"
    n = payload["notification"]
    assert n["kind"] == "assigned"
    assert n["board_id"] == board_id
    assert n["card_id"] == card["id"]
    assert card["ticket_number"] in n["body"]
    assert n["created_at"]  # a real ISO timestamp from the committed row


def test_signature_is_rejected_under_the_wrong_secret(owner, receiver):
    """Negative control: verifying with a different secret must fail — proving the
    signature is a real HMAC over the body keyed on the board's secret."""
    board_id = owner.get(BOARDS).json()[0]["id"]
    _configure_webhook(
        owner,
        board_id,
        outbound_webhook_url=receiver.url,
        outbound_webhook_secret=SECRET,
        outbound_webhook_enabled=True,
    )
    card = _card(owner)
    owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})

    raw = receiver.requests[0]["raw"]
    wrong = "sha256=" + hmac.new(b"not-the-secret", raw, hashlib.sha256).hexdigest()
    assert receiver.requests[0]["headers"]["x-hub-signature-256"] != wrong


# --- opt-in gating ----------------------------------------------------------


def test_disabled_board_fires_no_post(owner, receiver):
    board_id = owner.get(BOARDS).json()[0]["id"]
    # URL + secret set, but enabled stays False → no delivery.
    _configure_webhook(
        owner,
        board_id,
        outbound_webhook_url=receiver.url,
        outbound_webhook_secret=SECRET,
        outbound_webhook_enabled=False,
    )
    card = _card(owner)
    r = owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
    assert r.status_code == 200

    assert receiver.requests == []
    # The notification still persisted — only the outbound delivery is gated.
    assert len(_notification_rows()) == 1


def test_enabled_but_no_url_fires_no_post(owner, receiver):
    board_id = owner.get(BOARDS).json()[0]["id"]
    _configure_webhook(owner, board_id, outbound_webhook_enabled=True)  # no URL
    card = _card(owner)
    owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
    assert receiver.requests == []


# --- failure is non-fatal ---------------------------------------------------


def test_failed_delivery_is_non_fatal_to_the_mutation(owner):
    """A dead target (connection refused) must not break the mutation nor roll back
    the notification. Point at a closed port and assign a card."""
    board_id = owner.get(BOARDS).json()[0]["id"]
    _configure_webhook(
        owner,
        board_id,
        outbound_webhook_url="http://127.0.0.1:1/hook",  # nothing listens here
        outbound_webhook_secret=SECRET,
        outbound_webhook_enabled=True,
    )
    card = _card(owner)

    r = owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
    assert r.status_code == 200, r.text  # mutation succeeded despite the dead webhook

    rows = _notification_rows()
    assert len(rows) == 1  # notification committed, not rolled back
    assert rows[0].kind == "assigned"


def test_500_response_is_non_fatal(owner):
    board_id = owner.get(BOARDS).json()[0]["id"]
    failing = _Receiver(status=500)
    try:
        _configure_webhook(
            owner,
            board_id,
            outbound_webhook_url=failing.url,
            outbound_webhook_secret=SECRET,
            outbound_webhook_enabled=True,
        )
        card = _card(owner)
        r = owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
        assert r.status_code == 200, r.text
        # The receiver got the POST (a 500 back), and the mutation still succeeded.
        assert len(failing.requests) == 1
        assert len(_notification_rows()) == 1
    finally:
        failing.close()


# --- write-only secret ------------------------------------------------------


def test_secret_is_write_only_but_url_and_flag_are_readable(owner):
    board_id = owner.get(BOARDS).json()[0]["id"]
    patched = _configure_webhook(
        owner,
        board_id,
        outbound_webhook_url="https://example.com/hook",
        outbound_webhook_secret=SECRET,
        outbound_webhook_enabled=True,
    )
    # Neither the PATCH response nor a subsequent GET ever leaks the secret.
    assert "outbound_webhook_secret" not in patched
    assert patched["outbound_webhook_url"] == "https://example.com/hook"
    assert patched["outbound_webhook_enabled"] is True

    got = owner.get(f"{BOARDS}/{board_id}").json()
    assert "outbound_webhook_secret" not in got
    assert got["outbound_webhook_url"] == "https://example.com/hook"
    assert got["outbound_webhook_enabled"] is True

    listed = owner.get(BOARDS).json()[0]
    assert "outbound_webhook_secret" not in listed


def test_clearing_the_url_via_null_disables_delivery(owner, receiver):
    board_id = owner.get(BOARDS).json()[0]["id"]
    _configure_webhook(
        owner,
        board_id,
        outbound_webhook_url=receiver.url,
        outbound_webhook_secret=SECRET,
        outbound_webhook_enabled=True,
    )
    # Explicit null clears the URL (the raw API accepts it), so nothing dispatches.
    cleared = _configure_webhook(owner, board_id, outbound_webhook_url=None)
    assert cleared["outbound_webhook_url"] is None

    card = _card(owner)
    owner.patch(f"{CARDS}/{card['id']}", json={"assignee": "agent:foo"})
    assert receiver.requests == []
