"""Application rate limiting (V27, KAN-291) — a single classifying middleware.

Protects the sensitive/expensive endpoints against brute force + abuse:

- **auth** — ``POST /auth/login`` + the GitHub OAuth callback (credential brute force).
- **write** — every mutating ``/api/v1`` request (POST/PATCH/PUT/DELETE): card/epic/
  board/label/view/member/template writes, the card ``move``, board ``dispatch``, and
  ``POST /api/v1/tokens`` (PAT minting). All are non-safe methods under ``/api/v1``.
- **expensive** — the DB-heavy reads: full-text search (``GET /api/v1/cards?q=``) and
  board metrics (``GET /api/v1/boards/{id}/metrics``).
- **webhook** — ``POST /api/v1/webhooks/github`` (signature-authed, not owner-gated).

**Why a middleware and not slowapi decorators.** slowapi's ergonomics are per-route
decorators that need a ``request: Request`` in the endpoint signature. The two most
security-sensitive routes here — login and the OAuth callback — are *generated* by
fastapi-users (``get_auth_router`` / ``get_oauth_router``), so we cannot decorate them
cleanly, and decorating every ``/api/v1`` writer would churn dozens of signatures. A
single classifying middleware (the ticket's preferred shape) keeps ``main.py`` the
center of gravity and covers library-generated routes for free. We still ride slowapi:
its :class:`~slowapi.Limiter` holds the ``limits`` strategy + in-memory storage we call.

**Storage** is in-memory (``memory://``): single machine, resets on cold-start — the
accepted MVP tradeoff (KAN-291). No Redis, no cross-instance coordination.

**Keying.** On the **real Fly client IP** (the ``Fly-Client-IP`` header Fly's proxy
sets), *not* the raw ``X-Forwarded-For`` — the app runs uvicorn with
``--forwarded-allow-ips=*`` so XFF is caller-spoofable and must never be trusted for a
limit key. Falls back to ``request.client.host`` off-Fly (dev/tests). We also fold in a
cheap **principal hint** (a hash of the bearer PAT or the session cookie, no DB lookup)
so distinct agents behind one NAT IP get independent buckets.

**Config (env, all optional).** Defaults are generous so normal use — and the existing
test suite — never trips; tune per tier in prod:

- ``RATE_LIMIT_ENABLED`` — master switch. **Off unless truthy**, so dev + the test
  suite (which fire many requests from one client) are unaffected by default. Set it on
  in prod (a Fly secret/env) to turn protection on.
- ``RATE_LIMIT_AUTH`` (default ``"30/minute"``)
- ``RATE_LIMIT_WRITE`` (default ``"300/minute"``)
- ``RATE_LIMIT_EXPENSIVE`` (default ``"120/minute"``)
- ``RATE_LIMIT_WEBHOOK`` (default ``"240/minute"``)

Each value is any ``limits`` rate string (``"N/second|minute|hour|day"``). Over the
limit → **429** with a ``Retry-After`` header (seconds until the window frees up).
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from limits import RateLimitItem, parse
from slowapi import Limiter

logger = logging.getLogger("kanban.ratelimit")

# Tier → default limit string. Env vars ``RATE_LIMIT_<TIER>`` override each.
_DEFAULT_LIMITS: dict[str, str] = {
    "auth": "30/minute",
    "write": "300/minute",
    "expensive": "120/minute",
    "webhook": "240/minute",
}

_WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def classify(request: Request) -> str | None:
    """Map a request to its rate-limit tier, or ``None`` for unlimited routes.

    Ordering matters: the webhook and expensive-read tiers are checked before the
    generic ``/api/v1`` write catch-all (the webhook is itself a POST under
    ``/api/v1``; the expensive reads are GETs the write test would miss)."""
    path = request.url.path
    method = request.method

    # GitHub webhook — its own (looser) tier, checked before the write catch-all.
    if method == "POST" and path == "/api/v1/webhooks/github":
        return "webhook"

    if path.startswith("/api/v1"):
        # DB-expensive reads: full-text search + board metrics.
        if method == "GET":
            if path == "/api/v1/cards" and "q" in request.query_params:
                return "expensive"
            if path.endswith("/metrics"):
                return "expensive"
        # Every /api/v1 mutation: card/epic/board/label/view/member/template writes,
        # card move, board dispatch, POST /tokens — all non-safe methods.
        if method in _WRITE_METHODS:
            return "write"
        return None

    # Auth brute force: login + the OAuth callback (not logout, not authorize).
    if method == "POST" and path == "/auth/login":
        return "auth"
    if path == "/auth/github/callback":
        return "auth"

    return None


def client_ip(request: Request) -> str:
    """The trusted client IP to key on: Fly's ``Fly-Client-IP`` header, else the
    socket peer. **Never** the raw ``X-Forwarded-For`` — uvicorn runs
    ``--forwarded-allow-ips=*`` so XFF is spoofable and unsafe as a limit key."""
    fly = request.headers.get("fly-client-ip")
    if fly:
        return fly.strip()
    client = request.client
    return client.host if client is not None else "unknown"


def principal_hint(request: Request) -> str:
    """A cheap, DB-free discriminator for the acting principal, so two principals
    sharing one IP get separate buckets. Hashes the bearer PAT or the session
    cookie (never stored/logged in the clear); ``"anon"`` when neither is present."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return "t:" + hashlib.sha256(auth[7:].strip().encode()).hexdigest()[:16]
    cookie = request.cookies.get("kanbanauth")
    if cookie:
        return "c:" + hashlib.sha256(cookie.encode()).hexdigest()[:16]
    return "anon"


