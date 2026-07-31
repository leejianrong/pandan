---
shaping: true
---

# Milestone 7 — Slices ("Name & Sharpen the Tools")

Vertical increments of the [M7 shape](SHAPING.md). Each ends in **observable behaviour** and ships as
its own PR behind CI, matching the M1–M6 cadence.

Numbering continues the **global V-series** (M2 = V1–V5, M3 = V6–V10, M5 = V11–V19, M6 = V26–V39;
M4 was tracked directly as EPIC-3…EPIC-17). **M7 is V40–V50** — V50 was added after the initial plan
(see the correction note below) and **builds first within Wave 2** despite its number, the same way
M6's V35/V36 built out of numeric order inside EPIC-49.

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
| **V40 · Rebrand sweep** ✅ | code, CLI, MCP, skills, docs | N1 | 1 | KAN-423 | `pandan list` works; the UI, README and board all say *pandan*; a `KANBAN_*`-configured client still works with a deprecation notice |
| **V41 · Rebrand deploy identity** ⏸️ **deferred** | Fly app, ghcr, OAuth, CI | N2 | 1 | KAN-424 *(blocked-by KAN-439)* | — deferred behind the k8s homelab migration; the in-place renames are carved out as **KAN-437** |
| **V50 · CLI release discipline** ✅ | version-bump-on-fix + discriminating `--version` | A0 | 2 | KAN-435 | `pandan --version` says which build this is; a stale binary is detectable, not silent |
| **V42 · `--fields` + round-trip tests** ✅ | projection flag; pin the shipped ref handling | A1 | 2 | KAN-425 | `--fields` widens the row; a per-verb test feeds each printed identifier back |
| **V43 · Error contract** ✅ | structured errors, exit codes | A2 | 2 | KAN-426 | A bad flag, a bad value and a missing token each print a parseable error on **stdout** with the documented exit code |
| **V44 · Aggregates** | summary on every list verb | A3 | 2 | KAN-427 | `pandan list` ends with `42 cards · 12 todo · 5 in_progress · 25 done`; no second call needed for a count |
| **V45 · Truncation** | size hints + `--full` | A4 | 2 | KAN-428 | A long description prints truncated with `(truncated, 2847 chars total — use --full …)`; `--full` shows it all |
| **V46 · Content-first + disclosure** | bare command, `help[]` | A5 | 2 | KAN-429 | Bare `pandan` prints live board state and exits 0; results carry `help[]` next-step templates |
| **V47 · TOON** | `--format toon` for nested payloads | A6 | 2 | KAN-430 | `pandan get KAN-304 --format toon` returns the same data as `--json`, materially cheaper |
| **V48 · Ambient context** | session hook + packaged skill | A7 | 2 | KAN-431 | A fresh agent session already knows the open cards without calling anything |
| **V49 · MCP right-sizing** *(tail)* | measure, decide, ADR, execute | A8 | 3 | KAN-432 | The MCP schema token cost is measured and published; the chosen surface is an ADR and is live |

> **Correction (2026-07-31, after the plan was first written).** The AXI audit's headline finding —
> "the CLI prints identifiers it will not accept" — was an artefact of a **stale installed binary**.
> In source it was fixed by **KAN-285** on 2026-07-21, and the external user's `label create --color`
> report was likewise already fixed by **KAN-288**. The version was never bumped after either fix, so
> `--version` reported `0.3.0` both before and after and nothing revealed the staleness. Consequences
> folded into this plan: **V42 de-scoped** to `--fields` + regression tests (its round-trip half is
> shipped), **KAN-433 closed invalid**, and a new root-cause slice **V50 / KAN-435** added and
> prioritised **first** in Wave 2. Audit against `uv run python -m pandan_cli` from `pandan-cli/`,
> never a `kan` on `PATH` — see the [shaping](SHAPING.md)'s methodology note.

