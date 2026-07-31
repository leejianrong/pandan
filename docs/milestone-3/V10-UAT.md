# V10 — User Acceptance Testing (MCP board-scoping + retiring `API_TOKENS`)

- **Date:** 2026-07-09
- **Slice:** V10 (ADR 0015) — completes Milestone 3
- **Environment:** production — `https://simple-kanban-jian.fly.dev` (Fly.io `iad`, machine version 20)
- **Tester:** Claude (acting as the AI agent), driving the **V10 MCP server** (`mcp/pandan_mcp`)
  against the deployed API with a real personal access token (`KANBAN_TOKEN`).

## 1. Deploy verification

PR [#22](https://github.com/leejianrong/simple-kanban/pull/22) merged to `main` at
`2026-07-09T07:00:59Z`; all six CI jobs (lint, unit, integration, frontend build, e2e, mcp) passed.
The `Deploy` workflow ran on the merge and **succeeded** (~1m9s).

Fly deploy was clean (no crash loop):

```
07:03:07  Preparing to run: sh -c alembic upgrade head && uvicorn app.main:app ...
07:03:13  INFO [alembic.runtime.migration] Context impl PostgresqlImpl
07:03:14  INFO: Application startup complete.
07:03:14  INFO: Uvicorn running on http://0.0.0.0:8000
```

`flyctl status`: single `app` machine `started`, image `deployment-01KX2TYEHRKP0EDXFVGX5RP8Y0`.

## 2. Deployed-contract checks (the V10 change)

| Check | Request | Expected | Result |
|-------|---------|----------|--------|
| Health | `GET /api/health` | `200 {"status":"ok"}` | ✅ |
| Auth required | `GET /api/v1/boards` (no auth) | `401` | ✅ 401 |
| **SERVICE bypass gone** | `GET /api/v1/boards` with a shared-token-style bearer | `401` (not a bypass) | ✅ 401 |

The third row is the security-relevant confirmation for Part B: a shared `API_TOKENS`-style bearer no
longer authenticates — only a cookie session or a per-user PAT does.

## 3. Agent session via the MCP server

The agent authenticated with a PAT and worked entirely through the V10 MCP tools. To avoid polluting
the maintainer's real boards, it operated on a **dedicated throwaway board** (which also exercises the
new `create_board` tool) and tore it down at the end.

| # | Tool call | Outcome |
|---|-----------|---------|
| 0 | `list_boards()` | Discovered 2 owned boards (`My Second Board` #2, `Kanban Board` #3) |
| 1 | `create_board("uat-v10-scratch")` | Created board **#4** (owned by the PAT's user) |
| 2 | `create_epic(board_id=4, …)` | `EPIC-2` created on board 4 |
| 3 | `create_card(board_id=4, …)` ×2 | `KAN-8` (todo, sp=3) and `KAN-9` (linked to `EPIC-2`) — both `board_id=4` |
| 4 | `list_cards(board_id=4)` / `list_epics(board_id=4)` | Returned exactly the 2 cards + 1 epic on board 4 |
| 5 | `move_card(KAN-8, "in_progress")` | Moved to `in_progress`, position 0 |
| 6 | `update_card(KAN-9, title=…, story_points=8)` | Fields updated |
| 7 | `get_card(KAN-8)` | Confirmed `in_progress` |
| 8 | `list_cards(board_id=1)` (not owned) | **Refused** — `404 Board not found` (see §5) |
| T | Teardown: `DELETE /api/v1/boards/4` | `204`; board list back to the original two — real data untouched |

Every board-scoped call correctly targeted the chosen board via per-call `board_id`; the
card-id-addressed tools (`move_card`/`update_card`/`get_card`) needed none.

## 4. Error-mapping check (agent-facing messages)

Driving the MCP server with a bad token, the agent sees the framed hint (raw server detail preserved):

```
401: bad or expired token — set KANBAN_TOKEN to a valid PAT (create one in the Tokens UI)
     (authentication required)
```

(The `403` hint — "that board isn't yours — call list_boards …" — is exercised in the automated
suite and the local two-user acceptance run; see §5.)

## 5. Notes & caveats

- **403 (foreign board) not reproducible on prod.** Owner-scoping means the agent can't even *see*
  another user's boards, and prod currently has a single user, so there is no foreign `board_id` to
  probe. The closest live signal is `board_id=1 → 404` (the agent correctly refuses to act on a board
  not in its owned set). The full `403` isolation guarantee is covered by:
  - backend integration tests (`test_authz.py`: non-owner `403` on every board-scoped route), and
  - the pre-merge **local live acceptance** with two distinct users (create → `403` on the other's
    board, both create and list).
- **Session tooling needs a reconnect.** The MCP server already connected in a running Claude Code
  session keeps the *old* 7-tool set until it is restarted; after reconnecting it advertises the 10
  V10 tools (`list_boards`, `create_board`, `list_epics` added). This UAT drove the freshly-built
  server code directly to test the deployed changes.
- **Ticket sequences advanced** (`KAN-8`/`KAN-9`, `EPIC-2`) and are not reused — by design (global,
  immutable `KAN-`/`EPIC-` sequences). Deleting the throwaway board removed its rows but not the
  consumed numbers; this is expected and harmless.
- **Ops reminder:** the `API_TOKENS` Fly secret can now be dropped — the mechanism no longer exists.

## 6. Verdict

**PASS.** V10 deployed cleanly and behaves as specified in production: an agent, via the MCP server
with a PAT, discovers its boards, creates/moves/updates cards and epics on a **chosen** board, is
refused boards it doesn't own, and gets clear `401`/`403` guidance. Milestone 3 is complete.
