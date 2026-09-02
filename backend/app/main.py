"""FastAPI application entrypoint (SHAPING §Static + SPA, BREADBOARD §6).

Registration order matters: the API router and FastAPI's own /docs are mounted
first, then — only if a built SPA exists — static assets and a catch-all fallback
that returns index.html for any non-/api, non-/docs path (client-side routing).

In local dev the SPA is served by Vite (which proxies /api here), so ``STATIC_DIR``
usually does not exist and the fallback is simply not registered.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import get_db
from .observability import add_request_logging, configure_logging, init_error_tracking
from .ratelimit import install_rate_limiting
from .routers import (
    boards,
    cards,
    cycles,
    epics,
    labels,
    me,
    members,
    notifications,
    planning_intervals,
    team_members,
    teams,
    templates,
    tokens,
    views,
    webhooks,
)
from .users import register_auth_routes

# Observability (KAN-172): configure structured JSON logging and, only when
# SENTRY_DSN is set, error tracking — both before the app is built so startup is
# captured too. init_error_tracking() is a no-op (and imports nothing) when unset.
configure_logging()
init_error_tracking()

logger = logging.getLogger("kanban.health")

# --- Build provenance (KAN-595) -------------------------------------------
# The git revision this image was built from, baked in by the root Dockerfile
# (`ARG GIT_REVISION` -> `ENV GIT_REVISION`) and passed by
# .github/workflows/deploy.yml as `flyctl deploy --build-arg GIT_REVISION=<sha>`.
# Surfaced on GET /api/health/version so the deploy-drift watcher can OBSERVE
# what production is running instead of INFERRING it from GitHub Actions history
# (KAN-586). Read ONCE at import time, never per request: the endpoint has to
# stay a constant-time handler that reads no file and shells out to nothing.
#
# "unknown" is the honest default for a plain `docker build` with no build-arg,
# for a source checkout, and for any image predating this change. The watcher
# treats it as "I could not observe production" and fails LOUDLY rather than
# passing — see the `drift` job in deploy.yml.
GIT_REVISION = os.environ.get("GIT_REVISION", "").strip() or "unknown"


# --- Payload hardening: request body-size ceiling (V28, KAN-292) -----------
# Reject an over-large request by its declared Content-Length *before* the body is
# read or a route runs, so a giant upload can't buffer into the 256 MB box. String
# and array caps live in schemas.py (per-field). The ceiling is env-tunable with a
# generous default — normal JSON payloads are kilobytes, far below it.
def _max_body_bytes() -> int:
    try:
        value = int(os.environ["MAX_REQUEST_BODY_BYTES"])
    except (KeyError, ValueError):
        return 2_000_000  # ~2 MB
    return value if value > 0 else 2_000_000


MAX_REQUEST_BODY_BYTES = _max_body_bytes()


def install_body_size_limit(app: FastAPI) -> None:
    """Middleware that 413s a request whose declared ``Content-Length`` exceeds the
    ceiling. Header-only (no body buffering) so the rejection is cheap and early."""

    @app.middleware("http")
    async def _limit_body_size(request: Request, call_next):  # pyright: ignore[reportUnusedFunction]
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                declared = None
            if declared is not None and declared > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={
                        "detail": (
                            "Request body too large "
                            f"(limit {MAX_REQUEST_BODY_BYTES} bytes)."
                        )
                    },
                )
        return await call_next(request)


# --- Security headers (V29, KAN-293) ---------------------------------------
# Single-origin app (FastAPI serves the SPA + /docs from one host), so the CSP is
# tractable: everything is 'self' plus the inline scripts/styles the SPA and Swagger
# UI use.
#
# CSP ships as **Content-Security-Policy-Report-Only** first: browsers evaluate it
# and log violations to the console but do NOT block anything, so it cannot break the
# SPA or /docs (Swagger UI loads its bundle from a CDN + uses inline script/style).
# Watch prod consoles for report-only violations; once clean, flip to enforcing by
# renaming the header to ``Content-Security-Policy`` (and, for /docs, either
# self-host the Swagger assets or add the CDN host + relax to allow it).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


def install_security_headers(app: FastAPI) -> None:
    """Set defensive response headers on every response (API, SPA, /docs, and error
    responses alike). Registered outermost so it also covers a rate-limit 429 and
    HTTPException responses. ``setdefault`` so a route that sets its own wins."""

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # pyright: ignore[reportUnusedFunction]
        response = await call_next(request)
        headers = response.headers
        # HTTPS is enforced at the Fly edge (force_https); browsers ignore HSTS over
        # plain http, so setting it unconditionally is safe for dev/tests.
        headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Content-Security-Policy-Report-Only", _CSP)
        return response


app = FastAPI(title="Pandan API", version="0.1.0")

# Middleware registration order matters: Starlette runs the *last-registered*
# middleware outermost. We want security headers outermost (they must decorate every
# response, including a 429/413/4xx), the access logger just inside it (so those
# rejections still get logged), then the body-size + rate-limit guards.

# Rate limiting (V27, KAN-291): one classifying middleware over slowapi's in-memory
# limiter, guarding auth/write/expensive-read/webhook tiers. Off unless
# RATE_LIMIT_ENABLED is set, so dev + tests are unaffected.
install_rate_limiting(app)

# Payload hardening (V28, KAN-292): reject an over-large Content-Length with 413,
# early (before the route reads the body). String/array caps live in schemas.py.
install_body_size_limit(app)

# One structured access line per request (method/path/status/latency/principal).
# Registered after the guards above so it stays outermost of them and a 413/429 is
# still logged.
add_request_logging(app)

# Security headers (V29, KAN-293): HSTS/CSP(report-only)/nosniff/frame/referrer on
# every response. Registered last → outermost, so it also decorates rate-limit 429s
# and HTTPException error responses.
install_security_headers(app)

# Mount each router under the canonical versioned prefix /api/v1/... (P3,
# spike-p3-versioning.md). The temporary /api compat alias that eased the V2
# migration has been dropped now that all clients (SPA, e2e, backend tests) ride
# /api/v1. /api/health stays unversioned (infra, not a versioned resource).
app.include_router(boards.router, prefix="/api/v1")
app.include_router(members.router, prefix="/api/v1")  # KAN-12: board membership
app.include_router(cards.router, prefix="/api/v1")
app.include_router(epics.router, prefix="/api/v1")
app.include_router(labels.router, prefix="/api/v1")  # M5 V11 (KAN-244): card labels
app.include_router(views.router, prefix="/api/v1")  # M5 V14 (KAN-247): saved views
app.include_router(templates.router, prefix="/api/v1")  # M5 V19 (KAN-252): card templates
app.include_router(cycles.router, prefix="/api/v1")  # V33 (KAN-297): cycles / iterations
app.include_router(
    planning_intervals.router, prefix="/api/v1"
)  # M8 V57 (KAN-978): planning intervals
app.include_router(tokens.router, prefix="/api/v1")  # M3 V9 (ADR 0014): agent PATs
app.include_router(notifications.router, prefix="/api/v1")  # V37 (KAN-301): inbox
app.include_router(teams.router, prefix="/api/v1")  # M9 V65 (KAN-1054, ADR 0021): teams
app.include_router(team_members.router, prefix="/api/v1")  # M9 V66 (KAN-1055): team membership
# Who-am-I for the acting principal (KAN-530). Board-less: it resolves the
# principal and returns its id + email, so a bearer holder can finally ask who it
# is — fastapi-users' /users/me below is cookie-only.
app.include_router(me.router, prefix="/api/v1")
# GitHub webhook receiver (KAN-42): standalone — auth is the HMAC signature, NOT
# the cookie/PAT principal resolver, so it is intentionally not owner-gated.
app.include_router(webhooks.router, prefix="/api/v1")

# Human auth (M3 V6, ADR 0011): /auth/* + /users/*, unversioned like /api/health
# (session/identity plumbing, not versioned API resources). The GitHub OAuth
# routes register only when creds are set — see register_auth_routes.
register_auth_routes(app)


@app.get("/api/health", tags=["meta"])
def health(response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness probe (KAN-172): a cheap ``SELECT 1`` on the **sync board engine**
    (ADR 0008) so health reflects real dependency health, not just "process up".

    - DB reachable → ``200 {"status": "ok"}`` (the fast happy path Fly + the
      keepalive ping hit; a ``SELECT 1`` is sub-millisecond warm).
    - DB unreachable → ``503 {"status": "unavailable"}`` so the check flips red.

    A scaled-to-zero Neon adds a one-off cold-start delay on the first hit — a
    documented latency, not a failure (the keepalive poller allows for it).
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness probe failed: database unreachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}


@app.get("/api/health/live", tags=["meta"])
def liveness() -> dict[str, str]:
    """Liveness probe (KAN-172): the process is up and serving. No dependency
    checks — always ``200`` while the app runs, so an orchestrator can tell
    "process alive" apart from "DB ready" (the readiness probe above)."""
    return {"status": "ok"}


@app.get("/api/health/version", tags=["meta"])
def version() -> dict[str, str]:
    """Build provenance (KAN-595): the git revision this image was built from.

    A **sibling** of the readiness probe rather than a field on it, deliberately:
    ``GET /api/health`` is what Fly's health check and the keepalive poller hit,
    its body is asserted by equality in the suite, and its whole job is to answer
    one question cheaply. Provenance is a different question with a different
    consumer, so it gets its own route and leaves the probe's contract alone.

    Constant-time and DB-free (like ``/api/health/live``) — ``GIT_REVISION`` is
    read from the environment once at import. No file read, no subprocess.

    Unauthenticated, like the rest of ``/api/health*``. The repo is public and
    every one of these SHAs is already visible on GitHub, so the commit is not a
    secret; it is published on purpose so a watcher outside the deploy system can
    read it with nothing but ``curl``.

    The **full 40-char SHA**, not an abbreviation: the only consumer compares it
    to ``git rev-parse HEAD`` and feeds it to ``git merge-base --is-ancestor``,
    both of which want the whole thing. Prefix matching would be one more thing
    to get subtly wrong for no gain.

    ``{"revision": "unknown"}`` when the build passed no ``GIT_REVISION`` — see
    the constant's note above.
    """
    return {"revision": GIT_REVISION}


# Path to the built Svelte SPA. Overridable via env for the Docker image layout.
STATIC_DIR = Path(
    os.environ.get(
        "STATIC_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"),
    )
)

if STATIC_DIR.is_dir():
    # Serve hashed asset files (JS/CSS/images) built by Vite.
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    index_file = STATIC_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        # Serve a real static file if one exists (e.g. favicon), else index.html
        # so the client-side app boots for any unknown route.
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)
