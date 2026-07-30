# Developer Workflows — a portable playbook

This document describes the developer-workflow machinery used in **pandan** and how to
port it into another project (especially one also built with Claude Code agentic coding). It is
written to be lifted: each section says *what the mechanism is*, *why it exists here*, and *what
to copy / adapt* for a new repo.

The stack here is **FastAPI + `uv` (backend)** and **Svelte 5 + Vite + `npm` (frontend)**, deployed
as a single artifact to Fly.io with Postgres. Most of the workflow ideas are stack-agnostic — the
principles (fast local gate, layered tests, CI-as-merge-gate, deploy-only-green, worktrees for
parallel agents) transfer to any language.

---

## 0. The shape of the whole system

```
  local dev loop            pre-push hook           GitHub Actions (CI)          Deploy
  ────────────────          ─────────────           ───────────────────          ──────
  docker compose up db      ruff + unit  ─┐         lint ─┐                       workflow_run:
  alembic upgrade head      svelte-check  ├─push─▶  unit  ├─ all green ─┐         CI completed
  uvicorn --reload                        ┘         integration        ├─ on main ─▶ flyctl deploy
  npm run dev                    (fast, no Docker)  frontend build     │            (only if green)
                                                    e2e (Playwright) ──┘
```

Three gates, increasing in cost and coverage:

1. **Pre-push hook** — seconds, runs locally, no Docker. Catches the cheap mistakes before they
   ever reach GitHub.
2. **CI (5 parallel jobs)** — minutes, runs on every PR + push to `main`. The real merge gate.
3. **Deploy** — only fires *after* CI is green *on `main`*, deploying the exact validated commit.

The guiding principle: **each gate is a strict superset trigger of the one before it, but a subset
in cost.** Fast feedback locally; exhaustive feedback in CI; production only ever sees green code.

---

## 1. Layered testing strategy

The single most portable idea here is **splitting tests by cost/isolation**, not just by kind:

| Layer | Location | Needs | Speed | Runs in |
|-------|----------|-------|-------|---------|
| **Unit** | `backend/tests/unit/` | nothing (pure logic — Pydantic schema validation, pagination math) | ~instant | pre-push + CI |
| **Integration** | `backend/tests/integration/` | real Postgres via **testcontainers** (Docker daemon) | seconds–minutes | CI only |
| **E2E** | `frontend/e2e/` | full stack (backend + Vite + Chromium) via **Playwright** | minutes | CI only |

**Why split unit vs. integration by directory?** Because the *fixtures* differ. The integration
`client`/DB fixtures live in `tests/integration/conftest.py`, so anything under that directory
automatically gets a migrated throwaway Postgres; anything under `tests/unit/` gets nothing and
stays fast. This lets the pre-push hook run `pytest tests/unit` with zero infra, while CI runs both.

Pytest is configured (`backend/pyproject.toml`) so tests can `import app.*` regardless of CWD:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]          # put the backend root on sys.path
```

### 1a. Integration tests with testcontainers (no manually-managed DB)

The model depends on Postgres-specific features (sequences, `server_default`, CHECK constraints),
so tests run against **real Postgres**, not SQLite. Rather than requiring a hand-managed test
database, `tests/integration/conftest.py` spins one up per session and tears it down:

```python
@pytest.fixture(scope="session", autouse=True)
def _database():
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        os.environ["DATABASE_URL"] = postgres.get_connection_url()  # set BEFORE importing app
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")   # migrate → also exercises the migrations themselves
        yield

@pytest.fixture(autouse=True)
def _reset_tables():                    # deterministic ticket numbers between tests
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE card, epic RESTART IDENTITY CASCADE"))
        conn.execute(text("ALTER SEQUENCE card_ticket_seq RESTART WITH 1"))
        conn.execute(text("ALTER SEQUENCE epic_ticket_seq RESTART WITH 1"))
    yield
