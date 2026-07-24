"""GitHub webhook receiver (KAN-42) — foundation for auto-sync.

A single endpoint GitHub POSTs to. Its authentication is the **HMAC-SHA256
signature** over the raw request body (shared secret ``WEBHOOK_SECRET``), *not*
the cookie/PAT board authz the rest of ``/api/v1`` uses: webhooks come from
GitHub, not a logged-in user, so this route deliberately does **not** depend on
``get_principal``/``authorize_board`` (ADR 0013). It stays standalone.

KAN-42 established receive + verify + route (verify the signature, parse the
``X-GitHub-Event`` type + body, dispatch to a per-event handler, ack 200). KAN-43
fleshes out the handlers: each logs its structured summary **and** delegates to
:mod:`app.autosync`, which maps the event onto card work-links / comments / a move
to ``done`` — gated per board by the ``board.autosync_enabled`` opt-in (default
OFF). The signature check stays the only authentication; the opt-in flag is the
authorization for those writes (they act as the system, not a user).

Verification policy:
- ``WEBHOOK_SECRET`` unset → **503** (the receiver is not configured; we never
  skip verification silently).
- Missing / malformed / mismatched ``X-Hub-Signature-256`` → **401**.
- Unknown event types are acknowledged (**200**) and ignored.
"""
from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request, status

from .. import autosync
from ..webhook_signing import verify as verify_signature  # noqa: F401 (re-exported)

logger = logging.getLogger("app.webhooks.github")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Event types this receiver routes on. Anything else is acked (200) and ignored.
HANDLED_EVENTS = {"pull_request", "check_suite", "status"}

# ``verify_signature`` is the shared HMAC verifier (:mod:`app.webhook_signing`) — the
# SAME ``sha256=<hex>`` scheme the outbound signer (:mod:`app.outbound`) mirrors, so
# inbound-verify and outbound-sign stay in lockstep. Re-exported here under its
# historical name so the endpoint below (and its tests) read unchanged.


# --- per-event handlers ------------------------------------------------------
# Each handler logs a structured summary, then delegates the board side effects to
# :mod:`app.autosync`, which maps the event onto card work-links / comments / moves
# — gated per board by the ``autosync_enabled`` opt-in (KAN-43). The mapping layer
# parses the card ticket before touching the DB and no-ops when none is present, so
# a payload without a ``KAN-<n>`` opens no session (the unit tests stay DB-free).


def _handle_pull_request(payload: dict) -> None:
    pr = payload.get("pull_request") or {}
    logger.info(
        "webhook pull_request action=%s number=%s state=%s merged=%s title=%r",
        payload.get("action"),
        payload.get("number"),
        pr.get("state"),
        pr.get("merged"),
        pr.get("title"),
    )
    autosync.on_pull_request(payload)


def _handle_check_suite(payload: dict) -> None:
    suite = payload.get("check_suite") or {}
    logger.info(
        "webhook check_suite action=%s status=%s conclusion=%s head_sha=%s",
        payload.get("action"),
        suite.get("status"),
        suite.get("conclusion"),
        suite.get("head_sha"),
    )
    autosync.on_check_suite(payload)


def _handle_status(payload: dict) -> None:
    logger.info(
        "webhook status state=%s sha=%s context=%r",
        payload.get("state"),
        payload.get("sha"),
        payload.get("context"),
    )
    autosync.on_status(payload)


_DISPATCH = {
    "pull_request": _handle_pull_request,
    "check_suite": _handle_check_suite,
    "status": _handle_status,
}


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, object]:
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        # Misconfiguration, not a client auth failure — never skip verification.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook receiver is not configured (WEBHOOK_SECRET unset)",
        )

    raw = await request.body()
    if not verify_signature(secret, raw, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing signature",
        )

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not valid JSON",
        ) from exc

    event = x_github_event or ""
    handler = _DISPATCH.get(event)
    if handler is not None:
        handler(payload)
        return {"status": "ok", "event": event, "handled": True}

    logger.info("webhook ignored unknown event=%r", event)
    return {"status": "ok", "event": event, "handled": False}