> **Status:** 🚧 **in progress (4/11 shipped, 1 deferred).** **V40 / KAN-423 is shipped** (two PRs —
> structural then semantic; see its slice note), and Wave 2 has begun: **V50 / KAN-435** shipped as
> **v0.5.0** (release provenance in `--version` + the version-bump guard), **V42 / KAN-425** as
> **v0.6.0** (`--fields` + the identifier round-trip suite), and **V43 / KAN-426** as **v0.7.0** (the
> CLI's error contract: structured errors on stdout, the six-code exit scheme documented and pinned,
> and ref-resolution failure repaired to exit `5`). **V41 / KAN-424 is ⏸️ deferred**, `blocked-by`
> **KAN-439** (k8s homelab migration), with **KAN-437** carved out for the in-place renames.
> Board cards **KAN-423…KAN-432** + **KAN-435** under the three `M7:` epics
> **EPIC-66** (Pandan Rebrand), **EPIC-67** (Agent-Ergonomic CLI), **EPIC-68** (MCP Right-Sizing).
> The rebrand decision is [ADR 0018](../adr/0018-pandan-rebrand.md). The sister-app kickoff
> (**KAN-304**, human-owned) is **unblocked** now V40 has landed.
>
> **Also under EPIC-67, not a slice:** **KAN-434** — `list --json` returns `{cards: […]}` rather than a
> bare array, an intentional API-passthrough envelope that is **nowhere documented** (`SKILL.md` says
> only "pipe into `jq`"; `--help` says "the raw JSON from the API"). Externally reported and **still
> valid**. It must **not** be flattened, because V44 adds a `summary` field beside `cards`; the fix is
> to document the envelope per verb with a correct `.cards[]` example. Its sibling report,
> **KAN-433** (`label create --color`), was **closed invalid** — already fixed by KAN-288; see the
> correction note above.

---

## Wave 1 — Name

