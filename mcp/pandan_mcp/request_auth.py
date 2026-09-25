"""Per-request bearer-token override for the hosted Streamable HTTP transport
(ADR 0025, KAN-1732).

The stdio server (the only transport before this slice) is **one process per
user**: a single `PANDAN_TOKEN` env var, read once, good for the process's
whole lifetime — exactly what :func:`pandan_mcp.server._client_instance`'s
module-level singleton assumes. The hosted transport is the opposite shape:
**one process serving every caller**, so the credential has to come from each
individual HTTP request instead.

This module is the seam between the two. `backend/app/mcp_host.py`'s auth
middleware (which validates the caller's bearer against `personal_access_token`
— the same table and lookup `app.authz._resolve_pat` already uses for
`/api/v1`, since an OAuth-issued token is a `personal_access_token` row too,
ADR 0026) calls :func:`set_request_token` once it knows the token is valid, for
the duration of that one HTTP request; `_client_instance` reads it via
:func:`get_request_token` and builds a **fresh, per-request** `PandanClient`
from it instead of touching the stdio singleton.

A ``contextvars.ContextVar`` rather than a global: Starlette/ASGI serves
concurrent requests as concurrent asyncio tasks, and a context var's value is
task-local, so two hosted requests in flight at once never see each other's
token — the same isolation property a global would not have.
"""
from __future__ import annotations

from contextvars import ContextVar

_request_token: ContextVar[str | None] = ContextVar("_request_token", default=None)


def set_request_token(token: str) -> None:
    _request_token.set(token)


def get_request_token() -> str | None:
    return _request_token.get()


def clear_request_token() -> None:
    _request_token.set(None)
