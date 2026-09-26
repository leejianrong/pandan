"""RFC 8628 Device Authorization Grant endpoints (ADR 0024, KAN-1727/1729).

Five routes:

- ``POST /auth/device/code`` — no auth. The CLI calls this first; returns a
  ``device_code`` (secret, polled with) and a ``user_code`` (short, human-typed
  fallback) plus where a human approves.
- ``POST /auth/device/token`` — no auth (the credential itself, whichever grant
  presents one, is what authenticates the request). Polled at
  ``interval``-second intervals until the row resolves for RFC 8628 device-code
  polling; also, since ADR 0026 (KAN-1735), this is the one ``token_endpoint``
  every grant shares — ``grant_type=authorization_code`` (redeeming
  ``app/routers/oauth_authorize.py``'s consent-screen code) and
  ``grant_type=refresh_token`` (rotation) are handled by two helpers below,
  ``_exchange_authorization_code``/``_exchange_refresh_token``.
- ``GET /auth/device/{user_code}`` — **cookie/PAT auth required**
  (:func:`app.authz.get_principal`). The consent screen's own read: what scope
  and boards were requested, and the code's current status (so a re-visited
  link after already approving/denying reads as that state, not a mysterious
  404).
- ``POST /auth/device/{user_code}/approve`` — auth required. The human's final
  scope/board choice (pre-filled by the ``GET`` above, editable before
  submitting) mints nothing yet — see below for why.
- ``POST /auth/device/{user_code}/deny`` — auth required.

**Mounted at ``/auth/device``, not ``/api/v1``** — this is authentication
infrastructure, alongside ``/auth/github/*``, not a board-scoped resource. The
three consent routes still require a principal (unlike ``code``/``token``
above) because *approving* is an action only an authenticated human should be
able to take — the RFC 8628 asymmetry is "no credential to start," not "no
credential ever."

**The PAT is minted at first-poll-after-approval, not at approval time.** ADR
0024 doesn't fix the exact moment; minting at approval time would require
holding the raw secret in ``device_authorization`` between approval (in the
browser) and retrieval (by the CLI's next poll), which is a plaintext-secret-
at-rest pattern this codebase avoids everywhere else (R7.1: a PAT's raw form is
returned once, at creation, and never stored). So ``approve`` only stamps
``status``/``user_id`` and overwrites ``requested_scope``/``requested_board_ids``
with the human's final choice (approving is a fresh grant, not a diff against
the request) — ``poll_device_token`` does the actual minting, exactly like
``POST /api/v1/tokens`` already works elsewhere: a new minting *path* for an
existing credential type (ADR 0024's own framing), not a new storage pattern.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_models import (
    DeviceAuthorization,
    OAuthRefreshToken,
    PersonalAccessToken,
    PersonalAccessTokenBoard,
    User,
)
from ..authz import get_principal
from ..db import get_db
from ..device_flow import (
    DEVICE_CODE_TTL_SECONDS,
    DEVICE_POLL_INTERVAL_SECONDS,
    forget_poll_state,
    generate_device_code,
    generate_user_code,
    too_soon_to_poll,
)
from ..models import Board
from ..oauth_authorize import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    generate_refresh_token,
    verify_pkce,
)
from ..oauth_client import resolve_client
from ..schemas import (
    DeviceApproveRequest,
    DeviceAuthorizationRead,
    DeviceCodeRequest,
    DeviceCodeResponse,
)
from ..tokens import generate_token, hash_token

DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

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


async def _parse_token_request_body(request: Request) -> dict[str, str]:
    """Real OAuth clients (Claude.ai, ChatGPT, Cursor) POST RFC 6749 §4.1.3
    ``application/x-www-form-urlencoded`` bodies for ``authorization_code``/
    ``refresh_token`` — this repo's own CLI sends JSON instead (an accepted
    deviation, KAN-1727, since it's the only device-flow client). This endpoint
    is the one ``token_endpoint`` every grant shares
    (``app/oauth_server_metadata.py``), so it accepts either wire format rather
    than forcing every caller onto the CLI's own JSON convention."""
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        return {k: str(v) for k, v in form.items()}
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _mint_access_token(
    db: Session,
    *,
    user_id,
    name: str,
    scope: str,
    board_ids: list[int] | None,
    client_id: str,
) -> tuple[str, PersonalAccessToken, str]:
    """Mint a real ``personal_access_token`` (short-lived, unlike a Tokens-UI/
    device-flow PAT — see ``app.oauth_authorize``'s module docstring) plus a
    paired refresh token. Shared by the ``authorization_code`` exchange and the
    ``refresh_token`` rotation below, since both mint the same shape of
    credential."""
    raw, prefix, token_hash = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)
    pat = PersonalAccessToken(
        user_id=user_id,
        name=name,
        token_hash=token_hash,
        token_prefix=prefix,
        scope=scope,
        expires_at=expires_at,
    )
    db.add(pat)
    db.flush()  # assign pat.id before the board-scope / refresh-token FK rows
    for board_id in board_ids or []:
        db.add(PersonalAccessTokenBoard(personal_access_token_id=pat.id, board_id=board_id))

    refresh_raw = generate_refresh_token()
    refresh_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=REFRESH_TOKEN_TTL_SECONDS
    )
    db.add(
        OAuthRefreshToken(
            token_hash=hash_token(refresh_raw),
            personal_access_token_id=pat.id,
            client_id=client_id,
            expires_at=refresh_expires_at,
        )
    )
    return raw, pat, refresh_raw


