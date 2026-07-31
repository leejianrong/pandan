You're picking up an in-progress project on disk: `simple-kanban`, a deployed kanban app
(FastAPI + sync SQLAlchemy/psycopg on Postgres, Svelte 5 + Vite SPA served as one artifact; a
stdio MCP server in `mcp/`). It's live at https://simple-kanban-jian.fly.dev with CI/CD to Fly.io.

Milestones 1 and 2 are complete. **Milestone 3 (Accounts, Boards & Agent Access)** is nearly done —
V6–V9 are built, merged to `main`, and deployed:
- **V6 (ADR 0011):** human GitHub OAuth login + revocable cookie session (fastapi-users on a SECOND
  async engine beside the sync one).
- **V7 (ADR 0012):** multi-board with ownership (`board` table, NOT NULL `board_id` on card+epic,
  `/api/v1/boards` CRUD, board switcher).
- **V8 (ADR 0013):** board authorization — `/api/v1` is auth-required and owner-gated. One sync
  principal resolver in `backend/app/authz.py` (`get_principal`): cookie session → `User`, else a
  valid `API_TOKENS` bearer → a transitional **SERVICE** sentinel that bypasses ownership, else 401;
  `authorize_board` allows only the board's owner (else 403); lists are owner-scoped. First login
  claims unclaimed boards.
- **V9 (ADR 0014):** self-serve agent **personal access tokens** — `personal_access_token` table
  (migration `0006`), hashed HMAC-SHA256 (`app/tokens.py`), a sync PAT branch in `get_principal`
  (bearer → owning `User`), `/api/v1/tokens` CRUD, and a Tokens UI. A PAT acts as its owning user and
  is owner-gated exactly like a human.

Build the LAST slice, **V10 (MCP board-scoping + PAT auth)**, which completes Milestone 3. Follow the
same slice-behind-a-PR cadence.

READ THESE FIRST — they are authoritative:
- CLAUDE.md — repo conventions (branch/PR workflow, commands, architecture, ADRs). Follow exactly.
- docs/milestone-3/SLICES.md (§ V10), SHAPING.md (Shape part **A7**), BREADBOARD.md (place **S6**).
- docs/adr/0010 (`API_TOKENS`, being retired), 0013 (board authz), 0014 (agent PATs).
- Current code: mcp/pandan_mcp/{config,api,server}.py + mcp/tests/, backend/app/authz.py,
  backend/app/auth.py, backend/app/routers/tokens.py, backend/tests/integration/conftest.py,
  frontend/e2e/helpers.ts + frontend/playwright.config.ts, .mcp.json.example.

IMPORTANT — verify against the code, don't trust docs blindly. Re-confirm current behavior first.

WHAT V10 IS (two parts):

**Part A — MCP board-scoping (the feature).** Today the MCP tools send NO `board_id`, so `list_cards`
spans all the caller's boards and `create_card`/`create_epic` land on the globally-earliest board.
Make the agent work across **multiple boards dynamically** — note the API ALREADY supports this
(it's owner-scoped: `GET /boards`, `GET /cards?board_id=`, and `board_id` in create payloads all
work today). This is a thin MCP-client adapter (API-first, ADR 0005), not a backend feature.
- Add discovery tools: `list_boards()` (→ id + name of all your boards) and `create_board(name)`.
- Add an optional per-call `board_id` to the board-scoped tools: `list_cards`, `create_card`,
  `create_epic`, and a new `list_epics(board_id?)` for parity. `get_card`/`update_card`/`move_card`/
  `delete_card` are card-id-addressed and need no `board_id` (the server authorizes via the card's
  own board).
- Add an optional `KANBAN_BOARD_ID` env as the DEFAULT when a call omits `board_id`.
- Map errors clearly: 403 → "that board isn't yours", 401 → "bad/expired token".
- Update `.mcp.json.example` + `mcp/README.md` (board scoping + that a real PAT is now required).
- Net UX: the agent calls `list_boards`, then targets any of the caller's boards per call — switching
  boards at call time, no restart. Access is bounded to boards the PAT's user owns (403 otherwise).

**Part B — retire the transitional `API_TOKENS` SERVICE bypass.** Now that agents use real PATs,
remove the bypass V8 left in place:
- Remove the `SERVICE` sentinel + the `API_TOKENS` branch from `app/authz.py` (so `get_principal` is
  cookie-or-PAT-or-401; `authorize_board`/`visible_board_ids`/`require_user` simplify — every
  principal is now a real `User`).
