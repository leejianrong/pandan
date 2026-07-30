---
shaping: true
---

# Milestone 7 — Slices ("Name & Sharpen the Tools")

Vertical increments of the [M7 shape](SHAPING.md). Each ends in **observable behaviour** and ships as
its own PR behind CI, matching the M1–M6 cadence.

Numbering continues the **global V-series** (M2 = V1–V5, M3 = V6–V10, M5 = V11–V19, M6 = V26–V39;
M4 was tracked directly as EPIC-3…EPIC-17). **M7 is V40–V49.**

M7 changes no API, no schema and runs no migration (R4.1) — it lives in the CLI, MCP, docs and deploy
layers. So the usual "API first, then MCP + CLI parity" rule reads differently here: the **CLI is the
subject**, and each AXI slice must ask whether the MCP surface needs the same treatment (usually not —
MCP returns structured payloads to a model already, which is why `A8` exists).

**Waves.**
- **Wave 1 — Name (V40–V41):** ships first. Unblocks the `kaya` sister app (`KAN-304`) and means the
  AXI slices write their help/output text once, in the final name.
- **Wave 2 — Sharpen the tools (V42–V48):** AXI conformance. The milestone is demo-complete after this.
- **Wave 3 — MCP right-sizing (V49):** *Nice-to-have* tail; measure, ADR, execute.

| Slice | What | Part | Wave | Card | Ends in (demo) |
|-------|------|:----:|:----:|------|----------------|
| **V40 · Rebrand sweep** | code, CLI, MCP, skills, docs | N1 | 1 | KAN-423 | `pandan list` works; the UI, README and board all say *pandan*; a `KANBAN_*`-configured client still works with a deprecation notice |
| **V41 · Rebrand deploy identity** | Fly app, ghcr, OAuth, CI | N2 | 1 | KAN-424 | The app serves from the new origin over its own cert; GitHub login works there; the old Fly app is gone |
| **V42 · Identifier round-trip** | accept `KAN-`/`EPIC-` + `--fields` | A1 | 2 | KAN-425 | `pandan get KAN-304` returns the card it just listed; `--fields` widens the row |
| **V43 · Error contract** | structured errors, exit codes | A2 | 2 | KAN-426 | A bad flag, a bad value and a missing token each print a parseable error on **stdout** with the documented exit code |
| **V44 · Aggregates** | summary on every list verb | A3 | 2 | KAN-427 | `pandan list` ends with `42 cards · 12 todo · 5 in_progress · 25 done`; no second call needed for a count |
| **V45 · Truncation** | size hints + `--full` | A4 | 2 | KAN-428 | A long description prints truncated with `(truncated, 2847 chars total — use --full …)`; `--full` shows it all |
| **V46 · Content-first + disclosure** | bare command, `help[]` | A5 | 2 | KAN-429 | Bare `pandan` prints live board state and exits 0; results carry `help[]` next-step templates |
| **V47 · TOON** | `--format toon` for nested payloads | A6 | 2 | KAN-430 | `pandan get KAN-304 --format toon` returns the same data as `--json`, materially cheaper |
| **V48 · Ambient context** | session hook + packaged skill | A7 | 2 | KAN-431 | A fresh agent session already knows the open cards without calling anything |
| **V49 · MCP right-sizing** *(tail)* | measure, decide, ADR, execute | A8 | 3 | KAN-432 | The MCP schema token cost is measured and published; the chosen surface is an ADR and is live |

> **Status:** 🔜 **not started (0/10).** Board cards **KAN-423…KAN-432** under the three `M7:` epics
> **EPIC-66** (Pandan Rebrand), **EPIC-67** (Agent-Ergonomic CLI), **EPIC-68** (MCP Right-Sizing).
> The rebrand decision is [ADR 0018](../adr/0018-pandan-rebrand.md). The sister-app kickoff
> (**KAN-304**, human-owned) is blocked on V40 landing.
>
> **Also under EPIC-67, not slices:** two externally-reported discrepancies (`kan` 0.3.0, a user on
> another project, verified 2026-07-31) that belong to the same tooling-ergonomics theme —
> **KAN-433** (the skill documents `label create --color C`; the CLI takes colour as a *required
> positional*) and **KAN-434** (`list --json` returns `{cards: […]}`, an intentional envelope that is
> nowhere documented). Both are doc-side fixes; KAN-434 explicitly must **not** flatten the envelope,
> because V44 adds a `summary` field beside `cards`.

