---
shaping: true
---

# Milestone 5 — Slices (Shape A)

Vertical increments of the [Shape A breadboard](BREADBOARD.md). Each
ends in **observable behaviour** and ships as its own PR behind CI, matching the M1–M4 cadence.

Numbering continues the **global V-series** (M2 = V1–V5, M3 = V6–V10; M4 was tracked directly on the
board as EPIC-3…EPIC-17 rather than V-numbers). **M5 is V11–V19.**

Order respects dependencies: card fields (V11) are the inputs dispatch and triage need; dispatch
(V12) and the handoff flag (V13) are the agent-operate core; query/saved-views (V14) + search (V15)
feed the awareness dashboard (V16); reporting (V17) rides the activity feed. Scoped tokens (V18) and
batch/templates (V19) are the *Later / Nice-to-have* tail — the milestone demos complete without them.

Every slice includes **API + MCP + CLI parity** for what it adds (R1.3) — the endpoint first, then
the MCP tool + `kan` verb, then any UI.

| Slice | What | Parts | Ends in (demo) |
|-------|------|-------|----------------|
| **V11 · Card fields** ✅ | priority, labels, due date | A1 | Set `priority`/`label`/`due` on a card via `kan`; badges/chips/overdue pill render in the UI; filter the list by them |
| **V12 · Dispatch + fleet-safe claim** ✅ | next-ready + atomic claim | A2 | Two agents call `dispatch` at once → each gets a *different* ready card, both now `in_progress` with distinct assignees; `kan next`/`kan claim` |
| **V13 · needs-human handoff** ✅ | the `needs_human` flag | A3 | An agent flags a card `needs-human` with a note via `kan`; it shows in a "needs attention" filter; clearing it + a comment lets the agent see it's resolved |
| **V14 · Query depth + saved views** ✅ | JQL-lite filters + saved views | A5 | Save a view "needs me" (filtered) and switch to it in the UI; the same filter grammar works from `kan list` |
| **V15 · Full-text search** ✅ | Postgres FTS | A6 | `kan list --q "login"` and a UI search box find matching cards, ranked |
| **V16 · Awareness dashboard** ✅ | mission control | A7 | The Dashboard shows in-flight-by-agent (+ PR/CI), a needs-attention list, the activity feed, and a table view — all read-only, refreshing |
| **V17 · Fleet reporting** ✅ | derived metrics | A8 | `GET /boards/{id}/metrics` (and `kan`) returns throughput / cycle time / aging / per-assignee; small charts in the UI |
| **V18 · Scoped tokens** ✅ *(Later)* | observer vs operator PAT | A4 | Create a read-only PAT; a write via it → `403`; a write PAT still works |
| **V19 · Batch + templates** ✅ *(Nice-to-have)* | bulk ops + templates | A9 | Seed a plan from a template in one call; batch-update several cards at once |

> **Status (all 7 must-haves shipped + deployed + prod-verified):** V11–V17 ✅, plus the *Later*
> slice V18 ✅ and the *Nice-to-have* tail V19 ✅ — **M5 complete**. Per-slice "Shipped (KAN-…)" notes
> below record what each landed.

---

## V11 · Card fields (priority, labels, due date)

- **Build:** additive migrations — `card.priority` (`varchar` + CHECK `none/low/medium/high/urgent`,
  default `none`), `card.due_date` (`timestamptz` null); `label` table (`board_id` FK, `name`,
  `color`) + `card_label` M:N join. Schemas expose the fields; the query API gains `priority=`,
  `label=`, `due_before=`/overdue filters. MCP tools + `kan` (`create`/`update` flags, label
  create/list, list filters). UI: priority badge, colored label chips, due/overdue pill on the card
  (display + the create/edit form gains the selectors — the one place UI editing is retained).
- **Tests:** integration — set/read each field; CHECK rejects a bad priority; label is board-scoped
  (can't attach another board's label → 422); filters return the right subsets. Unit — schema
  validation. e2e — chips/badge render.