def _exchange_authorization_code(body: dict, request: Request, db: Session) -> JSONResponse | dict:
    """``grant_type=authorization_code`` (ADR 0026, KAN-1735) — redeem the code
    ``POST /auth/authorize/approve`` minted. Response shape is RFC 6749 §5.1
    verbatim (``access_token``/``token_type``/...), unlike the device-code
    branch's CLI-specific shape below — this branch's caller is a real
    third-party OAuth client, not this repo's own CLI."""
    code = body.get("code")
    redirect_uri = body.get("redirect_uri")
    client_id = body.get("client_id")
    code_verifier = body.get("code_verifier")
    resource = body.get("resource")
    if not all([code, redirect_uri, client_id, code_verifier, resource]):
        return _oauth_error("invalid_request")

    row = db.scalars(
        select(DeviceAuthorization).where(DeviceAuthorization.code_hash == hash_token(code))
    ).first()
    # Every "not a live, redeemable row" case collapses to `invalid_grant`,
    # uniformly — same "don't turn a lookup into an oracle" convention the
    # device-code branch below already follows for `expired_token`.
    if row is None or row.expires_at <= datetime.now(timezone.utc) or row.redeemed_at is not None:
        return _oauth_error("invalid_grant")
    if row.client_id != client_id or row.redirect_uri != redirect_uri or row.resource != resource:
        return _oauth_error("invalid_grant")
    if not verify_pkce(code_verifier, row.code_challenge or ""):
        return _oauth_error("invalid_grant")

    client_name = None
    resolved = resolve_client(db, client_id)
    if resolved is not None:
        client_name = resolved.client_name

    raw, pat, refresh_raw = _mint_access_token(
        db,
        user_id=row.user_id,
        name=f"{client_name or 'OAuth client'} (authorization code)",
        scope=row.requested_scope,
        board_ids=row.requested_board_ids,
        client_id=client_id,
    )
    row.pat_id = pat.id
    row.redeemed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "access_token": raw,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token": refresh_raw,
        "scope": pat.scope,
    }


def _exchange_refresh_token(body: dict, db: Session) -> JSONResponse | dict:
    """``grant_type=refresh_token`` (ADR 0026, KAN-1735) — rotate: consume the
    presented refresh token, mint a fresh access token + a fresh refresh token
    carrying over the old one's scope/board allow-list. A second attempt to use
    the now-consumed refresh token fails (single-use rotation; see the
    ``OAuthRefreshToken`` model docstring for the theft-detection reasoning)."""
    refresh_token = body.get("refresh_token")
    client_id = body.get("client_id")
    if not refresh_token or not client_id:
        return _oauth_error("invalid_request")

    row = db.scalars(
        select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == hash_token(refresh_token))
    ).first()
    if row is None or row.expires_at <= datetime.now(timezone.utc) or row.consumed_at is not None:
        return _oauth_error("invalid_grant")
    if row.client_id != client_id:
        return _oauth_error("invalid_grant")

    old_pat = db.get(PersonalAccessToken, row.personal_access_token_id)
    if old_pat is None:
        return _oauth_error("invalid_grant")
    old_board_ids = db.scalars(
        select(PersonalAccessTokenBoard.board_id).where(
            PersonalAccessTokenBoard.personal_access_token_id == old_pat.id
        )
    ).all()

    raw, pat, refresh_raw = _mint_access_token(
        db,
        user_id=old_pat.user_id,
        name=old_pat.name,
        scope=old_pat.scope,
        board_ids=list(old_board_ids),
        client_id=client_id,
    )
    row.consumed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "access_token": raw,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token": refresh_raw,
        "scope": pat.scope,
    }


