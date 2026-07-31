---
shaping: true
---

# Milestone 2 — Slices (Shape A)

Vertical increments of the breadboard (`BREADBOARD.md`). Each ends in **observable
behaviour** and ships as its own PR behind CI (R8), matching the MVP cadence. Order
respects dependencies: V5 (MCP) needs the versioned path (V2), token (V4), and query (V3);
V1 is foundational + immediately visible.

| Slice | Parts | Ends in (demo) |
|-------|-------|----------------|
| **V1 · Epic entity + story links** | P1, P1-v, UI | Create an epic in the Epics view (gets `EPIC-n`), link a story to it on the board; the story's epic-name tag + the epic's story rollup render and survive reload |
| **V2 · API versioning** | P3 | `/docs` shows `/api/v1/*`; SPA still works; `curl /api/v1/cards` (the temporary `/api` alias has since been dropped) |
| **V3 · Query API** | P4 | `curl "/api/v1/cards?column=done"`, `?epic_id=…`, `?updated_since=…`, `?limit=2` (+ `X-Next-Cursor` header) return the right filtered/paged results |
| **V4 · Agent token auth** | P2 | With `API_TOKENS` set: write without token → `401`, with token → `201`; reads open. Unset → open (unchanged) |
| **V5 · MCP server + Claude Code** | A5, A6 | Claude Code, via MCP, creates an epic + stories and moves one — the cards appear on the board. **The milestone demo.** |

---

## V1 · Epic entity + story links

> **Reshaped during build (ADR 0009).** The original sketch modeled an epic as a `card` with
> `kind='epic'` + a `parent_id` self-FK. Building it clarified that an epic is *not* a board card
> (no assignee/points, no column/position, its own `EPIC-` id, managed in a separate UI surface), so
> the epic became a **first-class entity** in its own table. What shipped is below.

- **Build:** new `epic` table (own `epic_ticket_seq` → `EPIC-n`; fields `name` + optional
  `description` only) + nullable `card.epic_id` FK (`ON DELETE SET NULL`); Alembic `0003`. New
  `/api/epics` CRUD; add `epic_id` to `CardCreate`/`CardRead`/`CardUpdate`. Validation P1-v:
  `epic_id`, if set, must reference an existing epic (else 422). UI: board shows stories only, each
  with its epic-name tag; an epic selector in `CardForm` (create + edit); a separate **Epics view**
  (top-bar `Board | Epics` toggle) for epic create/read with a child-story rollup.
- **Tests:** integration — epic CRUD; independent `EPIC-`/`KAN-` sequences; create/PATCH story with
  valid `epic_id`; reject missing epic; clear link; delete-epic-detaches-stories. e2e — create an
  epic in the Epics view, link a story on the board, assert the tag + rollup and that they survive
  reload.
- **Acceptance:** the demo above works; full suite green.

## V2 · API versioning (`/api/v1`) — **Built**

> **Built as shaped, extended to cover epics (V1 landed after this was written).** Both the
> `cards` **and** `epics` routers were re-prefixed and dual-mounted, and the `epics` refs in
> `api.ts` / e2e moved to `/api/v1` alongside the card ones. Reference counts differed from the
> pre-V1 spike: `api.ts` had **8** `fetch` calls (5 card + 3 epic), e2e had **5** refs
> (helpers.ts ×4 for cards+epics cleanup, smoke.spec.ts route glob ×1).
>
> **Follow-up (done):** the temporary `/api` compat alias has since been dropped — the ~87
> backend-test literals were swept to `/api/v1` and the second `include_router` mount removed,
> so `/api/v1` is now the only prefix.

- **Build:** re-prefix both routers to `/cards` / `/epics`; in `main.py` mount each under
  `/api/v1`. (V2 also carried a temporary `/api` alias, since removed.) Migrate `api.ts` (8 refs,
  via an `API = "/api/v1"` base) + e2e (5 refs) to `/api/v1`. `/api/health` unchanged. (Per
  `spike-p3-versioning.md`.)
- **Tests:** `test_versioning.py` — `/api/v1/{cards,epics}` work, OpenAPI shows only `/api/v1/*`
  (the dropped alias is absent), `/api/health` stays unversioned. The rest of the suite runs
  against `/api/v1`.
- **Acceptance:** met — `/docs` lists only `/api/v1/*` (+ health); SPA + e2e green on `/api/v1`;
  `curl` confirms `/api/v1` for cards and epics.

## V3 · Query API (filter / pagination / changed-since) — **Built**

> **Built; param list corrected against the ADR-0009 schema.** The pre-V1 sketch listed `kind`
> and `parent_id`, neither of which exists now: a card is always a story (no `kind`), and the
> parent link is the nullable FK `card.epic_id` (not `parent_id`). Shipped params are `column`,
> `epic_id`, `updated_since`, `limit`, `cursor`. `updated_since` is **inclusive** (`>=`).
> Requesting unassigned stories (`epic_id IS NULL`) was left out of V3. `/api/v1/epics` stays a
> plain full list. The keyset cursor codec lives in `app/pagination.py` (unit-tested, DB-free).