- **Acceptance:** the demo above; full suite green. Additive migration (deploys, prod-verify).

## V12 · Dispatch + fleet-safe claim

- **Build:** `POST /api/v1/boards/{id}/dispatch` — one transaction selecting the next `todo`,
  not-blocked card ordered `priority DESC, position` with `FOR UPDATE SKIP LOCKED`, setting `assignee`
  (from body/token) + moving to `in_progress`, recording activity, returning the card (or `204` when
  none ready). `GET /api/v1/boards/{id}/next` peeks without claiming. Authz `Access.WRITE`. MCP
  `dispatch`/`next` + `kan next [--claim] [--assignee] [--label] [--priority]`.
- **Tests:** integration — **concurrency test** (two sessions dispatch against a 1-card board; exactly
  one gets it, the other `204`); dispatch skips blocked cards and respects priority order; empty board
  → `204`. The `SKIP LOCKED` behaviour is the correctness crux — test it directly.
- **Acceptance:** the two-agents-no-collision demo; suite green. No migration (behaviour on existing
  columns) — still app-code, so it deploys.

## V13 · needs-human handoff

- **Build:** additive `card.needs_human` (bool default false) + `card.attention_note` (text null);
  CHECK-vocabulary migration adding `attention` + `resolved` activity actions (mirror EPIC-4's
  `restored`). `POST /cards/{id}/needs-human` (sets flag + note + activity) and `…/resolve` (clears +
  activity). Query filter `needs_human=true`. Resolution channel = the existing comments. MCP + `kan`
  verbs. UI: a needs-human badge on the card (full surfacing is V16).
- **Tests:** integration — raise → appears under `needs_human=true` + an `attention` activity row;
  resolve → cleared + `resolved` row; a comment round-trips. Auth gated.
- **Acceptance:** the flag/resolve demo; suite green. Additive migration (deploys, prod-verify).

## V14 · Query depth + saved views

- **Build:** extend the V3 query API with `priority`/`label`/`due`/`needs_human`/`assignee` filters +
  `sort`, sharing one filter grammar (structured JSON). `saved_view` table (`board_id`, `name`,
  `query` JSON); `GET/POST/DELETE /api/v1/boards/{id}/views`. MCP + `kan view` verbs. UI: a saved-view
  switcher + a table/list view honoring the active view.
- **Tests:** integration — each filter + combinations; save/list/delete a view; a view's query
  reproduces its result set. e2e — switch views.
