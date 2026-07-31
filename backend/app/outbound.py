"""Signed outbound webhook (V38, KAN-302) — best-effort, post-commit delivery.

When a board opts in (``board.outbound_webhook_enabled`` + a ``outbound_webhook_url``),
every notification the write path creates is POSTed to that URL as a small signed JSON
payload. The signature MIRRORS the inbound GitHub webhook exactly
(``X-Hub-Signature-256: sha256=<hexdigest>`` over the raw body, HMAC-SHA256 keyed on the
board's ``outbound_webhook_secret``; see :mod:`app.webhook_signing`), so a downstream
receiver — email/Slack/automation glue — verifies our POST the same way we verify
GitHub's inbound one. That powers those integrations without bespoke server code.

**Ordering is the crux (and why this module exists).** :func:`app.notifications.record_notification`
only ``db.add``s the row — the caller commits it later, IN THE SAME TRANSACTION as the
mutation that triggered it, and that transaction may still roll back. So we must NOT POST
inside ``record_notification`` (we'd fire a webhook for a notification that never
persisted, and we'd hold the DB transaction open across a network call). Instead
``record_notification`` **queues** a delivery intent onto the session
(:func:`queue_delivery`); a single SQLAlchemy ``after_commit`` session event
(:func:`_dispatch_after_commit`) fires the queued POSTs only once the transaction has
durably committed. A failed/slow POST is swallowed and logged — it is **never** fatal to
the mutation (which is already committed and returned by the time we dispatch).

**No worker infra (MVP).** Delivery is synchronous best-effort within the request. To
bound the added latency: a short per-request ``timeout`` (a few seconds), an optional
small ``retries`` count with backoff (default 0 — the mechanism exists but stays off so a
dead target adds at most one timeout to the request), and a per-board minimum-interval
throttle so a burst of notifications can't hammer the target (the extras are dropped +
logged, not queued). All in-process, resetting on restart — the same accepted tradeoff as
the V27 rate limiter.

Config (env, all optional):
- ``OUTBOUND_WEBHOOK_TIMEOUT`` (default ``3.0``) — per-attempt HTTP timeout, seconds.
- ``OUTBOUND_WEBHOOK_RETRIES`` (default ``0``) — extra attempts after the first, on failure.
- ``OUTBOUND_WEBHOOK_MIN_INTERVAL`` (default ``1.0``) — per-board min seconds between
  deliveries; a delivery inside the window is skipped (best-effort). ``0`` disables it.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import Notification
from .webhook_signing import SIGNATURE_HEADER, sign

logger = logging.getLogger("app.outbound")

# The event name carried in the payload + a dedicated header, so a receiver can route.
EVENT_TYPE = "notification.created"
EVENT_HEADER = "X-Kanban-Event"

# Key under which a session stashes its queued delivery intents (list of
# ``(notification, url, secret)``), consumed by the after_commit listener.
_SESSION_KEY = "_kanban_outbound_pending"

# Backoff base for the optional retry loop (seconds); attempt N waits base * 2**N.
_BACKOFF_BASE = 0.2

# Per-board last-dispatch clock (monotonic seconds), for the min-interval throttle.
# In-process only, resets on restart (accepted MVP tradeoff, mirrors app.ratelimit).
_last_sent: dict[int, float] = {}


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value >= 0 else default


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value >= 0 else default


def queue_delivery(db: Session, notification: Notification, board) -> None:
    """Queue a signed POST for ``notification`` to be sent AFTER ``db`` commits.

    Called by :func:`app.notifications.record_notification` right after it adds the
    row. No-op unless the board opted in (``outbound_webhook_enabled`` and a
    ``outbound_webhook_url`` are both set) — so a board that hasn't turned the webhook
    on fires nothing (the opt-in gate). Never sends here: the row isn't committed yet.
    """
    if not (board.outbound_webhook_enabled and board.outbound_webhook_url):
        return
    pending = db.info.setdefault(_SESSION_KEY, [])
    pending.append(
        (notification, board.outbound_webhook_url, board.outbound_webhook_secret or "")
    )


def _build_payload(notification: Notification) -> dict:
    """The small JSON body we sign + send. ``created_at`` is read from the committed
    row (falling back to now() if unavailable — delivery is best-effort)."""
    created = getattr(notification, "created_at", None)
    if isinstance(created, datetime):
        created_at = created.astimezone(timezone.utc).isoformat()
    else:
        created_at = datetime.now(timezone.utc).isoformat()
    return {
        "event": EVENT_TYPE,
        "notification": {
            "id": notification.id,
            "kind": notification.kind,
            "body": notification.body,
            "board_id": notification.board_id,
            "card_id": notification.card_id,
            "created_at": created_at,
        },
    }


def _post(url: str, body: bytes, headers: dict[str, str]) -> None:
    """POST ``body`` with a short timeout and an optional bounded retry/backoff.

    Swallows every error (network, timeout, non-2xx) — outbound delivery is
    best-effort and must never surface to the caller. Logs each outcome.
    """
    retries = _int_env("OUTBOUND_WEBHOOK_RETRIES", 0)
    timeout = _float_env("OUTBOUND_WEBHOOK_TIMEOUT", 3.0)
    attempt = 0
    while True:
        try:
            resp = httpx.post(url, content=body, headers=headers, timeout=timeout)
            resp.raise_for_status()
            logger.info(
                "outbound webhook delivered url=%s status=%s attempt=%d",
                url,
                resp.status_code,
                attempt + 1,
            )
            return
        except Exception as exc:  # noqa: BLE001 — best-effort, swallow everything
            if attempt >= retries:
                logger.warning(
                    "outbound webhook failed url=%s attempts=%d: %s",
                    url,
                    attempt + 1,
                    exc,
                )
                return
            time.sleep(_BACKOFF_BASE * (2**attempt))
            attempt += 1


def _deliver(notification: Notification, url: str, secret: str) -> None:
    """Throttle-check, build, sign, and POST one notification (best-effort)."""
    board_id = notification.board_id
    interval = _float_env("OUTBOUND_WEBHOOK_MIN_INTERVAL", 1.0)
    if interval > 0:
        now = time.monotonic()
        last = _last_sent.get(board_id)
        if last is not None and (now - last) < interval:
            logger.info(
                "outbound webhook throttled board=%s (min interval %.2fs)",
                board_id,
                interval,
            )
            return
        _last_sent[board_id] = now

    payload = _build_payload(notification)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        EVENT_HEADER: EVENT_TYPE,
        SIGNATURE_HEADER: sign(secret, body),
    }
    _post(url, body, headers)


@event.listens_for(Session, "after_commit")
def _dispatch_after_commit(session: Session) -> None:
    """Fire the session's queued outbound POSTs, once its transaction has committed.

    Registered process-wide on the ORM ``Session`` class (importing this module wires
    it up). A no-op for any session that queued nothing (the common case). Every
    delivery is individually guarded so one failure can't stop the others — and, being
    post-commit, none of it can roll back or block the already-committed mutation.
    """
    pending = session.info.pop(_SESSION_KEY, None)
    if not pending:
        return
    for notification, url, secret in pending:
        try:
            _deliver(notification, url, secret)
        except Exception:  # noqa: BLE001 — never let delivery break the request
            logger.exception("outbound webhook delivery raised (non-fatal)")
