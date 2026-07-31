# Pandan

A small, deployable Kanban board for scrum/software teams — **Svelte 5 + FastAPI + PostgreSQL**.
Its defining goal is **API-first**: every UI action is a plain REST endpoint, so an MCP server, a
CLI, or an LLM agent can drive the board without any UI or backend rework — and all three now exist.

> **🚀 Live demo: [simple-kanban-jian.fly.dev](https://simple-kanban-jian.fly.dev)**
> (Hosted on Fly.io + Neon; the free tier scales to zero, so the first request after idle can take
> ~1s to wake — that's a cold start, not a bug.)

> **Status: feature-complete and deployed — Milestones 1, 2, and 3 all shipped.**
> The core board (view / create / edit / delete / drag-to-move) runs end to end behind a full
> REST API, with a pytest + Playwright test suite and CI/CD to Fly.io. On top of that:
> GitHub login, multiple owned boards, epics, card dependencies / work-links / comments, a query
> API with keyset pagination, an [MCP server](mcp/) and a [`pandan` CLI](pandan-cli/) for agents, and
> a recent UI pass (card/epic modals, theme toggle). See [Current status](#current-status).

## What it is

Three fixed columns (**Todo / In Progress / Done**) holding cards. Each card has a Jira-style
ticket number (`KAN-1`, `KAN-2`, …), a title, and optional description, story points
({1,2,3,5,8,13}), assignee, epic link, dependencies, work-links, and comments. You log in with
GitHub and own one or more boards; every board is private to its owner (no sharing yet). Cards can
be grouped under epics (`EPIC-1`, …) and shown in a separate Epics view.

The interesting part is *how it's shaped*: a clean, versioned `/api/v1` surface with
auto-generated OpenAPI docs, so the Svelte UI is just the **first** API client rather than the only
way in — the MCP server and CLI are thin adapters over the exact same endpoints.

## Use it with your coding agent (MCP) or in CI (CLI)

This board is built to be driven by agents, not just clicked. Because everything is API-first
(ADR [0005](docs/adr/0005-api-first-mcp-ready.md)), you can point Claude Code — or any MCP client —
straight at it:

- **[MCP server](mcp/)** — one tool per endpoint, so an agent gets full CRUD over boards, cards,
  epics, dependencies, links, and comments. Run it from source with `uv`, or pull the public
  [ghcr.io image](https://github.com/leejianrong/pandan/pkgs/container/pandan-mcp)
  (`docker pull ghcr.io/leejianrong/pandan-mcp:latest`, no `docker login` needed). Wire it
  into Claude Code via `.mcp.json` (see [`.mcp.json.example`](.mcp.json.example)) and ask it to
  *"list my boards"*.
- **[`pandan` CLI](pandan-cli/)** — the same adapter as subcommands, for CI jobs and non-MCP
  automation, with a token-free `pandan warmup` you can loop on as a pre-step. Install from source, or
  download a prebuilt binary (`pandan-linux-x86_64`, `pandan-macos-arm64`) from the
  [latest release](https://github.com/leejianrong/pandan/releases/latest).

Both authenticate with a personal access token you mint in the **Tokens** tab; a PAT acts as you
and is owner-gated exactly like your session.

**→ New here? Start with the [Agent onboarding guide](docs/guides/agent-onboarding.md)** — it walks
through getting access, minting a token, wiring the MCP into Claude Code, verifying the connection,
and example agent workflows.

## Tech stack

| Layer | Choice |
|-------|--------|
| Frontend | Svelte 5 (runes) + Vite 8, TypeScript |
| Backend | FastAPI + synchronous SQLAlchemy 2.0, Pydantic v2 (Python 3.12, deps via `uv`) |
| Database | PostgreSQL, schema managed by Alembic (psycopg v3 driver) |
| Packaging | Single artifact — FastAPI serves the built SPA from one origin (no CORS) |
| Hosting | Fly.io (app) + Neon (Postgres), CI/CD via GitHub Actions |
| Drag & drop | `svelte-dnd-action` |
| Auth | GitHub OAuth + revocable cookie sessions (fastapi-users, async engine); per-user hashed PATs for agents |
| Agent clients | MCP server (`mcp/`, official `mcp` SDK) + `pandan` CLI (`pandan-cli/`), both over the shared `pandan-client` |

See [`docs/adr/`](docs/adr/) for the reasoning behind each of these choices.

## Quick start

Prerequisites: **Docker**, **Node 20+**, and **[uv](https://docs.astral.sh/uv/)** (Python 3.12).

**Fastest path:** `make up` boots the entire stack (Postgres + the combined app image serving the
SPA) in one command; open http://localhost:8000. Run `make help` to see all shortcuts (`make dev`
is the hot-reload loop below). Or do it by hand:

```bash
# 1. Start Postgres (from the repo root)
docker compose up -d db

# 2. Backend — from backend/
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload      # API on http://localhost:8000, docs at /docs

# 3. Frontend — from frontend/ (new terminal)
npm ci
npm run dev                               # UI on http://localhost:5173
```

Open **http://localhost:5173**. In dev, Vite proxies `/api` to the backend on `:8000`; in
production FastAPI serves the built SPA itself, so the whole thing is one origin.

Config is a single env var, `DATABASE_URL` (defaults to the docker-compose Postgres:
`postgresql+psycopg://kanban:kanban@localhost:5432/kanban`).

### Tests

```bash
# Backend — from backend/
uv run pytest tests/unit          # pure schema-validation logic, no DB
uv run pytest tests/integration   # full API against a throwaway Postgres (needs a running Docker daemon)

# Frontend — from frontend/
npm run check                     # svelte-check type/lint pass
```

The integration suite spins up an ephemeral Postgres 17 via **testcontainers** and runs the
migrations against it, so it's fully self-contained. CI runs lint, unit, integration, the frontend
build, Playwright e2e, and the MCP and CLI test suites as independent jobs on every push and PR.

## Project layout

```
backend/       FastAPI app (app/), Alembic migrations (alembic/), tests/ (unit + integration), pyproject.toml
frontend/      Svelte 5 SPA (src/), Vite config, e2e/ (Playwright)
mcp/           MCP server — one tool per /api/v1 endpoint (official mcp SDK, stdio)
pandan-cli/    `pandan` command-line client
pandan-client/ Shared httpx wrapper both mcp/ and pandan-cli/ depend on
docs/          Shape Up planning: FRAME → PRD/CONTEXT → SHAPING → BREADBOARD + ADRs + guides/
.github/workflows/   CI (lint, unit, integration, frontend build, e2e, mcp, cli) + deploy to Fly.io
Dockerfile           Multi-stage image — builds the SPA, then serves it from FastAPI
docker-compose.yml   Local Postgres + app for dev/CI parity
fly.toml             Fly.io deployment config
```

## API

REST + JSON under the versioned `/api/v1` prefix, with interactive OpenAPI docs at **`/docs`**.
Every board-scoped route is auth-required and owner-gated — a cookie session or a `pandan_pat_…`
bearer token resolves to a user, and only that board's owner is allowed (else `403`; no auth →
`401`). `/api/health` stays unversioned and unauthenticated.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/cards` | List cards; query params `board_id`/`column`/`epic_id`/`updated_since`/`limit`/`cursor` (keyset pagination via `X-Next-Cursor`) |
| `POST` | `/api/v1/cards` | Create a card (appended to the end of its column) |
| `GET` | `/api/v1/cards/{id}` | Read a single card (inlines dependencies + work-links) |
| `PATCH` | `/api/v1/cards/{id}` | Edit fields (title / description / story points / assignee / epic) |
| `DELETE` | `/api/v1/cards/{id}` | Delete a card |
| `POST` | `/api/v1/cards/{id}/move` | Move / reorder a card (column change + position within a column) |
| `POST` `DELETE` | `/api/v1/cards/{id}/dependencies…` | Add / remove a blocker link |
| `POST` `DELETE` | `/api/v1/cards/{id}/links…` | Add / remove a work-link (e.g. a PR URL) |
| `GET` `POST` `DELETE` | `/api/v1/cards/{id}/comments…` | Card comment thread |
| `GET` `POST` | `/api/v1/boards`, `/api/v1/epics` | List / create boards and epics (+ `GET`/`PATCH`/`DELETE` by id) |
| `GET` `POST` `DELETE` | `/api/v1/tokens…` | Manage your agent PATs |
| `GET` | `/api/health` | Health check (unversioned) |

Column and position changes go through the dedicated `/move` endpoint (not `PATCH`), so field edits
and reordering stay cleanly separated. Human login lives under unversioned `/auth/*` + `/users/*`.
See [`docs/BREADBOARD.md`](docs/BREADBOARD.md) §6 for the core-board contract.

## Current status

This repo is built in vertical slices. All three milestones are feature-complete and deployed:

| Area | Status |
|------|--------|
| Core board (view / create / edit / delete) | ✅ three columns, ticket numbers, story points, assignee |
| Move & reorder (drag-and-drop) | ✅ `/move` endpoint + `renumber_column()` + `svelte-dnd-action` UI |
| Epics | ✅ first-class `epic` entity, `EPIC-` tickets, story links, Epics view |
| Card dependencies / work-links / comments | ✅ blockers, PR links, and comment threads on cards |
| Query API + pagination | ✅ filters on `GET /api/v1/cards` + keyset pagination (`X-Next-Cursor`) |
| Auth | ✅ GitHub login + cookie sessions; owner-gated `/api/v1`; per-user PATs |
| Multiple boards | ✅ `board` entity with ownership + board switcher |
| MCP server + `pandan` CLI | ✅ thin adapters over `/api/v1` for agents and CI |
| UI polish | ✅ card/epic modals, epics grouping, light/dark theme toggle |
| Seed data | ✅ Alembic data migration (guarded to empty DBs) |
| Tests | ✅ `pytest` unit + integration + Playwright e2e |
| Docker / CI/CD / deploy | ✅ Dockerfile, docker-compose, GitHub Actions → Fly.io + Neon |

## How this project is planned

The [`docs/`](docs/) folder isn't an afterthought — it's a full [Shape Up](https://basecamp.com/shapeup)
planning trail that drives the build, and is the source of truth for *intended* behavior:

```
REQS.md  →  FRAME.md  →  PRD.md + CONTEXT.md (+ adr/)  →  SHAPING.md  →  BREADBOARD.md  →  build in slices
 (raw ask)  (framing)     (spec + glossary + decisions)   (chosen shape)  (UI places & wiring)
```

- **[CONTEXT.md](docs/CONTEXT.md)** — canonical glossary and domain model.
- **[SHAPING.md](docs/SHAPING.md)** — three candidate shapes, a fit check, and why "Thin Slice" won.
- **[BREADBOARD.md](docs/BREADBOARD.md)** — every UI place, affordance, and API wiring.
- **[adr/](docs/adr/)** — fifteen decisions (0001–0015; all Accepted except 0010, superseded)
  tracing the whole arc: stack, Postgres-from-day-one, single-artifact serving, hosting/CI,
  API-first, data model, and last-write-wins concurrency, then epics, agent tokens, GitHub login,
  multi-board ownership, board authorization, self-serve PATs, and MCP board-scoping.
- **[guides/](docs/guides/)** — practical how-tos, including the
  [Agent onboarding guide](docs/guides/agent-onboarding.md) and the
  [GitHub PR-board auto-sync setup guide](docs/guides/autosync-github-setup.md).

## Still out of scope

The early non-goals that have since shipped — authentication, multiple boards, comments, and the
MCP/CLI agent clients — are now built. What remains deliberately out of scope: billing, custom
columns, WIP limits, labels, attachments, due dates, history/audit, real-time collaboration, and
**board sharing** (boards are single-owner today; multi-user collaboration is a future milestone).
