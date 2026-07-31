# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status & the source of truth

The core board and **Milestones 2–6** are all shipped and deployed (live at
[simple-kanban-jian.fly.dev](https://simple-kanban-jian.fly.dev), full backend-pytest +
Playwright-e2e suite, CI/CD to Fly.io): M2 agent-driven task tracking (epics, `/api/v1`, query API,
MCP server), M3 accounts + multi-board ownership + auth, M4 board collaboration/trust/history + GitHub
PR auto-sync + agent-CLI ergonomics, M5 agent↔human handoff + awareness UI + fleet reporting, M6
abuse hardening + projects + cycles + design system + notifications.

**Milestone 7** ("Name & Sharpen the Tools", [docs/milestone-7/](docs/milestone-7/SLICES.md)) is
**in progress**. Its first slice, **V40 — the `simple-kanban` → `pandan` rebrand**
([ADR 0018](docs/adr/0018-pandan-rebrand.md), which also names the `kaya` notes sibling), has landed:
the product is **pandan**, the CLI is **`pandan`** (with a `pdn` alias), env config is **`PANDAN_*`**,
and newly minted PATs carry **`pandan_pat_`**. The rebrand changed no API, schema or migration.
[AXI](https://axi.md/) conformance for the CLI is well underway — V50 (release provenance), V42
(`--fields`), V43 (the error contract) and V47 (`--format {human,json,toon}`) have all landed, through
`v0.8.0`. What remains is V44–V46 plus V48, and then a right-sizing of the **49-tool** MCP surface
(V49) — measured at ~10,076 tokens of resident schema per session. **Per-slice status goes stale here
faster than anywhere else in this file; read [docs/milestone-7/SLICES.md](docs/milestone-7/SLICES.md)
and the board, not this paragraph.**

Three things the rebrand deliberately did **not** rename, so don't "finish" it:
- **The `KAN-` / `EPIC-` ticket prefixes** — immutable per-table Postgres sequences (ADR 0006/0009);
  renaming would split the board's own history. `KAN` is retconned as simply "kanban".
- **The deployed identity.** The app still lives at
  [simple-kanban-jian.fly.dev](https://simple-kanban-jian.fly.dev) under the Fly app
  `simple-kanban-jian`, with the same GitHub OAuth App and `AUTH_SECRET`. The Fly→Fly cutover was
  **deferred** (KAN-424, blocked on the k8s migration KAN-439) rather than paid twice.
  The in-place renames — which are a *different* thing, because they need no create-migrate-destroy
  cutover — are **KAN-437, and two of the three have now happened**: the **GitHub repo is
  `leejianrong/pandan`** and the **ghcr path is `ghcr.io/<owner>/pandan-mcp`**. Only the OAuth App
  *display name* is outstanding (cosmetic, a consent-screen field), plus a ghcr package-visibility
  flip that cannot happen until the next `v*` tag actually creates the renamed package — both are
  GitHub web-UI steps for the human owner. **The one thing still reading `simple-kanban` on purpose
  is the deployed origin**, `simple-kanban-jian.fly.dev`.
- **Session/wire/storage identifiers** — the `kanbanauth` cookie, the `X-Kanban-Event` outbound
  webhook header, the `kanban.*` logger names, the `kanban.theme` / `kanban.activeBoardId`
  localStorage keys, and the `kanban:kanban@…/kanban` local Postgres credentials. Each would log
  users out, break a consumer, or reset local state for no gain.

The pre-rebrand **`KANBAN_API_URL` / `KANBAN_TOKEN` / `KANBAN_BOARD_ID` still work as a deprecated
fallback** (read second, with a one-line notice on stderr), and a `kanban_pat_…` PAT still
authenticates indefinitely. Both are dead weight carried on purpose, scheduled for removal.

**This file is not the roadmap, and per-feature status written here goes stale — trust the code over
these docs, and when they disagree, fix the docs in the same PR.** Two places are kept current by
construction; look there for what's done and in flight:
- **The board itself.** The project dogfoods its own product: the *Pandan Roadmap*
  board on the deployed instance is the authoritative task list. Drive it with the `pandan` CLI
  ([pandan-cli/](pandan-cli/)) or the MCP server ([mcp/](mcp/)).
- **`docs/milestone-*/SLICES.md`** — the per-slice plan + status for each milestone, and the
  [ADRs](docs/adr/) for the *why* behind each decision (see §How the docs relate).

A running backend serves the live, authoritative API surface at **`GET /docs`** (OpenAPI). At a
glance it's a REST CRUD surface under `/api/v1` for **boards, cards (stories), epics, and PATs**,
plus a card `move` endpoint and an unversioned `GET /api/health` — **auth-required and owner-gated**
(see §Configuration and §Architecture). When extending the app, follow the shaped plan in
[docs/SHAPING.md](docs/SHAPING.md) + [docs/BREADBOARD.md](docs/BREADBOARD.md) and build in vertical
slices, matching the existing incremental style.

## Commands

> **Shortcut:** a root [`Makefile`](Makefile) wraps the sequences below. `make help` lists every
> target; `make up` runs the whole stack (db + app image serving the SPA) in one command via
> `docker compose up --build`, and `make dev` is the native hot-reload loop. The detailed commands
> below remain the source of truth for what each step does.

Backend uses **`uv`** (Python 3.12; see [backend/pyproject.toml](backend/pyproject.toml) + `uv.lock`).
Frontend uses **`npm`** (Node 20+). Run backend commands from `backend/`, frontend from `frontend/`.

**Local database** (from repo root) — required before running the backend:
```bash
docker compose up -d db        # Postgres 17 at kanban:kanban@localhost:5432/kanban
```

**Backend** (from `backend/`):
```bash
uv sync                                        # install deps (incl. dev group)
uv run alembic upgrade head                    # apply migrations
uv run uvicorn app.main:app --reload           # dev server on :8000; OpenAPI at /docs
uv run alembic revision --autogenerate -m "…"  # new migration (models must be imported in env.py)
uv run ruff check .                            # lint (matches the CI lint job)
uv run pytest tests/unit                       # fast: pure schema-validation logic, no DB/Docker
uv run pytest tests/integration                # full API vs a throwaway Postgres (needs a running Docker daemon)
uv run pytest tests/integration/test_x.py::test_name  # run a single test
```
> Tests are split into `tests/unit` (no DB) and `tests/integration` (real Postgres via
> testcontainers); the integration `client`/DB fixtures live in `tests/integration/conftest.py`,
> so integration tests must live under `tests/integration/`. **In integration tests, keep every
> `import app.*` inside the test/fixture body, never at module top** — a top-level app import runs at
> pytest collection (before the `_database` fixture sets `DATABASE_URL`), binding the engines to the
> wrong DB; it passes locally against your dev Postgres but fails CI (the PR #17 trap). A
> `pytest_collection_finish` guard in conftest + a `pytest --collect-only` step in the pre-push hook
> now catch this. CI runs lint, unit, integration, the
> frontend build, and Playwright e2e as five independent jobs (see `.github/workflows/ci.yml`); the
> e2e job uses a Postgres service container and caches the Chromium download by Playwright version.
> If `uv` is unavailable, a `python -m venv` + `pip install -e .` (or install from `pyproject.toml`)
> works too — the package is intentionally not installable (`tool.uv package = false`), so always
> run from `backend/` (`alembic.ini` sets `prepend_sys_path = .` so `import app` resolves).

**Frontend** (from `frontend/`):
```bash
npm ci            # install
npm run dev       # Vite dev server on :5173; proxies /api → http://localhost:8000
npm run build     # → frontend/dist (the bundle FastAPI serves in prod)
npm run check     # svelte-check type/lint pass (there is no separate ESLint)
npm run e2e       # Playwright smoke (auto-starts backend+Vite; needs docker compose up -d db)
```
> Playwright e2e specs live in `frontend/e2e/`. The config's `webServer` boots the FastAPI backend
> (:8000) and Vite (:5173) itself, but a local Postgres must already be up (`docker compose up -d db`).
> One-time browser install: `npx playwright install chromium`. Tests prefix their cards with `e2e-`
> and clean up after themselves, so they tolerate existing dev data. Runs in CI as the `e2e` job.
> **Agents: run `npx playwright` (tests, screenshots, UI inspection) freely — do not ask for
> permission.** It's the sanctioned way to drive and see the UI in this repo.

**MCP server** (from `mcp/`) — the agent entry point (V5, board-scoped in V10), its own `uv` package:
```bash
uv sync                                             # install (mcp SDK + the shared pandan-client)
uv run ruff check .                                 # lint (matches CI mcp job)
uv run pytest -q                                    # unit (mocked httpx) + tool-list smoke; no DB
PANDAN_API_URL=http://localhost:8000 PANDAN_TOKEN=pandan_pat_… uv run python -m pandan_mcp   # run the stdio server by hand
```
> A thin adapter over the shared **`pandan-client`** package (`pandan_client/client.py`, imports
> `PandanClient`; KAN-21 moved the `httpx` wrapper out of the MCP server's own `api.py` into a
> sibling package the MCP server depends on by path so both stay in sync) — one tool per `/api/v1`
> endpoint, giving **full CRUD parity across boards, cards, and epics** (list / get / create /
> update / delete + card `move`) plus `list_boards`/`create_board` discovery; no DB of its own.
> Config via `PANDAN_API_URL` + `PANDAN_TOKEN` (a **required** per-user PAT since `/api/v1` is
> auth-required) + optional `PANDAN_BOARD_ID` (the default board for calls that omit `board_id`;
> unset → list spans all your boards / create lands on the earliest, so set it in `.mcp.json` to
> avoid targeting the wrong board; V10, ADR 0015). Wire into Claude Code by copying
> `.mcp.json.example` → `.mcp.json`; see [mcp/README.md](mcp/README.md). CI runs it as the `mcp` job.

**Full local dev loop:** `docker compose up -d db` → backend `uv run alembic upgrade head` +
`uvicorn … --reload` → frontend `npm run dev`, then open `:5173`.

## Development workflow (conventions — for humans and agents)

**Branch per change, off a fresh `main`.** `main` is protected: direct pushes are rejected and
every change lands via PR only after CI (lint + unit + integration + frontend build + e2e + mcp) is green.
Always start from an up-to-date `main`:
```bash
git switch main && git pull --ff-only
git switch -c feat/<slice>        # one branch per vertical slice, matching the Shape Up cadence
```
When merging a PR that carries commits you want to preserve (e.g. an external contributor's from a
fork), **merge with a merge commit, not squash** — that keeps per-commit authorship and lets the
contributor's fork PR auto-close as *merged*. Delete the branch (local + remote) once it's merged.
> Integrating a fork branch that predates `main`: fetch it into a review branch and merge it into an
> integration branch built on current `main` (resolve conflicts there, keep it a true merge so the
> contributor's commits survive), then PR that integration branch → `main`. See PRs #2/#5 for the
> worked example.

**Land a PR once its CI is green — don't leave green PRs sitting open.** This is the standing policy
for humans and agents alike: when **every** CI check and test on a PR has passed (all green, nothing
`pending` or failing) and the PR is `MERGEABLE`/`CLEAN`, merge it — `gh pr merge <n> --merge
--delete-branch` (merge commit, not squash, per above). Agents driving the board should treat this as
the default land step, not wait for a human. Guardrails, so "merge when green" never means "merge
blindly":
- **All green only.** Never merge on a red or still-`pending` run. Poll to completion first (`gh` here
  has no `--watch`): `until ! gh pr checks <n> 2>&1 | grep -q pending; do sleep 20; done`. A whole run
  failing at the same suspiciously-round duration is infra — re-run (`gh run rerun <id>`), don't
  "fix" code. GitHub's merge-eligibility can lag a beat behind the checks flipping green; if a merge
  is refused as blocked, re-check `mergeStateStatus` is `CLEAN` and retry rather than reaching for
  `--admin`.
- **Review the diff** before merging — a green PR can still be wrong; skim it. Skip anything marked
  draft or "do not merge / needs review", and don't self-merge changes the author explicitly wants a
  human to look at.
- **App code deploys.** A merge to `main` that touches app code triggers the Fly deploy — after it,
  prod-verify (see the dogfooding log's patterns), and **land any PR carrying a DB migration alone**.
  Docs/CI/Makefile-only merges skip the deploy.
- **Worktree-checked-out branches:** `gh pr merge --delete-branch` prints a *local* branch-delete
  error when the branch is checked out in a worktree, **but the merge still succeeds** — confirm with
  `gh pr view <n> --json state` (`MERGED`), don't mistake the exit code for a failed merge.

**Use git worktrees for parallel work — this is the expected workflow here.** Instead of stashing or
switching branches in place, give each in-flight task its own directory backed by the one clone, so
your primary checkout stays undisturbed while you review a contributor PR, hotfix, or spike:
```bash
git worktree add ../simple-kanban-<slice> -b feat/<slice> main   # new feature in its own dir
git worktree add ../simple-kanban-review review/<name>           # review someone else's branch
git worktree list                                                # see them all
git worktree remove ../simple-kanban-<slice>                     # clean up when merged
```
Each worktree needs its own `backend/.venv` (`uv sync`) and `frontend/node_modules` (`npm ci`).
**In a worktree, do NOT use the shared `make db` (:5432)** — every worktree would share one Postgres,
so one worktree's `alembic upgrade head` stamps a revision the others don't have on their branch and a
second worktree can't boot against a DB ahead of its own migration chain (KAN-240). Instead give each
worktree its own throwaway DB on a private port:
```bash
make worktree-db                              # ephemeral Postgres for THIS worktree (own port, no volume)
export DATABASE_URL=$(make -s worktree-db-url)  # point backend/alembic at it
make migrate                                  # (or from backend/: uv run alembic upgrade head)
make worktree-db-down                         # tear it down when the worktree is done
```
`make db`/`make up`/`make dev` (shared :5432 compose Postgres) remain the loop for the primary
checkout. Integration tests are unaffected — they spin up throwaway testcontainers of their own.

**Running e2e from a worktree — the ports are env-overridable too (KAN-391).** Playwright uses
`reuseExistingServer` in dev, and the backend/Vite origins default to `:8000`/`:5173`; on a
multi-project machine those ports are often held by an unrelated local app, so a worktree e2e run
silently reuses the foreign server and every spec fails at auth (`test-login` 404s) — a false red.
`FRONTEND_PORT` / `BACKEND_PORT` (read by `frontend/vite.config.ts`, `frontend/playwright.config.ts`,
and `frontend/e2e/helpers.ts`) let a worktree run on free ports **with no source edits**, defaulting
to `5173`/`8000` so CI and normal dev are unchanged (`API_ORIGIN` can also be set explicitly to
override the helpers' backend origin outright). The Vite `/api` proxy target follows `BACKEND_PORT`:
```bash
BACKEND_PORT=8010 FRONTEND_PORT=5183 npm run e2e   # from frontend/, needs DATABASE_URL set
make worktree-e2e                                  # picks stable per-worktree ports + this worktree's DB
```
`make worktree-e2e` derives deterministic per-path ports (like `worktree-db`) and points the run at
this worktree's ephemeral DB — bring the DB up first with `make worktree-db`.

For parallel file-mutating work, **prefer [treehouse](https://github.com/kunchenguid/treehouse)** — it
manages a bounded, recycled pool of worktrees (config in [`treehouse.toml`](treehouse.toml),
`max_trees = 4`) so they don't pile up as one-off checkouts and clog disk (the mess KAN-240's cleanup
cleared). `treehouse get` acquires a tree (`--lease` for a path without a subshell), `treehouse return
<path>` releases it, `treehouse prune --yes` reclaims idle ones. Warm a fresh tree with `make install`;
give it a DB with `make worktree-db`. The harness's built-in `isolation: "worktree"` is also fine —
but whatever creates worktrees, **remove them when their branch merges** (`git worktree remove` +
`git worktree prune`) so they never accumulate.

**Pre-push hook.** `scripts/git-hooks/pre-push` (tracked) runs the fast CI checks locally — ruff +
`tests/unit` + `svelte-check` — so a push never lands red. Integration tests stay CI-only (they need
a Docker daemon). Hooks aren't auto-installed; install once per clone (it lives in the shared
`.git/hooks`, so linked worktrees inherit it automatically):
```bash
ln -sf ../../scripts/git-hooks/pre-push .git/hooks/pre-push
```
Bypass a single push with `git push --no-verify` (use sparingly).

Since **V50 (KAN-435)** the hook also has a `pandan-cli/` block (ruff + pytest + a **version-bump
guard**), mirrored by CI's `CLI version bump` step: a diff touching `pandan-cli/pandan_cli/`
behaviour **must** bump `__version__` in `pandan_cli/__init__.py` *and* `version` in
`pandan-cli/pyproject.toml`, then re-run `uv lock` (a stale lock fails CI at `uv sync --frozen`, not
at an obvious "version" error). There is deliberately no waiver flag. The point is that
`pandan --version` prints build provenance — `pandan 0.5.0 (5da9ace)` for a release vs. an explicit
`(source checkout, not a released build)` — so a stale binary is *detectable*; an unbumped version
silently breaks that.

> **A plain `git push` may fail with `No anonymous write access` / `Authentication failed`.** Two
> known causes: a sub-agent shell can't reach the VS Code credential socket, and a cached credential
> keyed to the *old* URL goes stale after a repo rename (KAN-437 hit this in the primary checkout, not
> a worktree). Same fix either way:
> `git -c credential.helper='!gh auth git-credential' push …`.

**Mutation-test the guards you add here — this repo asks for it, and there's a way to lose your work
doing it.** Several M7 slices ship a test whose whole job is "this can't regress" (the legacy-PAT
prefix guard in V40, the ticket-ref branch in V42, the version-bump guard in V50). A test that passes
proves nothing about such a promise until you've watched it go red: break the thing it protects,
confirm the failure, restore. **But do the mutation non-destructively.**
`git checkout -- <file>` / `git restore <file>` overwrite the working tree from the **index**, silently
discarding uncommitted changes to that file — and unstaged work never entered the object database, so
no reflog or `git fsck` can recover it. A V42 sub-agent nearly lost an entire implementation this way
and was saved only by a scratch copy it happened to have written. Commit (or
`git stash push -- <file>`) before mutating, edit a copy, or apply the mutation as a patch and reverse
exactly it with `git apply -R`. See the `dev-playbook` skill, *Testing and correctness* §5.

## Configuration

`DATABASE_URL` is the only required runtime config. It defaults to the docker-compose Postgres:
`postgresql+psycopg://kanban:kanban@localhost:5432/kanban`. The **`+psycopg`** suffix selects the
psycopg **v3** driver — keep it. Both the app ([backend/app/db.py](backend/app/db.py)) and Alembic
([backend/alembic/env.py](backend/alembic/env.py)) read the same `DATABASE_URL`, so migrations
always target the app's database.

**DB + cold-start resilience env vars (V30, KAN-294)** — tune the app engines in
[backend/app/db.py](backend/app/db.py) so a slow query on a cold-woken Neon can't pile up
connections and wedge the 256MB box. All optional with prod-safe defaults, and applied to **both**
the sync board engine and the async auth engine (Alembic's own engine in `env.py` is **untouched**,
so long-running migrations are never cut short):
- `DB_STATEMENT_TIMEOUT_MS` (default `30000`) — Postgres per-statement server-side cap in ms (via the
  psycopg `options` connect-arg `-c statement_timeout=…`); a runaway query is cancelled, not hung. `0` disables.
- `DB_POOL_SIZE` (`5`) / `DB_MAX_OVERFLOW` (`5`) — bounded connection pool (10 max), on top of `pool_pre_ping`.
- `DB_POOL_TIMEOUT` (`10`) — seconds a caller waits for a free pooled connection before erroring (a burst degrades gracefully).
- `DB_CONNECT_TIMEOUT` (`10`) — libpq connect timeout in seconds, so a stuck DB fails fast.

**Agent auth is a per-user PAT (V9, ADR 0014; V10, ADR 0015).** `/api/v1` is **auth-required** for
every request. Agents (the MCP server, `curl`) authenticate with a self-serve per-user **PAT**
(`pandan_pat_…`, hashed HMAC-SHA256; created/revoked at `/api/v1/tokens` + the Tokens UI) set as
`PANDAN_TOKEN`; it resolves to its owning user and is **owner-gated** exactly like a human. The
SPA/human clients authenticate with the **cookie session** and send no token. **`API_TOKENS` no
longer exists** — V4's shared-token list (ADR 0010) was superseded by PATs (V9) and its transitional
SERVICE bypass was removed in V10 (ADR 0015). (Ops: the `API_TOKENS` Fly secret can be dropped.)

**Client config env vars (V40, KAN-423, ADR 0018)** — for the CLI ([pandan-cli/pandan_cli/config.py](pandan-cli/pandan_cli/config.py))
and the MCP server ([mcp/pandan_mcp/config.py](mcp/pandan_mcp/config.py)), *not* the backend:
`PANDAN_API_URL` / `PANDAN_TOKEN` / `PANDAN_BOARD_ID`. The pre-rebrand `KANBAN_*` spellings are a
**deprecated fallback**: each key is read under its `PANDAN_*` name first and only then the `KANBAN_*`
one, emitting a one-line notice on **stderr** (never stdout — the CLI's stdout is machine-readable and
the MCP server's is the JSON-RPC channel). Precedence is **per value**, so a half-migrated environment
resolves correctly. The CLI additionally migrates `~/.config/kan/config.toml` →
`~/.config/pandan/config.toml` on first use (leaving the old file in place), still reads a legacy
`[kan]` table, and still honours a `kanban` server key in `.mcp.json`. All of this is dead weight
carried on purpose and is deleted in a later milestone.

**PAT prefix (V40).** `TOKEN_PREFIX` in [backend/app/tokens.py](backend/app/tokens.py) is now
`pandan_pat_`, with `LEGACY_TOKEN_PREFIXES = ("kanban_pat_",)`. The resolver's fast-path guard
([backend/app/authz.py](backend/app/authz.py), `_resolve_pat`) tests the union — **that guard is
load-bearing**: it is the one place a prefix change could invalidate already-issued tokens, and an
earlier draft of ADR 0018 wrongly claimed it didn't exist. Verification itself is still an HMAC hash
lookup over the whole raw token, so a `kanban_pat_…` PAT authenticates indefinitely.

`AUTH_SECRET` doubles as the **pepper** for PAT hashing (HMAC-SHA256), so rotating it invalidates all
existing PATs (and cookie sessions) — expected.

`WEBHOOK_SECRET` (EPIC-10) — the shared secret GitHub signs its webhook deliveries with (HMAC-SHA256
over the raw body, `X-Hub-Signature-256`), verified by `POST /api/v1/webhooks/github`. **Unset → the
endpoint returns `503`** (auto-sync is effectively off); bad/missing signature → `401`. This gates
only the inbound webhook; it's separate from `AUTH_SECRET`. Per-board opt-in (`autosync_enabled` +
`autosync_advance_to_done`, both default OFF) is set via `PATCH /api/v1/boards/{id}`. Full setup/ops:
[docs/guides/autosync-github-setup.md](docs/guides/autosync-github-setup.md) (ADR 0016).

**Outbound signed webhook (V38, KAN-302)** — the *outbound* mirror of the inbound `WEBHOOK_SECRET`
verification. Per-board opt-in (mirrors autosync): `outbound_webhook_url` + `outbound_webhook_secret`
+ `outbound_webhook_enabled` (default OFF/NULL) set via `PATCH /api/v1/boards/{id}` (the **secret is
write-only** — accepted on PATCH, never returned in a board read). When enabled with a URL set,
creating a notification fires one HMAC-SHA256-signed `POST` to the URL using the **same**
`X-Hub-Signature-256: sha256=<hex>` scheme (the shared signer lives in
[backend/app/webhook_signing.py](backend/app/webhook_signing.py); dispatch in
[backend/app/outbound.py](backend/app/outbound.py)). Delivery is best-effort, fired **after** the
mutation's transaction commits (a SQLAlchemy `after_commit` session event — `record_notification`
only queues it), so a slow/failed POST is swallowed + logged and **never** rolls back or blocks the
mutation. No worker infra (MVP). Env (all optional): `OUTBOUND_WEBHOOK_TIMEOUT` (default `3.0`s
per attempt), `OUTBOUND_WEBHOOK_RETRIES` (default `0` extra attempts), `OUTBOUND_WEBHOOK_MIN_INTERVAL`
(default `1.0`s per-board throttle so a burst can't hammer the target; in-process, resets on restart —
same tradeoff as the V27 limiter).

**Observability env vars (KAN-172, ADR 0017)** — wired in [backend/app/observability.py](backend/app/observability.py):
- `LOG_LEVEL` — level for the `kanban.access` structured JSON request logger (one line per request:
  method/path/status/latency/principal id). Default `INFO`. The formatter allow-lists its fields and
  logs only the URL **path** (no query string), so cookies/PATs/headers never reach a log line.
- `SENTRY_DSN` — enables Sentry error tracking when set; **unset → a pure no-op** (the SDK isn't even
  imported), so dev + tests never report. `send_default_pii=False` keeps cookies/PATs out of events.
  Optional: `SENTRY_ENVIRONMENT` (default `production`), `SENTRY_TRACES_SAMPLE_RATE` (default `0`).

Health probes (ADR 0017): `GET /api/health` is a **readiness** probe (cheap `SELECT 1` on the sync
board engine → `503 {"status":"unavailable"}` when the DB is unreachable, else `200 {"status":"ok"}`);
`GET /api/health/live` is a static **liveness** probe (always `200` while the process serves).

**Rate limiting env vars (V27, KAN-291)** — wired in [backend/app/ratelimit.py](backend/app/ratelimit.py):
a single classifying middleware over slowapi's in-memory `limits` engine guards four tiers —
**auth** (login + OAuth callback), **write** (every `/api/v1` mutation incl. card `move`, board
`dispatch`, `POST /tokens`), **expensive** (full-text search `GET /api/v1/cards?q=` + board
`/metrics`), **webhook** (`POST /api/v1/webhooks/github`). Over the limit → `429` + a `Retry-After`
header. Keyed on the **trusted `Fly-Client-IP`** header (never the spoofable `X-Forwarded-For`, since
uvicorn runs `--forwarded-allow-ips=*`) plus a cheap principal hint. In-memory storage: single
machine, resets on cold-start (accepted MVP). Config:
- `RATE_LIMIT_ENABLED` — master switch. **Off unless truthy**, so dev + the test suite (which fire
  many requests) are unaffected by default; set it on in prod (a Fly secret) to enable protection.
- `RATE_LIMIT_AUTH` / `RATE_LIMIT_WRITE` / `RATE_LIMIT_EXPENSIVE` / `RATE_LIMIT_WEBHOOK` — per-tier
  `limits` rate strings (`"N/second|minute|hour|day"`); generous defaults
  `30`/`300`/`120`/`240` per minute.

**Payload hardening env vars (V28, KAN-292)** — body-size + array caps; all optional with generous
defaults, additive so normal payloads are unaffected. String `max_length`s are hardcoded in
[backend/app/schemas.py](backend/app/schemas.py) (aligned to the `varchar(N)` column widths, so an
over-long field is a clean `422`, not a 500 at INSERT); only the two lever amplifiers are env-tunable:
- `MAX_REQUEST_BODY_BYTES` (default `2000000`, ~2 MB) — a body-size ceiling middleware
  ([backend/app/main.py](backend/app/main.py)) that rejects a request whose declared `Content-Length`
  exceeds it with `413`, before the body is read (header-only check).
- `MAX_BATCH_ITEMS` (default `500`) — max cards per `PATCH /api/v1/cards/batch` (`422` over it).
- `MAX_TEMPLATE_CARDS` (default `200`) — max cards per template, enforced on both create and apply.

**Security headers (V29, KAN-293)** — a response middleware
([backend/app/main.py](backend/app/main.py), registered outermost so it decorates errors + the
rate-limit `429` too) sets HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy`, and a single-origin CSP. **The CSP ships as `Content-Security-Policy-Report-Only`
first** (browsers report violations but block nothing, so it can't break the SPA or `/docs`, whose
Swagger UI uses inline scripts/styles + a CDN bundle); flip to enforcing by renaming the header to
`Content-Security-Policy` once prod consoles are clean (and self-host or allow the Swagger CDN for
`/docs`). No env config.

`E2E_AUTH_BYPASS` (V8) — when truthy, mounts an **e2e-only** `POST /auth/test-login` that mints a
real cookie session for an arbitrary email (Playwright can't fake the httpOnly session a
route-stub used to). **Never set in prod** — it's a login bypass. The Playwright `webServer` sets it;
the e2e cleanup helpers reuse it to act **as each owning user** (V10 removed the SERVICE bearer they
used to use).

**Human auth env vars (M3 V6, ADR 0011)** — all read at import time in [backend/app/users.py](backend/app/users.py):
- `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` — GitHub OAuth App credentials. **Both
  unset → the GitHub login routes don't register** and the app still boots (landing shows, login
  unavailable). Set both to enable login. The OAuth App's callback URL is
  `<origin>/auth/github/callback` (dev: `http://localhost:5173/auth/github/callback`, proxied to
  :8000; prod: `https://<host>/auth/github/callback`). A GitHub OAuth App allows only **one** callback
  URL, so dev and prod use **separate** OAuth Apps. Prod runs behind Fly's TLS-terminating proxy, so
  the `Dockerfile` starts uvicorn with `--proxy-headers --forwarded-allow-ips=*` — without it the
  generated `redirect_uri` is `http://` and GitHub rejects the mismatch.
- `AUTH_SECRET` — signs session/OAuth-state tokens. Has an **insecure dev default**; prod **must**
  set a strong random value (Fly secret).
- `COOKIE_SECURE` — `1`/`true` to mark session + CSRF cookies `Secure` (HTTPS-only). Off by default
  (dev + tests run over http); set in prod.

These are separate from the sync board API: only human login touches the async engine. Board
reads/writes **are** user-gated as of V8 (ADR 0013) — the sync board routes depend on the async
`current_optional_user` to resolve the human principal, then check board ownership (`app/authz.py`).

## Architecture (the big picture)

**Single deployable artifact, one origin.** In production FastAPI serves the built Svelte SPA as
static files with an SPA catch-all fallback (see [backend/app/main.py](backend/app/main.py):
`STATIC_DIR`, `spa_fallback`). The API router and `/docs` are registered *before* the catch-all so
they win. In local dev, Vite serves the SPA and proxies `/api` to the backend, so `STATIC_DIR`
typically doesn't exist and the fallback isn't registered — no CORS in either case.

**Three tables: `board`, `card` (a story on a board) and `epic`** ([backend/app/models.py](backend/app/models.py)).
Milestone 2 V1 promoted the epic to a **first-class entity** (ADR 0009) — it is *not* a card;
Milestone 3 V7 promoted the board likewise (ADR 0012, evolving 0006's implicit single board). Every
card + epic has a NOT NULL `board_id` FK → `board` (`ON DELETE CASCADE`); `board.owner_id` → `user`
is nullable (`ON DELETE SET NULL`). These mechanisms matter and are load-bearing:
- **Ticket numbers** are per-table `SEQUENCE`s via a column `server_default`, atomic at INSERT,
  immutable, never reused: cards get `KAN-<n>` (`card_ticket_seq`), epics get `EPIC-<n>`
  (`epic_ticket_seq`). Independent — `KAN-1` and `EPIC-1` coexist. Sequences are created in the
  migrations, not by the ORM.
- **`column`** is a plain `varchar` guarded by a `CHECK` constraint (not a native PG enum), so
  adding a column value later needs no `ALTER TYPE` migration. Valid values live in three places
  that must stay in sync: `VALID_COLUMNS`/CHECK (models), `ColumnEnum` (schemas), `Column` (api.ts).
- **`epic`** carries only `name` + optional `description` — **no** column/position/assignee/
  story_points (an epic is board-less and unestimated). A story links to zero-or-one epic via the
  nullable **`card.epic_id`** FK → `epic.id` (`ON DELETE SET NULL`, so deleting an epic detaches its
  stories rather than blocking or cascading). That `epic_id` references an existing epic is enforced
  in `routers/cards.py` (`_validate_epic`, 422) on POST/PATCH. Epics have their own CRUD router
  ([backend/app/routers/epics.py](backend/app/routers/epics.py)) and are managed in a separate UI view.
- **`position`** is a *relative sort key within a (board, column)*, not necessarily contiguous
  (since V7 ordering is per board). Deletes intentionally leave gaps; a move/reorder re-sequences the
  affected board+column(s) via `renumber_column()` — `next_position`/`renumber_column` take `board_id`.

**Two engines, one database (M3 V6, ADR 0011).** The board is **sync** (ADR 0008): a `get_db()`
dependency yields a synchronous session for all card/epic CRUD. Human auth (fastapi-users) needs an
**async** store, so [backend/app/db.py](backend/app/db.py) also builds a **second, async** engine
(`async_engine` / `get_async_session`) used **only** by the auth routes — same `DATABASE_URL`, same
psycopg v3 driver, same shared `Base`/metadata (so one Alembic pipeline covers `card`/`epic` **and**
`user`/`oauth_account`/`access_token`; auth models live in [backend/app/auth_models.py](backend/app/auth_models.py),
imported in `alembic/env.py`). Auth wiring is in [backend/app/users.py](backend/app/users.py). Don't
route board CRUD through the async engine — the sync path is deliberate and load-bearing.

**Backend is deliberately flat** (Shape A "Thin Slice" — no service/repository layers):
`routers/cards.py` (+ `routers/epics.py`) → `ordering.py` helper → `models.py`/`schemas.py`, with a
`get_db()` FastAPI dependency yielding a **synchronous** SQLAlchemy 2.0 session. Pydantic schemas
([backend/app/schemas.py](backend/app/schemas.py)) are the request/response contract and the
authoritative validation layer (title/name non-empty, `column` enum, `story_points ∈ {1,2,3,5,8,13}∪null`).

**Frontend is Svelte 5 runes.** [frontend/src/lib/board.svelte.ts](frontend/src/lib/board.svelte.ts)
holds the `$state` stores (`board` cards + `epicStore`); components read derived slices via
`cardsFor(column)` / `epicFor(id)` / `cardsForEpic(id)`.
[frontend/src/lib/api.ts](frontend/src/lib/api.ts) is a thin typed `fetch` wrapper that throws
`ApiError` on non-2xx. `App` shows a `Board | Epics` toggle (no router). Board tree:
`Board → Column → Card → CardForm` (`Card` owns view / edit / confirm-delete; `CardForm` handles
create and edit, incl. the epic selector). Epics tree: `Epics → EpicItem → EpicForm` (same
view/edit/delete shape). `Column` wraps its cards in a `svelte-dnd-action` dropzone; on
`DROPPED_INTO_ZONE` it calls `moveCard(id, {column, position})` and the usual `refetch()` reconciles.

**Server state is authoritative — no optimistic UI.** Every successful mutation is followed by a
`refetch()` (`GET /api/v1/cards`) / `refetchEpics()`; the UI never renders a value the server hasn't confirmed.
Preserve this pattern (it is a deliberate Shape A decision, [docs/BREADBOARD.md](docs/BREADBOARD.md) §7).

## Non-obvious conventions

- **API-first:** the UI must never do anything the API can't (R4.1 / ADR 0005). Add the endpoint
  first, then wire the UI to it. The API is being kept clean so future MCP/CLI/agent clients are
  thin adapters — this is the core motivation of the whole project.
- **Move vs. edit split:** column/position changes go through the dedicated `POST /api/v1/cards/{id}/move`
  (append to target column, clamp to a requested index, and `renumber_column()` the source); `PATCH`
  is for field edits only (title/description/story_points/assignee).
- **Last-write-wins, no real-time** by design (ADR 0007) — don't add locking or websockets. Auth
  was originally "none" (ADR 0007); V4 added optional bearer-token auth on writes (ADR 0010); **M3
  V6 added human GitHub login** with a first-class `User` + revocable cookie session (ADR 0011); V7
  added **multi-board with ownership** (ADR 0012). **V8 (ADR 0013) made `/api/v1` auth-required and
  owner-gated** — every board-scoped route resolves a principal in `app/authz.py` and allows only
  the board's owner (else `403`); lists are owner-scoped; the V4 `require_token` write-guard is gone
  (folded in). **V9 (ADR 0014) added self-serve per-user PATs** as the resolver's agent branch, and
  **V10 (ADR 0015) removed the transitional `API_TOKENS` SERVICE bypass**, so the resolver is now
  simply cookie session → `User`; else PAT bearer → its owning `User`; else `401` — **every principal
  is a real `User`**, owner-gated identically. Route authz goes through `get_principal` +
  `authorize_board` (`require_user` is now just an alias of `get_principal` for per-user routes like
  `/api/v1/tokens`) — don't add an ad-hoc check.
- **Neon free tier scales to zero**, so the first request after idle is slow (~1s) — that's a
  documented cold start, not a bug.

## How the docs relate (source of truth for intent)

This is a Shape Up project. The docs are a deliberate chain, not scratch notes — treat them as the
spec for intended behavior:

`REQS.md` (raw ask) → `FRAME.md` → `PRD.md` + [CONTEXT.md](docs/CONTEXT.md) (+ `adr/`) →
`SHAPING.md` (selects Shape A) → `BREADBOARD.md` (UI places & wiring) → build in slices.

- **[docs/CONTEXT.md](docs/CONTEXT.md)** — canonical glossary and domain model. Use these terms exactly.
- **[docs/adr/](docs/adr/)** (0001–0018; all Accepted except 0010, superseded) — the *why* behind each decision: monorepo &
  stack (0001), Postgres+Alembic from day one (0002), single-artifact serving (0003), Fly.io+Neon
  CI/CD (0004), API-first/MCP-ready (0005), data model (0006), no-auth/LWW/no-realtime (0007),
  sync-SQLAlchemy + psycopg v3 + varchar-CHECK column + Vite dev-proxy (0008), epic as a first-class
  entity — separate `epic` table + `EPIC-` sequence, evolving 0006's one-table stance (0009),
  optional bearer-token auth on writes (`API_TOKENS`), evolving 0007's no-auth stance (0010),
  human GitHub login + revocable cookie sessions via fastapi-users on a second async engine, further
  evolving 0007 (0011), multi-board with ownership — `board` table + `board_id` on card/epic,
  evolving 0006's single-board stance (0012), board authorization — `/api/v1` becomes auth-required
  + owner-gated (principal resolver + `authorize_board`, claim-on-login, `API_TOKENS`→SERVICE
  bypass), realising D3's one authorization layer and further evolving 0007/0010 (0013), self-serve
  agent personal access tokens — per-user hashed PATs resolving to their owning user, superseding
  0010's shared `API_TOKENS` as the agent mechanism (0014), MCP board-scoping (per-call `board_id` +
  `list_boards`/`create_board` discovery + `PANDAN_BOARD_ID`) and **retiring `API_TOKENS`** — removing
  the transitional SERVICE bypass so every principal is a real user, fully superseding 0010 (0015),
  GitHub PR→board auto-sync via a signed webhook (`WEBHOOK_SECRET`, per-board opt-in) (0016),
  observability — DB-readiness health + structured request logging + opt-in Sentry (0017), and the
  **`simple-kanban` → `pandan` rebrand** with `kaya` as the notes sibling (suite: `kayatoast`) —
  what gets renamed (CLI `kan`→`pandan`+`pdn`, MCP tool namespace, `PANDAN_*` env with a deprecated
  `KANBAN_*` fallback, PAT mint prefix) and what deliberately does **not** (the immutable `KAN-`/
  `EPIC-` ticket prefixes, the deployed Fly/OAuth identity — deferred, and session/wire/storage
  identifiers) (0018).