- Delete `app/auth.py`'s `API_TOKENS` reading (keep the bearer scheme the PAT branch needs).
- ADR 0010 becomes fully superseded/retired.
- OPS (call this out in the PR): drop the `API_TOKENS` Fly secret. (Won't affect the maintainer —
  they're already on a PAT.)

DECISIONS ALREADY MADE (locked in by the maintainer):
- **Dynamic multi-board via per-call `board_id` + `list_boards`/`create_board` discovery + optional
  `KANBAN_BOARD_ID` default** — NOT a single pinned board.
- **Retire the `API_TOKENS` SERVICE bypass in this slice** (Part B).

FORKS TO CONFIRM WITH THE MAINTAINER BEFORE BUILDING (ask, with a recommendation, like prior
kickoffs):
1. **No-board-specified fallback.** When neither a per-call `board_id` nor `KANBAN_BOARD_ID` is given:
   error out ("pick a board — call list_boards"), or keep today's fallback (list = all your boards;
   create = earliest owned board)? (Recommend: keep the fallback, but make `list_boards` the obvious
   entry point.)
2. **Cross-user test cleanup after SERVICE removal (the real hazard).** The e2e cleanup helpers and a
   few backend tests currently use the unscoped `API_TOKENS` SERVICE bearer to act across users.
   Removing it needs a replacement: per-user cleanup (each throwaway test user cleans its own boards)
   vs introducing a real `is_superuser` admin bypass. (Recommend: per-user cleanup — don't add an
   admin capability that isn't a product requirement — but flag the tradeoff.)

⚠️ THE BIGGEST PRACTICAL HURDLE IS THE TEST HARNESS (Part B) — plan for it up front:
- `backend/tests/integration/conftest.py` has a `service_client` fixture (sets `API_TOKENS` + a
  bearer). Removing SERVICE means reworking it and every test that uses it:
  - `test_auth.py` — the SERVICE-token tests (and the whole "API_TOKENS" model) go away; this file
    largely becomes "unauthenticated → 401" + PAT is covered in test_tokens.
  - `test_boards.py::test_default_board_exists_and_is_unclaimed` — observes the unclaimed default
    board via `service_client`; replace with a direct DB check or a logged-in observation.
  - `test_tokens.py::test_service_principal_cannot_manage_tokens` — no more SERVICE principal; drop
    or repurpose.
- e2e: `frontend/e2e/helpers.ts` cleanup helpers send `Authorization: Bearer e2e-service-token`, and
  `frontend/playwright.config.ts` sets `E2E_AUTH_BYPASS` + `API_TOKENS` on the backend webServer.
  Decide cleanup per fork #2; you can likely keep `E2E_AUTH_BYPASS`/test-login and drop `API_TOKENS`.
- Keep the whole suite green: backend ruff + pytest (unit + integration), the `mcp` job, frontend
  check/build/e2e.

TESTS (fold into the slice):
- MCP unit (mcp/tests, mocked httpx): each tool sends the right `board_id` + bearer; `list_boards`/
  `create_board` hit the right endpoints; 401/403 error mapping; the tool-list smoke includes the new
  board tools.
- Backend: rework the SERVICE-dependent tests (above); confirm authz still holds (owner 200,
  non-owner 403, unauthenticated 401) with cookie + PAT only.
- e2e: cleanup works without the SERVICE bearer; the existing specs stay green.
- Acceptance: an agent via MCP lists boards, creates/moves cards on a CHOSEN board, and is blocked
  (403) from a board it doesn't own.

DOCS (fold in): write ADR 0015 (MCP board-scoping + retiring `API_TOKENS`, superseding 0010). Mark
V10 built in docs/milestone-3/SLICES.md. Update CLAUDE.md (built/slice tables — V10 built, drop
`API_TOKENS` from config/conventions, ADR index → 0015). Update mcp/README.md + .mcp.json.example
(board scoping; `KANBAN_BOARD_ID`).

WORKFLOW (per CLAUDE.md — follow exactly):
1. `git switch main && git pull --ff-only`, then `git switch -c feat/mcp-board-scoping`.
2. The pre-push hook is symlinked in .git/hooks; if not: `ln -sf ../../scripts/git-hooks/pre-push
   .git/hooks/pre-push`.
3. Local dev: `docker compose up -d db`; from backend/ `uv run alembic upgrade head` before the app.
   MCP from mcp/ (`uv sync`, `uv run pytest -q`, `uv run ruff check .`). e2e via `npm run e2e`.
4. Verify locally before the PR: backend ruff + unit + integration, mcp ruff + tests, frontend
   check + build + e2e — all green.
5. Small logical commits (MCP client changes; SERVICE removal; test rework; docs/ADR). Open a PR to
   main with a clear description that CALLS OUT the ops step (drop the `API_TOKENS` Fly secret) and
   the contract change. DO NOT self-merge — main is protected/PR-only. End commit messages with
   `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` and PR bodies with the
   "Generated with Claude Code" line.

This slice is small in new code but touches security (removing the bypass) and the test harness, so
if the SERVICE-removal/test-cleanup story fights the plan, STOP and flag it rather than guessing.
Completing it finishes Milestone 3 — the milestone demo is dogfooding (an agent keeps this repo's own
board current via MCP + a PAT).