### V40 · Rebrand sweep: code, CLI, MCP, skills, docs (N1) — KAN-423
- **Build:** rename `simple-kanban` → **`pandan`** across the repo (~52 files carry the brand string).
  - **Packages:** `simple-kanban-{backend,frontend,cli,mcp}` → `pandan-*`; the `kanban-cli/`,
    `kanban-client/` and `mcp/kanban_mcp/` directories and import roots were moved with them, so the
    packages are now `pandan-cli/` / `pandan_cli`, `pandan-client/` / `pandan_client` and
    `mcp/pandan_mcp/`. (`kanban-docs-tooling` → `pandan-docs-tooling` too.)
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
    `kanban_pat_` → `pandan_pat_`, **plus** `LEGACY_TOKEN_PREFIXES = ("kanban_pat_",)` and an
    accepted-prefix tuple at the resolver's fast-path guard, so already-issued tokens keep
    authenticating. **This slice note originally said the change was "safe by inspection" because
    "verification is a hash lookup over the whole raw token with no `startswith` guard" — that was
    wrong.** The guard exists at [`backend/app/authz.py:85`](../../backend/app/authz.py) (`_resolve_pat`,
    a deliberate no-DB-round-trip-for-a-stray-bearer optimisation), so a bare prefix flip would have
    `401`'d every existing PAT. See ADR 0018 §"The PAT prefix" for the full correction and the
    "cite the `file:line` you inspected" convention it adopted.
  - **UI:** document title, nav/brand text, landing copy, `frontend/index.html`.
  - **Skills:** `simple-kanban` → `pandan`, `project-manager-kanban` → `pandan-pm` (directory,
    frontmatter name, description, and every in-body command example).
  - **Docs:** `README.md`, `CLAUDE.md`, `docs/**` (including this milestone's own files), and the
    Roadmap **board name** via `PATCH /api/v1/boards/5`.
  - **Explicitly NOT renamed:** the `KAN-` / `EPIC-` ticket prefixes (R1.6) and the config file's
    generic keys — with a comment at `TOKEN_PREFIX` and in `models.py` saying why, so nobody
    "finishes" the rename later. Also left alone, and recorded in ADR 0018's non-goals: the
    `kanbanauth` cookie, the `X-Kanban-Event` webhook header, the `kanban.*` logger names, the
    `kanban.theme` / `kanban.activeBoardId` localStorage keys, the `kanban:kanban@…/kanban` local
    Postgres credentials, and the **CI job display names** (branch protection matches required checks
    on them — ops work, sequenced with KAN-437). The deployed Fly origin and OAuth App stay too, see
    V41 below.
- **Tests:** backend integration — a newly minted PAT carries `pandan_pat_`, and a pre-existing
  `kanban_pat_`-shaped token (seeded via `hash_token`) still authenticates. CLI unit — `PANDAN_*`
  wins over `KANBAN_*`; `KANBAN_*` alone still resolves and warns; neither set → the structured
  "token required" error. MCP unit — the tool-list smoke passes under the new module path. Frontend —
  `svelte-check` + the e2e smoke (title assertion updated).
- **Acceptance:** the demo; suite green. App code + docs — **deploys** (no migration).
- **Notes:** **shipped as two sequential PRs, not one** (the original note said one). PR 1 was
  structural — directory / package / import-root / distribution-name moves plus every path that
  references them, with *no* user-visible string change — and is verifiable by CI. PR 2 was semantic
  (command names, env vars, PAT prefix, UI copy, prose) and verifiable only by reading. Splitting kept
  the second reviewable instead of buried in the first, and surfaced the `startswith` bug above before
  any user-visible change shipped; see ADR 0018's amendment. Grep for the old strings as the last
  review step:
  `grep -ri 'simple.kanban\|kanban_cli\|kanban_mcp\|kanban_client\|KANBAN_' --exclude-dir={.venv,node_modules,.git}`
  should return only the intentional fallback, the deliberate non-renames, and the "why we kept `KAN-`"
  comments.

### V41 · Rebrand deploy identity: Fly app, ghcr image, OAuth callbacks (N2) — KAN-424 ⏸️ DEFERRED

> **⏸️ Deferred, not descoped (decided 2026-07-31, after V40 landed).** The project is moving to a
> **self-hosted k8s homelab** — board card **KAN-439** — which replaces the Fly deployment outright. A
> Fly→Fly cutover first would pay the same migration **twice**: two new OAuth Apps, two DNS cuts, two
> verification passes, for an interim hostname with a short remaining life. So **KAN-424 is deferred
> and marked `blocked-by` KAN-439**; the deploy identity is renamed **once**, when the homelab is stood
> up. See ADR 0018 §"The deploy identity: DEFERRED, not executed".
>
> **What that means concretely:**
> - The origin **stays** `simple-kanban-jian.fly.dev`, on the Fly app `simple-kanban-jian`, with the
>   **existing** prod GitHub OAuth App and the **existing** `AUTH_SECRET` (rotating it would invalidate
>   every PAT and session for nothing). V40 therefore rewrote **no** `*.fly.dev` URL, and `fly.toml`'s
>   `app = "simple-kanban-jian"` is untouched.
> - The renames that *can* happen in place are carved out as **KAN-437**: the **GitHub repository**
>   name, the **OAuth App display name**, and the **ghcr image path**
>   (`ghcr.io/…/simple-kanban-mcp` → `…/pandan-mcp`). Cheap and reversible, but they still move URLs
>   (repo, `github.io` docs site, image pull), so they are their own change. This is why the repo URL,
>   the docs-site URL and the ghcr path still read `simple-kanban` after V40. Pair the **CI job
>   display-name** rename with it — branch protection matches required checks on those strings.
> - **Nothing is blocked.** V40 already unblocked **KAN-304** (the `kaya` kickoff); the hostname is
>   the only place the retired name is still user-visible.

The original plan is preserved below for whoever executes the homelab cutover — the *sequence* is
still the right one, only the target changes from a new Fly app to the k8s ingress.

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
- **Notes:** superseded by the deferral above — do **not** execute this as a Fly→Fly move. Leaving the
  old app running until the final step is still the right shape for the homelab cutover: every step
  stays reversible up to the DNS cut.

## Wave 2 — Sharpen the tools

### V50 · CLI release discipline: version-bump-on-fix + a discriminating `--version` (A0) — KAN-435
- **Build:** the root cause behind two false bug reports (see the correction note above). Timeline:
  version `0.3.0` set 2026-07-21 01:48 (`6289e92`) → the standalone binary built 02:01 **from** it →
  KAN-285 (`a10eaee`) and KAN-288 (`0a7af29`) landed the same day at 23:36/23:39 → **no bump since**.
  So `--version` cannot distinguish a pre-fix build from current source, and `release-cli.yml` fires
  only on a `v*` tag, so nothing forces a bump when a user-visible fix lands.
  1. **Bump-on-fix:** a user-visible CLI change bumps the version in the **same PR**. Enforce as far
     as is cheap — a PR-checklist line plus a pre-push/CI check that a diff touching
     `pandan_cli/`'s behaviour also touches the version.
  2. **Discriminating `--version`:** embed the build's `git describe`/short sha at package time so
     `--version` prints e.g. `pandan 0.4.0 (a10eaee)` for a release and marks a source run as such.
     This is the part that makes staleness *detectable* rather than merely *avoidable*.
  3. **Cut a release** so a binary carrying KAN-285/KAN-288 actually exists downstream.
  4. **Document "is my `pandan` stale?"** in the CLI README, and apply the same reasoning to the MCP
     image (`publish-mcp-image.yml`).
- **Tests:** unit — `--version` renders both the release and source-run forms; the version-bump guard
  fires on a behavioural diff and stays quiet on a docs-only one. Manual — build the binary and confirm
  the embedded sha matches `HEAD`.
- **Acceptance:** the two-forms demo + a tagged release; suite green. CLI/CI-only — no deploy.
- **Notes:** **builds first in Wave 2**, before the other AXI slices. Every guarantee they add is
  unverifiable in the field while "which build am I running?" has no answer.

### V42 · `--fields` projection + identifier round-trip regression tests (A1) — KAN-425 ✅
- **Build:** de-scoped from the original plan (see the correction note). The **round-trip half is
  already shipped** — `_id_or_ticket_arg` + `_parse_id_or_ticket` accept `KAN-`/`EPIC-` refs
  case-insensitively wherever an id is taken (KAN-285), and an unknown ref already exits `1` with
  `no card found with ticket KAN-99999`. What's left:
  - **`--fields` (AXI 2), genuinely absent:** keep the 4-field default row, add `--fields a,b,c` to
    widen it on any list verb, with a documented vocabulary and a clear error naming the unknown field.
    Do not confuse this with the `Fields:` line in `list --help`, which is `--sort`'s vocabulary.
  - **Regression tests for the shipped behaviour**, which currently has none — the reason a
    ten-day-old fix could be mistaken for a live defect.
- **Tests:** a **round-trip test per id-taking verb** (`get`/`update`/`move`/`delete`/`dep`/`link`/
  `comment`/`needs-human`/`resolve` + the epic verbs): list, take the printed identifier verbatim, feed
  it back, assert success. Ref parsing: mixed case, a bare int, an unresolvable ref (exit 1,
  not exit 2), an epic ref handed to a card verb. `--fields` selects, rejects unknown names, and leaves
  the default row untouched.
- **Acceptance:** the `--fields` demo + the round-trip suite; green. CLI-only — no deploy.
- **Non-goal, recorded: a leading `#` (`#KAN-1`) is NOT accepted.** An earlier draft of this slice
  listed `#`-tolerance as a test case; that was invention, not a requirement. The contract is *"any
  identifier the tool prints must be accepted"*, and nothing prints `#KAN-1` — while leniency in an
  identifier parser buys a future ambiguity for no measured need. It stays a usage error (exit `2`),
  pinned by a test so the decision is visible rather than accidental.
- **Shipped** as **v0.6.0** (PR #205): `--fields` on all ten list verbs with the vocabulary derived
  from the row's own `--json` keys (so it can't drift from the API), the 4-field default row pinned
  byte-identically, and 77 new tests — one round-trip per id-taking verb (13 card-ticket, 6 epic-ticket,
  8 numeric-id, plus `link rm`). `--sort`'s help line was reworded `Fields:` → `Sort keys:` with a test,
  killing the ambiguity that made the audit misread it. `--fields` deliberately does **not** touch
  `--json` (a verbatim passthrough; V44 adds `summary` there).

### V43 · Structured errors on stdout + documented exit codes (A2) — KAN-426 ✅
- **Build:** AXI 6 — *stream and shape*, plus pinning and repairing what already exists. Emit a
  parseable error on **stdout** (single-line, or JSON/TOON matching the output flag) carrying a stable
  **machine code**, the human message and the offending argument; guarantee **no verb prompts** when
  stdin isn't a tty (`login`'s `getpass` is already tty-gated — give it a structured failure instead of
  a bare stderr line); keep the usage text on `--help`.
  **Document and pin the real scheme, which is six codes, not three** (the earlier "0/1/2 contract"
  here was wrong): `0` ok, `1` general/config, `2` usage (argparse), `3` `401`, `4` `403`, `5` `404`.
  **Do not renumber them** — they're a published scripting contract.
  **And fix the one genuine inconsistency:** client-side ref-resolution failure must return **`5`**,
  not `1`, so `get 999999` and `get KAN-999999` agree on "no such card" (it applies to every verb that
  resolves a ref, not just `get`).
