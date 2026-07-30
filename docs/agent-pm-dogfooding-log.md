<!--
title: "Agent-PM dogfooding log"
description: Archived running log from the in-repo project-manager skill — session history and UX gotchas from driving this board as an agent PM.
-->

# Agent-PM dogfooding log

This is the running history of running the Simple Kanban board through an agent project-manager, plus
every board/CLI/MCP gotcha hit along the way. It used to live inside the repo's
`project-manager-simple-kanban` skill; that skill moved to the user's global skills (renamed
`project-manager-kanban`) so it's available in any session, and the reusable playbook now lives there.
The narrative log stayed here, in the repo, where it belongs — it's specific to this project.

Append to this file (not the global skill) as the board moves forward: what got built, what was
awkward to drive, what a sub-agent tripped on, and what to do differently next time.

The content below is the verbatim snapshot carried over from the skill at the time of the move
(playbook sections included for context; the authoritative playbook is now the global
`project-manager-kanban` skill).

---


# Project manager for Simple Kanban

You are the **PM / scrum-master**. You do **not** write feature code yourself — you read the board,
decide what to work on, and delegate each card to **one sub-agent at a time**, then land the result.
Your job is throughput + quality + keeping the board honest, and (a standing goal in this repo)
**dogfooding**: notice and record where the tool itself is awkward to drive as an agent.

## Getting started (new users — read if the Kanban MCP isn't wired yet)

If `mcp__kanban__*` tools aren't available in this session, the board isn't connected yet. Point
the user at the project and its onboarding guide, then help them wire it up:

