# syntax=docker/dockerfile:1
# Single deployable artifact (ADR 0003): build the Svelte SPA, then serve it plus
# the API from one FastAPI/uvicorn process. Also used by docker-compose for local
# full-stack runs.
#
# ---------------------------------------------------------------------------
# BUILD INPUTS: TWO FLOAT ON PURPOSE, ONE IS BOUNDED (KAN-513)
# ---------------------------------------------------------------------------
# Measured 2026-08-01 with `docker buildx imagetools inspect` + `docker run`:
#
#   node:22-slim            Node 22.23.2, Debian 12 bookworm, glibc 2.36
#   python:3.12-slim        Python 3.12.13, Debian 13 trixie,  glibc 2.41
#   ghcr.io/astral-sh/uv    uv 0.12.0, a static musl binary
#
# The two LANGUAGE BASES ARE LEFT FLOATING. `3.12` and `22` are upstream
# compatibility LINES: they promise the language version and self-update for
# security patches, which is the property that matters most for an
# internet-facing deploy. They are not surprise-free — `python:3.12-slim` has
# already crossed a Debian MAJOR underneath us (12/glibc 2.36 -> 13/glibc 2.41,
# the same jump KAN-475 measured) and prod runs trixie today. We take that trade
# knowingly: the backend is pure Python plus manylinux wheels, the node stage
# contributes nothing to the runtime image except the static `dist/` it builds,
# and KAN-439 replaces this deployment with self-hosted k8s anyway.
#
# `uv` IS THE EXCEPTION, and it is why this comment exists. `:latest` is not a
# compatibility line — it is "whatever astral shipped most recently", on a
# pre-1.0 tool, straight into the deploy path. Alone among the three it makes NO
# version promise whatsoever: `3.12` and `22` each name a series, `latest` names
# nothing, and the series it currently points at (`:0.12` and `:latest` are the
# same digest today) is seven minors on from the oldest one astral still
# publishes. So bound it to `:0.12` — the coarsest bound available; there is no
# `:0` tag, checked — while the tag still floats for patches.
#
# Be clear about what this does and does not claim. uv has NOT been breaking:
# building this exact Dockerfile against `uv:0.5` (which resolves to 0.5.31,
# seven minor series back) installs the same 51 packages from backend/uv.lock
# with no error, and uv 0.5.0 reads today's lock without so much as a warning.
# backend/uv.lock is at `version = 1`, `revision = 3`; `revision` is
# backwards-compatible metadata, so only a `version =` bump could lock an old uv
# out. The bound is not a prediction that minors break — it
# is insurance against the ONE unbounded event `:latest` cannot exclude, uv 1.0
# landing on an ordinary Tuesday and taking the next deploy (possibly a hotfix)
# with it. Today `:0.12` and `:latest` resolve to the SAME index digest
# (sha256:606e70c7...), so this bound cost the image nothing.
#
# WHO BUMPS THE SERIES: a human, deliberately, and nothing else — no Dependabot
# ecosystem can see this ref (see below). That is an accepted, mild staleness:
# uv here is a BUILD tool whose binary is never executed at runtime (CMD runs
# alembic + uvicorn out of /app/.venv/bin), so a slightly old uv costs features,
# not security posture, and it fails loudly at `uv sync --frozen` if it ever
# stops being able to read the lock. Bump it when you want a newer uv, or if
# backend/uv.lock's `version =` (NOT `revision =`) ever moves.
#
# DELIBERATELY NOT DONE, so the next person need not re-derive it:
#   * NO committed digest pins and NO `docker` dependabot ecosystem. See the
#     long note in .github/dependabot.yml: Dependabot cannot bump a `COPY --from`
#     ref at all (dependabot-core#5103), so a digest pin here would be a pin with
#     no watcher — it looks maintained and rots into a stale security patch.
#   * NO build-arg + OCI-label provenance like mcp/Dockerfile carries
#     (KAN-452/KAN-475). That pattern needs somewhere to ASSERT the labels. This
#     image is built by a single `flyctl deploy --remote-only`
#     (.github/workflows/deploy.yml) — one build, so there is nothing to make
#     consistent between builds; there is no gate step; and nobody pulls this
#     image, so there is no consumer for the claim (Fly already records the
#     deployed image digest per release). Shipping the resolve half without the
#     assert half is precisely the "labels that look maintained and aren't" that
#     KAN-475 rejected.
#
# One more reason to prefer the low-risk option here: CI NEVER BUILDS THIS FILE.
# `.github/workflows/ci.yml` does not mention `Dockerfile` anywhere, so a change
# to it matches no paths filter, every job reports success having skipped its
# heavy steps, and deploy.yml then ships it (its filter DOES match `Dockerfile`).
# Any build-input change here is unvalidated until the production deploy.

# ---- Stage 1: build the Svelte SPA ----
FROM node:22-slim AS frontend
WORKDIR /frontend
# Install deps against the lockfile first for better layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build   # -> /frontend/dist

# ---- Stage 2: Python runtime serving API + built SPA ----
FROM python:3.12-slim AS runtime
# uv for fast, reproducible dependency installs. Bounded to the 0.12 series
# rather than `:latest` — see the BUILD INPUTS note at the top of this file.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    STATIC_DIR=/app/static \
    PATH="/app/.venv/bin:$PATH"

# Install backend deps first (cached unless pyproject/lock change).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# Backend source (alembic.ini, alembic/, app/).
COPY backend/ ./
# Built SPA -> the directory FastAPI serves (main.py reads STATIC_DIR).
COPY --from=frontend /frontend/dist ./static

EXPOSE 8000
# Apply migrations (incl. future seed) then start the server. Migrations are
# idempotent, so this is safe on every start.
#
# --proxy-headers + --forwarded-allow-ips=* make uvicorn honour Fly's
# X-Forwarded-Proto/Host, so request URLs are built as https://<host> behind the
# TLS-terminating edge proxy. This is required for the GitHub OAuth callback
# (M3 V6, ADR 0011): without it the generated redirect_uri is http:// and GitHub
# rejects the mismatch. Trusting all forwarded IPs is safe here because only the
# Fly proxy can reach the container's internal port.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*"]