- **Tests:** CLI unit — one case per failure class asserting **stream, shape and exit code**: unknown
  flag (2), invalid enum value (2), missing token (1), 404 (5), 401 (3), 403 (4), transport error (1),
  success (0), and both identifier forms of a missing card agreeing on 5. `login` with a non-tty stdin
  errors structured instead of hanging. The exit-code scheme and the code→exit table are pinned by
  literal-value tests.
- **Acceptance:** the three-error demo; suite green. CLI-only — no deploy.
- **Notes:** this slice defines the error shape the rest of Wave 2 emits, so it lands before V44–V47.
- **Shipped** as **v0.7.0** (PR #207), paired with KAN-425 under one agent because V42's regression
  tests cover the identifier-resolution path this slice then had to repair. The exit-code
  inconsistency was fixed **in the resolver** (`_resolve_card_id`/`_resolve_epic_id`) rather than at
  the call sites, so it covers every ref-taking verb including `dep --blocked-by`. An add-only
  `ERROR_CODES` table (`pandan-cli/pandan_cli/cli.py:73`) maps 14 named codes → exit numbers so a
  raise site picks a *meaning*, never a number; 24 generic `ConfigError` sites were converted. The
  `403 → 4` row was shipped **flagged unverified** by the PM and then genuinely closed by the agent
  (prod board 11 exists but isn't ours → `403` → exit `4`; policy at `backend/app/authz.py:194-205`) —
  flagging the gap is what got it closed.

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
- **Build:** AXI 3 — and note the audit correction: the gap is **not** that human `get` dumps a long
  description. Human `get` prints a **one-line** card summary with **no description at all**, while
  `comment list` and every `--json` payload emit **full bodies untruncated**. So this slice does two
  complementary things:
  - **Add** a truncated description to human `get` (the under-disclosure) with an explicit, accurate
    hint — `(truncated, 2847 chars total — use --full to see complete body)` — and `--full` to opt out.
  - **Truncate** the currently-unbounded surfaces: `comment list` bodies, and long text inside
    `--json`/`--format toon` payloads (where a `get` on a card with a long description is today the
    single most expensive call an agent can make). Structured output keeps an escape hatch via `--full`.
  Limit configurable via the config file / an env var.
- **Tests:** CLI unit — under-limit text is byte-identical; over-limit truncates at the limit with a
  **true** total in the hint; `--full` restores the whole body everywhere it applies; multi-byte
  characters don't split mid-character; a card with no description renders unchanged.
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

### V47 · `--format toon` for nested payloads (A6) — KAN-430 ✅
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
- **Shipped** as **v0.8.0**: `--format {human,json,toon}` on every verb, `--json` kept as a supported
  alias (`--format` wins if both are given), and `_structured_payload` → `_render_structured` as the
  one shaping+serializing seam both structured formats go through. Errors and `config show` follow the
  flag too. The encoder is `pandan_cli/toon.py` — stdlib only, a port of the reference
  `@toon-format/toon` verified **byte-identical** on a 36-case corpus including 11 live board
  payloads; it is encode-only, and the round-trip contract is proven by a test-only decoder
  (`tests/toon_decode.py`) rather than by shipping a parser.
- **The measurement gate said ship, with a caveat worth keeping.** Measured on the real Pandan Roadmap
  board in `o200k_base` tokens, **toon vs today's `--json`**: `metrics` **−56%**, `activity` **−43%**,
  `dep list` **−38%**, `epic list` **−37%**, `get` −18%, cards list −10%. But roughly half of that is
  pretty-printing: **vs *compact* JSON** the tabular payloads still win big (`metrics` −29%,
  `activity` −24%, `epic list` −20%) while **`get` is +2% and the cards list is +12%** — TOON pays for
  uniform *rows*, not for a single object or for rows carrying non-uniform nested arrays. The slice's
  own scoping was therefore right on the evidence, and the cheap non-TOON win it implies —
  a compact `--json` — is left un-taken on purpose: `--json`'s indentation is a published,
  human-diffable contract, and `--format toon` now exists for callers who want the tokens back.

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
- **Build:** the MCP tool schemas load into every agent's context before any work happens, and the
  CLI now has full parity — so for a shell-capable agent the CLI path is strictly cheaper per task.
  1. **Measure** (the Must half): the token cost of the current schema set, and of each option
     below, on the same yardstick. **The surface is 49 tools, not the 48 this plan and KAN-432
     originally said** — verified 2026-07-31 by driving the server over stdio (`initialize` →
     `tools/list` returns 49) against the live `.mcp.json` config. The measured resident cost is
     **~10,076 tokens per session**. Re-count rather than trusting either number when you start.
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
  shaping ([kaya-vision](../kaya-vision.md), renamed from `simple-markdown-vision.md` in V40).
- **The Cloudflare edge setup** (`KAN-305`) — still open from M6, and V41 must coordinate with it
  rather than absorb it.