- **Repo:** <https://github.com/leejianrong/simple-kanban>
- **Full onboarding guide (source of truth):**
  [`docs/guides/agent-onboarding.md`](https://github.com/leejianrong/simple-kanban/blob/main/docs/guides/agent-onboarding.md)

The short path to a working `kanban` MCP server in Claude Code:

1. **Get access + mint a PAT.** Log in at <https://simple-kanban-jian.fly.dev> (GitHub), open the
   **Tokens** tab, create one, and copy the `kanban_pat_…` secret (shown once). It authenticates as
   that user and is owner-gated exactly like them. (Or self-host — see the guide.)
2. **Wire the MCP** in `.mcp.json`. Two options (the guide has copy-paste blocks for both):
   - **Container (no local toolchain):** run the published image —
     `docker run -i --rm -e KANBAN_API_URL -e KANBAN_TOKEN -e KANBAN_BOARD_ID
     ghcr.io/leejianrong/simple-kanban-mcp:latest`. (Requires a published release; if the image
     isn't available yet, use the source path below.)
   - **From source with `uv`:** `uv run --directory ./mcp python -m pandan_mcp` from a checkout.
3. **Set env:** `KANBAN_API_URL` (`https://simple-kanban-jian.fly.dev` or a self-host origin),
   `KANBAN_TOKEN` (the PAT), and **`KANBAN_BOARD_ID`** (set it, or list/create tools span all your
   boards / land on the earliest). Restart Claude Code, then verify with the `warmup` then
   `list_boards` tools.

> Two personas: someone who just wants to **use** the board (track their own work via the MCP —
> steps above are enough) vs. a **contributor** driving the *simple-kanban repo itself* forward (the
> PM playbook below — needs a repo checkout, `gh`, and follows the branch/PR/merge conventions). The
> orchestration playbook that follows assumes the contributor persona.

## Prerequisites (check once, up front)

- The **Kanban MCP** is wired (`.mcp.json` at repo root points at the deployed API with a `KANBAN_TOKEN`
  PAT). Tools appear as `mcp__kanban__*`. If they're missing, tell the user to check `.mcp.json`.
- `gh` CLI is available and authenticated (`gh auth status`) — needed to open/merge PRs.
- You're in the repo working tree, `main` is protected (PR-only, CI must be green), and the app is
  **live in production** — landing a PR deploys. Treat merges accordingly.
- Confirm the **land policy** with the user before merging anything (see *Merge / land policy*).

## Step 0 — Orient

Always start by reading the whole board, top-down:

1. `mcp__kanban__list_boards` → find the target board's `id` (e.g. "Simple Kanban Roadmap").
2. `mcp__kanban__list_epics(board_id=…)` → the epics give you the thematic groupings + intent.
3. `mcp__kanban__list_cards(board_id=…)` → all cards with `column`, `position`, `story_points`,
   `epic_id`, `description`. Cards come back ordered by (column, position).

Read each card's `description` — this board writes real acceptance criteria and **dependency hints**
in prose (e.g. "Depends on the shared-client extraction", "Prerequisite for the CLI"). There is **no
structured dependency field**, so you must parse dependencies out of the text yourself and sequence
around them.

## Step 1 — Sequence the backlog

Pick the next card by these rules, in order:

1. **Respect prose dependencies.** If a card says it depends on another, don't start it until the
   dependency is `done`. (e.g. "extract shared client" before the CLI cards that import it.)
2. **Dogfooding-first / unblock-first.** Prefer small, self-contained cards that improve your own
   tooling or unblock a whole epic. Tool/parity gaps you personally hit belong at the front.
3. **Then by epic coherence + story points** — finish a started epic before opening a new one; among
   equals, smaller points first to keep momentum and validate the loop early.

State your chosen order to the user before diving in for a long run.

## Step 2 — The PM loop (per card, one sub-agent at a time)

**a. Pull.** Move the card into flight and tag it so the board reflects reality:
```
mcp__kanban__move_card(card_id=<id>, column="in_progress")
mcp__kanban__update_card(card_id=<id>, assignee="agent:<slug>")   # who's on it
```

**b. Delegate.** Spawn a `general-purpose` sub-agent with `isolation: "worktree"` (keeps your primary
checkout clean; the shared local Postgres works across worktrees). Give it the full card + the brief
template below.
- *Default:* one implementer at a time.
- *Measured parallel (when it pays off):* you MAY run 2+ agents concurrently **if their files are
  disjoint** (e.g. backend card vs a new CLI package) — worktree isolation prevents collisions. But
  always **serialize the landing**: review + merge one PR at a time so `main`/CI stay reviewable, and
  **land any card with a production migration ALONE** (undivided attention + prod-verify after deploy).
  Cards touching the same files (e.g. `server.py`/`EXPECTED_TOOLS`, or two docs cards both editing
  `CLAUDE.md`) must be combined into one agent/PR or run strictly serially.

**c. Verify.** When it reports back: sanity-review the diff and the PR, then poll CI to green (the
installed `gh` has **no** `--watch`; loop until no `pending`):
```
until ! gh pr checks <pr-number> 2>&1 | grep -q pending; do sleep 20; done; gh pr checks <pr-number>
```
CI is **7 jobs** (lint, unit, integration, frontend build, e2e, mcp, **client**). Don't land on red
or pending — but check *why* a red is red: a whole run failing at the same round duration is infra
(re-run), not your code (see UX log).

**d. Land** (per agreed policy). On green CI, for auto-merge:
```
gh pr merge <pr-number> --merge --delete-branch      # merge commit, not squash (repo convention)
mcp__kanban__move_card(card_id=<id>, column="done")
```

**e. Capture.** Append concrete learnings to this skill's *UX notes* log — what was awkward in the
board/MCP, what the sub-agent tripped on, anything worth doing differently next card.

## Sub-agent brief template

Fill the `<…>` and paste as the agent prompt:

```
You are implementing one vertical slice of the simple-kanban project. Ticket <KAN-N>: "<title>".

<full card description>

READ FIRST and follow exactly: /home/…/simple-kanban/CLAUDE.md — especially the dev workflow
(branch-per-slice off a fresh `main`), the exact local check commands, API-first (ADR 0005), and
the "verify against the code, don't trust the docs" rule. This is a thin slice — match the existing
incremental style; do not refactor beyond the ticket.

Workflow:
1. You are in an isolated worktree. Do NOT `git switch main` (it exits 128 when `main` is already
   checked out at the primary checkout). Base off latest main directly:
   `git fetch origin && git switch -c feat/<slice> origin/main`. Run all git against THIS worktree
   only — never `cd` into the parent/primary checkout (Bash is not sandboxed to the worktree).
2. Implement the slice. Keep it minimal and consistent with surrounding code.
3. Run the local checks for every package you touched (mirror of the pre-push hook):
   - backend (from backend/): `uv run ruff check .` + `uv run pytest tests/unit -q`
     + `uv run pytest tests/integration --collect-only -q` (import-hygiene guard)
   - frontend (from frontend/): `npm run check`
   - mcp (from mcp/): `uv run ruff check .` + `uv run pytest -q`
   Update any hard-coded expectations you change (e.g. mcp/tests/test_server.py `EXPECTED_TOOLS`,
   the tool table in mcp/README.md).
4. Commit (end the message with the repo's Co-Authored-By trailer), push, and open a PR with `gh`
   (clear title + body: what/why, test evidence, and OPS notes if any).

Report back, structured: branch name, PR URL, files touched, exactly which checks you ran + their
results, and any FRICTION / UX notes (anything about the board, MCP tools, or repo that slowed you
down — the PM is separately assessing tool UX).
```

## Merge / land policy

Confirm with the user which applies, then stick to it:
- **Auto-merge on green CI** — you merge once CI passes and you've sanity-reviewed the diff, then
  move the card to `done`. Fast; you are merging to production unattended, so review the diff.
- **Open PR, user merges** — you get CI green and report the PR; the user does the final merge.
- **Branch only** — sub-agent pushes a branch; no PR.

## Definition of done (per card)

CI green **and** PR merged **and** card moved to `done` **and** this skill's UX log updated. A card
is not done just because the code is written.

## UX notes & gotchas (running log — append as you learn)

Dogfooding observations about driving this board as an agent PM. Seeded from the plan; extend it.

- **No dependency field.** Dependencies live only in card `description` prose — you must read and
  sequence manually. A blocked-by relation on the board would remove guesswork.
- **`list_cards` spans/return shape.** Pass `board_id` explicitly (or set `KANBAN_BOARD_ID`) — with
  neither, list/create tools span all your boards / land on the earliest board. Cards return ordered
  by (column, position); there's no server-side "next up" concept — priority == your reading of it.
- **Column ≠ status of the *work*.** `in_progress` on the board just means "an agent is on it"; the
  real state (branch pushed? PR open? CI green? merged?) lives in git/`gh`, not the board. Keep the
  two in sync manually — move to `done` only after merge, not after the code is written.
- **No comment / note tool.** There's no way to attach a progress note, PR link, or decision to a
  card via MCP. `assignee` is the only free-text handle — repurpose it (`agent:<slug>`) to show who's
  on a card. A PR-URL / notes field would close the loop between board and repo.
- **`move_card` vs `update_card` split.** Column/position changes go through `move_card`; field edits
  through `update_card`. You can't set column + assignee in one call — it's two calls to pull a card.

- **Cold start is a HARD FAILURE, not just slow (biggest gotcha).** The free-tier app scales to zero.
  The docs call this a "~1s slow first request," but in practice the first calls after idle fail
  outright: the MCP tool returns `read operation timed out` / `SSL: UNEXPECTED_EOF_WHILE_READING`, and
  `curl` shows a TLS handshake `decode error` at ~5s — indistinguishable from "server is down." It
  took ~6 failed requests plus a `flyctl status` check before it served 200s. **Mitigation as PM:**
  before the first board call after any idle period, warm the app yourself and retry until healthy:
  `curl -sS -m 30 https://simple-kanban-jian.fly.dev/api/health` (loop 3–6×; expect `{"status":"ok"}`).
  Only then drive the MCP. (This is exactly what board Epic 7 / KAN-25/26/27 exist to fix — live proof
  the tickets are real.)
- **Pre-push hook is all-or-nothing across packages.** The tracked hook always runs `svelte-check`,
  which isn't installed in a worktree where the agent only `uv sync`'d the mcp package (no `npm ci`),
  so a *mcp-only* change fails the hook on the frontend toolchain and the agent must `git push
  --no-verify`. Tell single-package sub-agents up front that `--no-verify` is expected for a scoped
  slice (CI still gates the real check), or have them `npm ci` too.
- **`gh pr checks --watch` isn't available** in the installed gh here. Poll instead: loop
  `gh pr checks <n>` until the output has no `pending` (integration + e2e are the slow jobs, ~1–3 min).
- **Docs pin exact tool counts in prose** ("10 tools") in CLAUDE.md + mcp README/docstrings, so every
  parity slice silently staleness them. As PM, either budget a doc-sweep card or stop pinning counts.
- **What works well:** the MCP/backend is genuinely pleasant to extend — API-first means feature cards
  like KAN-10/11 are pure thin-adapter slices (add a `KanbanClient` method + a `@mcp.tool()`, mirror
  the `_clean`/`{"deleted": id}` conventions, bump the exact-match `EXPECTED_TOOLS` test). Sub-agents
  finish these in one pass. Lean into small, self-contained parity/tooling cards early.
- **Worktree sub-agents start from your CURRENT local `main`, not `origin/main`.** After you merge a
  PR, your local `main` is *behind* the remote (the merge happened on GitHub). The next worktree
  agent then branches off the stale commit and won't see the just-merged work — it has to
  `git fetch && git merge --ff-only origin/main` itself. **Two-part fix:** (1) after every merge, run
  `git -C <repo> fetch origin && git -C <repo> branch -f main origin/main` (or `git switch main &&
  git pull --ff-only` if main isn't checked out elsewhere) so the next worktree is spawned from fresh
  main; (2) still tell each sub-agent to `git switch main && git pull --ff-only` before branching, as
  a belt-and-braces guard. Also warn agents: `git reset --hard` is auto-denied as destructive in the
  harness — the clean-tree `--ff-only` merge is the sanctioned path anyway.
- **Sequential dependent cards need explicit hand-off of the prior state.** KAN-11 depended on KAN-10's
  merged `EXPECTED_TOOLS`=14. Put the *exact* prior-state facts in the next brief ("14 tools now, the
  4 KAN-10 tools are X/Y/Z, you're going to 16") so the agent can self-verify it's on the right base.
- **The MCP client's timeout is tighter than a cold-wake.** After idle, a raw `curl .../api/health`
  can return 200 on the first try while the *MCP tool call* still times out — the client gives up
  before the machine finishes waking. So warming with curl isn't always enough; you may still need to
  retry the first MCP call once or twice. (Reinforces KAN-25: generous timeout + one auto-retry in
  the shared client.)
- **Worktree isolation does NOT sandbox `Bash` — brief agents explicitly.** The harness blocks the
  `Write`/`Edit` tools from touching paths outside the agent's worktree, but `Bash` can still `cd`
  into the shared primary checkout and run `git switch -c` there, silently moving YOUR `main` checkout
  onto a feature branch. Two agents did a version of this. **In every sub-agent brief, say: "run all
  git against your worktree path only; never `cd` into the parent checkout."** As PM, keep your primary
  checkout parked on `main` and re-check `git branch --show-current` after each agent returns (both
  times it self-restored, but verify — don't assume).
- **Shared-package pattern in this uv monorepo: path source, not a root workspace.** KAN-21 extracted
  `pandan-client/` as a standalone uv package that `mcp` depends on via
  `[tool.uv.sources] pandan-client = { path = "../pandan-client", editable = true }`. A repo-root uv
  *workspace* would be auto-discovered when running `uv` from `backend/` and force `backend` into the
  workspace, breaking its independent `--frozen` flow. Each package stays independently locked; the
  lockfile records a *relative* path so CI's fresh checkout stays portable. Any new shared package
  also needs its own CI job (mirror the `mcp` job) — CI is now 7 jobs.
- **Distinguish CI *infra* failures from real ones before reacting.** A whole run of jobs all "failing"
  at the *same suspiciously-round duration* (e.g. every job at `15m1s`, including ones that normally
  take 11s) is an infrastructure symptom, not your code. Check the run's annotations
  (`gh run view <run-id>`): here it was *"The job was not acquired by Runner of type hosted even after
  multiple attempts"* — GitHub had no hosted runners free. Fix is a re-run, not a code change:
  `gh run rerun <run-id>` (or `gh run rerun <run-id> --failed`). Never move a card back or "fix" a
  red that's actually infra. Free-tier CI is flaky the same way the free-tier app is — budget for it.
- **Cold start recurs after ~5 min idle — warm before EVERY board interaction in a long session,**
  not just once at the start. A single card can span a >5-min CI wait, and the app scales to zero in
  the meantime, so the *move-to-done* call at the end of a card cold-starts again. Cheap habit: a
  `curl .../api/health` warm loop immediately before any `mcp__kanban__*` call that follows a gap.
- **`gh pr merge --delete-branch` can't delete the branch while it's checked out in the agent's
  worktree** — you'll see `failed to delete local branch … checked out at …/.claude/worktrees/…` and
  a non-zero exit, but the **merge itself still succeeds** (confirm with `gh pr view <n> --json state`
  → `MERGED`). The remote branch is deleted; the local one is cleaned when the harness reaps the
  worktree. Don't mistake that exit code for a failed merge.
- **A superseded Deploy shows `cancelled`, not failed — and is still covered.** When two mergeable
  PRs land seconds apart, the second merge's Deploy cancels the first's (deploy concurrency group).
  But Deploy checks out current `main` HEAD, so the *later* deploy contains the earlier merge's code
  too. Observed: #45 (backend, KAN-29) Deploy `cancelled` when #46 merged right after, but #46's
  Deploy (`success`) shipped HEAD which included KAN-29 — prod-verified live. A `cancelled` Deploy
  superseded by a newer merge is a non-event; verify prod reflects HEAD rather than re-running it.
- **`pandan-cli/`-only merges still trigger a real (harmless) Deploy.** The Deploy skip-filter treats
  docs/.claude/.github/mcp/client as non-deployable but did NOT exclude `pandan-cli/`, so #46 (cli-only)
  ran a full ~46s Deploy though nothing in the Fly image changed. Harmless (no-op image), but an
  avoidable rollout window — worth extending the Deploy skip-filter to cli/mcp/client (none are in the
  deployed artifact). Separate from CI's `changes` filter (which KAN-24 did extend to `pandan-cli/**`).
- **Right-side of the "MCP restart" nuance, reconfirmed at scale.** KAN-29's new `blocked` FIELD showed
  up in `claim_card`/`list_cards` MCP output the same session, no restart (JSON passthrough). But
  KAN-31's new TOOLS (`add_dependency`/`remove_dependency`/`list_dependencies`) are NOT callable until
  the user restarts this session + re-`uv sync`s `mcp/`. So during the same session you *build* dep
  tools in, you still can't set dependencies via MCP — use `curl` against the API if you must set one.
- **3-wide measured parallel works cleanly when disjointness is verified against the CODE first.**
  Extended the KAN-28+KAN-22 two-agent precedent to three concurrent Wave-1 agents (backend / mcp+client
  / cli) with zero conflicts, then serialized landing. The enabler was checking file sets in the source,
  not the plan: KAN-23 (cli) does NOT touch `pandan-client/` even though KAN-31 does — the client's
  board/epic methods already existed — so cli-vs-client were genuinely disjoint. Don't trust a
  "same-ish area" hunch; grep the actual imports/methods before declaring two cards parallel-safe.
- **A monorepo path-source package installs cleanly over `git+…#subdirectory=`.** Contrary to the
  assumption that the `../pandan-client` path dependency would break a git install,
  `uv tool install "git+https://…/simple-kanban.git#subdirectory=pandan-cli"` resolves the sibling path
  source from the same fetched clone. uv's monorepo resolution over git is more capable than expected —
  relevant to the distribution cards (KAN-46 binary / KAN-47 OCI image).
- **CI is now the `changes` gate + 8 work jobs = 9 checks** (added `cli` in KAN-24). Only Lint/Unit/
  Integration/Frontend are branch-protection *required*; `cli`/`mcp`/`client`/`e2e` report green but
  aren't individually required (per KAN-37). A gotcha this created: a `pandan-cli/`-only PR *before*
  KAN-24 (e.g. KAN-23's #46) wasn't mapped, so its heavy jobs pass-*skipped* — green CI there meant
  nothing; the sub-agent's local `ruff`+`pytest` was the real signal. KAN-24 closed that by mapping
  `pandan-cli/**`, so its own #47 was the first PR where the `cli` job actually ran (8s, real work).

## Session log (what's been run through this playbook)

- **Epic 5 — Agent & API Completeness: COMPLETE.** KAN-10 (MCP write parity → PR #26, tools 10→14)
  and KAN-11 (MCP read parity → PR #27, tools 14→16) both merged + `done`. Net: the MCP server now
  has full CRUD parity for cards, epics, and boards (16 tools) — the `delete_board` gap that
  triggered KAN-10 during dogfooding is closed.
- **KAN-21 (Epic 6, kan CLI): shared `pandan_client` extracted** → PR #29, `done`. The httpx client
  moved out of `mcp/` into a standalone `pandan-client/` uv package (path source, see gotcha above);
  CI grew a 7th `client` job. Unblocks the CLI cards (KAN-22/23/24) and KAN-25.
- **KAN-25 (Epic 7, cold-start): retry + generous timeout in the shared client** → PR #31, `done`.
  35s read / 5s connect timeout, 1s backoff, one retry — connect/handshake errors retried for all
  methods, `ReadTimeout` only for idempotent GET, never on 4xx/5xx (LWW → no double writes). Directly
  targets the cold-start failures logged above.
  - **Caveat: this does NOT fix cold starts for THIS session.** Claude Code loads the MCP server once
    at session start, so its `pandan_client` is the pre-merge code until the user restarts the session
    (and re-`uv sync`s `mcp/`). The retry benefits *future* sessions + the future CLI. Keep warming by
    hand for the rest of this session. **KAN-27 (keep-alive cron) is the complementary server-side fix.**
- **Known doc-drift to clean up (flagged by 2 sub-agents):** `CLAUDE.md`'s MCP section still says
  "10 tools" (now 16) and references the MCP server's old `api.py` (moved to `pandan-client/` in KAN-21).
  Good PM hygiene: file it or fix it rather than let it rot.
- **Backlog groomed from dogfooding.** The "board can't tell the whole story" friction (no
  dependency field; no PR-link/notes field; column = "an agent is on it" ≠ real work state) was turned
  into **EPIC-8 "M4: Board as an Agent-PM Surface"** with 7 vertical slices, **KAN-28…KAN-34**:
  card dependencies (model+API → ready/blocked query filter → UI → MCP) and card work-links + notes
  (model+API × 2 → MCP+UI). This is the PM job working as intended: dogfooding surfaces a gap → it
  becomes prioritised backlog. A good PM agent files what it learns, not just what it's told.
- **KAN-27 (Epic 7): keep-alive GitHub Actions cron** → PR #33, `done`. Verified it live: it succeeds
  instantly when the app is up but FAILED (curl exit 35) when triggered during a deploy rollout — so
  *verifying shipped work found a defect*, filed as KAN-45.
- **KAN-45 (Epic 7): hardened the keep-alive** → PR #35, `done`. Poll `/api/health` for ~150s and
  soft-fail (warn, exit 0) so a deploy/cold-start window neither under-warms nor falsely reds the run.
- **EPIC-9 "M4: PM & Ops Ergonomics": COMPLETE** (all groomed from this session's own friction):
  - **KAN-36** (PR #36) — pre-push hook path-scoped to changed areas; scoped slices no longer forced
    to `--no-verify`.
  - **KAN-35 + KAN-41** (PR #37) — refreshed stale `CLAUDE.md` MCP prose + documented/defaulted
    `KANBAN_BOARD_ID`.
  - **KAN-37** (PR #38) — CI path filters: docs-only PRs skip heavy work while ALL required checks
    still report green (gate-safe step-level skip; the aggressive runner-count cut needs a
    branch-protection change, documented as follow-up). **Confirmed live**: PR #39's untouched jobs
    finished in 3–5s. Also discovered the *actual* required checks are only 4 (Lint, Unit, Integration,
    Frontend) — the e2e/mcp/client jobs aren't individually required.
  - **KAN-38/39/40** (PR #39) — `claim_card` (atomic pull), `warmup` (wake via MCP), `create_cards`
    (batch); tools 16→19, logic in the shared client so the future CLI inherits it. *Future-session
    benefit only* (MCP loads at session start), same caveat as KAN-25.
- **Two new epics filed** from the UX assessment: **EPIC-9** (done) and **EPIC-10 "PR-Board Auto-Sync"**
  (KAN-42/43/44 — GitHub webhook → auto-update the linked card; the big bet to make column reflect real
  work state; depends on EPIC-8).
- **Workflow lessons that worked this session:**
  - **Pipeline the loop.** "One sub-agent at a time" means one *implementer coding* at a time — you can
    still spawn the next card's agent while the previous PR sits in CI, as long as their files don't
    overlap. Cut a lot of idle CI-watching. (Cards touching the same files — e.g. anything editing
    `server.py`/`EXPECTED_TOOLS`, or two docs cards both editing `CLAUDE.md` — must be combined into one
    agent/PR or run strictly serially.)
  - **Only *deployable* merges trigger a CD deploy + rollout outage.** Corrected from an earlier note:
    the Deploy workflow **skips** docs/CI/`.claude`-only merges (observed: #40's deploy = `skipped`),
    so those cause at most a plain cold start. A merge that touches app code (backend/frontend) DOES
    deploy → a ~60–90s rollout where the app returns TLS-EOF; warm through it before the next
    `mcp__kanban__*` call. Neither KAN-25's retry nor KAN-27/45's keep-alive fully covers a rollout —
    a rolling/blue-green deploy would (host-independent; not yet filed).
  - **`update_card` silently ignores `column`** — column changes go through `move_card` only. (Live
    proof of why KAN-38's `claim_card` exists.)
- **KAN-28 + KAN-22 in PARALLEL (measured parallel):** two agents coded concurrently in worktrees
  (backend deps model vs new `pandan-cli/` package — disjoint files, zero conflict), then **landed
  serially**. Refinement to the "one at a time" rule: parallelize *implementation* freely when files
  don't overlap; **serialize the *landing*** (review + merge one PR at a time). **A card carrying a
  production migration lands ALONE and gets verified on prod** — after KAN-28 deployed, confirmed
  migration `0007` live by reading `/api/v1/cards` and checking `blocked_by`/`blocks` appear (the read
  queries `card_dependency`, so a 200-with-arrays proves both code + table deployed). Wait for the
  **Deploy** workflow to finish (`gh run list --workflow deploy.yml`) before prod-verifying — a green
  PR merge ≠ deployed yet (build takes minutes).
- **Nuance on the "MCP changes need a restart" caveat:** *tool-list* changes (new tools, KAN-38/39/40)
  are fixed at session start. But the MCP passes API JSON straight through, so an **API response-shape
  change is visible immediately** — KAN-28's `blocked_by`/`blocks` showed up in `move_card` output
  this same session once deployed. Restart is only needed for new/changed *tools*, not new *fields*.
- **Reading the PAT for a prod smoke-test:** never inline the `kanban_pat_…` literal (the safety
  classifier blocks it as credential leakage). Read it from `.mcp.json` into an env var:
  `export KANBAN_TOKEN=$(python3 -c "import json;print(json.load(open('.mcp.json'))['mcpServers']['kanban']['env']['KANBAN_TOKEN'])")` then use `$KANBAN_TOKEN`. Also: raw `GET /api/v1/cards`
  returns a bare JSON **array** (the MCP client wraps it as `{"cards":[…]}`).
- **Session tally:** EPIC-5 ✅, EPIC-9 ✅ complete; EPIC-7 all but KAN-26 (needs CLI); KAN-21+KAN-22
  done (CLI card commands shipped; KAN-23/24 remain); KAN-28 done (EPIC-8 foundation — unblocks
  KAN-29/30/31 and, with links/comments, EPIC-10). 15 feature cards + skill merged across the session.
- **Suggested next pull:** KAN-29 (ready/blocked query filter — builds directly on KAN-28 and gives
  the PM a "next unblocked card" query), or KAN-23/24 to finish the CLI, or KAN-31 (dependencies in
  MCP so the agent PM can set blockers directly).
- **EPIC-8 (deps) + EPIC-6 (CLI) batch — 4 cards via 3-wide measured parallel, all merged + done:**
  Wave 1 ran three concurrent worktree agents on disjoint dirs, landed serially; Wave 2 was the one
  overlapping card. All four are dependency-free of a DB migration (KAN-28 already shipped the table),
  so the "migration lands alone + prod-verify" rule was NOT triggered.
  - **KAN-29** (#45, EPIC-8) — `blocked` field + `blocked=true|false` filter on `GET /api/v1/cards`
    (SQL `EXISTS` twin of the Python compute, applied before the cursor clause so keyset pagination
    stays exact; no N+1). **Prod-verified** read-only: field present, filter partitions
    (true=0 / false=38 / all=38). Backend → deployed.
  - **KAN-31** (#44, EPIC-8) — `add_/remove_/list_dependencies` MCP tools + client methods (thin
    adapter over KAN-28's endpoints; `list_dependencies` = `get_card` reshaped, since there's no list
    endpoint). `EXPECTED_TOOLS` 19→22. mcp/+client, no deploy.
  - **KAN-23** (#46, EPIC-6) — `kan board list/create` + `kan epic list/create/update/delete` as
    nested subcommand groups (client methods already existed; cli-only, disjoint from KAN-31).
  - **KAN-24** (#47, EPIC-6) — CLI README + `readme` pointer + `--help` polish + a CI `cli` job
    mirroring `mcp`, and extended KAN-37's `changes` filter to map `pandan-cli/**`. CI now 9 checks.
- **Two distribution cards filed** from a user design discussion (how to ship the CLI + MCP so end
  users need no toolchain): **KAN-46** (EPIC-6) — ship `kan` as a standalone PyInstaller `--onefile`
  binary via a per-OS CI release matrix → GitHub Releases (no Python needed); **KAN-47** (EPIC-5) —
  publish the MCP server as an OCI image to **ghcr.io** (`docker run`, bundles `pandan-client` at build
  time). Rationale worth keeping: **GitHub Packages has NO native pip index** (it hosts npm / Container
  / Maven / Gradle / NuGet / RubyGems), so for our Python packages the GitHub-hosted options are a
  container image (ghcr.io) or loose files on Releases — not a `pip install`-by-name index. PyPI would
  be the real index but needs accounts + trusted-publishing CI + cross-package version management;
  deferred, not part of this batch.
- **Epic status after this batch:** EPIC-8 — KAN-28/29/31 done; **KAN-30 (deps in the board UI)**
  remains (the only non-done EPIC-8 card besides the work-links/notes line KAN-32/33/34). EPIC-6 (kan
  CLI) — KAN-21/22/23/24 done; **KAN-26 (`kan warmup`)** and **KAN-46 (binary)** remain.

- **EPIC-8 CLOSED + EPIC-7 CLOSED (this session — 5 cards, auto-merge on green CI):** finished the
  agent-PM-surface epic. Order run: **KAN-26** (`kan warmup`, #49 — closed EPIC-7) → **KAN-32**
  (work-links model+API, #50, migration `0008`) → **KAN-33** (comments model+API, #51, migration
  `0009`) → **KAN-30** (deps UI, #52) → **KAN-34** (links+notes MCP+UI, #53, `EXPECTED_TOOLS` 22→26).
  All merged + `done`. **EPIC-8 is now fully done (KAN-28/29/30/31/32/33/34) → EPIC-10 (PR-board
  auto-sync) is unblocked.**
  - **Interrupted-agent RECOVERY (new, important):** the KAN-34 agent was mid-flight when the prior CC
    process exited — its notification came back `status: stopped` with "no completion record". **Do
    NOT restart from scratch.** The worktree preserves ALL uncommitted work (here: ~600 lines across
    11 files, un-committed, no PR). Diagnose first: `gh pr list` (none), `git ls-remote --heads origin`
    (nothing pushed), `git worktree list` (worktree still there, branch at base commit), then
    `git -C <worktree> status --short` + `diff --stat` to see the partial work. Then **resume the same
    agent via SendMessage(to=<agentId>)** — it picks up from its transcript with full context and just
    needs to finish (justify stray files, run checks, commit, push, PR). Cost of the interruption: ~0.
  - **2-wide parallel migration-backend ∥ frontend worked cleanly.** Ran KAN-33 (backend, migration
    `0009`) concurrently with KAN-30 (frontend deps UI) — genuinely disjoint file sets — then landed
    serially (KAN-33 alone + prod-verify first). Confirms the rule: parallelize *implementation* when
    files don't overlap; serialize the *landing*; migration cards still land ALONE.
  - **KAN-34 had to run SOLO despite being unblocked in principle:** it edits the same Card-view files
    (`Card.svelte`/`CardForm.svelte`/`api.ts`/`board.svelte.ts`/`app.css`) that KAN-30 just landed, AND
    `mcp/server.py`. So it was sequenced last (after KAN-30 merged) to avoid frontend collisions. Lesson
    reinforced: "unblocked by dependency" ≠ "parallel-safe" — check the actual file overlap.
  - **Deploy timing gotcha (reconfirmed + refined):** the Deploy workflow triggers `on: workflow_run`
    AFTER CI completes on `main`, so right after a merge you'll see the *previous* HEAD's deploy, not
    yours. To prod-verify the right commit: wait for **CI on the merge commit** to finish, THEN wait
    for **Deploy on that same SHA** (`gh run list --workflow deploy.yml … | select(.headSha|startswith(<sha>))`).
    Don't trust `-L 1` — it may be a stale/older-SHA `workflow_run` firing.
  - **Prod-verify pattern for migration cards held up well:** for KAN-32 read a card and asserted the
    new `links` field is present (`[]`); for KAN-33 did a full POST→GET→DELETE(204) comment round-trip
    via `curl` (reading the PAT from `.mcp.json` into `$KANBAN_TOKEN`, never inlining the literal). Raw
    `GET /api/v1/cards` returns a bare JSON array (MCP wraps it).
  - **Forward-looking authz note (file under EPIC-3):** KAN-33's "delete your own comment" 403 path is
    **not reachable via HTTP under the single-owner board model (V8)** — any principal that can reach a
    card IS the board owner, and their PATs resolve to the same user, so every comment they can post
    shares their `author_id`. The author-check is dormant defense that only bites once boards become
    shareable (EPIC-3 KAN-12+). The KAN-33 tests exercise it by seeding a foreign-authored row via the
    DB directly. Good signal that EPIC-3 (membership/roles) is the natural next milestone.
  - **`session.svelte.ts` rune pattern (new, reusable):** KAN-34 needed the signed-in user id deep in
    the tree (comment thread's delete-own affordance) without prop-threading Board→Column→Card→CardForm.
    Solution: a tiny `$state` rune module (`session.svelte.ts`) set once in `App.svelte` after the auth
    check (and cleared on logout). Clean pattern for any future "current user" UI need.
  - **New MCP FIELD vs new MCP TOOL, reconfirmed:** KAN-34's `links[]` on card reads is a *field* → it
    passes straight through this session (JSON passthrough), but its 4 new *tools* (`add_link`/
    `remove_link`/`add_comment`/`list_comments`) are NOT callable until a session restart + `uv sync`
    in `mcp/`. So the PM can't set links/comments via MCP this session — use the UI or `curl`.
  - **Session tally:** EPIC-7 ✅ and EPIC-8 ✅ both closed. Remaining backlog: EPIC-6 KAN-46 (CLI
    binary), EPIC-5 KAN-47 (MCP OCI image), EPIC-10 KAN-42/43/44 (now unblocked — needs a GitHub
    webhook receiver first), and the two big new milestones EPIC-3 (board collaboration/sharing,
    KAN-12→16) and EPIC-4 (trust & history: activity log + soft-delete, KAN-17→20).

- **Distribution + UI-polish batch (2-agent parallel, distribution vs UI):** user asked for KAN-46/47
  (distribution) plus a fresh UI-polish stream, split across 2 concurrent agents (disjoint: CI/packaging
  vs frontend). All landed + prod-verified.
  - **KAN-46** (#54) — `kan` PyInstaller `--onefile` binary + tag-triggered `release-cli.yml` matrix.
    **KAN-47** (#55) — MCP server OCI image to ghcr.io (`mcp/Dockerfile` at REPO-ROOT context, bundling
    `pandan-client`) + tag-triggered publish workflow. Both CI/packaging-only (no deploy). **Closed
    EPIC-6 (kan CLI).** Key gotchas the agent surfaced: PyInstaller must freeze a dedicated
    absolute-import entry file (`__main__.py`'s relative import breaks frozen); the mcp Docker build
    context MUST be the repo root to COPY the sibling `pandan-client/`; publishing is tag-gated only
    (no artifact on PR/merge) and the first ghcr push is PRIVATE until made public.
  - **NEW epic EPIC-16 "M4: UI/UX Polish"** (filed this session) + cards **KAN-65/66/67**, all done in
    ONE PR (#56): card detail modal (click-anywhere, edit-in-place, Status via move endpoint), epic
    edit modal, Epics page centered + Active/Completed grouping (empty→Active), Tokens page centered,
    board-switcher restyle, unified `Brand` (top bar + landing), persistent light/dark theme toggle.
    New shared `Modal`/`CardModal`/`EpicModal`/`Brand` + `theme.svelte.ts`; `CardForm` slimmed to
    create-only.
  - **UI workflow pattern that worked well (reuse this):** a UI card with a visual bar was run in TWO
    phases by the SAME agent. Phase 1 = design only: run the app, Playwright-screenshot the current
    (bad) state, extract the real design tokens from `app.css`, build a self-contained HTML MOCKUP —
    NO real code. The PM strips the mockup's `<!doctype>/<html>/<head>/<body>` wrappers (Artifact
    publisher re-adds them; a `sed -n '<style-range>p;<body-range>p'` slice works) and publishes it as
    an **Artifact** for the user to approve. Then RESUME the same agent (SendMessage, keeps context) to
    implement, capturing real-UI screenshots. PM confirms fidelity by Read-ing the PNGs, then builds a
    second **Artifact gallery** embedding them as data-URIs — generate the base64 in a SHELL script that
    appends to the HTML file so the base64 never enters PM context (`base64 -w0 … >> out.html`).
  - **Mid-run scope growth is fine via SendMessage to a still-running agent.** The user added asks
    mid-flight (board-selector polish, then epic modal + logo standardization + theme toggle); each was
    queued to the running UI agent and folded into the same PR. Confirm genuine scope forks (the epic
    modal) with the user via AskUserQuestion before instructing the agent.
  - **Prod-verify for a frontend-only deploy:** no migration to check, so instead curl the deployed
    `/` for the hashed `/assets/index-*.js`, then `curl` that bundle and `grep` for distinctive NEW
    strings ("add a blocker", "Save changes", "data-theme") to prove the new SPA actually shipped —
    cheap and definitive without a browser. (e2e in CI already covers behavior.)
  - **Interrupted-agent recovery, AGAIN (KAN-34 earlier + reused here):** resuming a stopped agent from
    its transcript+worktree via SendMessage is the default move — never restart from scratch; the
    worktree preserves all uncommitted work.
  - **Session tally (this run):** EPIC-7 ✅, EPIC-8 ✅, EPIC-6 ✅ (KAN-46 closed it), EPIC-16 ✅ (new).
    KAN-47 done (EPIC-5's last non-webhook card). Remaining: EPIC-10 KAN-42/43/44 (auto-sync, unblocked),
    EPIC-3 (KAN-12→16 collaboration), EPIC-4 (KAN-17→20 trust/history).

- **Docs / distribution-readiness (new epic EPIC-17 "Onboarding & Distribution Docs"):** user asked
  whether the CLI/MCP are ready to hand to other teams + to refresh docs. Findings + work:
  - **Distribution readiness gotcha (important):** the KAN-46/47 release+publish workflows are
    tag-gated and had **NEVER RUN** — the only tag `v0.1.0` (Jul 7) predates them (Jul 11), so **no
    GitHub Release binary and no ghcr image exist yet** (`gh release view v0.1.0` → not found; the ghcr
    package → 404). "Code-complete + CI-green" ≠ "distributable". To actually ship the clients you must
    cut a NEW `v*` tag (both workflows fire) AND make the ghcr package public (first push is private).
    Filed as **KAN-79** (deferred by the owner — outward-facing, so gated on explicit go).
  - **KAN-77 + KAN-78 (#57) → done. Closed EPIC-17.** Refreshed the badly-stale root README (it still
    said "one global board, no accounts, no auth" + "status: core board complete, seed+e2e left" +
    unversioned `/api/cards`) and added `docs/guides/agent-onboarding.md` (mint a PAT → wire MCP into
    Claude Code via the uv-from-source path → example agent workflows → CLI for CI → self-host →
    single-owner note). Docs-only; verified against source.
  - **Docs-honesty catch worth reusing:** the sub-agent flagged that `mcp/README.md` + `pandan-cli/README.md`
    already presented the ghcr image + a `curl …/releases/latest/download/…` binary as if they WORK
    TODAY (dead 404s until a release is cut). Since the release was deferred, I had it soften both to
    "available once a versioned release is published" in the SAME PR. Lesson: when writing onboarding
    docs, grep the EXISTING package READMEs for premature "download/pull" instructions that assume an
    uncut release — fix or gate them, don't ship users toward 404s.
  - **EPIC-3 (board sharing) timing guidance given to the owner:** defer until a real second-user/team
    need appears — it's the largest, authz-sensitive, migration-carrying chunk, and the cost of waiting
    is only felt once there are concurrent users; self-hosting covers multi-team in the interim. Start
    it earlier ONLY if external adoption of the HOSTED instance becomes the priority (it's the sole
    unblock for shared hosted boards). Ship EPIC-10 (auto-sync) + EPIC-4 (soft-delete) first — both
    deliver value single-user and are smaller/safer.

- **First real release cut + UAT'd (KAN-79 → v0.2.0/0.2.1/0.2.2; KAN-81 defect; KAN-85 UAT):** the
  whole "make it distributable" arc, PM-orchestrated tag pushes + a prod-verify loop.
  - **Cutting a tag-gated release, mechanics that worked:** version-bump PR first (bump mcp/cli/client
    pyproject + **regenerate uv.lock** — the release paths `uv sync --frozen`, so a stale lock fails
    the moment the tag runs), merge, then `git tag vX.Y.Z <merge-sha> && git push origin vX.Y.Z` fires
    both `release-cli.yml` + `publish-mcp-image.yml` (both trigger `on: push tags 'v*'`; artifacts
    version off the TAG, not pyproject). Pre-push hook lets a tag through fine.
  - **ghcr first push is PRIVATE — a manual GitHub web-UI step to make public** (the `gh` token here
    lacks `packages` scope; `gh api PATCH visibility` 403s). Path: github.com/users/<u>/packages/
    container/<pkg>/settings → Change visibility → Public. Until then unauth `docker pull` 404s. This
    is a hard hand-off to the human owner; can't be automated with the default token.
  - **Prod-verify caught a real defect CI structurally couldn't (KAN-81).** The `kan-linux-x86_64`
    PyInstaller binary built on `ubuntu-latest` (24.04, glibc 2.39) required GLIBC_2.38 and FAILED on
    Ubuntu 22.04/Debian 12 (glibc ≤2.36) — but CI's in-job smoke test passed because it runs the binary
    on the same 24.04 it built on. Only downloading the asset and running it on an older-glibc box
    (this WSL is 2.35) exposed it. **Lesson: for a distributable binary, "CI smoke test green" is not
    prod-verify — pull the actual asset and run it on the OLDEST target you support.**
  - **glibc-floor fix, two rounds (user suggested the base):** build the linux leg in a glibc-2.28
    container. Round 1 used `quay.io/pypa/manylinux_2_28`'s preinstalled `/opt/python` — FAILED:
    "Python was built without a shared library, which is required by PyInstaller" (manylinux CPython is
    static). Round 2 fix: keep the manylinux container (for glibc 2.28 + GH-Actions tooling) but use
    **uv's managed standalone CPython** (`uv python install 3.12` + `UV_PYTHON_PREFERENCE=only-managed`,
    scoped to the linux leg) — python-build-standalone ships a SHARED libpython AND is built ~glibc 2.17.
    Verified on v0.2.2: the binary now runs on this glibc-2.35 box. (Set the env-pref via `$GITHUB_ENV`
    on the linux step only; a job-level matrix `env` with `''` on the macOS legs errors in uv.)
  - **UAT round (KAN-85), what to actually exercise:** MCP — `docker logout` then unauth `docker pull`,
    then pipe JSON-RPC `initialize` + `notifications/initialized` + `tools/list` (unauth) and a
    `tools/call list_boards` (real PAT) through `docker run -i`. CLI — install to `~/.local/bin` (on
    PATH, no sudo; `/usr/local/bin` needs sudo which isn't available non-interactively here), run from
    an unrelated dir to prove PATH, then reads + a full create→update→move→delete→verify-404 CRUD with
    a `uat-` throwaway card. Wrote it up as a proper UAT doc (`docs/UAT-cli-mcp-v0.2.2.md`).
  - **Skill made global (this session):** added a "Getting started (new users)" onboarding section
    (repo link + `docs/guides/agent-onboarding.md` + container/uv MCP wiring) and installed a CLEANED,
    portable copy at `~/.claude/skills/project-manager-simple-kanban/` (playbook + reusable gotchas,
    session log trimmed) so it's available in all sessions; the in-repo copy keeps this full log.
    Global user-skills live in `~/.claude/skills/` (real dir or symlink); a same-named project skill
    still wins inside the repo.
- **M4 Wave 1 — first 2-agent parallel wave (KAN-42 ‖ KAN-12): both merged + `done`.** Ran two
  worktree sub-agents concurrently on file-disjoint cards — KAN-42 (GitHub webhook receiver, PR #64,
  no migration) alongside KAN-12 (board membership model + API, PR #65, migration
  `0010_board_members`). Land policy: auto-merge on green; migration card landed alone.
  - **Disjointness was grep-verified, but `app/main.py` is the shared choke point.** Both backend
    cards must register a router in `main.py` (the `from .routers import …` line + an
    `include_router`). The first PR to land (#64) merged clean; the second (#65) then CONFLICTED on
    exactly that file. Cheap (union of two one-liners) but it means "two new backend routers in
    parallel" always costs one rebase. Next time: land in quick succession and plan for the rebase,
    or branch the second card off the first. Resolved by resuming the same agent via SendMessage to
    `git rebase origin/main` (keep both routers) + `--force-with-lease` — PR updated in place, and the
    migration chain stayed linear (0010 on 0009, single head — #64 added no migration).
  - **Migration prod-verify = exercise the new relation, not just watch the deploy go green.** After
    the `fccef46` merge deployed, `GET /api/v1/boards/5/members` → `200 []` (proves the `board_member`
    table exists — a missing migration would 500 on the query), and a bogus-email POST → `404 User
    not found` (write path + error contract, zero mutation). GET-the-new-endpoint is the cheapest
    honest migration verify.
  - **Alembic autogenerate is noisy here (flagged by the KAN-12 agent).** `alembic revision
    --autogenerate` reports every migration-created index as "removed" (indexes are created in
    migrations, not declared on the models) and omits `sa.Identity` on PKs — so hand-writing the
    migration is the right convention. Worth a CLAUDE.md note so future slices don't blind-commit
    autogenerate output.
  - **Product decision captured into card scope mid-flight.** User asked whether GitHub auto-sync is
    opt-out — decided PER-BOARD OPT-IN, default OFF (`board.autosync_enabled` toggle + a separate,
    also-default-off column-auto-advance flag). Written straight into the KAN-43/KAN-44 descriptions
    so Wave 2 builds the agreed shape; the close-the-loop ADR (KAN-44) must document both.
- **M4 Wave 2 — KAN-43 (auto-sync mapping) ‖ KAN-14 (members UI): both merged + `done`.** The
  proposed trio (KAN-13 + KAN-14 + KAN-43) did NOT survive grep-verification — so it became a clean
  2-agent backend/frontend split instead. The two collision findings are the reusable lesson:
  - **`routers/cards.py` is a concentration point.** Card links, comments, dependencies AND `move`
    all live in that one ~600-line router. So KAN-13 (role enforcement — edits ~15 `authorize_board`
    call sites there) and KAN-43 (needs link/comment/move logic) both pull toward it. Fix: brief the
    KAN-43 agent to write side effects DIRECTLY against the `CardLink`/`CardComment` ORM models +
    `ordering.py` helpers in a NEW module (`app/autosync.py`), explicitly barred from `cards.py`. It
    complied (`git diff --name-only` confirmed 0 cards.py hits), staying disjoint and leaving KAN-13
    a clean cards.py to rebase onto later. **Extracting the shared logic into a new module is how you
    keep a router-heavy card parallelizable.**
  - **The frontend is monolithic in `App.svelte` + `board.svelte.ts`.** Top-bar view toggle, board
    switcher, and the board store all route through those two files, so ANY two frontend cards (e.g.
    KAN-14 members panel vs KAN-15 switcher) collide there the way two backend routers collide on
    `main.py`. Practical rule: **the reliably-disjoint parallel split here is backend-vs-frontend**;
    two same-side cards need serialized landing + a rebase. KAN-43 (0 frontend files) ‖ KAN-14 (0
    backend files) had zero shared files and both PRs merged without a rebase.
  - **An opt-in flag needs an opt-in API — agent caught it.** KAN-43's card listed the per-board
    toggle but no way to SET it; the agent exposed both flags on `BoardRead`/`BoardUpdate` (settable
    via the existing `PATCH /api/v1/boards/{id}`, no boards-router change). Good scope judgment —
    flagged rather than silently expanded.
  - **Migration prod-verify by round-trip:** `GET /api/v1/boards/5` showed both `autosync_*` flags
    defaulting `false` (0011 migrated), then `PATCH autosync_enabled=true` → re-GET `true` → reset to
    `false`. Frontend prod-verify: grepped the deployed hashed bundle for `Members`/`/members`.
  - **`gh pr edit --body` gotcha (KAN-14 agent):** it aborts on a "Projects (classic) deprecated"
    GraphQL warning, leaving the body stale. Workaround: `gh api -X PATCH repos/:owner/:repo/pulls/N
    -F body=@file`.
- **M4 Wave 3 — KAN-13 (role enforcement) ‖ KAN-44 (auto-sync docs + ADR): both merged + `done`;
  EPIC-10 auto-sync now COMPLETE (KAN-42/43/44).** The disjoint split this wave was **code vs docs**
  — the reliable third axis alongside backend-vs-frontend.
  - **KAN-13 was deliberately run near-solo among backend cards.** It rewrites `authorize_board`
    into an `Access(IntEnum)` (READ<WRITE<MANAGE) + effective-role resolver and touches EVERY call
    site across cards/epics/boards/members routers — so it collides with essentially any other
    backend card. Pairing it only with a docs card (KAN-44) was the right call; a second backend card
    would have fought it in four routers at once. Lesson: **a card that edits a cross-cutting helper's
    call sites everywhere is a "solo-backend" card — schedule it with docs/frontend only.**
  - **Prod-verify a central-authz refactor = prove the owner path didn't regress, not just the new
    branch.** The viewer/editor 403 differentiation is covered by 192 integration tests (8 new), but
    the real prod risk of refactoring `authorize_board` is breaking ALL board access. Verified with
    the owner PAT: READ (GET cards/members) 200, WRITE (no-op PATCH card, same title) 200, MANAGE
    (no-op PATCH board) 200. Reproducing the 403s in prod needs a second real user/member (no board
    sharing to a throwaway user exists yet), so that stayed test-covered — called out rather than
    faked.
  - **Docs card closed an epic cleanly + caught a UX gap.** KAN-44 (guide + ADR 0016) verified the
    documented behavior against the actual source and noted there is **no frontend toggle** for the
    per-board `autosync_*` flags — the `PATCH /api/v1/boards/{id}` API is the only way to set them
    today. Worth a future small frontend card (a board-settings switch) so opt-in isn't API-only.
  - **Worktree isolation guard is consistent across agents:** several agents' first Write hit the
    shared-checkout path and was rejected, then succeeded against the worktree path — harmless, but
    brief agents that Write targets must be the worktree copy.
- **M4 Wave 4 — EPIC-4 "Trust & History" closed: KAN-19 (soft-delete) → KAN-18 (activity feed) →
  KAN-20 (trash & restore), all merged + `done`.** Sequencing was dictated by two hard facts, worth
  reusing: (1) KAN-20 (trash/restore) hard-depends on KAN-19's `deleted_at` and edits the same
  routers, so it had to land *after* KAN-19; (2) the reliable disjoint parallel split was again
  **backend-router A vs backend-router B + frontend** — KAN-19 (models + `cards.py`/`epics.py` +
  migration, no frontend) ran concurrently with KAN-18 (`boards.py` + a new frontend panel), whose
  only shared file was `schemas.py` (additive append, no conflict). KAN-18's `ActivityRead` and
  KAN-19's model columns never touched the same lines.
  - **The activity feed was two cards, split at the write/read seam.** KAN-17 had already shipped the
    `Activity` model + write path (hooked into every mutating route); KAN-18 was *only* the read
    endpoint + panel. Briefing the agent explicitly "the write path exists, do NOT re-add it" kept it
    from scope-creeping into a migration it didn't need. Lesson: **when a feed/audit feature is
    half-built, name the exact seam in the brief.**
  - **`kan login` isn't in a released binary — had to cut v0.2.3.** The published v0.2.2 CLI predated
    KAN-199 (config-file/login), so "install the published CLI and run `kan login`" was impossible
    until a new tag was pushed. `release-cli.yml` + `publish-mcp-image.yml` are `v*`-tag-gated;
    tagging `v0.2.3` produced the login-capable binary. **Reminder (already logged): code-complete ≠
    downloadable — a feature only ships to users on a version tag.**
  - **The Intel-mac release leg silently ships nothing.** `release-cli.yml`'s `macos-13`
    (`kan-macos-x86_64`) leg sits `queued` waiting for a scarce runner, so *every* release
    (v0.2.0–v0.2.3) attaches Linux + macOS-arm64 but no Intel-mac binary, and the overall run shows
    "queued" indefinitely (reads like a hung release). Because each matrix leg attaches its own asset
    independently, the other two publish fine. Filed as **KAN-225** (drop the leg → arm64 + Rosetta,
    or bound it with a timeout). Note: a Linux container can't fix this — PyInstaller can't
    cross-compile a macOS binary.
  - **Prod-verify caught nothing that CI didn't, but the SPA fallback nearly fooled the probe.** In
    prod an unmatched `/api/v1/...` GET returns **200 `text/html`** (the SPA catch-all serving
    `index.html`), *not* 404. A status-code-only check of a not-yet-deployed endpoint therefore looks
    like success. **Always assert `content-type: application/json` (or grep the body) when
    prod-verifying an API endpoint** — I confirmed KAN-18 by content-type, not status. The full
    KAN-20 lifecycle prod-verify (create→soft-delete→trash→restore→re-delete→purge→404, plus a
    `restored` event in the live feed) all passed.
  - **Shared local Postgres is a cross-worktree hazard.** Two concurrent worktree agents share the
    one `docker compose` Postgres on `:5432`. The KAN-19 agent's `alembic upgrade head` stamped its
    new revision onto that shared DB; the KAN-18 agent (branched off older `main`) then failed to
    boot its backend against a DB ahead of its own migration chain. Both agents independently
    worked around it by running against a throwaway `postgres:17` on an alt port with a
    `DATABASE_URL` override. Integration tests were unaffected (isolated testcontainers). **Brief
    parallel agents to use a throwaway DB for any manual run/e2e, never the shared `:5432`.**
  - **An agent committed a machine-local absolute path into an e2e test.** KAN-18's `activity.spec.ts`
    hardcoded its worktree path in `page.screenshot({ path: "/home/jian/.../worktrees/agent-…/…png" })`,
    which passed locally and failed CI with `ENOENT` (`/home/runner/...`). Fix: `testInfo.outputPath(…)`
    — Playwright's per-test output dir, CI-safe on any runner. **Brief UI agents up front: screenshots
    for PM review go to the worktree root as loose files; anything a committed test writes must use
    `testInfo.outputPath`, never an absolute path.** (KAN-20's agent, briefed with this, got it right.)
  - **`restored` needed a CHECK-vocabulary migration.** The `activity.action` CHECK only allowed
    `created/updated/deleted/moved`; KAN-20 added `restored` via a drop+recreate-CHECK migration
    (`0013`) rather than mislabel a restore as `updated`. Clean linear chain
    `0012 → 1f2fe64fcab2 → 0013`; purge is intentionally *not* audited (a second `deleted` row would
    confuse the feed — a `purged` action is a possible follow-up).
- **M5 — all 7 must-have slices shipped in 4 waves of 1–3 parallel agents (V11–V17): card fields,
  dispatch, needs-human, saved views, search, dashboard, reporting.** The milestone reframed the board
  as a human↔multi-agent coordination surface (agents operate via API/MCP/CLI; humans observe via a
  read-first dashboard). Each slice: implement in a worktree → PR → adversarial review → CI green →
  land → Fly deploy → prod-verify → `done`. Reusable learnings from running it as PM:
  - **The parallelism reality for this repo: cores are disjoint, adapters are not.** Two full-stack
    slices can always split their *substantive* work (e.g. `boards.py`+`ordering.py` vs
    `cards.py`+`models.py`), but they *always* collide on the thin shared adapters
    (`pandan-cli/cli.py`, `mcp/server.py`, `pandan-client/client.py`), `schemas.py`, and the frontend
    shell (`App.svelte`, `api.ts`). So "provably disjoint" is never literally true here — the working
    rule is: **land the first PR, then the second does a mechanical keep-both rebase** of the adapter
    files (V13-after-V12, V14-after-V17). Brief both agents to APPEND/localize adapter additions (new
    verb at the end of the list, don't reflow) so the rebase is trivial. Occasionally git auto-merges
    them with no rebase at all (V16 after V15).
  - **Migration pairing rule: at most ONE migration per parallel pair.** Two slices branched off the
    same `main` each adding a migration = two alembic heads when the second lands. Every M5 wave was
    paired so only one carried a migration (V12∅‖V13mig, V14mig‖V17∅, V15mig‖V16∅); the migration
    slice **lands alone**, the no-migration sibling lands first if ready. Zero heads conflicts all
    milestone.
  - **The "Bash isn't sandboxed to the worktree" hazard bites even with the warning in the brief.**
    V14's agent's very first `git switch -c` ran (via a stray `cd`) in the PARENT checkout, moving the
    primary checkout onto an empty branch. No damage (the primary was already back on `main` from a
    prior `git switch`, and the real work was safe on the worktree branch) — but recovery meant
    deleting a stray local branch. The agent also had to push via refspec (`HEAD:feat/…`) since its
    local branch kept the `worktree-agent-…` name. **Reinforce "run ALL git in THIS worktree; never
    cd into the parent" — and consider a hard guard, because agents still slip on the first command.**
  - **Deploy poll gotcha: every merge fires TWO `deploy.yml` `workflow_run` events** — a real
    `success` and a deduped `skipped` no-op. Polling `head -1` can catch the `skipped` one and look
    like a skipped deploy (it happened on V15). Poll for `conclusion==success`, or — better —
    **prod-verify the feature directly** (a working `q=` search proved V15 deployed regardless of the
    misleading `skipped`).
  - **Validate chart palettes for CVD.** V16's dashboard agent ran the dataviz palette validator and
    found the app's teal+green two-series pair fails the normal-vision ΔE floor; it switched to
    teal+violet and added value labels + a legend as a secondary (non-color) encoding.
  - **Prod-verify concurrency + derived metrics with real round-trips.** Dispatch: seed two cards,
    confirm priority order + that a second dispatch gets the next one (the `FOR UPDATE SKIP LOCKED`
    unit of the fleet-safety test). Metrics: dispatch→done a throwaway card and confirm it shows in
    per-assignee throughput (validates the activity-summary parsing in prod). Fields: assert 422 on
    both a bad-enum and a cross-board label.
  - **Known M5 tech debt:** the metrics layer derives transitions by **parsing activity summary
    text** (`"moved … to in_progress"`, `"dispatched …"`) — correct today but fragile; a structured
    from/to on the activity row would harden it. And MCP/CLI parity for the activity `actor`/`action`
    filters was left undone (endpoint is the contract). Tail slices **V18 (scoped tokens, Later)** and
    **V19 (batch/templates, Nice-to-have)** + **KAN-239 (audit purge)** remain in the backlog.
- **M5 tail — Wave 1: KAN-239 (audit purge, migration) ‖ KAN-261 (activity parity, no migration):
  both merged + `done`.** The tail is 5 cards, **4 of which carry a migration** (only KAN-261
  doesn't), so parallelism is migration-bound: the plan is Wave 1 parallel then KAN-260/251/252 solo,
  each starting only *after* the prior migration card merges (so it branches off a main that already
  has the prior migration → linear chain, never sibling heads). Wave 1 was the one clean disjoint
  pair: KAN-261 is adapter-only (`pandan-client`/`mcp`/`cli`, no backend, no deploy) and KAN-239 is
  backend-only (routers + migration), so zero shared files and only one migration in flight.
  - **The disjoint axis here is adapter-package vs backend, not just backend-vs-frontend.** KAN-261
    touched only the three thin client packages; KAN-239 only `backend/`. They never met — no rebase,
    both merged straight. When one card is pure API-client parity and the other is pure server-side,
    that's as clean a parallel pair as backend-vs-frontend.
  - **"Surface the existing filter" was actually "add the whole read."** KAN-261's card implied the
    activity `actor`/`action` filters just needed exposing on MCP/CLI. In fact the activity feed was
    **never surfaced in any adapter** — only the server-derived `metrics` read touched it. So parity
    (ADR 0005) meant a net-new `list_activity` client method + `activity` MCP tool + `kan activity`
    command (with `limit`/`cursor`/`actor`/`action`), not a two-param append. The agent flagged the
    premise gap rather than silently doing the minimum. Lesson: a "surface the filter" card can hide a
    "there's no read to surface" — brief the agent to grep for the existing plumbing first and report
    if it's absent.
  - **A new MCP *tool* isn't callable in the building session, but its API *is*.** KAN-261 adds an
    `activity` MCP tool — not loadable until the user restarts + re-`uv sync`s `mcp/`. No prod-verify
    needed though: adapters aren't deployed (they're client tools; CI covers them), and the underlying
    `GET /boards/{id}/activity?actor=&action=` endpoint already worked (I exercised it by `curl`).
  - **Migration card, landed alone, prod-verified by round-trip.** KAN-239's `0018` widens
    `ck_activity_action` to admit `purged` (mirrors 0013/0015 drop+recreate, chained off
    `0017_card_search_vector`, single head). `record_activity(action="purged")` fires **before**
    `db.delete` in both purge handlers — safe because `Activity.entity_id` is a plain int (not an FK),
    so the audit row outlives the entity it names (same guarantee the soft-delete `deleted` row uses).
    Prod-verify: create→soft-delete(204)→purge(204)→`GET /boards/5/activity?action=purged` showed the
    row with `content-type: application/json` (not the SPA-fallback 200 HTML) and correct summary.
  - **Pre-existing frontend gap surfaced (candidate follow-up card):** `Activity.svelte`'s icon/badge
    map is behind the backend action vocabulary — it already omits `attention`/`resolved`, and
    `api.ts`'s `ActivityAction` type doesn't include them; `purged` now joins that gap. KAN-239 kept
    itself a clean backend+migration slice and did *not* patch one action into a map missing three
    (would be an incomplete fix). A small "Activity panel: complete the action icon/badge map
    (attention/resolved/purged)" frontend card is worth filing.
  - **`pandan-cli/README.md` command table is stale** — documents only core CRUD, missing the M5
    verbs `next`/`needs-human`/`resolve`/`metrics`/`view` (KAN-261 added just its own `activity` row,
    in scope). Worth a docs card to backfill.
- **M5 tail — Wave 2: KAN-260 (structured activity transitions, migration) solo: merged + `done`.**
  Retired the V17 tech debt where `metrics.py` recovered a card's column transition by **regexing the
  human activity summary** (`"moved … from X to Y"`). Migration `0019` adds nullable `from_column` /
  `to_column` varchars to `activity`; `record_activity` stamps them at write time; a new
  `move_target(from_column, to_column, summary)` reads the structured fields and keeps the old
  `parse_move_target(summary)` as a **NULL-only fallback** (used solely when `to_column IS NULL`, i.e.
  pre-migration rows), so no historical metric regresses.
  - **The card's file pointer was wrong; the agent verified against the code.** The ticket said the
    dispatch handler lives in `routers/cards.py`; it's actually `dispatch_card` in `routers/boards.py`.
    The agent grepped for the real `action="moved"`/`"dispatched"` producers (exactly two: `move_card`
    in cards.py, `dispatch_card` in boards.py) and edited the true locations. Reinforces the standing
    "trust the code over the docs" brief — a stale file hint in a card is a trap, not a spec.
  - **Hardening old data safely = keep the old parser as a NULL-gated fallback, don't delete it.** The
    clean instinct is to rip out the regex, but historical `activity` rows have NULL structured fields.
    Gating the fallback on `to_column IS NULL` means new moves use the robust path while legacy metrics
    are byte-identical to before. A unit test pins the legacy-summary fallback so a future cleanup
    can't silently drop it. Summary wording was left EXACTLY unchanged (tests/humans depend on it).
  - **Prod-verify a derived-metrics migration by driving the real transition, not just reading a
    field.** The structured columns aren't exposed on the activity API response (internal to metrics),
    so I verified end-to-end: create a throwaway card → `move` todo→in_progress→done in prod →
    `GET /boards/5/metrics` recomputed cleanly (throughput/cycle-time/aging, `application/json`),
    proving the new write+read path works against the deployed DB. Then soft-delete+purge to clean up.
  - **PM slip caught by the metrics I was verifying:** the `aging_wip` list showed card KAN-261 still
    `in_progress` — I'd merged its PR and marked the task done but never ran `kan move 261 done` on the
    board. The dashboard/metrics surface *is* the safety net for board-vs-reality drift (exactly R2.1's
    point). Move the board card to `done` in the same step as the merge, not "later".
- **M5 tail — Wave 3: KAN-251 (V18 scoped tokens, migration) solo: merged + `done`.** The last
  must-have-adjacent slice. `personal_access_token.scope` (`read`/`write`, varchar+CHECK,
  `server_default 'write'` so every existing PAT stays a writer); a `read` (observer) PAT is denied
  all writes with 403.
  - **The clean enforcement point was HTTP-method in the one principal resolver, not per-route
    `Access.WRITE` hooks.** `get_principal` is the single dependency every `/api/v1` route flows
    through (board routes via `authorize_board`, per-user routes like `/tokens` directly). The agent
    stashed the PAT's scope on the resolved principal as a transient `_pat_scope` and, in
    `get_principal`, denied a `read` PAT any non-safe method (`POST/PATCH/PUT/DELETE`) with 403. In
    this API every write is an unsafe method and every read is `GET`, so the method test *is* the
    `Access.WRITE`+ test — and it covers board writes AND per-user writes (token creation) uniformly,
    with zero scattered checks. Cookie humans + `write`/legacy PATs have no `_pat_scope` → unaffected.
    The one caveat to keep in mind: if a future `/api/v1` `POST` is ever semantically a *read* (none
    today — the query API is `GET`-based), it would be wrongly blocked for observers; revisit then.
  - **Card said "kan/MCP surface scope at creation" — but neither CLI nor MCP can create a token.**
    They only *consume* a PAT (`KANBAN_TOKEN`). The agent grepped, confirmed token creation is API/UI
    only, surfaced scope where creation actually happens (the `POST /tokens` schema + the Tokens UI),
    did NOT invent a token-create verb, and corrected the aspirational wording in SLICES.md in the same
    PR (docs-in-lockstep). Good scope judgment on a card whose parity clause didn't match reality.
  - **Prod-verify the whole matrix, not just the happy 403.** Minted a real `read` PAT (via the write
    PAT), then confirmed: reads (boards/cards/metrics) 200; writes (create card, `dispatch`, and
    `POST /tokens`) all 403; the write PAT's read 200 AND a no-op board PATCH 200 (proves the gate
    didn't regress normal writers); then deleted the observer PAT. Exercising the write-PAT path too is
    the part that proves you didn't just break everything — the real risk of an authz change.
- **M5 tail — Wave 4: KAN-252 (V19 batch + templates, migration) solo: merged + `done`. M5 backlog
  fully cleared.** The nice-to-have tail. Added atomic `PATCH /cards/batch` + a `card_template` store
  (`0021`) with an apply endpoint that seeds a plan in one call.
  - **The card's premise about existing batch-create was wrong, and the agent's correction was the
    right one.** The card assumed a backend batch-create endpoint existed (from KAN-40) to build on.
    It doesn't — KAN-40's "batch create" is a **client-side fail-fast loop** in `KanbanClient.create_cards`
    (loops `POST /cards`), explicitly non-atomic. The agent did not add a redundant public batch-create
    endpoint; instead it got atomic multi-card creation for free by extracting `_create_card_row`
    (flush-not-commit) and reusing it inside template-apply's single transaction. Lesson: "build on the
    existing X" cards need the agent to first confirm X is what the card thinks it is.
  - **Extracting a shared flush-not-commit helper is the clean way to make a single-item op atomic in
    bulk.** `_create_card_row` / `_apply_card_update` each validate + record activity + `flush()` but
    do NOT commit; the single `create_card`/`update_card` endpoints keep their own `commit()`+`refresh()`
    (behaviour-preserving — verified the commit lines survive as diff context, and card-CRUD
    integration suites stayed green), while batch/apply call the helper N times and commit ONCE. The
    caller owning the transaction is what makes all-or-nothing free.
  - **Route ordering: `/cards/batch` must be declared before `/cards/{card_id}`** or `batch` binds as
    a card id — the same trick `/cards/trash` already uses. Easy to get wrong; worth checking on any
    new fixed sub-path under an id-parameterised router.
  - **Scope held on a nice-to-have.** Board-level templates (cloning columns/settings) were deferred
    as scope creep — card templates only. CLI takes the per-card JSON as a string/`-`-stdin rather than
    exploding arbitrary fields into flags. Both flagged, not silently expanded.
  - **Prod-verify the atomicity claim, not just the happy path.** Beyond create→apply→batch-update
    (all 200), I sent a batch with one bad id and confirmed 404 + the good card in that batch was
    **unchanged** — the all-or-nothing guarantee is the actual contract, so it's the thing to verify.
- **M5 tail retrospective (all 5 cleared: KAN-239, KAN-261, KAN-260, KAN-251, KAN-252).** Ran as
  Wave-1 parallel (KAN-261 adapter ‖ KAN-239 backend, one migration) then three solo migration slices,
  each starting only after the prior MERGED so its migration chained linearly (`0018→0019→0020→0021`,
  zero head conflicts — the proven M5 rule held). **The recurring theme across four of five cards: the
  card description was factually off** (KAN-261 "surface the filter" → no read existed; KAN-260 wrong
  file for dispatch; KAN-251 "kan/MCP surface scope" → no token-create verb exists; KAN-252 "existing
  batch-create endpoint" → it's a client loop). Every agent caught it by grepping the code first and
  corrected the docs in-PR. The standing "trust the code over the card" brief is doing real work —
  keep briefing agents to verify the premise before implementing, and to fix the stale doc in the same
  slice. Two frontend/docs follow-ups filed (Activity panel action-badge map; pandan-cli README verb
  table).
- **Post-M5 cleanup batch — KAN-267/269/270 (‖) + KAN-268 & a discovered bug KAN-277 (‖): all merged
  + `done`; turned 2 GitHub issues into cards first.** A housekeeping round: pruned stale branches (59
  merged remote + 7 local; kept only `main` + the 3 open-PR branches — merged-vs-unmerged cleanly
  separated in-use from stale), then converted the two open issues (#76 story-points, #77 CLI deps)
  into cards KAN-269/KAN-270 (linked to EPIC-6, each with a GitHub-issue work-link), and cleared all
  four backlog cards.
  - **`gh issue view` / `gh pr edit` are broken by GitHub's classic-Projects GraphQL deprecation.**
    Both error with `Projects (classic) is being deprecated … (repository.issue.projectCards)`. Use
    the REST API instead: `gh api repos/OWNER/REPO/issues/N` to read an issue,
    `gh api -X PATCH …/pulls/N -F body=@file` to edit a PR body. (The dogfooding log already flagged
    the `gh pr edit` variant for KAN-14; it bites `gh issue view` too.)
  - **The disjoint axis was frontend / backend-less-CLI: 3 of 4 cards lived in `pandan-cli/`.** Only
    KAN-267 (frontend) was collision-free. KAN-269 (points) & KAN-270 (dep verbs) both edit `cli.py`;
    KAN-268 (README) & KAN-270 both edit `README.md`. Ran 267‖269‖270 in Wave 1, landed 269 first, and
    269/270 **git-auto-merged with no manual rebase** because each kept its edits localized (269 in the
    render helpers ~L130, 270 appended subparsers/handlers ~L800+ and appended README rows). Briefing
    "append, don't reflow; another slice is editing region X" is what makes concurrent same-file work
    auto-merge. KAN-268 (README) ran in Wave 2 after 270 so its backfill didn't fight 270's new rows.
  - **A card's stated root-cause can be wrong — verify before implementing (again).** KAN-269's issue
    (#76) claimed the API returns an always-null `points` field. It doesn't — the API has ONLY
    `story_points`; the reporter's `jq '{points}'` returned null for a MISSING KEY (jq fills absent
    keys with null). The real gap was CLI-side: `_card_line` never displayed points and `--points`
    didn't obviously map to `story_points`. Fix was CLI-only (`pts=N`), NOT an API change (adding a
    `points` alias would've been the wrong direction). Brief agents with the corrected diagnosis when
    you already know the issue misdiagnosed it — it stops them re-deriving or over-reaching.
  - **Dogfooding found what unit tests structurally couldn't (KAN-277).** KAN-270's LIVE prod check
    surfaced that `kan get`/`create`/`update`/`move` print `(no labels)` on real cards: `_humanize()`
    checked `"labels" in result` (list_labels) BEFORE the single-card branch, and every real
    `CardRead` carries `labels: []`. It also silently **masked KAN-269's just-shipped `pts=`** for
    those commands (`kan list` was fine — different branch). The unit tests passed because the test
    fixtures OMITTED `labels` — the exact shape difference that hid the bug. Lesson: **CLI/adapter
    tests must use fixtures that match the REAL API response shape** (all keys the server actually
    returns), and a live smoke against prod catches dispatch bugs a hand-built fixture never will. Fix
    (KAN-277): guard the branch with `"labels" in result and "ticket_number" not in result`, and the
    regression test now bakes `labels: []` into the single-card fixtures so the omission can't recur.
  - **Fold a same-file follow-up into the open PR instead of a new card when it's the identical bug on
    a sister component.** KAN-267's agent flagged that `Dashboard.svelte` had the same missing-`purged`
    icon gap as `Activity.svelte`. Rather than file a card, I resumed the SAME agent to add the
    one-line parity fix on the SAME PR (#148) — full fix, one review, no extra tracking. (Contrast:
    KAN-277 got its OWN card because it's a distinct dispatch bug in different code, discovered after
    269 had already merged.)
  - **Land policy note: none of these four deployed except KAN-267 (frontend).** The `kan` CLI + docs
    changes ship to users only via a `v*` release tag (distribution is tag-gated), so "merged + CI
    green + live-checked from source" = `done`; a release tag is a separate, deliberate step. Prod-
    verified KAN-267 by grepping the deployed bundle for `purged`/`data-action`; verified the CLI
    fixes by running `kan` from the merged source against prod (`kan get 260` → card line with `pts=3`,
    not `(no labels)`).
- **Release v0.3.0 — cut the first tag since v0.2.3, shipping the whole M5 CLI surface + `kan
  --version`.** `v0.2.3` turned out to point at c546358 (2026-07-14, PRE-M5), so every M5 CLI verb
  (`dispatch`/`next`, `needs-human`/`resolve`, `metrics`, `activity`, `view`, `dep`/`link`/`comment`,
  `batch-update`, `template`, labels, card-field flags, search) had accumulated undownloadable behind
  the tag (cli.py +775 lines since v0.2.3). Bumped **minor → v0.3.0** (not another patch) to signal
  the dozen-plus new commands.
  - **The release is tag-driven; the in-code version strings were dead and stale.** `release-cli.yml`
    fires on `push: tags: v*` and builds the binary from the code AT THE TAG — it never reads the
    version from `pyproject`/`__init__`, which is why v0.2.1→v0.2.3 were all tagged while
    `pyproject` sat at `0.2.0` and `__init__.__version__` at `0.1.0`. There was **no `kan --version`**,
    so the only "version" a user could see was the GitHub release/tag name.
  - **Added `kan --version`/`-v` mid-cut, so the binary can self-report.** User asked for it right
    after the first tag push. Since the tag was seconds old and nothing was published yet, the clean
    move was: **cancel the in-flight `release-cli.yml` run (`gh run cancel`), delete the unreleased tag
    (`git push origin :refs/tags/v0.3.0` + `git tag -d`), land the `--version` PR, then re-tag on the
    new HEAD.** Wired via argparse `action="version"` on the ROOT parser (`version=f"kan {__version__}"`,
    reading a hardcoded `__version__`) — pure argparse, no `importlib.metadata`, because the
    PyInstaller onefile has no reliable package metadata at runtime. Synced `__init__.__version__` +
    `pyproject` to `0.3.0` so the frozen binary self-reports correctly. (Standing debt to consider: the
    release should assert `__version__` matches the tag, or derive one from the other, so they can't
    drift again — today it's a manual bump.)
  - **`git push <tag>` is the reliable trigger** (not `gh release create`, whose API-created tag may
    not fire `on: push: tags`). The workflow's `softprops/action-gh-release@v3` then created the
    release and attached both assets. Shipped legs are `kan-linux-x86_64` (glibc-2.28 container, runs
    on Ubuntu 20.04+/Debian 11+/RHEL 8+, KAN-81) and `kan-macos-arm64`; the Intel-mac leg stays
    dropped (KAN-225, Rosetta/from-source/MCP-image for those users).
  - **Verified the downloaded binary end-to-end, not just that it built.** `gh release download
    v0.3.0 --pattern kan-linux-x86_64` → `kan --version` → `kan 0.3.0`; then functional proof against
    prod that the FIXES are actually in the artifact: `kan get 260` → `KAN-260  done  …  pts=3` (not
    `(no labels)`), `kan list` shows `pts=` per row, `kan dep/activity/comment --help` all present.
    Building green ≠ shipped-and-working — download the real asset and run it.
- **M6 planning + Wave 1a (hardening + CLI bugs): 3 agents ‖, all merged + `done`.** After a full
  `kan` CLI exercise surfaced 4 real bugs (filed KAN-285…288), shaped M6 "Harden & Sharpen" (5 epics
  EPIC-46…50, cards KAN-290…304; docs PR #156) and ran the first parallel wave. Land policy:
  auto-merge on green, serialized landing.
  - **The disjoint axis was subsystem, and `main.py` is the hardening chokepoint.** Wave 1a =
    V27 rate-limiting (KAN-291: `main.py`+routers+new `ratelimit.py`) ‖ V30 DB resilience (KAN-294:
    `db.py` only) ‖ CLI batch (KAN-285…288: `pandan-cli/` only) — three provably non-overlapping file
    sets. Every M6 *middleware* card touches `backend/app/main.py`, so those must serialize; V27 owned
    it this wave and V28/V29 were deferred to Wave 1b to rebase on V27's merged version.
  - **Two Deploy `workflow_run` events fire per PR merge — poll the right one.** A merge triggers the
    Deploy workflow twice: once from the *PR-branch* CI completion (gated out by the workflow's
    `head_branch == 'main'` check → shows `completed/skipped`) and once from the *main-push* CI (the
    real deploy). A naïve `gh run list … | head -1` grabs the skipped twin and falsely reports
    "deployed/skipped". Select the run whose triggering CI was on `main` (or simply: wait for a deploy
    run with `conclusion == success`, ignore `skipped`). Cost me one false "skip" read on V30.
  - **`isolation: worktree` sandboxes Edit/Write but NOT Bash — all three agents hit it.** Each
    agent's first `Edit` targeted the *shared*-checkout path (from the CLAUDE.md context) and was
    correctly rejected (Edit is confined to the worktree); but two agents also ran `uv lock`/`uv sync`
    via `cd …/backend` against the shared checkout before catching themselves. No harm (verified the
    primary checkout `git status` clean after each returned), but the brief's "run all git/uv against
    your worktree only" line is load-bearing — keep it, and re-verify the primary checkout is clean on
    every agent return.
  - **Adding a global middleware must not break the existing suite — ship it off by default.** V27's
    limiter is gated behind `RATE_LIMIT_ENABLED` (unset = no-op), because the module-singleton app
    shares one in-memory `limits` store across the whole pytest session, so a default-on limiter with
    cumulative hits would trip existing tests. Off-by-default + a targeted test that injects a low
    limit is the clean pattern; it also means the prod deploy is a no-op until the Fly secret is set.
    (V30 followed the same "configurable, safe defaults" shape for `DB_*`.)
  - **Two PRs editing CLAUDE.md's Configuration section did NOT conflict** — V30 added its `DB_*`
    bullet after the `DATABASE_URL` paragraph, V27 its rate-limit bullet near the auth/E2E env vars, so
    the edits were far enough apart that GitHub reported `MERGEABLE`. Adjacent-line edits still would
    (the KAN-9/#10 lesson); non-adjacent same-section edits are fine.
  - **Verify by the change's actual observable.** V30/V27 (DB timeouts / off-by-default limiter) can't
    be seen externally, so prod-verify = readiness+liveness `ok` + an authenticated read served (proves
    the new engine connect-args / installed middleware didn't regress serving). The CLI batch is
    tag-gated (no deploy), so it was verified by running the CLI **from merged source** against prod
    (`kan get KAN-250` by ticket, `--sort -priority` space form, human `template list`, `label
    --color`) — not from the on-PATH v0.3.0 binary, which predates the fixes.
  - **`kan` friction the CLI exercise surfaced (now fixed in KAN-285…288, PR #159):** every id-taking
    command rejected the `KAN-`/`EPIC-` ticket it displays and demanded the numeric DB id; `--sort
    -x` failed unless written `--sort=-x` (argparse eats the leading dash); `template list` dumped raw
    JSON in human mode; `label create --color` was undocumented (color was positional). Also confirmed
    the CLI has **no** purge/restore/trash, no `board delete`, and no comment delete — so smoke-test
    cards soft-delete but their ticket numbers (KAN-278…284, 289) are permanently burned; called out,
    not a bug.
- **M6 Wave 1b + Wave 2 (hardening finish + Projects + Cycles): the migration-serialized spine, and CI
  earning its keep.** Wave 1b landed the remaining hardening (V26 edge/fly.toml + a Cloudflare human
  runbook; V28 payload caps + V29 report-only-CSP headers bundled since both touch `main.py`). Wave 2
  shipped Projects (V31 fields + V32 rollup) and Cycles (V33 model + V34 burndown), all auto-merged on
  green + prod-verified. **M6 must-haves complete**; EPIC-49/50 (palette, notifications) left as the
  Nice-to-have tail by choice.
  - **Two migrations can't be implemented in parallel — the alembic head serialises them.** V33's
    `alembic revision --autogenerate` has to run off V31's *merged* head (0022) or it branches a second
    head and alembic gets two heads. So the migration cards go strictly one-at-a-time (V31 merged →
    then V33 starts), and land ALONE with prod-verify. The **derived** follow-ups (V32 rollup, V34
    burndown — no migration) are what you parallelise: V32 ‖ V33, then V34 solo. Migration-alone is a
    *landing* rule; the head-dependency is an even harder *implementation* rule.
  - **Parallel edits to one shared file (`schemas.py`) stayed conflict-free by region discipline.**
    V32 (EpicRead area) ‖ V33 (card `cycle_id` + a new Cycle section appended at EOF) — briefing each
    "stay in your region, don't reflow the rest" made GitHub report MERGEABLE with zero manual rebase,
    even landing them a migration apart. Same lesson as the CLI batch: localized appends auto-merge.
  - **CI caught a real regression a narrow local test missed (V32).** The agent ran only its own new
    `epic-rollup.spec.ts` locally, not the full e2e suite, and shipped a green-looking PR that broke an
    *existing* ui-polish test. Root cause was a genuine bug: V32 made the Epics grouping read the
    server-derived `epic.progress`, but the card-mutation helpers only `refetch()`-ed cards, never
    `refetchEpics()` — so `epicStore` went stale after a move and the "Completed" group never rendered.
    Fix: `addCard/editCard/removeCard/moveCard` now `refetch()` **and** `refetchEpics()` (server-
    authoritative + fresh, mirroring the `refetchLabels` pattern). **Standing rule: a change to a shared
    UI component must run the FULL `npm run e2e`, not just its new spec.** The green gate did its job.
  - **`alembic --autogenerate` has phantom index churn in this repo — every migration must review +
    strip it.** Both V31 and V33 saw autogen emit spurious drop/create_index for existing indexes
    (`ix_card_search_vector`, `ix_card_comment_card_id`, the two `card_dependency` FK indexes,
    `ix_card_link_card_id`) — pre-existing model-vs-DB drift, unrelated to the slice. Both hand-stripped
    to only their real ops and re-ran autogen to confirm a clean diff. Filed a tech-debt card to
    reconcile the model `Index()` declarations so future autogen is clean.
  - **Worktree e2e can silently bind to the WRONG backend on fixed ports.** V34's full-suite e2e failed
    all 31 at login because ports 8000/5173 were held by an *unrelated* local project and Playwright's
    `reuseExistingServer` connected to it (test-login 404). The agent did NOT kill the user's app —
    it retargeted the e2e stack to free ports, ran green, then reverted the config (verified the PR had
    no stray `vite.config`/`playwright.config`). Worth a per-worktree port offset if this recurs.
  - **Dogfooded the feature mid-build:** used V32's just-shipped epic progress rollup (`GET /epics/{id}`
    → `progress {done,total,percent}`) to report M6 epic completion back to the user. The prod-verify of
    each migration/derived slice was an API round-trip against the live app (set→read→clear for epic
    fields; create→assign→filter→delete for cycles; endpoint-shape for metrics), not just "CI green".

- **EPIC-49 (M6 "UI Enhancement & Design System") — Wave 1: U1 (KAN-316) dark-mode form controls.**
  The visible white-in-dark-mode bug across all native controls (filter-row selects, card-modal
  form, date picker, checkbox). Root cause was a *missing* declaration, not a wrong one: `color-scheme`
  was set nowhere, so every native control fell back to the UA light default regardless of theme.
  One-agent CSS-only slice, merged as PR #168 → `c13e494`, deployed + prod-verified. Learnings:
  - **The fix is `color-scheme` on `:root`, in all THREE theme contexts.** This repo themes via
    `:root`/`[data-theme="light"]` (light), `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`
    (OS dark), and `:root[data-theme="dark"]` (forced dark). A `color-scheme` fix has to land in each
    of the three, not just one — easy to under-fix by only touching the media query.
  - **Use `background-color`, not the `background` shorthand, on `.rail-select`.** The custom select
    carries its dropdown-caret as a `background-image`; the shorthand wipes it. The agent caught this
    itself and used `background-color` to theme the control while preserving the caret. Worth a
    reviewer's eye whenever an `appearance:none` control gets a themed background.
  - **Headless Chromium lies about open native `<select>` popups.** An opened option menu screenshots
    as *light* even when `color-scheme: dark` is correctly applied — the popup chrome ignores
    `color-scheme` in headless. The reliable dark-mode signals are the *closed* control's rendering and
    the computed `color-scheme`/`background-color` via `page.evaluate`, not an open-popup screenshot.
    This exact artifact could produce a false "still broken" report on the very bug being fixed.
  - **Prod-verify for a CSS card = grep the deployed hashed `/assets/index-*.css`** (not the JS bundle)
    for the new declarations (`color-scheme:dark`/`light`, `.rail-select{…background-color:var(--card-bg)`).
  - **e2e "screenshot" specs dirty the tree.** The activity/dashboard/trash specs overwrite tracked
    baseline PNGs in the repo root on every run; the agent reverted them to keep the PR scoped to
    `app.css`. Standing friction — those baseline artifacts arguably shouldn't be git-tracked.

- **EPIC-49 Wave 2: U2 (KAN-317) design system — Bits UI primitives.** The foundation the rest of the
  epic adopts. Ran **design-first, two phases, one agent** (PR #170 → `d17bed2`, deployed + verified):
  Phase 1 the agent built a self-contained `mockup.html` (both themes side by side, real extracted
  tokens); the PM screenshotted it, confirmed it matched the locked decisions (Bits UI headless,
  Zinc/Teal tokens, NO Tailwind, Command primitive for V35), then resumed the SAME agent via
  SendMessage for Phase 2. Learnings:
  - **Design-first phases in one agent is the right shape for a big UI refactor.** The mockup locked
    the visual spec (radius unified to 7px, teal focus ring, custom caret) and surfaced 4 real design
    questions (native date input vs Bits DatePicker; radius unification; labels multi-select scope;
    Command-wrapper-only vs ⌘K wiring) *before* any code was written — cheap to decide, expensive to
    rework. Resuming the same agent kept full mockup context into implementation.
  - **Full e2e was load-bearing (again).** The Bits `Select` trigger renders a `<button>`; the agent
    gave the board switcher `aria-label="Board"`, which collided with the **"Board" view-nav tab**
    under `getByRole("button", {name:"Board"})` and broke a *shared* helper (`createStoryUnder`) used
    across epic specs. Only the FULL suite caught it (fixed by relabelling to "Switch board"). A
    subset run would have shipped a broken `main`. This is the second consecutive shared-UI card where
    the full-suite requirement paid for itself.
  - **Bits UI e2e pattern:** a Bits `Select` is NOT a native `<select>`, so Playwright `selectOption`
    and `toHaveValue`/`<option>` assertions don't work. The new `pickSelect()` helper (click combobox →
    click `role=option`) + `toContainText` on the trigger is the pattern future specs (incl. V35) reuse.
  - **`bits-ui@^2.18.1`** is the current Svelte-5-native line; its `@internationalized/date` peer is
    only for Calendar/DatePicker (unused — we kept native `<input type=date>`), so it's not installed
    and npm's peer warning is harmless. Commit BOTH `package.json` + `package-lock.json`.
  - **Portalled popups justify keeping primitive CSS global.** Bits portals its Select/menu content to
    `<body>`, so the `.ui-*` styles were appended as a token-only block in `app.css` (not per-component
    scoped `<style>`), matching how `.rail-select`/`.board-switcher` already lived.
  - **Scope discipline on a "standardize everything" card:** the agent replaced the genuinely ad-hoc
    native `<select>`s but left CardModal's title/description/assignee inputs (already deliberately
    styled in the KAN-65/66 modal redesign) native — forcing the wrapper there risked regressing a
    tuned layout for zero visual change. Reasonable; U3 reworks the description into markdown anyway.

- **EPIC-49 Wave 3: U3 ‖ U4 ‖ U5 — three slices in parallel, serialized landing.** Ran U3 (KAN-318
  card-modal markdown, PR #174), U4 (KAN-319 top-nav reorg, PR #175), U5 (KAN-320 filter/sort clarity,
  PR #173) concurrently, all off post-U2 `main`. U4 was **design-first (mockup → PM review → resume
  same agent)** like U2; U3/U5 went straight to implementation. All merged + deployed + prod-verified.
  Learnings:
  - **Disjointness held because the target files were genuinely distinct**, verified by grepping actual
    imports before launch — U3 = `CardModal.svelte` + `package.json` (its own new deps) + the `.desc-*`
    section of `app.css`; U5 = `ViewSwitcher.svelte`'s **own scoped `<style>`** only; U4 = `App.svelte`
    + new `SideNav.svelte` + `ui/DropdownMenu.svelte` + the **top-bar section** of `app.css`. `app.css`
    is one 1700-line global sheet touched by two slices (U3, U4), but in far-apart sections
    (`.desc-*` vs `.topbar`/`.board-tab`), so git auto-merged with zero conflicts. The trick was
    briefing each agent on exactly which files/sections it owned and which to stay out of.
  - **Launch UI-heavy design-first slices as mockup-only while the others implement.** U4's Phase 1
    (mockup, no real code) ran concurrently with U3/U5's implementation — three agents, fully disjoint,
    because a mockup-only agent writes nothing that can collide. Then resumed U4 for Phase 2 once its
    mockup was approved. Kept the pipeline full without risking a merge conflict.
  - **The last parallel PR to land needs an update-branch + full-suite re-CI even when GitHub says
    CLEAN.** This repo's protection doesn't force "up to date", so U4 (#175) showed `MERGEABLE` on a CI
    run that had **never executed U3's new `card-markdown.spec.ts`** (U4 branched before U3 merged). Since
    U4 rewires how *every* secondary view is reached (drawer nav), a spec added by a sibling slice could
    have broken semantically with no textual conflict. `gh pr update-branch` merged current `main` in and
    forced the **combined** full suite (U3+U5+U4) to re-run green before merge — the documented
    serialized-landing safeguard, worth doing on the tail PR of any parallel batch that changes shared
    navigation/behavior. (Here it was provably safe — `card-markdown.spec.ts` is Board-only — but "prove
    it green on the combined tree" beats "reason about why it's probably fine".)
  - **`isolation: worktree` does NOT sandbox Bash — an agent's muscle-memory `cd .../frontend` hit the
    PARENT checkout.** U3 ran `npm install` in the primary checkout by reflex; the Edit-tool worktree
    guard caught it before any source write, and the agent reverted the parent's `package.json`/lock. The
    PM re-verified the primary tree was clean (`git status` + `git diff` on the lockfiles) after the agent
    returned. Mitigation applied: briefs now name the exact worktree `frontend/` path. Always re-check the
    primary checkout is clean after each worktree agent.
  - **U3 XSS handling is the reference pattern for `{@html}` user text:** `marked.parse` → `DOMPurify.sanitize`
    with a narrow `ALLOWED_TAGS`/`ALLOWED_ATTR`, `ALLOWED_URI_REGEXP` locking link schemes to
    http(s)/mailto/#, and an `afterSanitizeAttributes` hook forcing `rel="noopener noreferrer"`. The e2e
    proves it by injecting `<script>`/`<img onerror>` and asserting they're stripped + `window.__pwned`
    is undefined. Stays clean under V29's report-only CSP (rendered DOM only, no inline handlers).
  - **Prod-verify a frontend card by grepping the deployed hashed `/assets/index-*.js`** for a distinctive
    NEW string per slice: `group-label`/`Filter cards` (U5), `No comments yet`/`markdown-body`/`dompurify`
    (U3), `drawer-scrim`/`Account menu`/`Account settings are coming soon` (U4).

- **EPIC-49 Wave 4: V35 (⌘K palette) → V36 (keyboard shortcuts + help) — serialized, and EPIC-49 DONE.**
  Ran V35 (KAN-299, PR #177) then V36 (KAN-300, PR #178) **serially, not in parallel**, because both add
  a global `<svelte:window onkeydown>` handler to the same area (App.svelte / Board.svelte) — conceptually
  coupled (V36's help overlay must list V35's ⌘K) and touching overlapping files. Both merged + deployed +
  prod-verified. **All 7 EPIC-49 cards (U1–U5, V35, V36) shipped; EPIC-50 notifications stays deferred.**
  Learnings:
  - **A slice whose design was already locked upstream skips the mockup phase.** V35's palette visuals were
    approved back in U2's mockup (the Command panel), and `ui/Command.svelte` shipped styled-but-unmounted
    for exactly this — so V35 went straight to implementation (wiring the registry + Cmd-K + overlay). The
    agent confirmed the primitive was "genuinely drop-in per its declarative `groups` API; the only real
    work was the registry + overlay/keybind." Building the reusable primitive one slice early (U2) paid off.
  - **Two global keydown handlers coexist cleanly by owning disjoint key sets.** App.svelte's ⌘K handler
    fires only on the Cmd/Ctrl-`K` chord; V36's board handler bails on the FIRST line for any
    Cmd/Ctrl/Alt chord. Neither clobbers the other. The pattern to repeat: chord-shortcuts and
    single-key-shortcuts live in separate handlers that each early-return on the other's trigger shape.
  - **The anti-typing-hijack guard is the load-bearing correctness property of a single-key-shortcut
    feature** — a regression breaks typing in every form. V36's guard early-returns when: a Cmd/Ctrl/Alt
    modifier is present; the target is `INPUT`/`TEXTAREA`/`SELECT`/`isContentEditable`/closest
    `[contenteditable]`; OR any overlay is open (`.modal-backdrop`, Bits UI floating wrapper, `[role=listbox]`).
    Prove it with an e2e that **types the shortcut letters into a field** (`jklheonc`) and asserts they land
    as text, not navigation — not just that the happy-path shortcuts work.
  - **Bits UI focus quirk (V35):** selecting a Command item by MOUSE moves focus to the `role=application`
    root; with `shouldFilter=false` (a free-text sub-mode, e.g. typing a new card title) root-level
    keystrokes aren't routed to the search value, so typed text silently dropped. Fix = refocus the input
    on sub-mode entry. Keyboard flow (arrow/Enter) never lost focus; only mouse-select did.
  - **`reuseExistingServer: !CI` in `playwright.config.ts` is a multi-project-machine trap.** Locally it
    silently reuses whatever holds :8000/:5173 — here an unrelated app — so worktree e2e binds to the wrong
    backend (login 404s). Both V35 and V36 worked around it by retargeting to free ports + a per-worktree
    Postgres and reverting the config before commit. **Standing tech-debt: make the e2e port/API-origin
    env-overridable** so worktree runs need zero source edits (it currently requires editing 3 files:
    vite config, playwright config, `helpers.ts` `API_ORIGIN`). This recurred across the whole epic.
  - **Programmatic `.focus()` needs a visible ring of its own.** Browsers don't reliably paint
    `:focus-visible` for a `.focus()` call, so V36 added a persistent teal `.kbd-focused` class to mark the
    active card during keyboard nav — otherwise the "where am I" state is invisible.

- **EPIC-49 follow-up: KAN-392 — expose the shortcuts help via a visible avatar-menu entry (PR #180).**
  Prompted by a human (on Windows) asking how to try the shortcuts: V36's help overlay was reachable
  ONLY by pressing `?` — a chicken-and-egg discoverability dead-end (you can't discover the `?` help
  without knowing `?`). Fix (user-approved placement): a "Keyboard shortcuts" item (⌨ icon + teal `?`
  hint chip) in U4's avatar `DropdownMenu`, opening the same `kbd.helpOpen` overlay. Learnings:
  - **A keyboard-only entry point to a keyboard-help overlay is not discoverable** — always pair a
    keyboard shortcut with a visible affordance for the same action. General UX rule, not specific to
    this app.
  - **The overlay was mounted inside `Board.svelte`, so a global trigger needed the mount moved to
    `App.svelte`.** Triggering `kbd.helpOpen = true` from the always-visible avatar menu while on a
    non-board view (Epics/Dashboard/…) flipped the flag but rendered nothing. Moving the
    `{#if kbd.helpOpen}<ShortcutsHelp/>` mount up to `App.svelte` (and removing it from `Board.svelte`,
    NOT leaving it in both — that double-renders on the board) made it work from any view; the board
    `?` handler still opens it since it sets the same shared rune. The e2e asserts `toHaveCount(1)` for
    the dialog to lock in "no double-render".
  - **The help overlay is OS-aware:** it labels the palette chord `⌘K` on macOS and `Ctrl-K` elsewhere
    (`/mac/i.test(navigator.platform)`), so Windows/Linux users see the right modifier.