```

**Portable lessons:**
- Set `DATABASE_URL` (or whatever your app reads) **before** any app module is imported — do all
  app imports inside fixtures/test bodies, not at module top.
- Run your real migrations in the fixture. This tests the migrations *and* the app in one shot.
- Reset state (truncate + restart sequences) between tests so results are deterministic.
- The suite is fully self-contained and CI-ready — no external database to provision.

> **⚠️ The import-order trap (learned the hard way — PR #17).** The app builds its SQLAlchemy
> engines from `DATABASE_URL` **at import time**. Pytest imports every test module at *collection*,
> which happens **before** the session `_database` fixture sets `DATABASE_URL` to the throwaway
> container. So a **top-level** `from app.db import engine` (or any `import app.*`) in an integration
> test binds the engines to the *default* `localhost:5432` URL. On a dev box with `docker compose up
> db` running, that **silently passes against your dev database**; in CI, with nothing on 5432, all
> integration tests error with `connection refused`. It's a nasty trap precisely because local and
> CI disagree.
>
> Two defenses now guard against it:
> 1. A `pytest_collection_finish` hook in `tests/integration/conftest.py` **fails collection** if
>    `app.db` is in `sys.modules` — a deterministic, DB-independent signal (fires the same locally
>    and in CI, whether or not a Postgres is up).
> 2. The pre-push hook runs `pytest tests/integration --collect-only` — Docker-free, so it triggers
>    that guard **before** the push, not just in CI.
>
> The rule that avoids it entirely: **keep every app import inside a test/fixture body**, never at a
> module's top. (A tiny lazy helper like `test_github_login.py`'s `_query_one()` is the idiom.)

### 1b. E2E tests with Playwright (Playwright boots the whole stack)

`frontend/playwright.config.ts` uses the `webServer` feature so Playwright itself starts the
backend and frontend — you don't manage processes by hand:

```ts
webServer: [
  { command: 'sh -c "cd ../backend && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8000"',
    port: 8000, reuseExistingServer: !CI, timeout: 120_000 },
  { command: "npm run dev", port: 5173, reuseExistingServer: !CI, timeout: 120_000 },
]
```

Key config choices worth copying:
- `reuseExistingServer: !CI` — locally, reuse a dev server you already have running (fast
  iteration); in CI, always boot fresh.
- `fullyParallel: false, workers: 1` — the specs share one backend/DB, so they run **sequentially**
  for determinism. (If your app isolates per-test data you can parallelize.)
- `retries: CI ? 1 : 0`, `trace: "on-first-retry"` — one retry in CI with a trace captured on the
  retry, so flakes are debuggable from the uploaded artifact.
- `forbidOnly: CI` — a stray `.only` fails the CI build instead of silently skipping everything.

**Self-cleaning tests tolerate shared/dev data.** Every entity a test creates is prefixed
(`e2e-`) and uniquified (`uniqueTitle()` appends timestamp+random). An `afterAll`-style helper
(`cleanupE2eCards()`) deletes everything with that prefix **via the API**, so the suite can run
against the same docker-compose Postgres you develop against without trashing your data. See
`frontend/e2e/helpers.ts` for the pattern (reusable locators, a `createCard()` action helper, and
a `dragTo()` that drives low-level mouse steps because the DnD library needs a movement threshold).

---

## 2. Linting / type-checking

| Tool | Scope | Command | Where |
|------|-------|---------|-------|
| **ruff** | Python lint + import sort | `uv run ruff check .` | pre-push + CI `lint` job |
| **svelte-check** | TS/Svelte type-check | `npm run check` | pre-push + CI `frontend` job |

Ruff config (`backend/pyproject.toml`) is deliberately small:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
extend-exclude = ["alembic/versions"]   # generated migrations follow their own template
[tool.ruff.lint]
select = ["E", "F", "I"]                 # pycodestyle errors, pyflakes, import sorting
```

There is no separate ESLint — `svelte-check --tsconfig ./tsconfig.json` is the frontend gate. The
frontend "test" in CI is really **type-check + build** (`npm run check && npm run build`): if it
compiles and type-checks, it passes.

---

## 3. The pre-push hook (fast local gate)

`scripts/git-hooks/pre-push` mirrors the *fast* CI jobs so a push never lands red:

```bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"

echo "pre-push ▸ backend: ruff + unit tests"
( cd "$repo_root/backend" && uv run ruff check . && uv run pytest tests/unit -q )

# Docker-free import-hygiene check: *collecting* integration tests (not running
# them) fires a conftest guard against app modules imported at top level — the
# PR #17 trap where the DB engine binds to the wrong URL and passes locally / fails CI.
echo "pre-push ▸ backend: integration import hygiene (collect-only, no Docker)"
( cd "$repo_root/backend" && uv run pytest tests/integration --collect-only -q >/dev/null )

echo "pre-push ▸ frontend: svelte-check"
( cd "$repo_root/frontend" && npm run check )
```

Design decisions:
- **Only the cheap checks.** Integration + e2e need Docker/browsers, so they stay CI-only. The
  hook is meant to be sub-minute, or people disable it. (The one exception is *collecting* the
  integration suite — Docker-free — purely to trip the import-order guard; it runs no tests.)
