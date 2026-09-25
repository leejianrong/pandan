"""RFC 8628 Device Authorization Grant endpoints (ADR 0024, KAN-1727).

Two routes, neither behind ``get_principal`` — the whole point of the device
flow is letting a CLI with **no credential yet** obtain one:

- ``POST /auth/device/code`` — no auth. The CLI calls this first; returns a
  ``device_code`` (secret, polled with) and a ``user_code`` (short, human-typed
  fallback) plus where a human approves.
- ``POST /auth/device/token`` — no auth (the ``device_code`` itself is the
  credential). Polled at ``interval``-second intervals until the row resolves.

**Mounted at ``/auth/device``, not ``/api/v1``** — this is authentication
infrastructure, alongside ``/auth/github/*``, not a board-scoped resource.

**What is deliberately NOT here.** The consent screen's own backend surface — a
lookup of what a ``user_code`` is requesting, and approve/deny — is KAN-1729
(bundled with the SPA that is its only caller, per ADR 0005's "add the endpoint
first, then wire the UI to it" read the other way: nothing calls it yet). Until
then, a device_authorization row can only reach ``status = 'approved'`` by a
test inserting the row directly (mirroring how KAN-1728's board-scoping tests
predate KAN-1727/1729's own minting path) — this file's own tests do exactly
that to exercise the success path.

**The PAT is minted here, on the first successful poll after approval — not at
approval time.** ADR 0024 doesn't fix the exact moment; minting at approval time
would require holding the raw secret in ``device_authorization`` between
approval (in the browser) and retrieval (by the CLI's next poll), which is a
plaintext-secret-at-rest pattern this codebase avoids everywhere else (R7.1: a
PAT's raw form is returned once, at creation, and never stored). Minting at
first-poll-after-approval means the raw secret exists only in memory for the
one response that carries it, exactly like ``POST /api/v1/tokens`` already
works — a new minting *path* for an existing credential type (ADR 0024's own
framing), not a new storage pattern.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_models import DeviceAuthorization, PersonalAccessToken, PersonalAccessTokenBoard
from ..db import get_db
from ..device_flow import (
    DEVICE_CODE_TTL_SECONDS,
    DEVICE_POLL_INTERVAL_SECONDS,
    forget_poll_state,
    generate_device_code,
    generate_user_code,
    too_soon_to_poll,
)
from ..schemas import DeviceCodeRequest, DeviceCodeResponse, DeviceTokenRequest
from ..tokens import generate_token, hash_token

router = APIRouter(prefix="/auth/device", tags=["auth"])

# Retry budget for the astronomically unlikely user_code collision (~26 bits of
# entropy over an ever-growing but short-lived population) before giving up and
# surfacing a 500 rather than looping forever.
_USER_CODE_COLLISION_RETRIES = 5


def _oauth_error(error: str) -> JSONResponse:
    """The RFC 8628 / OAuth 2.0 error body — ``{"error": "<code>"}``, deliberately
    flat rather than this API's usual ``{"detail": ...}`` FastAPI default, because
    a spec-aware device-flow client (this repo's own CLI included, KAN-1730) reads
    the ``error`` field name verbatim. Always ``400`` — RFC 8628 §3.5 uses the
    token endpoint's ordinary error status for every one of these, unlike a
    board-API 401/403/404 split."""
    return JSONResponse(status_code=400, content={"error": error})


@router.post("/code", response_model=DeviceCodeResponse)
def create_device_code(
    payload: DeviceCodeRequest, request: Request, db: Session = Depends(get_db)
) -> DeviceCodeResponse:
    """Start a device-flow login. No auth — this is the entry point for a CLI
    that has no credential yet."""
    device_code = generate_device_code()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)

    # user_code has a UNIQUE constraint; retry (a fresh row each time, mirroring
    # create_board's own board-key collision retry) on the vanishingly unlikely
    # collision rather than letting it surface as a raw 500 from the commit.
    for attempt in range(_USER_CODE_COLLISION_RETRIES):
        row = DeviceAuthorization(
            device_code_hash=hash_token(device_code),
            user_code=generate_user_code(),
            requested_scope=payload.scope.value,
            requested_board_ids=payload.board_ids,
            expires_at=expires_at,
        )
        db.add(row)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if attempt == _USER_CODE_COLLISION_RETRIES - 1:
                raise
    db.refresh(row)

    base = str(request.base_url).rstrip("/")
    verification_uri = f"{base}/device"
    return DeviceCodeResponse(
        device_code=device_code,
        user_code=row.user_code,
        verification_uri=verification_uri,
        verification_uri_complete=f"{verification_uri}?user_code={row.user_code}",
        expires_in=DEVICE_CODE_TTL_SECONDS,
        interval=DEVICE_POLL_INTERVAL_SECONDS,
    )


@router.post("/token")
def poll_device_token(payload: DeviceTokenRequest, db: Session = Depends(get_db)):
    """Poll for the outcome of a device-flow login.

    Every "not a live, pending row" case (unknown code, expired, already
    redeemed) collapses to the same ``expired_token`` response — uniformly, so a
    stale poll can't be used to probe whether a code ever existed, matching this
    API's existing batch-read convention of not turning a lookup into an
    existence oracle."""
    row = db.scalars(
        select(DeviceAuthorization).where(
            DeviceAuthorization.device_code_hash == hash_token(payload.device_code)
        )
    ).first()
    if row is None:
        return _oauth_error("expired_token")
    if row.expires_at <= datetime.now(timezone.utc) or row.redeemed_at is not None:
        forget_poll_state(row.device_code_hash)
        return _oauth_error("expired_token")
    if too_soon_to_poll(row.device_code_hash):
        return _oauth_error("slow_down")
    if row.status == "denied":
        forget_poll_state(row.device_code_hash)
        return _oauth_error("access_denied")
    if row.status == "pending":
        return _oauth_error("authorization_pending")

    # status == "approved": mint the PAT now, on this first successful poll (see
    # the module docstring for why minting happens here and not at approval).
    raw, prefix, token_hash = generate_token()
    pat = PersonalAccessToken(
        user_id=row.user_id,
        name="Device flow login",
        token_hash=token_hash,
        token_prefix=prefix,
        scope=row.requested_scope,
    )
    db.add(pat)
    db.flush()  # assign pat.id before the board-scope rows / device_authorization FK
    for board_id in row.requested_board_ids or []:
        db.add(
            PersonalAccessTokenBoard(personal_access_token_id=pat.id, board_id=board_id)
        )
    row.pat_id = pat.id
    row.redeemed_at = datetime.now(timezone.utc)
    db.commit()
    forget_poll_state(row.device_code_hash)

    return {
        "token": raw,
        "id": pat.id,
        "name": pat.name,
        "token_prefix": pat.token_prefix,
        "scope": pat.scope,
        "created_at": pat.created_at,
    }
