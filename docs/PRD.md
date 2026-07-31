# PRD — Pandan (MVP)

- **Status:** Draft (step B of build-plan-product)
- **Date:** 2026-07-07
- **Sources:** REQS.md, CONTEXT.md, docs/adr/0001–0007
- **Owner:** leejianrong2@gmail.com

---

## 1. Problem statement

Small software / scrum teams need a lightweight, self-hostable Kanban board to track work across
Todo → In Progress → Done. Existing tools (Jira, Trello, etc.) are either heavyweight, paid, or not
easily driven by automation. This team specifically wants a **simple, deployable board they can
demo today**, built so that **every action is available over a clean API** — so that later, MCP
servers, a CLI, and LLM agents can operate the board without any UI or backend rework.

The MVP's job is to prove the end-to-end slice — frontend + backend + persistent database +
deployment + CI/CD — while deliberately excluding auth, billing, and the integrations themselves.

## 2. Goals & non-goals

### Goals
- A working, deployed web Kanban board with three fixed columns and draggable cards.
- Full CRUD + move over a documented REST API; the UI is just the first API client.
- Persistent PostgreSQL storage with Alembic-managed schema.
- Free/low-cost public deployment (Fly.io + Neon) with GitHub Actions CI/CD.
- A codebase and API shaped for future MCP/CLI/agent integration.

### Non-goals (MVP)
Authentication/authorization, billing, multiple boards, custom/renamable columns, WIP limits,
comments, labels/tags, attachments, due dates, card history/audit, real-time collaboration, and the
MCP server / CLI / agent clients themselves. (See CONTEXT §8.)

## 3. Personas

- **Team member (primary UI user):** creates, edits, assigns, estimates, and moves cards on the
  shared board during standups and day-to-day work.
- **API consumer (secondary, forward-looking):** a script, CLI, MCP server, or LLM agent that
  performs the same actions programmatically. Only the *capability* is delivered in the MVP (a
  documented API), not a specific client.

## 4. User stories

Format: *As a … I want … so that …* — with acceptance criteria (AC).

### Epic A — View the board
- **US-A1** As a team member, I want to see all cards laid out in Todo / In Progress / Done
  columns so that I can understand the current state of work at a glance.
  - AC: The board shows exactly three columns in fixed order.
  - AC: Each card shows its ticket number, title, story points (if set), and assignee (if set).
  - AC: Cards appear in their stored `position` order within each column.
  - AC: An empty board renders the three empty columns (plus any seed cards on first run).

### Epic B — Create & edit cards
- **US-B1** As a team member, I want to create a card in a column so that I can capture new work.
  - AC: A new card requires a non-empty title; description, story points, and assignee are optional.
  - AC: On creation the card receives the next `KAN-<n>` ticket number automatically.
  - AC: The card is created in the chosen column and appended to the end (highest `position`).
  - AC: `created_at`/`updated_at` are set.
- **US-B2** As a team member, I want to edit a card's title, description, story points, and
  assignee so that I can keep it accurate.
  - AC: Editing updates only the provided fields and bumps `updated_at`.
  - AC: `ticket_number` cannot be changed.
  - AC: Story points, if provided, must be one of {1,2,3,5,8,13}; otherwise the edit is rejected.
- **US-B3** As a team member, I want to delete a card so that I can remove work that no longer
  applies.
  - AC: Delete is a hard delete; the card disappears from the board and API.
  - AC: Deleting a card does not renumber other cards' ticket numbers.

### Epic C — Move & reorder cards
- **US-C1** As a team member, I want to drag a card to another column so that I can reflect its
  progress.
  - AC: The card's `column` updates and it takes a `position` in the destination column.
  - AC: `updated_at` is bumped.
- **US-C2** As a team member, I want to reorder a card within a column so that I can prioritize.
  - AC: The card's `position` updates so the visible order matches the drop location.
  - AC: Order is preserved across reloads.

### Epic D — API access
- **US-D1** As an API consumer, I want a documented REST API covering list/create/read/update/
  delete/move so that I can automate the board.
  - AC: OpenAPI docs are available at `/docs`.
  - AC: Every UI action maps to an API endpoint under `/api/*` (no UI-only backdoor).
  - AC: Validation errors return a standard JSON error shape with a helpful message.