@router.post("/token")
async def poll_device_token(request: Request, db: Session = Depends(get_db)):
    """The one ``token_endpoint`` every grant this server issues shares
    (``app/oauth_server_metadata.py``): RFC 8628 device-code polling (below,
    unchanged since ADR 0024) plus the ``authorization_code``/``refresh_token``
    grants ADR 0026 adds (KAN-1735, delegated to the two helpers above)."""
    body = await _parse_token_request_body(request)
    grant_type = body.get("grant_type") or DEVICE_CODE_GRANT
    if grant_type == "authorization_code":
        return _exchange_authorization_code(body, request, db)
    if grant_type == "refresh_token":
        return _exchange_refresh_token(body, db)
    if grant_type != DEVICE_CODE_GRANT:
        return _oauth_error("unsupported_grant_type")

    device_code = body.get("device_code")
    if not device_code:
        return _oauth_error("invalid_request")

    # RFC 8628 device-code polling, unchanged since ADR 0024. Every "not a
    # live, pending row" case (unknown code, expired, already redeemed)
    # collapses to the same `expired_token` response — uniformly, so a stale
    # poll can't be used to probe whether a code ever existed, matching this
    # API's existing batch-read convention of not turning a lookup into an
    # existence oracle.
    row = db.scalars(
        select(DeviceAuthorization).where(
            DeviceAuthorization.device_code_hash == hash_token(device_code)
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


def _get_live_row_or_404(db: Session, user_code: str) -> DeviceAuthorization:
    """Load by ``user_code``, 404 for unknown **or expired** — a stale link reads
    as gone, not as a confusing 200 for a code that can never resolve. Unlike
    :func:`poll_device_token`'s uniform ``expired_token`` collapse, an
    *already-resolved* (approved/denied) row is NOT folded in here — the consent
    screen needs to render that state distinctly (e.g. "you already approved
    this"), so status is the caller's to branch on, not this helper's."""
    row = db.scalars(
        select(DeviceAuthorization).where(DeviceAuthorization.user_code == user_code)
    ).first()
    if row is None or row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found")
    return row


def _reject_unowned_boards(db: Session, principal: User, board_ids: list[int] | None) -> None:
    """403 if any of ``board_ids`` isn't a board the approving principal **owns**
    (deliberately narrower than ``authorize_board``'s READ-is-enough check — a
    consent screen granting board-scoped agent access should only ever be able
    to grant access to boards the approving human is the actual owner of, not
    boards merely shared with them). Uniform for an unknown board id too, same
    "can't point at what you can't touch" pattern as
    ``boards._reject_non_member_workspace``."""
    if not board_ids:
        return
    owned = set(
        db.scalars(
            select(Board.id).where(
                Board.id.in_(board_ids), Board.owner_id == principal.id
            )
        ).all()
    )
    not_owned = set(board_ids) - owned
    if not_owned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"you do not own board(s): {sorted(not_owned)}",
        )


@router.get("/{user_code}", response_model=DeviceAuthorizationRead)
def get_device_authorization(
    user_code: str,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> DeviceAuthorization:
    """The consent screen's own read: what was requested, and the code's current
    status. Requires an authenticated human/PAT (:func:`app.authz.get_principal`)
    — the ``code``/``token`` routes above are the only unauthenticated ones."""
    return _get_live_row_or_404(db, user_code)


@router.post("/{user_code}/approve", response_model=DeviceAuthorizationRead)
def approve_device_authorization(
    user_code: str,
    payload: DeviceApproveRequest,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> DeviceAuthorization:
    """Approve a pending device-flow login as the calling principal. Does **not**
    mint the PAT (see the module docstring) — it only records who approved it
    and with what final scope/board selection; ``poll_device_token`` mints on the
    CLI's next poll.

    409 if the code isn't `pending` anymore (already approved/denied is a state
    conflict, not a missing-resource or permission problem)."""
    row = _get_live_row_or_404(db, user_code)
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"this code was already {row.status}",
        )
    _reject_unowned_boards(db, principal, payload.board_ids)
    row.status = "approved"
    row.user_id = principal.id
    row.requested_scope = payload.scope.value
    row.requested_board_ids = payload.board_ids
    db.commit()
    db.refresh(row)
    return row


@router.post("/{user_code}/deny", status_code=status.HTTP_204_NO_CONTENT)
def deny_device_authorization(
    user_code: str,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Deny a pending device-flow login. 409 if it isn't `pending` anymore (same
    state-conflict reasoning as ``approve``)."""
    row = _get_live_row_or_404(db, user_code)
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"this code was already {row.status}",
        )
    row.status = "denied"
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
