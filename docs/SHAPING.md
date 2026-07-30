# SHAPING — Pandan (MVP)

Shape Up shaping workbook. Sources: FRAME.md, docs/PRD.md, CONTEXT.md, docs/adr/*.
Steps: Build R → Sketch S → Fit Check (R×S) → [Spikes] → Select → Detail.

---

## Build R (Requirements)

Status legend: **Core** = core goal (the point of the MVP) · **Must** = must-have to ship ·
**Undecided** = needs a call · **Out** = explicitly out of scope.

### R0 — Board view *(Core)*
- **R0.1** Show three fixed columns in order: Todo, In Progress, Done. *(Core)*
- **R0.2** Render each card with ticket number + title; show story points and assignee when set. *(Must)*
- **R0.3** Cards appear in `position` order within each column; order is stable across reloads. *(Must)*
- **R0.4** Board loads with seed/demo cards on a fresh database. *(Must)*

### R1 — Card CRUD *(Core)*
- **R1.1** Create a card in a chosen column with a required non-empty title. *(Core)*
- **R1.2** Optional fields on create/edit: description, story points, assignee. *(Must)*
- **R1.3** Edit an existing card's title/description/story points/assignee. *(Must)*
- **R1.4** Hard-delete a card. *(Must)*

### R2 — Move & reorder *(Core)*
- **R2.1** Drag a card from one column to another; its column updates. *(Core)*
- **R2.2** Reorder a card within a column; its position updates. *(Must)*
- **R2.3** Moves/reorders persist and survive reload. *(Must)*

### R3 — Ticket numbering *(Must)*
- **R3.1** Each card gets a `KAN-<n>` number auto-assigned at creation. *(Must)*
- **R3.2** Ticket number is immutable and never reused (even after delete). *(Must)*

### R4 — REST API (API-first) *(Core)*
- **R4.1** Every UI action has a matching `/api/*` endpoint; no UI-only backdoor. *(Core)*
- **R4.2** Auto-generated OpenAPI docs served at `/docs`. *(Must)*
- **R4.3** Dedicated `POST /api/cards/{id}/move` for column/position changes. *(Must)*
- **R4.4** Validation with standard JSON errors (title required, valid column, story points in set). *(Must)*

### R5 — Persistence *(Must)*
- **R5.1** PostgreSQL as the datastore. *(Must)*
- **R5.2** Schema managed by Alembic migrations from day one. *(Must)*
- **R5.3** Data persists across restarts/redeploys. *(Must)*

### R6 — Packaging & deployment *(Must)*
- **R6.1** Single deployable artifact: FastAPI serves the built Svelte SPA + API from one origin. *(Must)*
- **R6.2** SPA fallback routing coexists with `/api/*` and `/docs`. *(Must)*
- **R6.3** Deployed to a public URL (app on Fly.io, DB on Neon). *(Must)*
- **R6.4** Runtime config via env (`DATABASE_URL`); secrets via platform/GitHub. *(Must)*

### R7 — CI/CD *(Must)*
- **R7.1** On PR: run backend tests + frontend build/lint. *(Must)*
- **R7.2** On merge to `main`: build image and deploy to prod. *(Must)*
- **R7.3** Alembic migrations applied as part of deploy/startup. *(Must)*

### R8 — Testing baseline *(Must)*
- **R8.1** Backend `pytest` covering CRUD, move/reorder, ticket numbering, validation. *(Must)*
- **R8.2** Minimal frontend happy-path smoke test (load → create → move). *(Must)*

---

## Sketch S (Shapes)

Three mutually-exclusive approaches. The stack (Svelte 5/FastAPI/Postgres/Alembic/Fly/Neon,
single artifact) is fixed by the ADRs, so the shapes vary in **backend structure, card-ordering
mechanism, and frontend move/sync mechanism** — i.e. how much we build for the MVP appetite.
Each cell describes *what we build* (a mechanism), not an intention.

### Shape A — "Thin Slice" (minimal, ship fastest)

| Part | Mechanism |
|------|-----------|
| Backend structure | Single small FastAPI package: one SQLAlchemy model, Pydantic schemas, one `cards` router — no service/repository layers |
| Ordering mechanism | Integer `position`, kept contiguous per column; on move/reorder, renumber the affected column's rows 0..n inside one transaction |
| Move API | `POST /api/cards/{id}/move { column, position }`; server clamps + renumbers |
| Frontend DnD | `svelte-dnd-action` library for drag between and within columns |
| State sync | After every mutation, refetch `GET /api/cards` and re-render (no optimistic UI) |
| Seed data | Alembic data migration inserts demo cards when the table is empty |
| Serving | Multi-stage Dockerfile; FastAPI `StaticFiles` mount + SPA fallback route |
| Deploy | Fly.io app + Neon DB; migrations run via Fly release command |
| Testing | pytest API suite; one Playwright happy-path smoke |

### Shape B — "Layered & Optimistic" (robust, more structure)

| Part | Mechanism |
|------|-----------|
| Backend structure | Layered: `routers/` → `services/` (numbering, ordering, validation) → `repositories/` (SQLAlchemy); ORM models separate from Pydantic DTOs |
| Ordering mechanism | Gap/fractional rank — new position = midpoint between neighbors (spaced ints / LexoRank-lite); avoids per-move renumbering; occasional rebalance |
| Move API | `POST /api/cards/{id}/move { column, before_id \| after_id }`; server derives rank from neighbors |
| Frontend DnD | `svelte-dnd-action` + optimistic update: apply move locally instantly, call API, roll back on error |
| State sync | Optimistic local store reconciled with server response; refetch on window focus |
| Seed data | Dedicated seeding service run by a management command / startup hook |
| Serving | Same single-artifact (Dockerfile + StaticFiles + SPA fallback) |
| Deploy | Fly.io + Neon; migrations via explicit release step |
| Testing | pytest unit tests on services + API integration tests; Playwright smoke |

### Shape C — "API-first, buttons not drag" (lowest frontend risk)

| Part | Mechanism |
|------|-----------|
| Backend structure | Thin single-package FastAPI (as Shape A) |
| Ordering mechanism | None — cards ordered by `created_at` within a column; no manual reorder |
| Move API | `POST /api/cards/{id}/move { column }` only (no position); appends to target column |
| Frontend DnD | No drag-and-drop; each card has a "Move ▸" dropdown/buttons to send it to another column |
| State sync | Full refetch after each mutation |
| Seed data | Startup script inserts demo cards when empty |
| Serving | Same single-artifact |
| Deploy | Fly.io + Neon; migrations on startup |
| Testing | pytest API suite; simple smoke test |

## Fit Check (R × S)

Binary fit only (✅ passes / ❌ fails). Notes explain every ❌.

| Requirement | A (Thin Slice) | B (Layered+Optimistic) | C (Buttons, no drag) |
|-------------|:--:|:--:|:--:|
| R0 Board view (3 cols, render, stable order, seed) | ✅ | ✅ | ✅ |
| R1 Card CRUD | ✅ | ✅ | ✅ |
| **R2.1 Drag between columns** | ✅ | ✅ | ❌ |
| **R2.2 Reorder within column** | ✅ | ✅ | ❌ |
| R2.3 Moves persist | ✅ | ✅ | ✅ |
| R3 Ticket numbering | ✅ | ✅ | ✅ |
| R4 REST API + OpenAPI + move endpoint + validation | ✅ | ✅ | ✅ |
| R5 Persistence (Postgres + Alembic) | ✅ | ✅ | ✅ |
| R6 Packaging & deployment (single artifact, Fly+Neon) | ✅ | ✅ | ✅ |
| R7 CI/CD (GitHub Actions) | ✅ | ✅ | ✅ |
| R8 Testing baseline | ✅ | ✅ | ✅ |

### Notes on failures
- **C / R2.1:** Shape C replaces drag with a "Move ▸" dropdown, so it fails the explicit
  *drag between columns* requirement (Core in REQS.md).
- **C / R2.2:** Shape C has no within-column ordering, so manual reorder is impossible.

### Appetite read (tie-breaker between A and B, which both pass)
Both A and B satisfy every requirement, so the fit check doesn't separate them — the **appetite**
does. B's layered structure, fractional ranking, and optimistic-with-rollback UI are more robust
but are **more machinery than a ship-fast MVP calls for** (over the appetite). A delivers the same
requirement coverage with the least code. No requirements were left uncovered, and the choice is
unambiguous → **no spikes needed (step C5 skipped)**.

### Minor consideration (not a flag)
For future agents, A's move API takes an absolute `position` integer, whereas B's takes
`before_id`/`after_id` (neighbor-relative). B's is arguably friendlier for agents, but A's is fine
for the MVP and simpler; revisit if/when the MCP/CLI clients are built (ADR 0005). Logged, not
blocking.

## Selected shape

**Shape A — "Thin Slice".** Rationale: it passes 100% of the fit check, matches the small MVP
appetite (ship fast, fewest moving parts), and aligns with the standing "go simpler / MVP-suited"
guidance. Shape B is a sound *later* evolution (adopt fractional ranking + layering when scale or
concurrency demands it — see R4 minor consideration and ADR 0007 future work). Shape C is rejected
for failing the Core drag requirement (R2.1/R2.2).

## Detailed shape (Shape A — "Thin Slice")

Concrete component breakdown. Every part is understood — no ⚠️ remain (see "Resolved unknowns").

### Repository layout
```
simple-kanban/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app: include API router, mount static, SPA fallback
│   │   ├── db.py            # engine + SessionLocal + get_db() dependency
│   │   ├── models.py        # SQLAlchemy Card model
│   │   ├── schemas.py       # Pydantic: CardCreate / CardUpdate / CardMove / CardRead
│   │   ├── ordering.py      # renumber_column() helper
│   │   └── routers/cards.py # /api/cards endpoints
│   ├── alembic/             # env.py, versions/ (schema + seed migrations)
│   ├── alembic.ini
│   ├── pyproject.toml       # uv-managed deps
│   └── tests/               # pytest API suite
├── frontend/
│   ├── src/
│   │   ├── lib/api.ts       # typed fetch wrapper over /api
│   │   ├── lib/board.svelte.ts   # board state (runes)
│   │   └── lib/components/{Board,Column,Card,CardForm}.svelte
│   ├── App.svelte, main.ts, index.html
│   ├── vite.config.ts       # dev proxy /api → :8000; build base "/"
│   └── package.json
├── Dockerfile               # multi-stage: build SPA → assemble Python image
├── fly.toml                 # release_command = "alembic upgrade head"
├── docker-compose.yml       # local Postgres for dev/CI
└── .github/workflows/{ci.yml, deploy.yml}
```

### Backend components
| Component | Concrete mechanism |
|-----------|--------------------|
| **Card model** (`models.py`) | Table `card`: `id` PK, `ticket_number` (unique), `title`, `description` (null), `column` (varchar), `position` (int), `story_points` (int null), `assignee` (null), `created_at`, `updated_at` (timestamptz, server defaults) |
| **Ticket number** | Postgres `SEQUENCE card_ticket_seq`; column `server_default = text("'KAN-' || nextval('card_ticket_seq')")` → assigned atomically at INSERT, immutable, never reused |
| **Column value** | Stored as `varchar` validated by a Python `Enum` (`todo`/`in_progress`/`done`) in Pydantic + a DB CHECK constraint — avoids native-PG-enum migration pain, easy to extend later |
| **Schemas** (`schemas.py`) | `CardCreate{title!, description?, column?=todo, story_points?, assignee?}`, `CardUpdate{...all optional}`, `CardMove{column, position}`, `CardRead{all fields}`; `story_points` validated ∈ {1,2,3,5,8,13}∪null |
| **Endpoints** (`routers/cards.py`) | `GET /api/cards`, `POST /api/cards`, `GET/PATCH/DELETE /api/cards/{id}`, `POST /api/cards/{id}/move` |
| **Ordering** (`ordering.py`) | `renumber_column(db, column)`: load column's cards ordered by `position`, reassign `position = 0..n`. Create appends (position = count). Move: in one transaction insert card at clamped index in target column, then renumber target (and source if different) |
| **DB session** (`db.py`) | Synchronous SQLAlchemy 2.0 + `psycopg` (v3) driver; `SessionLocal`; `get_db()` FastAPI dependency; `DATABASE_URL` from env |
| **Static + SPA** (`main.py`) | Register API router + `/docs` first; mount built assets; catch-all `GET /{path:path}` returns `index.html` for non-`/api`/`/docs` paths (client-side routing) |
| **Seed** | Alembic data migration inserts ~4–6 demo cards across columns when the table is empty (runs once on a fresh DB) |

### Frontend components
| Component | Concrete mechanism |
|-----------|--------------------|
| **API client** (`api.ts`) | Thin `fetch` wrapper: `listCards`, `createCard`, `updateCard`, `deleteCard`, `moveCard`; throws on non-2xx with parsed JSON error |
| **Board state** (`board.svelte.ts`) | Svelte 5 runes store holding cards; derived grouping by column, sorted by position; `refetch()` after every mutation (no optimistic UI) |
| **Board / Column / Card** | `Board` renders three `Column`s; `Column` lists its `Card`s; `Card` shows ticket #, title, points, assignee + edit/delete controls |
| **Drag & drop** | `svelte-dnd-action` for drag between & within columns; on drop, call `moveCard(id, {column, position})` then `refetch()` |
| **Create/Edit** (`CardForm.svelte`) | Modal/inline form for create + edit; client-side required-title check mirrors server validation |
| **Dev proxy** | `vite.config.ts` proxies `/api` → `http://localhost:8000` in dev (no CORS); prod is same-origin |

### Packaging, deploy, CI/CD, testing
| Component | Concrete mechanism |
|-----------|--------------------|
| **Dockerfile** | Stage 1: Node builds SPA (`npm ci && npm run build`). Stage 2: Python image, install backend via `uv`, copy built SPA into a static dir FastAPI serves; run `uvicorn app.main:app` |
| **docker-compose** | Local Postgres 17 for dev + CI parity; app reads `DATABASE_URL` pointing at it |
| **fly.toml** | App config; `release_command = "alembic upgrade head"` runs migrations (incl. seed) before each release; `DATABASE_URL` set as a Fly secret pointing at Neon |
| **CI** (`ci.yml`) | On PR: spin up Postgres service, `alembic upgrade head`, run `pytest`; separately `npm ci && npm run build && npm run lint`; run Playwright smoke |
| **Deploy** (`deploy.yml`) | On push to `main`: build image + `flyctl deploy`; auth via `FLY_API_TOKEN` secret |
| **Tests** | Backend `pytest`: CRUD, ticket-number assignment + immutability, story-point & column validation, ordering after move/reorder, delete leaves gaps but order intact. Frontend: one Playwright smoke (load → create → move) |

### Resolved unknowns (would-be ⚠️, now decided)
1. **Ticket numbering** → Postgres `SEQUENCE` + column `server_default`; atomic, immutable, no reuse. *(Resolved)*
2. **Column enum representation** → `varchar` + Python-enum/Pydantic validation + CHECK constraint (not native PG enum), for painless future extension. *(Resolved)*
3. **Move/reorder algorithm** → transactional insert-at-index then `renumber_column` to contiguous 0..n; O(column size), trivial at MVP scale. *(Resolved)*
4. **SPA + API routing precedence** → API & `/docs` registered before the catch-all `index.html` fallback. *(Resolved — Q-A2.3 closed)*
5. **`svelte-dnd-action` on Svelte 5** → current versions support Svelte 5; **fallback** = native HTML5 drag events if any incompat arises. *(Resolved with fallback)*
6. **Sync vs async SQLAlchemy** → synchronous SQLAlchemy 2.0 + `psycopg` v3, for MVP simplicity. *(Resolved)*
7. **Tooling** → backend deps via `uv`, Python 3.12; frontend via `npm`, Node 20+. *(Resolved)*
8. **Migrations in prod** → Fly `release_command = alembic upgrade head`; seed is a one-time data migration. *(Resolved)*

### Ripple check (shaping → upstream docs)
Detailing surfaced only implementation-level specifics that are consistent with existing docs. Items
to fold in during step E (final grill): sync-SQLAlchemy + `psycopg`, `uv`/`npm` tooling, `varchar`+
CHECK for the column field, and the Vite dev-proxy. No contradictions with REQS/CONTEXT/PRD/ADRs;
no requirement changes. **Shape A is ready to breadboard.**