- **Tracked in the repo, not auto-installed.** Git won't run a hook from a tracked file directly,
  so each clone installs it once with a symlink into `.git/hooks`:
  ```bash
  ln -sf ../../scripts/git-hooks/pre-push .git/hooks/pre-push
  ```
  Because `.git/hooks` is shared, linked **worktrees inherit it automatically**.
- **Escape hatch:** `git push --no-verify` bypasses it for a one-off (use sparingly).

**To port:** put the script under `scripts/git-hooks/`, make it executable, mirror your own
fast-vs-slow split, and document the one-time `ln -sf` in your README/CLAUDE.md.

---

## 4. GitHub Actions — CI (`.github/workflows/ci.yml`)

Triggers on **every PR** and **every push to `main`**. Five independent jobs run in parallel:

| Job | Does | Notable infra |
|-----|------|---------------|
| `lint` | `ruff check` | `astral-sh/setup-uv@v5` with `enable-cache: true` |
| `unit` | `pytest tests/unit` | no DB, no Docker |
| `integration` | `pytest tests/integration` | testcontainers → real Postgres 17 (runner has Docker) |
| `frontend` | `svelte-check` + `vite build` | `actions/setup-node@v4` with `cache: npm` |
| `e2e` | `npm run e2e` (Playwright) | Postgres **service container** + cached browser |

Patterns worth copying:

- **`uv run --frozen --group dev …`** everywhere — `--frozen` fails if `uv.lock` is stale, so CI
  installs exactly the locked deps. Node side uses `npm ci` (lockfile-exact) not `npm install`.
- **Dependency caching** via the official setup actions (`enable-cache` for uv, `cache: npm` +
  `cache-dependency-path` for node) — no manual cache keys needed for deps.
- **Two different ways to get Postgres, chosen by test style:**
  - *integration* uses **testcontainers** (in-process, the test starts/stops the DB).
  - *e2e* uses a GitHub **service container** (a long-running DB the separate uvicorn process
    connects to), with a health check:
    ```yaml
    services:
      postgres:
        image: postgres:17
        env: { POSTGRES_USER: kanban, POSTGRES_PASSWORD: kanban, POSTGRES_DB: kanban }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U kanban -d kanban"
          --health-interval 5s --health-timeout 3s --health-retries 10
    env:
      DATABASE_URL: postgresql+psycopg://kanban:kanban@localhost:5432/kanban
    ```
- **Playwright browser caching keyed on the Playwright version** — the browser (~120 MB) is only
  re-downloaded when `@playwright/test` is bumped. On a cache *miss* install browser + OS libs; on
  a *hit* install only the (uncacheable) OS libs:
  ```yaml
  - id: pw
    run: echo "version=$(node -p "require('@playwright/test/package.json').version")" >> "$GITHUB_OUTPUT"
  - id: pw-cache
    uses: actions/cache@v4
    with: { path: ~/.cache/ms-playwright, key: ${{ runner.os }}-playwright-${{ steps.pw.outputs.version }} }
  - if: steps.pw-cache.outputs.cache-hit != 'true'
    run: npx playwright install --with-deps chromium
  - if: steps.pw-cache.outputs.cache-hit == 'true'
    run: npx playwright install-deps chromium
  ```
- **Upload the Playwright report on failure** so a red e2e run is debuggable:
  ```yaml
  - if: ${{ failure() }}
    uses: actions/upload-artifact@v4
    with: { name: playwright-report, path: frontend/playwright-report/, retention-days: 7 }
  ```

---

## 5. GitHub Actions — Deploy (`.github/workflows/deploy.yml`)

Deploy is **decoupled from CI via `workflow_run`** — it runs only after CI *completes*, and only
proceeds if CI *succeeded on `main`*. A red build can never ship:

```yaml
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  deploy:
    if: >-
      github.event.workflow_run.conclusion == 'success' &&
      github.event.workflow_run.head_branch == 'main'
    concurrency: { group: deploy-production, cancel-in-progress: true }
    steps:
      - uses: actions/checkout@v4
        with: { ref: ${{ github.event.workflow_run.head_sha }} }   # deploy the exact validated commit
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env: { FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }} }
```

Transferable ideas regardless of host (Fly/Vercel/Render/…):
- **Gate deploy on CI success + branch = main**, not on a separate push trigger — one source of truth.
- **Check out `workflow_run.head_sha`**, so you deploy the *commit CI validated*, not "latest main"
  (which could have advanced).
- **`concurrency` with `cancel-in-progress`** — a newer merge supersedes an in-flight deploy.
- Auth via a **repo secret** (`FLY_API_TOKEN`); nothing sensitive in the workflow file.

---

## 6. Branching & git worktrees

**Branch per vertical slice, off a fresh `main`.** `main` is protected — no direct pushes; every
change lands via PR after CI is green.