---

## Wave 1 — Name

### V40 · Rebrand sweep: code, CLI, MCP, skills, docs (N1) — KAN-423
- **Build:** rename `simple-kanban` → **`pandan`** across the repo (~52 files carry the brand string).
  - **Packages:** `simple-kanban-{backend,frontend,cli,mcp}` → `pandan-*`; the `kanban-cli/`,
    `kanban-client/` and `mcp/kanban_mcp/` directories and import roots follow (`pandan_cli`,
    `pandan_client`, `pandan_mcp`).
  - **CLI:** console script `kan` → **`pandan`**, plus a **`pdn`** alias (a second
    `[project.scripts]` entry pointing at the same `main`). The PyInstaller entry + the standalone
    binary release name follow.
  - **MCP:** server name `kanban` → `pandan`; `.mcp.json.example` and every wiring snippet in
    `mcp/README.md` updated (the `mcpServers` key is what tool names are prefixed with, so this
    changes `mcp__kanban__*` → `mcp__pandan__*` — call that out in the PR body).
  - **Config:** `PANDAN_API_URL` / `PANDAN_TOKEN` / `PANDAN_BOARD_ID`, resolved first; the
    `KANBAN_*` names remain a **deprecated fallback** (read second, emit a one-line notice to stderr)
    so the live `.mcp.json`, the CLI config file and CI keep working through the cutover. The config
    file's own keys (`api_url`/`token`/`board_id`) are already brand-free — unchanged. Config path
    `~/.config/kan/…` → `~/.config/pandan/…`, migrating an existing file if present.
  - **PAT mint prefix:** `TOKEN_PREFIX` in [`backend/app/tokens.py`](../../backend/app/tokens.py)
    `kanban_pat_` → `pandan_pat_`. **Safe by inspection:** the prefix is used only at mint time and for
    the non-secret display hint; verification is a hash lookup over the whole raw token with no
    `startswith` guard, so existing `kanban_pat_…` tokens keep authenticating.
  - **UI:** document title, nav/brand text, landing copy, `frontend/index.html`.
  - **Skills:** `simple-kanban` → `pandan`, `project-manager-kanban` → `pandan-pm` (directory,
    frontmatter name, description, and every in-body command example).
  - **Docs:** `README.md`, `CLAUDE.md`, `docs/**` (including this milestone's own files), and the
    Roadmap **board name** via `PATCH /api/v1/boards/5`.
  - **Explicitly NOT renamed:** the `KAN-` / `EPIC-` ticket prefixes (R1.6) and the config file's
    generic keys. Leave a comment at `TOKEN_PREFIX` and in `models.py` saying why, so nobody "finishes"
    the rename later.
- **Tests:** backend integration — a newly minted PAT carries `pandan_pat_`, and a pre-existing
  `kanban_pat_`-shaped token (seeded via `hash_token`) still authenticates. CLI unit — `PANDAN_*`
  wins over `KANBAN_*`; `KANBAN_*` alone still resolves and warns; neither set → the structured
  "token required" error. MCP unit — the tool-list smoke passes under the new module path. Frontend —
  `svelte-check` + the e2e smoke (title assertion updated).
- **Acceptance:** the demo; suite green. App code + docs — **deploys** (no migration).
- **Notes:** land as one PR. It is large but mechanical, and splitting it leaves the repo in a
  half-renamed state that's worse to review. Grep for the old strings as the last review step:
  `grep -ri 'simple.kanban\|kanban_cli\|kanban_mcp\|KANBAN_' --exclude-dir={.venv,node_modules,.git}`
  should return only the intentional fallback + the "why we kept `KAN-`" comments.

### V41 · Rebrand deploy identity: Fly app, ghcr image, OAuth callbacks (N2) — KAN-424
- **Build:** ops-only, sequenced (a Fly app **cannot** be renamed, and a GitHub OAuth App permits
  exactly **one** callback URL):
  1. `fly apps create pandan` (or the final chosen app name) and set every secret on it —
     `DATABASE_URL`, `AUTH_SECRET`, `WEBHOOK_SECRET`, `COOKIE_SECURE`, `RATE_LIMIT_ENABLED`,
     `SENTRY_DSN` if set. Same Neon database — this is not a data move.
  2. Create a **new prod GitHub OAuth App** for the new origin's `/auth/github/callback`; set its
     client id/secret as secrets on the new app. Update the **dev** OAuth App only if the dev origin
     changes (it doesn't — dev stays `localhost:5173`).
  3. Deploy to the new app, verify on its `*.fly.dev` hostname: health, login, a board read, a write.
  4. Move the custom cert/DNS if one is in use; re-point the Cloudflare setup from
     `docs/guides/edge-hardening.md` (still pending as `KAN-305` — coordinate, don't duplicate).
  5. Retarget `fly.toml`, the deploy + keep-alive workflows, and the ghcr MCP image path
     (`ghcr.io/…/simple-kanban-mcp` → `…/pandan-mcp`); publish one image under the new path.
  6. Only then `fly apps destroy simple-kanban-jian`.
- **Tests:** n/a in CI (external). Post-cutover prod verification is the test: `/api/health` 200,
  GitHub login round-trip, a card create + move via `pandan` against the new origin, the keep-alive
  workflow green on its next run, and the inbound-webhook signature path still verifying.
- **Acceptance:** the demo; the old app destroyed; docs' URLs updated. Config + ops — the deploy
  workflow change itself deploys.
- **Notes:** do **not** start this until V40 is merged and deployed. Leaving the old app running until
  step 6 means every step is reversible up to the DNS cut.

## Wave 2 — Sharpen the tools

### V42 · Identifier round-trip: accept `KAN-`/`EPIC-` refs + `--fields` (A1) — KAN-425
- **Build:** two things, both about the identifier contract.
  - **Round-trip (the defect):** every verb that takes a card or epic id accepts the **ticket
    reference** the tools print — `KAN-304`, `epic-66`, case-insensitive, `#`-tolerant — as well as the
    bare integer. Add one shared resolver in the CLI (and in `pandan_client` if the MCP path needs it)
    that maps a ref to an id, resolving via the existing query API rather than guessing. Covers
    `get`/`update`/`move`/`delete`/`dep`/`link`/`comment`/`needs-human`/`resolve` and the epic verbs.
    An unresolvable ref is a structured "not found" (V43's contract), not an argparse `invalid int`.
  - **`--fields` (AXI 2):** keep the 4-field default row, add `--fields a,b,c` to widen it on any list
    verb, with a documented field vocabulary and a clear error naming the unknown field.
- **Tests:** CLI unit + integration — a **round-trip test per id-taking verb**: list, take the printed
  identifier verbatim, feed it back, assert success (this is the regression guard that the defect can't
  return). Ref parsing: lower/upper case, `#KAN-1`, a bare int, a non-existent ref, an epic ref given
  to a card verb (clean error). `--fields` selects, rejects unknown names, and leaves the default
  untouched.
- **Acceptance:** `pandan get KAN-304` demo; suite green. CLI-only — no deploy.

### V43 · Structured errors on stdout + documented exit codes (A2) — KAN-426
- **Build:** AXI 6. Replace argparse's stderr-and-usage behaviour with an explicit error contract:
  a parseable single-line (or TOON/JSON, matching `--format`) error on **stdout** carrying a stable
  machine code, a human message and the offending argument. Exit codes, documented in `--help` and the
  CLI README: **0** success, **1** error (auth, not-found, conflict, API/transport failure), **2**
  unknown or invalid flag/argument. Guarantee **no verb prompts** when stdin isn't a tty — `login`'s
  `getpass` becomes tty-gated and fails structured otherwise. Keep the human-readable usage text
  available via `--help`.
- **Tests:** CLI unit — one case per failure class asserting **stream, shape and exit code**: unknown
  flag (2), invalid enum value (2), missing token (1), 404 (1), 401 (1), transport error (1), success
  (0). `login` with a non-tty stdin errors structured instead of hanging.
- **Acceptance:** the three-error demo; suite green. CLI-only — no deploy.
- **Notes:** this slice defines the error shape the rest of Wave 2 emits, so it lands before V44–V47.

### V44 · Pre-computed aggregates on every list verb (A3) — KAN-427
- **Build:** AXI 4. Every list verb ends with a summary the agent would otherwise pay a round trip for:
  cards → `42 cards · 12 todo · 5 in_progress · 25 done` (plus `· 3 needs-human` when non-zero); epics
  → count + rollup spread; and the analogous one-liner for label/view/template/comment/dep lists.
  Under `--json`/`--format toon`, emit a `summary` object instead of a trailing line (per the shaping's
  open question) so parity holds for structured consumers.
- **Tests:** CLI unit + integration — the aggregate matches the rows actually returned (including under
  `--limit` and filters, where it must describe the returned set, not the whole board — assert this
  explicitly); an empty result still prints its definitive zero state (AXI 5 regression guard);
  `--json` carries `summary` and no trailing line.
- **Acceptance:** the summary-line demo; suite green. CLI-only — no deploy.

### V45 · Content truncation with size hints + `--full` (A4) — KAN-428
- **Build:** AXI 3. Long text fields (card `description`, comment `body`) truncate to a default
  character limit with an explicit, accurate hint —
  `(truncated, 2847 chars total — use --full to see complete body)` — and `--full` opts out. Applies to
  `get`, `comment list`, and anywhere else a body is rendered. Configurable limit via the config file /
  an env var; unaffected under `--json` (structured consumers asked for the data).
- **Tests:** CLI unit — under-limit text is byte-identical to today; over-limit truncates at the limit
  with a **true** total in the hint; `--full` restores the whole body; multi-byte characters don't split
  mid-character; `--json` is untouched.
- **Acceptance:** the truncation demo; suite green. CLI-only — no deploy.

### V46 · Content-first bare invocation + `help[]` next-step hints (A5) — KAN-429
- **Build:** AXI 8 + 9.
  - **Content first:** bare `pandan` (no args) prints **live, actionable state** and exits **0** — the
    default board's open cards plus V44's aggregate, prefixed by the executable path and a one-sentence
    description of what the tool does. No default board configured → the board list. No token → V43's
    structured auth error, not a stack trace. `--help` still prints usage.
  - **Contextual disclosure:** results carry `help[]` lines suggesting the logical next command as a
    **template** — fixed flags carried forward, runtime values left parameterised (`pandan move <id>
    in_progress`, `pandan comment add <id> "…"`). Per-verb, small, and suppressed under
    `--json`/`--format toon`.
- **Tests:** CLI unit + integration — bare invocation exits 0 and prints rows, not usage; with no board
  configured it lists boards; hints are **parameterised** (assert the literal `<id>` placeholder is
  present and no concrete id was interpolated); hints absent under `--json`; `--help` unchanged
  (AXI 10 regression guard).
- **Acceptance:** the bare-command demo; suite green. CLI-only — no deploy.

### V47 · `--format toon` for nested payloads (A6) — KAN-430
- **Build:** AXI 1, **scoped deliberately** (see the shaping): the TSV list default is already
  key-free and stays the default. Add `--format {human,json,toon}` (with the existing `--json` kept as
  a documented alias for `--format json`) and implement TOON for the **nested** payloads where it
  actually pays: `get`, `metrics`, `activity`, `epic list` with rollups, `dep list`, `template`/`view`
  reads. One shared serializer feeding both `json` and `toon` so they can't drift.
- **Tests:** CLI unit — for each nested payload, the TOON output parses back to data **equal** to the
  `--json` output (round-trip equality is the contract, not a golden string); the TSV default is
  byte-identical to before this slice; an unknown `--format` value is a V43-shaped exit-2 error.
  Record the measured token delta vs `--json` in the PR body — if it isn't a real saving on our actual
  payloads, say so and scope the slice down rather than shipping it for the rubric's sake.
- **Acceptance:** the round-trip demo + the measured delta; suite green. CLI-only — no deploy.

### V48 · Ambient context: session-hook install + packaged skill (A7) — KAN-431
- **Build:** AXI 7. A `pandan install-context` (name TBD in the slice) that wires board state into an
  agent session **before** it acts — a Claude Code session hook emitting the default board's open cards
  + V44's aggregate, so the agent starts already knowing the state instead of calling for it. Idempotent
  install and uninstall, a no-op with a clear message when no board is configured, and it must never
  block session start (bounded timeout, soft-fail — the cold-start reality from `KAN-25`/`KAN-45`
  applies). Package the renamed `pandan` skill for distribution alongside it.
- **Tests:** unit — install is idempotent; uninstall is clean; unconfigured → a no-op with a message;
  a slow/failing API soft-fails within the timeout instead of hanging. Manual — a fresh session shows
  the ambient block.
- **Acceptance:** the fresh-session demo; suite green. Tooling-only — no deploy.

## Wave 3 — MCP right-sizing *(Nice-to-have; the milestone demos complete without this)*

### V49 · MCP right-sizing: measure, decide, ADR, execute (A8) — KAN-432
- **Build:** the 48 MCP tool schemas load into every agent's context before any work happens, and the
  CLI now has full parity — so for a shell-capable agent the CLI path is strictly cheaper per task.
  1. **Measure** (the Must half): the token cost of the current 48-tool schema set, and of each option
     below, on the same yardstick.
  2. **Decide** between: (a) consolidate to a small verb set (e.g. one tool per entity with an action
     argument); (b) expose a single exec-`pandan` tool and let the CLI be the surface; (c) keep the
     breadth as the documented fallback for shell-less agents and **freeze its growth**.
  3. **ADR** recording the measurement, the choice and what moved where.
  4. **Execute** it, keeping the `pandan_client` library as the shared core either way.
- **Tests:** MCP unit — the tool-list smoke reflects the chosen surface; each retained tool still
  round-trips against mocked `httpx`; if tools are removed, a test asserts the CLI covers each removed
  capability (parity can't silently regress, per ADR 0005).
- **Acceptance:** the published measurement + the ADR + the live surface; suite green. MCP-only — no
  deploy (a new ghcr image publish).
- **Notes:** deliberately last. Deciding what MCP can shed requires the CLI to *already* be
  AXI-conformant, or the comparison is against a worse baseline.

---

## Out of scope for M7

Recorded so it doesn't creep in:
- **Any API, schema or migration change** (R4.1). Every gap M7 fixes is in the adapter layer.
- **New board features.** M6 closed the feature roadmap; M7 is names and tooling.
- **Renaming the `KAN-`/`EPIC-` ticket prefixes** (R1.6) — see the shaping's decisions log.
- **Removing the `KANBAN_*` env-var fallback.** It ships deprecated in V40 and is deleted in a later
  milestone, once nothing reads it.
- **The `kaya` sister app itself.** V40 unblocks `KAN-304`; building `kaya` is its own repo and its own
  shaping ([simple-markdown-vision](../simple-markdown-vision.md), to be renamed with the app).
- **The Cloudflare edge setup** (`KAN-305`) — still open from M6, and V41 must coordinate with it
  rather than absorb it.
