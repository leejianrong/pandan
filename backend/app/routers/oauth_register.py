"""RFC 7591 Dynamic Client Registration (ADR 0025/0026, KAN-1734).

One route: ``POST /auth/register``, no auth — the whole point is obtaining a
first client identity, the same asymmetry ``/auth/device/code``/``/auth/device/token``
already have (ADR 0024). See ``app/oauth_client.py`` for the registration logic
itself and why this backend also supports the newer Client ID Metadata Document
mechanism alongside it.

**Mounted at ``/auth``, not ``/api/v1``** — authentication infrastructure,
alongside ``/auth/device/*`` and ``/auth/github/*``, not a board-scoped
resource.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..oauth_client import InvalidClientMetadata, register_client
from ..schemas import ClientRegistrationRequest, ClientRegistrationResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _registration_error(error: str, description: str) -> JSONResponse:
    """The RFC 7591 §3.2.2 error body — ``{"error": ..., "error_description":
    ...}``, always ``400`` (RFC 7591 defines no other status for a registration
    failure)."""
    return JSONResponse(
        status_code=400, content={"error": error, "error_description": description}
    )


@router.post("/register", response_model=ClientRegistrationResponse, status_code=201)
def register(payload: ClientRegistrationRequest, db: Session = Depends(get_db)):
    if payload.token_endpoint_auth_method not in (None, "none"):
        return _registration_error(
            "invalid_client_metadata",
            "this server registers public clients only; "
            'token_endpoint_auth_method must be "none"',
        )

    try:
        client = register_client(
            db, redirect_uris=payload.redirect_uris, client_name=payload.client_name
        )
    except InvalidClientMetadata as exc:
        error = "invalid_redirect_uri" if "redirect_uri" in str(exc) else "invalid_client_metadata"
        return _registration_error(error, str(exc))

    return ClientRegistrationResponse(
        client_id=client.client_id,
        client_id_issued_at=int(client.created_at.timestamp()),
        redirect_uris=client.redirect_uris,
        client_name=client.client_name,
    )