### Epic E — Deploy & operate
- **US-E1** As the owner, I want the app deployed to a public URL so that I can demo it to users.
  - AC: A single deployed artifact serves both the SPA and the API from one origin.
  - AC: Data persists across restarts/redeploys (Neon Postgres).
- **US-E2** As the owner, I want CI/CD so that merges to `main` ship automatically.
  - AC: PRs run backend tests + frontend build/lint.
  - AC: Merge to `main` builds the image and deploys to Fly.io.

## 5. Solution overview

A monorepo (`/frontend`, `/backend`). Svelte 5 + Vite 8 SPA calls a FastAPI + SQLAlchemy backend
backed by PostgreSQL (Alembic migrations). FastAPI also serves the built SPA as static files, so the
whole app is one Docker image deployed to Fly.io, with the database on Neon. See CONTEXT.md and the
ADRs for the full rationale.

### Data model (single `card` table)
| Field | Type | Rules |
|-------|------|-------|
| `id` | int PK | surrogate |
| `ticket_number` | text unique | `KAN-<n>` from global sequence, immutable |
| `title` | text | required, non-empty |
| `description` | text null | optional plain text |
| `column` | text + CHECK | `todo` \| `in_progress` \| `done` (app-level enum, not native PG enum) |
| `position` | int | relative sort key within column (not necessarily contiguous) |
| `story_points` | int null | ∈ {1,2,3,5,8,13} or null |
| `assignee` | text null | free text |
| `created_at` | timestamptz | set on create |
| `updated_at` | timestamptz | set on every update |

### API endpoints (REST + JSON, under `/api`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/cards` | List all cards (client groups by column, orders by position) |
| POST | `/api/cards` | Create a card |
| GET | `/api/cards/{id}` | Read one card |
| PATCH | `/api/cards/{id}` | Edit title/description/story_points/assignee |
| DELETE | `/api/cards/{id}` | Hard-delete |
| POST | `/api/cards/{id}/move` | Set target `column`; optional `position` (append to end if omitted) |

## 6. Implementation decisions

- **DB & migrations:** PostgreSQL + Alembic from day one (ADR 0002). Local dev via docker-compose
  Postgres for prod parity.
- **Ticket numbers:** backed by a dedicated Postgres sequence; format `KAN-<n>`; assigned at insert.
- **Ordering:** `position` is a relative sort key; deletes may leave gaps (Q-A2.1). A move/reorder
  recomputes positions of affected rows in the target column. Simple integer stepping is acceptable
  for MVP scale.
- **Move endpoint:** dedicated `POST /cards/{id}/move` for clear semantics vs. field-edit `PATCH`
  (ADR 0006), which is also cleaner for future agent tools.
- **Serving:** multi-stage Dockerfile builds the SPA, copies it into the Python image; FastAPI
  mounts static assets and returns `index.html` as SPA fallback for unknown non-`/api`/`/docs`
  paths (Q-A2.3).
- **Config:** `DATABASE_URL` env var is the only required runtime config; `FLY_API_TOKEN` is a
  GitHub Actions secret.
- **Concurrency/real-time:** last-write-wins, no server push; UI refetches after mutations / on
  focus (ADR 0007).
- **No auth:** all endpoints open (ADR 0007).

## 7. Testing decisions

- **Backend (primary):** `pytest` against the API — create/read/update/delete/move, ticket-number
  assignment/immutability, story-point validation, column-enum validation, and ordering after
  move/reorder. Run against a real Postgres (docker-compose / CI service container) for parity.
- **Frontend (minimal):** a happy-path smoke test — load board, create a card, move it between
  columns. Keep it light for the MVP.
- **CI:** both suites run on PRs; deploy only proceeds from `main` (ADR 0004).

## 8. Rollout & deployment

- Provision a Neon Postgres project; set `DATABASE_URL` as a Fly secret.
- Fly.io app runs the combined image; Alembic migrations run on deploy/startup.
- GitHub Actions: PR → test+build; merge to `main` → build image + `fly deploy`. Single prod env.
- **Known MVP quirk:** Neon free tier scales to zero, so the first request after idle has a brief
  cold-start delay (Q-A2.2) — expected, not a bug.

## 9. Open questions / future work

- Optimistic locking + real-time updates when concurrent editing becomes painful.
- Auth + real user identities (would upgrade `assignee` from free text).
- Custom columns / multiple boards / WIP limits.
- The actual MCP server, CLI, and agent clients (the API is already designed to host them —
  ADR 0005).
