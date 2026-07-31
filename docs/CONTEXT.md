# CONTEXT.md

Shared language, domain model, and locked decisions for the **Pandan** MVP.
This is the canonical vocabulary; downstream docs (PRD, shaping, breadboard) should use these
terms exactly. Produced during step A (grill-with-docs). See `docs/adr/` for the reasoning behind
each significant decision, and `QUESTIONS.md` for the resolved Q&A trail.

---

## 1. Product in one line

A simple, deployable web Kanban board for scrum/software teams — a CRUD app (Svelte frontend,
FastAPI backend, PostgreSQL) whose every action is also available over a clean REST API, so that
future MCP/CLI/LLM integrations can drive it without UI changes.

## 2. Glossary (shared terms)

- **Board** — the single, global Kanban board. There is exactly one board in the MVP; it is
  implicit and not a stored entity.
- **Column** — one of the three fixed lanes a card can be in: **Todo**, **In Progress**, **Done**.
  Represented as an enum on the card (`todo`, `in_progress`, `done`). Not user-editable in the MVP.
- **Card** — the core work item (analogous to a Jira ticket). Belongs to exactly one column and
  has a position within that column.
- **Ticket number** — a human-facing identifier of the form `KAN-<n>` (e.g. `KAN-1`, `KAN-2`),
  assigned once at creation from a global monotonic sequence, immutable, never reused.
- **Position** — the integer/rank ordering a card *within* its column (for drag-to-reorder).
- **Assignee** — free-text name of who owns the card (nullable). Not a user account (no auth).
- **Story points** — optional estimate from the Fibonacci set {1, 2, 3, 5, 8, 13}; null = unestimated.
- **Move** — the act of changing a card's column and/or position. Exposed as a dedicated API action.
- **API client** — any consumer of the REST API. The Svelte UI is just the first API client;
  future clients include an MCP server, a CLI, and LLM agents (all out of MVP scope).

## 3. Domain model (MVP)

**Card**
| Field | Type | Notes |
|-------|------|-------|
| `id` | int (PK) | Internal surrogate key |
| `ticket_number` | string | `KAN-<n>`, unique, immutable, from global sequence |
| `title` | string | Required, non-empty |
| `description` | string | Optional, plain text |
| `column` | text (app-enum) | `todo` \| `in_progress` \| `done`; stored as `varchar` + CHECK (not native PG enum) — see ADR 0008 |
| `position` | int | Order within the column |
| `story_points` | int? | One of {1,2,3,5,8,13} or null |
| `assignee` | string? | Free text, nullable |
| `created_at` | timestamp | Set on create |
| `updated_at` | timestamp | Set on every update |

No other entities in the MVP (no users, boards, columns, comments, labels, attachments as tables).

## 4. API surface (shape only — detailed in PRD/breadboard)

REST + JSON, auto-documented via FastAPI OpenAPI at `/docs`. The UI performs no action the API
can't. Anticipated endpoints:

- `GET /api/cards` — list all cards (grouped/orderable by column + position)
- `POST /api/cards` — create a card
- `GET /api/cards/{id}` — read one card
- `PATCH /api/cards/{id}` — edit fields (title, description, story_points, assignee)
- `DELETE /api/cards/{id}` — hard-delete
- `POST /api/cards/{id}/move` — change a card's `column` and, optionally, `position`; if `position`
  is omitted the card is appended to the end of the target column (dedicated move semantics)

Validation: `title` required/non-empty; `column` must be a valid enum; `story_points` in the
allowed set or null. Errors returned as standard JSON problem responses.

## 5. Architecture & stack

- **Frontend:** Svelte 5 + Vite 8 (SPA), Node 20+ / `npm`. Built to static assets. Drag-and-drop
  via `svelte-dnd-action` (native HTML5-DnD fallback). Vite dev server proxies `/api` → backend for
  local dev; prod is same-origin. (See ADR 0008.)
- **Backend:** FastAPI (Python 3.12), Pydantic models, **synchronous** SQLAlchemy 2.0 ORM with the
  `psycopg` (v3) driver; deps managed with `uv`. (See ADR 0008.)
- **Database:** PostgreSQL from day one. Schema managed by **Alembic** migrations.
- **Packaging:** Single monorepo (`/frontend`, `/backend`). FastAPI serves the built Svelte
  bundle as static files → one deployable artifact, one origin, no CORS.
- **Container:** One Dockerfile producing the combined app image.

## 6. Deployment & CI/CD

- **Hosting:** App on **Fly.io** (Docker deploy, free allowance); database on **Neon** (managed
  serverless PostgreSQL, free tier, scales to zero).
- **Config:** Runtime config via env vars — primarily `DATABASE_URL`. Deploy token
  (`FLY_API_TOKEN`) stored as a GitHub Actions secret.
- **CI/CD (GitHub Actions):** On PR → run backend `pytest` + frontend build/lint. On merge to
  `main` → build image and deploy to Fly.io (prod only, single environment).

## 7. Non-functional posture (MVP)

- **Scale:** Small — a handful of concurrent users, up to a few hundred cards. Postgres is
  comfortably sufficient; chosen for zero future migration debt, not for scale needs today.
- **Concurrency:** Last-write-wins; no optimistic locking.
- **Real-time:** None. UI refetches after its own mutations (required); refetch-on-window-focus is
  an optional enhancement, not required by Shape A. No server push; no optimistic UI.
- **Testing:** Backend API tests with `pytest`; minimal frontend happy-path smoke test.
- **Responsiveness:** Desktop-first; usable but not optimized on mobile.

## 8. Explicit non-goals (MVP)

Authentication, authorization, billing, multiple boards, custom/renamable columns, WIP limits,
comments, labels/tags, attachments, due dates, card move history/audit, real-time collaboration,
and the MCP server / CLI / LLM integrations themselves (the API is merely *designed to be ready*
for them).