@dataclass
class RateLimitEngine:
    """The live rate-limit configuration + slowapi limiter (strategy + storage)."""

    enabled: bool
    limiter: Limiter
    items: dict[str, RateLimitItem]


def _parse_limit(tier: str, value: str) -> RateLimitItem:
    """Parse a ``limits`` rate string, falling back to the tier default if it's
    malformed (a bad env value must not crash startup)."""
    try:
        return parse(value)
    except ValueError:
        logger.warning("invalid rate limit for %s: %r; using default", tier, value)
        return parse(_DEFAULT_LIMITS[tier])


def build_engine(
    *, enabled: bool, limits_map: dict[str, str] | None = None
) -> RateLimitEngine:
    """Build an engine with a **fresh** in-memory store. ``limits_map`` overrides
    individual tier limits (used by tests to set a deterministically low bound);
    unspecified tiers keep their default."""
    merged = dict(_DEFAULT_LIMITS)
    if limits_map:
        merged.update(limits_map)
    # A dummy key_func — we call limiter.limiter (the strategy) directly with our
    # own identifiers, so slowapi never invokes this.
    limiter = Limiter(
        key_func=lambda: "unused", strategy="moving-window", storage_uri="memory://"
    )
    items = {tier: _parse_limit(tier, value) for tier, value in merged.items()}
    return RateLimitEngine(enabled=enabled, limiter=limiter, items=items)


def _enabled_from_env() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "").lower() in {"1", "true", "yes"}


def build_engine_from_env() -> RateLimitEngine:
    limits_map = {
        tier: os.environ.get(f"RATE_LIMIT_{tier.upper()}", default)
        for tier, default in _DEFAULT_LIMITS.items()
    }
    return build_engine(enabled=_enabled_from_env(), limits_map=limits_map)


# Module-global engine the middleware consults live on each request, so tests can
# swap in a low-limit engine at runtime without rebuilding the app.
_engine: RateLimitEngine | None = None


def current_engine() -> RateLimitEngine | None:
    return _engine


def set_engine(engine: RateLimitEngine | None) -> None:
    global _engine
    _engine = engine


def _too_many(engine: RateLimitEngine, item: RateLimitItem, *ids: str) -> JSONResponse:
    """Build the 429 response, with a ``Retry-After`` derived from the window's
    reset time (seconds), falling back to the item's fixed expiry."""
    try:
        stats = engine.limiter.limiter.get_window_stats(item, *ids)
        retry_after = max(1, math.ceil(stats.reset_time - time.time()))
    except Exception:
        retry_after = item.get_expiry()
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please retry later."},
        headers={"Retry-After": str(retry_after)},
    )


def install_rate_limiting(app: FastAPI) -> None:
    """Read config from the env and register the single rate-limit middleware.

    The middleware is always registered but consults the live engine each request,
    so it is a pure pass-through when disabled (the default) — zero effect on the
    existing test suite."""
    set_engine(build_engine_from_env())

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):  # pyright: ignore[reportUnusedFunction]
        engine = _engine
        if engine is None or not engine.enabled:
            return await call_next(request)
        tier = classify(request)
        if tier is None:
            return await call_next(request)
        item = engine.items[tier]
        ids = (tier, client_ip(request), principal_hint(request))
        if not engine.limiter.limiter.hit(item, *ids):
            return _too_many(engine, item, *ids)
        return await call_next(request)