```bash
git switch main && git pull --ff-only
git switch -c feat/<slice>        # one branch per slice
```

**Worktrees are the expected parallel-work mechanism** (rather than stashing / in-place branch
switching). Each in-flight task gets its own directory backed by the one clone:

```bash
git worktree add ../simple-kanban-<slice> -b feat/<slice> main   # new feature
git worktree add ../simple-kanban-review review/<name>           # review someone's branch
git worktree list
git worktree remove ../simple-kanban-<slice>                     # when merged
```

- Each worktree needs its own `backend/.venv` (`uv sync`) and `frontend/node_modules` (`npm ci`);
  the docker-compose Postgres is **shared** across all of them.
- The pre-push hook lives in shared `.git/hooks`, so linked worktrees inherit it for free.
- **Merge policy:** merge-commit (not squash) when preserving per-commit authorship matters (e.g.
  a fork contributor's commits, so their PR auto-closes as *merged*). Delete the branch after merge.

### Agentic angle (Claude Code)

- Claude Code has **built-in worktree isolation** — prefer `isolation: "worktree"` for parallel
  file-mutating agent work, which maps directly onto the human worktree workflow above.
- The whole layered-gate design is *agent-friendly*: an agent can run the fast pre-push checks
  itself (`uv run ruff check . && uv run pytest tests/unit -q && npm run check`) before proposing a
  push, and rely on CI as the exhaustive backstop.

---

## 7. Claude Code project setup (`.claude/`)

- **`CLAUDE.md`** at the repo root is the primary agent brief. Notice how it's structured: a
  "what is and isn't built" table up front (so the agent doesn't trust docs over code), explicit
  commands, and a "Development workflow (conventions — for humans and agents)" section that
  literally spells out the branch/worktree/pre-push rules. **This is the highest-leverage thing to
  copy**: encode your workflow conventions in `CLAUDE.md` so every agent session follows them.
- **`.claude/settings.local.json`** holds a per-developer **permission allowlist** so common,
  safe commands don't prompt every time — e.g. `Bash(uv run *)`, `Bash(npm run *)`,
  `Bash(git commit *)`, `Bash(gh pr *)`, `Bash(npx playwright *)`, `Bash(docker compose *)`.
  Curate this to the commands your workflow actually uses. (It's `.local.json`, so it's typically
  git-ignored / per-machine.)

**To port:** write a `CLAUDE.md` that (a) states build status honestly, (b) lists exact commands,
(c) documents the branch/worktree/pre-push/PR conventions, and seed a
`.claude/settings.local.json` allowlist for your routine commands.

---

## 8. The local dev loop (reference)

```bash
# once per machine
ln -sf ../../scripts/git-hooks/pre-push .git/hooks/pre-push

# every session
docker compose up -d db                       # shared Postgres 17
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && npm ci && npm run dev          # Vite :5173, proxies /api → :8000
# open http://localhost:5173
```

The Vite dev proxy (`frontend/vite.config.ts`) forwards `/api → http://localhost:8000` so dev
mirrors the same-origin production setup and needs **no CORS** — a small but meaningful choice that
keeps dev/prod parity.

---

## 9. Adoption checklist for a new project

Copy in roughly this order — each step is independently useful:

1. **`CLAUDE.md`** documenting build status, commands, and workflow conventions (§7).
2. **Split tests** into a no-infra fast layer and a heavier infra layer by directory/fixtures (§1).
3. **Pre-push hook** running only the fast layer + lint/type-check; document the `ln -sf` install (§3).
4. **CI workflow** with parallel jobs, lockfile-frozen installs (`--frozen` / `npm ci`), and
   dependency caching (§4).
5. **Testcontainers** (or equivalent) so integration tests need no hand-managed DB (§1a).
6. **Playwright with `webServer`** booting your stack + self-cleaning, prefixed test data (§1b).
7. **Deploy gated on CI success via `workflow_run`**, checking out the validated SHA (§5).
8. **Branch-per-slice + worktrees**, protected `main`, PR-only merges (§6).
9. **`.claude/settings.local.json`** permission allowlist for routine commands (§7).

---

*Generated by surveying the actual workflow files in this repo: `.github/workflows/ci.yml`,
`.github/workflows/deploy.yml`, `scripts/git-hooks/pre-push`, `backend/pyproject.toml`,
`backend/tests/integration/conftest.py`, `frontend/package.json`, `frontend/playwright.config.ts`,
`frontend/vite.config.ts`, `frontend/e2e/helpers.ts`, `.claude/settings.local.json`, and `CLAUDE.md`.*