- **Acceptance:** save + switch "needs me"; suite green. Additive migration.
- **Shipped (KAN-247):** `GET /cards` gained an `assignee` filter + a `sort` grammar — comma-separated
  keys, `-` prefix = descending (`sort=-priority,position`); `priority` sorts by rank (none→urgent),
  NULLs sink, `id` is the stable tiebreaker; valid fields: `position`/`priority`/`due_date`/
  `created_at`/`updated_at`/`story_points`/`assignee`/`title`/`column`/`id`. A custom `sort` overrides
  the keyset order, so it is rejected with `cursor` (422) and emits no `X-Next-Cursor`. The grammar is
  one Pydantic model (`schemas.CardQuery`, field names = the `GET /cards` params) reused by the query
  API and the saved-view store; the SQL sort builder lives in `app/card_query.py`. `saved_view`
  (`id, board_id FK CASCADE, name, query JSON, created_at`, migration `0016_saved_views`) is CRUD'd
  at `GET/POST/GET-one/DELETE /api/v1/boards/{id}/views` (READ to list/get, WRITE to create/delete;
  cross-board id → 404). A view's stored `query` (e.g. `{"priority":"high","assignee":"me","sort":
  "-priority"}`) replays verbatim as `GET /cards` params — reproduction by construction. Parity:
  `kan view list|create|delete` + `kan list --assignee/--sort`; MCP `list_views`/`create_view`/
  `delete_view` + `list_cards` `assignee`/`sort`. UI: a query bar with a saved-view dropdown, live
  filters (priority/assignee/needs-human/sort), Save-view, and a board/table toggle (sortable table).

## V15 · Full-text search

- **Build:** Postgres FTS — a `tsvector` (generated column or trigger) over `title`+`description`, GIN
  index (migration); `GET /api/v1/cards?q=` ranks by relevance (owner/member-scoped like the rest).
  MCP + `kan list --q`. UI: a search box.
- **Tests:** integration — `q` matches title and description, ranks, respects board access; empty `q`
  is a no-op. e2e — search returns hits.
- **Acceptance:** search demo; suite green. Additive migration.

## V16 · Awareness dashboard (mission control)

- **Build:** a read-first **Dashboard** view (new nav entry): in-flight-by-assignee (join work-links +
  auto-sync PR/CI status), a needs-attention list (from V13), the deepened activity feed (filter by
  actor/action — API gains `actor=`/`action=` on the activity endpoint), and the table + saved-view
  switcher (V14). Poll/refresh only (no websockets). No new write path.
- **Tests:** integration — activity filters; the in-flight query. e2e — dashboard renders in-flight,
  needs-attention, activity; light + dark screenshots (CI-safe via `testInfo.outputPath`).
- **Acceptance:** the mission-control demo; suite green. Frontend + small API extension — deploys.
- **Shipped (KAN-249):** the **Dashboard** nav view (`frontend/src/lib/components/Dashboard.svelte`,
  state in `dashboard.svelte.ts`) composes, for the active board: a headline **stat strip**
  (completed / in-progress / needs-attention / median cycle time), **in-flight-by-assignee** (cards in
  `in_progress` grouped by assignee, each with its PR/work-link chips + handoff/blocked badges),
  **needs-attention** (V13's `needs_human=true` cards with their `attention_note`), **flow metrics**
  (V17's `GET /boards/{id}/metrics` rendered as a per-assignee throughput/WIP grouped bar, an aging-WIP
  bar list with a *stale* flag, and a cycle-time stat readout — theme-aware CSS bars, no chart libs,
  teal/violet series validated CVD-safe with a legend + direct labels), a **recent-activity** feed
  filterable by actor/action, and an optional **board snapshot** reusing V14's `BoardTable`. Read-only,
  refresh-on-demand / on board switch (no websockets). The activity endpoint gained optional
  `actor=` (exact `actor_label`) + `action=` filters (AND-ed, compose with the cursor) — the only
  backend change; no migration.

## V17 · Fleet reporting

- **Build:** `GET /api/v1/boards/{id}/metrics` — throughput (done/period), cycle time
  (first-`in_progress`→`done` from the activity feed), aging WIP, per-assignee — all derived,
  no writes. MCP `metrics` tool + `kan metrics [--board] [--since] [--window]` (pretty + `--json`).
  UI: **deferred to V16** (the Dashboard, not yet built) — building a standalone metrics nav view now
  would collide with V14's frontend and be superseded by V16's mission-control charts; API + CLI +
  MCP ship the value. Charts, when added, follow the dataviz conventions.
- **Tests:** integration — seed activity (drive real moves, backdate ts), assert each metric; empty
  board → zeroed; window scoping; authz (READ-gated / 401 / 403 / 404). Unit — `parse_move_target` +
  the cycle-time/aging/throughput computation (`app.metrics`, pure).
- **Acceptance (shipped):** metrics via API + `kan metrics` + MCP `metrics`; suite green. No
  migration (app-code, so it deploys). UI charts deferred to V16.

## V18 · Scoped tokens *(Later)*

- **Build:** `personal_access_token.scope` (`read`/`write`, default `write` — existing PATs stay
  writers). Authz denies `Access.WRITE`+ to an agent principal on a `read` PAT (`403`). Tokens UI +
  `kan`/MCP surface the scope at creation.
- **Tests:** integration — a `read` PAT can GET but a write → `403`; a `write`/legacy PAT unaffected.
- **Acceptance:** observer-token demo; suite green. Additive migration.
- **Shipped (KAN-251):** `personal_access_token.scope` added as a `varchar`+CHECK (`read`/`write`)
  with `server_default 'write'` — every pre-V18 PAT stays an operator (migration `0020_pat_scope`,
  additive). Enforcement lives in the **one chokepoint**, `app.authz.get_principal`: `_resolve_pat`
  stashes the PAT's scope on the resolved principal, and a `read`-scoped PAT is denied any unsafe
  HTTP method (POST/PATCH/PUT/DELETE — every board write *and* per-user writes like `POST /tokens`)
  with **403** (authenticated, not authorized); GET/HEAD/OPTIONS pass. Cookie-session humans and
  `write`/legacy PATs are unaffected (no `_pat_scope`, or a `write` one). `scope` is accepted
  (default `write`, enum-validated) on `POST /tokens` and returned on token read/list; the **Tokens
  UI** has an operator/observer selector at creation and shows each token's scope. Token creation is
  **API/UI-only** — the `kan` CLI and MCP server only *consume* a PAT (`KANBAN_TOKEN`), they have no
  token-create verb, so there was nothing to surface there (the "kan/MCP surface" line above was
  aspirational; scope is surfaced everywhere creation actually happens).

## V19 · Batch + templates *(Nice-to-have)*

- **Build:** batch create/update endpoints (or extend existing); card/board templates (a `template`
  store + apply). MCP + `kan` verbs.
- **Tests:** integration — batch creates N cards atomically; apply a template yields the expected
  cards.
- **Acceptance:** seed-a-plan-from-template demo; suite green.
- **Shipped (KAN-252):** two additive capabilities, built **on** the pre-existing batch-*create*
  (KAN-40's `create_cards` client method + MCP `create_cards` tool — a client-side, fail-fast loop
  over `POST /cards`, *not* a server endpoint; left as-is).
  - **Batch update** — a new **atomic** `PATCH /api/v1/cards/batch` taking a non-empty JSON array of
    `{id, ...fields}` (the same field edits as single `PATCH /cards/{id}`: title/description/
    story_points/assignee/epic_id/priority/due_date/label_ids; **not** column/position — those stay on
    `/move`, ADR 0006). **All-or-nothing** in one transaction: a missing/soft-deleted id → **404**,
    a duplicate id → **422**, an empty body → **422**, a card on a board you can't write → **403**, a
    per-card validation failure → **422**; on any of these nothing commits. Records one `updated`
    activity row per card. The single-PATCH handler was refactored to share `_apply_card_update`.
  - **Card templates** — a new `card_template` table (migration `0021_card_templates`, additive,
    mirrors `saved_view`: `id, board_id FK ON DELETE CASCADE, name, cards JSON, created_at`) storing a
    named, board-scoped list of card payloads. CRUD-lite + apply under the board (mirrors the
    saved-views router): `GET/POST /boards/{id}/templates`, `GET/DELETE …/{tid}`, and **`POST
    …/{tid}/apply`** which instantiates the template's cards on the board in **one transaction**
    (reusing the cards router's extracted `_create_card_row`), returning the created cards — the
    seed-a-plan-in-one-call demo. Cross-board template id → **404**; READ to list/get, WRITE to
    create/delete/apply. Card templates only — board-level template (clone columns/settings) was
    **deferred** as scope creep for a nice-to-have tail slice.
  - **Parity (R1.3):** new `pandan-client` methods (`update_cards`, `list/create/get/delete/
    apply_template`), MCP tools (`update_cards`, `list/create/delete/apply_template`), and `kan` verbs
    (`batch-update <json>`, `template list/create/delete/apply`), all appended at the end of their
    lists. No UI (agent-facing capability).

---

> **Board mapping.** These slices are tracked on the *Simple Kanban Roadmap* board as M5 epics + cards
> (dogfooding, as always). See the EPIC-`M5:` epics; each V-slice above corresponds to one or more
> cards under the matching epic.