- **Build:** `column`, `epic_id`, `updated_since`, `limit`, `cursor` on `GET /api/v1/cards`;
  keyset pagination ordered by `(updated_at, id)`; next cursor via the `X-Next-Cursor` response
  header (present only on a full page); **body stays a bare `CardRead[]`** (SPA unaffected — it
  re-sorts by `position` client-side); no params → full list.
- **Tests:** unit — cursor codec round-trip + malformed→ValueError. integration — each filter;
  `updated_since` inclusive boundary + excludes-older; combined filters AND; `limit` + cursor
  paging returns disjoint gap-free pages; last page omits the cursor; `(updated_at, id)` order;
  empty result; bad inputs (unknown column / malformed cursor / out-of-range limit → 422);
  back-compat (no params = all).
- **Acceptance:** met — the `curl` demos return correct filtered/paged results; SPA + e2e green.

## V4 · Agent token auth (writes) — **Built**

> **Built as shaped (ADR 0010); "both mounts" is moot** — the `/api` alias was dropped in the V2
> cleanup, so the guard applies to the single `/api/v1` mount. Extended to cover epic writes too.

- **Build:** `require_token` dependency ([backend/app/auth.py](../../backend/app/auth.py)) on every
  mutating route — cards **and** epics (POST/PATCH/DELETE/move). Tokens from `API_TOKENS` (comma-sep
  env, read per request). **Unset → writes open** (existing tests + local dev unaffected); set →
  enforced, `401` + `WWW-Authenticate: Bearer` on missing/bad. Reads always open. Uses
  `HTTPBearer(auto_error=False)` so `/docs` gets an Authorize button. Flat token list — scopes +
  revocation (R3.4) deferred.
- **Tests:** integration `test_auth.py` sets `API_TOKENS` — write without/with-bad token → `401`,
  with token → `201`/`200`/`204`, every mutating card + epic route guarded, GET open. One test pins
  the unset → open default. The rest of the suite runs with `API_TOKENS` unset (unchanged).
- **Acceptance:** met — the 401/201 demo works; SPA + e2e green (tokenless). **Prod opts in** by
  setting `API_TOKENS` as a Fly secret; until then prod writes stay open (unchanged).

## V5 · MCP server + Claude Code wiring — **Built**

- **Build:** `/mcp` package (own `pyproject.toml` + `uv.lock`) — official `mcp` SDK (FastMCP,
  stdio); seven tools `list_cards` / `get_card` / `create_card` / `create_epic` / `update_card` /
  `move_card` / `delete_card`, each a thin `httpx` wrapper over `/api/v1` (`api.py` →
  `server.py`). Config via `KANBAN_API_URL` + optional `KANBAN_TOKEN` (`config.py`); the token is
  sent as `Authorization: Bearer` and is only needed when the target has `API_TOKENS` set. `list_cards`
  exposes the V3 query params. `.mcp.json.example` at the repo root + `mcp/README.md` document Claude
  Code wiring (local + prod). CI gains a sixth job (mcp lint + tests); pre-push hook mirrors it.
- **Tests:** unit — each client method issues the expected request against a mocked httpx transport
  (method/path/params/body), sends the bearer header when a token is set, and maps non-2xx → a
  `PandanApiError` carrying the API's `detail`; a smoke asserting the server advertises exactly the
  seven tools with descriptions + schemas. Verified end-to-end over a real stdio MCP session against
  a live backend (create epic → create linked story → move → list), including the 401-without-token
  and 201-with-token paths against an auth-enabled backend.
- **Acceptance:** met — an MCP client lists/creates/moves cards over stdio and they appear on the
  board; token auth enforced end-to-end. Ready to connect Claude Code via `.mcp.json` and dogfood.

---

## Notes / decisions folded in

- **Pagination via header, not envelope** (P4): keeps `GET /cards` returning a bare array so
  the SPA `listCards(): Card[]` is untouched — back-compat over a cleaner envelope.
- **Auth off when `API_TOKENS` unset** (P2): preserves MVP/dev behaviour and avoids churning
  ~40 existing write tests; prod opts in via a Fly secret.
- **`/api` alias kept temporarily, then dropped** (P3): V2 shipped a hidden `/api` compat alias so
  the ~87 backend-test literals could move in a follow-up rather than in the same PR. That
  follow-up has since landed — the tests were swept to `/api/v1` and the alias removed, so `/api/v1`
  is now the sole prefix.
- **CI:** V5 adds an `/mcp` package — extend CI with an mcp unit-test job (mirrors the
  backend jobs); e2e/backend jobs unchanged.
