---
shaping: true
---

# Milestone 7 — Shaping ("Name & Sharpen the Tools")

M6 finished the product: the board is hardened, has projects, cycles, a palette, keyboard nav and an
inbox, and the roadmap board has **no open agent work left**. What remains is not more board features
— it's the two things standing between this repo and its next phase:

1. **The name.** A sister notes app is about to start (`KAN-304`), and "simple-kanban" cannot be half
   of a two-app family. Naming the pair is a prerequisite for the sibling's shaping, not a cosmetic
   pass — the sister app's shared-identity and cross-link contract
   ([kaya-vision](../kaya-vision.md)) bakes in whatever names exist when it
   starts.
2. **The tools.** This project's whole thesis is that the API is kept clean so *agent clients are
   thin adapters* (ADR 0005). M2–M6 delivered the surface — the `kan` CLI reached full API parity and
   the MCP server grew to 48 tools — but nobody ever audited whether that surface is **pleasant for an
   agent to consume**. The [10 AXI design principles](https://axi.md/) are the first external rubric
   for exactly that, and a walk-through against the live CLI found one real defect and six gaps.

So M7 is two movements: **name** (rebrand, ships first, unblocks the sibling) then **sharpen the
tools** (AXI conformance, then right-size MCP). No new board features, no schema change, no API
change — M7 is entirely about the *edges* of the system: what it's called and how an agent talks to it.

This records a single **shape-of-record** — the maintainer settled scope directly (rebrand first;
AXI as the tooling rubric; MCP breadth reconsidered) — with the fit check confirming coverage.

## Why these requirements

### The rebrand — why now, and why it's more than a rename

`simple-kanban` was an accurate name for one app. It is a bad name for a **family**, because the
sibling would have to be `simple-markdown` — and "simple-X" as a naming scheme announces a
tech-demo, not a product pair. The chosen names are **pandan** (this app) and **kaya** (the notes
sibling): two Southeast Asian ingredients that pair in one dish, which the suite name **kayatoast**
then names for free. Rationale, alternatives considered, and the mechanical consequences are in
[ADR 0018](../adr/0018-pandan-rebrand.md).

Doing it *before* the AXI work is deliberate: the AXI slices rewrite the CLI's output and help layer
substantially, and every line of that text carries the product name. Rebrand-first means it gets
written once.

The rebrand looked like the riskiest single step in M7 — not the code sweep (mechanical) but the
**deploy identity**. A Fly app cannot be renamed, and a GitHub OAuth App allows exactly one callback
URL, so the cutover would be a create-migrate-destroy sequence with DNS in the middle. That earned its
own slice — and then, once V40 landed, **the slice was deferred rather than executed** (see R1.5 and
part N2 below): the project is moving to a self-hosted k8s homelab (**KAN-439**), so a Fly→Fly cutover
would pay the same migration twice. The riskiest step turned out to be one worth *not taking yet*.

### AXI conformance — the honest audit

Walked the CLI against all ten principles (2026-07-31). **Audited against `pandan-cli/` at `main`, not
against an installed binary** — see the methodology warning below, which is in this doc because the
first pass got it wrong. The discipline principles were already satisfied — a credit to the M4/M5 CLI
work — and the real gaps cluster in *what the output tells an agent to do next*:

| # | AXI principle | State before M7 (verified against source) |
|---|---|---|
| 1 | Token-efficient output | ~ list output is already tab-separated with no repeated keys; `--json` for piping. No `--format`, no TOON. |
| 2 | Minimal default schemas | ~ ✅ 4 fields per list row (`ticket  column  title  pts=N`); ❌ no `--fields` to widen (the `Fields:` text in `list --help` is `--sort`'s vocabulary, not a projection flag). |
| 3 | Content truncation | ❌ but *not* where first assumed: human `get` prints a **one-line** card summary with **no description at all** (an under-disclosure), while `comment list` and every `--json` payload emit **full bodies untruncated**. No limit, no size hint, no `--full`. |
| 4 | Pre-computed aggregates | ❌ no list verb prints a total or summary; a count needs a second round trip. |
| 5 | Definitive empty states | ✅ `(no cards)` — explicit. |
| 6 | Structured errors & exit codes | ~ **richer than AXI asks, and inconsistent in one place.** The scheme is **six** codes, not the `0`/`1`/`2` first written here: `0` ok, `1` general/config, `2` usage (argparse), `3` `401`, `4` `403`, `5` `404` — all six verified against the deployed API (`403`→`4` against a real foreign board; a nonexistent board id is `5`). ❌ The actual defect: **the same failure returned different codes depending on the identifier form** — `pandan get 999999` (numeric, `404` server-side) exited `5` while `pandan get KAN-999999` (ticket, resolved client-side) exited `1`, so an agent branching on the code got a different answer for "no such card" depending on how it addressed it. ❌ Messages went to **stderr** as prose with no machine-readable code. (`login` prompting unconditionally was **wrong** — `_cmd_login` has always gated `getpass` on `sys.stdin.isatty()`; what it lacked was a structured failure when no token arrived.) |
| 7 | Ambient context | ~ a distributable skill exists; nothing installs board state into a session before the agent acts. |
| 8 | Content first | ❌ bare `kan` prints usage + `error: the following arguments are required` and exits 2. |
| 9 | Contextual disclosure | ❌ no next-step hints on any result. |
| 10 | Consistent `--help` | ✅ every subcommand. |

**Identifier round-trip was already fixed — and the way we got that wrong is the more useful finding.**
The first pass of this audit reported a headline defect: *the CLI prints identifiers it will not
accept* (`kan list` emits `KAN-304`, but `kan get KAN-304` fails with `invalid int value` while
`kan get 304` works). It reproduced — against a **stale installed binary**. In source it has been
fixed since **KAN-285** (commit `a10eaee`, 2026-07-21): `_id_or_ticket_arg` + `_parse_id_or_ticket`
accept `KAN-`/`EPIC-` refs case-insensitively wherever an id is taken, and an unknown ref is already a
clean `exit 1` with `no card found with ticket KAN-99999`.

The same stale build produced a second false report, this time from **an external user**: that
`label create` takes colour positionally rather than as `--color` as the skill documents. Also fixed
in source (**KAN-288**, commit `0a7af29`) — the skill was right and the binary was old.

**Why it happened, and why it's a slice and not a footnote.** `pyproject` set version `0.3.0` on
2026-07-21 01:48; the binary was built at 02:01 **from** that version; KAN-285 and KAN-288 landed the
same day at 23:36 and 23:39; and the version **has not been bumped since**. So `kan --version` reports
`0.3.0` for both a build that lacks those fixes and current source that has them, with nothing to
distinguish them — and `release-cli.yml` only fires on a `v*` tag, so nothing forces a bump when a
user-visible fix lands. That cost two false bug reports and, in this very milestone, one duplicate
slice and one invalid card. It is tracked as **KAN-435** and is the highest-priority item in EPIC-67.

> **Methodology, for anyone auditing this CLI again: run `uv run python -m pandan_cli …` from
> `pandan-cli/`, never a `kan` on your `PATH`.** An installed binary may predate any fix, and until
> KAN-435 lands `--version` cannot tell you. Two of this audit's four "findings" were artefacts of
> ignoring this.

**Where we deviate from AXI, deliberately.** Principle 1 says to adopt TOON in place of JSON for
~40% savings. Our default list output is **already** tab-separated rows with no per-record keys,
which is at least as cheap as TOON — TOON's win is measured against JSON, not against TSV. So we
adopt TOON where it actually pays (the **nested** payloads: `get`, `metrics`, `activity`, epic
rollups, dependency graphs) as `--format toon`, and keep TSV as the list default. Rewriting an
already-efficient path to satisfy a rubric literally would be cargo-culting it.

### MCP right-sizing — the unexamined cost

The MCP server has **48 tools**. Every one of those schemas loads into an agent's context before it
does any work, and the CLI now has full parity with all of them — so for any agent that can run a
shell, the CLI-plus-skill path is *strictly cheaper per task* than the MCP path. That's a real
tradeoff nobody has priced. M7 prices it and acts on the answer; it does not assume the answer is
"delete things" (MCP is the documented fallback for agents without shell access, and that's a
legitimate reason to keep breadth). The decision needs a measurement and an ADR, so it's a slice.

---

## Requirements (R)

| ID | Requirement | Status |
|----|-------------|--------|
| **R0** | **The product carries one coherent name across code, deploy and docs; the tools an agent drives are token-cheap, self-describing and unambiguous** | Core goal |
| **R1** | **Rebrand to `pandan`** | |
| R1.1 | Product, repo, packages, UI and docs renamed; the Roadmap board renamed | Must-have |
| R1.2 | CLI renamed (`kan` → `pandan`, with a short `pdn` alias); MCP server renamed | Must-have |
| R1.3 | Config renamed (`PANDAN_*` env vars) **with the `KANBAN_*` names honoured as a deprecated fallback**, so a live `.mcp.json` / CLI config keeps working through the cutover | Must-have |
| R1.4 | Skills renamed (`simple-kanban` → `pandan`, `project-manager-kanban` → `pandan-pm`) | Must-have |
| R1.5 | ⏸️ **Deferred.** Deploy identity moved: Fly app, ghcr image path, GitHub OAuth App(s), CI + keep-alive. Deferred to the k8s homelab migration (**KAN-439**) so the cutover is paid once, not twice — **KAN-424** is `blocked-by` it. The origin, Fly app name, prod OAuth App and `AUTH_SECRET` all stay as they are. The subset that *can* rename in place — GitHub repo, OAuth App display name, ghcr image path, CI job display names — is carved out as **KAN-437** | Must-have → **deferred** |
| R1.6 | **Ticket prefixes `KAN-` / `EPIC-` are NOT renamed** — ticket numbers are immutable by construction (ADR 0006/0009); a prefix change would split the board's own history | Must-have (non-goal) |
| **R2** | **AXI conformance for the CLI** | |
| R2.1 | **Identifier round-trip** stays working — already implemented (KAN-285); M7 adds the **per-verb regression test** that currently doesn't exist | Must-have |
| R2.2 | **Structured errors on stdout** + a machine-readable code + never prompt non-interactively (AXI 6). Exit codes 0/1/2 are already correct — document and pin them | Must-have |
| R2.3 | **Pre-computed aggregates** on every list verb (AXI 4) | Must-have |
| R2.4 | **Content truncation** with an explicit size hint + `--full` (AXI 3) | Must-have |
| R2.5 | **`--fields`** to widen the minimal default schema on demand (AXI 2) | Must-have |
| R2.6 | **Content-first** bare invocation — live board state, not usage text (AXI 8) | Must-have |
| R2.7 | **Contextual disclosure** — `help[]` next-step command templates, values parameterised (AXI 9) | Must-have |
| R2.8 | **TOON output for nested payloads** (`--format toon`); TSV stays the list default (AXI 1, scoped) | Nice-to-have |
| R2.9 | **Ambient context** — a session-hook installer + the packaged skill (AXI 7) | Nice-to-have |
| R2.10 | Existing conformance (AXI 5 empty states, AXI 10 per-subcommand `--help`) is **regression-guarded by tests**, not re-implemented | Must-have |
| R2.11 | **Release discipline**: a user-visible CLI change bumps the version in the same PR, and `--version` **discriminates** a released build from a source run — so "which `kan` am I running?" is answerable | Must-have |
| **R3** | **MCP right-sizing** | |
| R3.1 | Measure the schema token cost of the 48-tool surface and of each alternative | Must-have |
| R3.2 | Record the chosen surface as an ADR and execute it | Nice-to-have |
| **R4** | **Constraints (non-functional)** | |
| R4.1 | **No API, schema or migration change** — M7 lives in the CLI/MCP/docs/deploy layers only | Must-have |
| R4.2 | Each AXI principle lands with a test that pins the **output contract**, so conformance can't silently regress | Must-have |
| R4.3 | Ships as demo-able vertical slices behind CI (M2–M6 cadence) | Must-have |
| R4.4 | The sister app (`kaya`) is **unblocked** when Wave 1 lands — `KAN-304` no longer waits on a naming decision | Must-have |

---

## Decisions log

- **Rebrand ships first (Wave 1), as its own epic.** It unblocks the sibling and means the AXI work
  writes its help/output text once, in the final name.
- **`pandan` + `kaya`, suite `kayatoast`.** Two ingredients that pair in one dish; the dish names the
  family. Rejected `lotus`/`lotus-notes`: an in-category trademark collision with HCL (ex-IBM) Notes,
  unwinnable SEO, and a connotation of exactly the clunky enterprise software this app isn't. Full
  reasoning in ADR 0018.
- **The CLI *is* renamed, despite the churn.** Initial instinct was to keep `kan` (muscle memory, an
  already-distributed standalone binary, every skill and `.mcp.json` referencing it). Overruled by the
  maintainer on the grounds that we are still the only user and still dogfooding — the cost is paid
  once now, versus permanently carrying a command named after the old brand. `pdn` ships as a short
  alias so the ergonomics don't regress.
- **`KANBAN_*` env vars keep working as a deprecated fallback.** Not for other users — for *us*, so
  the cutover can't brick the live `.mcp.json`, the CLI config, or CI mid-sweep. Removed in a later
  milestone once nothing reads them.
- **Ticket prefixes stay `KAN-` / `EPIC-`.** Ticket numbers are atomic, immutable and never reused by
  construction (per-table sequences + `server_default`). Renaming the prefix would leave `KAN-1…432`
  and `PAN-433…` on one board — worse than a legacy prefix. `KAN` is retconned as just "kanban".
- **The PAT mint prefix can safely change** (`kanban_pat_` → `pandan_pat_`) — **but not on its own.**
  This note originally claimed verification was "a hash lookup over the whole raw token with **no
  `startswith` guard** anywhere", and said it was "verified in the code, not assumed". **It was
  neither.** The guard is at [`backend/app/authz.py:85`](../../backend/app/authz.py) in `_resolve_pat`,
  a deliberate no-DB-round-trip-for-a-stray-bearer optimisation, and a bare prefix flip would have
  `401`'d every already-issued token. V40 shipped the prefix change *plus* a
  `LEGACY_TOKEN_PREFIXES` tuple honoured by that guard. Convention adopted as a result: **a claim
  about the code cites the `file:line` it inspected**, which forces the grep to be repo-wide rather
  than confined to the file you happened to open. Full correction in ADR 0018 §"The PAT prefix".
- **Fly cutover is create-migrate-destroy — and was therefore deferred.** Fly apps cannot be renamed
  and a GitHub OAuth App permits one callback URL, so it is a sequenced ops task with DNS in the
  middle, never something to bury in a code-sweep PR. Once V40 landed, the k8s homelab migration
  (**KAN-439**) made a Fly→Fly cutover a migration paid twice, so **KAN-424 was deferred behind it**
  and the origin stays `simple-kanban-jian.fly.dev`. The lesson worth keeping: isolating the ops step
  in its own slice is what made deferring it a one-line decision instead of an unpick.
- **TOON is adopted where it pays, not everywhere.** TSV list output is already key-free; TOON
  replaces JSON for *nested* payloads only. Rubric conformance is not a reason to make an efficient
  path less efficient.
- **AXI 5 and 10 are already satisfied — we add tests, not code.** Recording this so a future reader
  doesn't "implement" them. Same for the identifier round-trip (KAN-285) and the `1`/`2` exit-code
  split: shipped, unguarded, so M7 pins them with tests.
- **Audit the source, never an installed binary.** The first pass of the AXI audit produced two
  findings that were artefacts of a stale `~/.local/bin/kan`. Both had been fixed in `main` for ten
  days. The lesson is promoted to a requirement (R2.11) rather than a footnote, because an unbumped
  version is what made the staleness undetectable.
- **Release discipline is an ergonomics feature, not chores.** An agent (or a user) that cannot tell
  which build it is running cannot trust any other guarantee in this list — a documented output
  contract is worthless if the binary predates it. Hence KAN-435 leads EPIC-67.
- **MCP right-sizing is measured before it's decided.** The 48-tool surface may be correct as a
  documented fallback for shell-less agents; the slice's job is to price it and write the ADR, not to
  presume deletion.
- **No API/schema change in M7.** Every gap found is in the adapter layer. If a fix seems to need an
  endpoint, that's a signal it belongs in a later milestone, not scope creep here.

## Open questions (resolve during slicing)

- Aggregate line under `--json`: suppress it entirely, or add a `count`/summary object to the JSON
  payload? Leaning a JSON summary field (so parity holds) and no trailing line.
- `help[]` hint placement: trailing lines after the data, or a distinct `help[]`-prefixed block?
  Leaning the AXI-literal `help[]` prefix so it's unambiguously not data.
- Truncation default limit: a fixed character count vs. a token-aware estimate. Leaning a fixed
  character count (simple, predictable, and the hint reports the true total).
- Bare-invocation scope: the default board only, or a cross-board summary when no default is set?
  Leaning default-board, falling back to a board list when unset.
- Whether `pandan` or `pdn` is the name used in docs and skills (one canonical, the other an alias).
  Leaning `pandan` canonical in prose, `pdn` documented once as the alias.

---

## Shape — "Name & Sharpen the Tools"

Parts are vertical slices (mechanism + its surface), traced to the R's they satisfy.

| Part | Mechanism | Wave |
|------|-----------|:----:|
| **N1** | **Rebrand sweep.** Packages, UI, docs, board name, CLI console script (`pandan` + `pdn`), MCP server name, `PANDAN_*` config with `KANBAN_*` fallback, PAT mint prefix, skills. (R1.1–R1.4, R1.6) | 1 |
| **N2** | ⏸️ **Deferred. Deploy identity.** Was: new Fly app + secrets + cert/DNS cutover + destroy old; new OAuth App(s); ghcr image path; CI + keep-alive retarget. (R1.5) Now folded into the k8s homelab migration (**KAN-439**), with the in-place renames carved out as **KAN-437**. | 1 |
| **A0** | **Release discipline.** Version-bump-on-fix + a discriminating `--version` (embed the build's git describe/sha), so a stale build is detectable. (R2.11) | 2 |
| **A1** | **`--fields` + round-trip regression tests.** Widen the minimal schema on demand; pin the shipped `KAN-`/`EPIC-` ref handling with a per-verb test. (R2.1, R2.5) | 2 |
| **A2** | **Error contract.** Structured errors on stdout, documented exit codes, non-interactive guarantee. (R2.2) | 2 |
| **A3** | **Aggregates.** A summary line (or JSON summary field) on every list verb. (R2.3) | 2 |
| **A4** | **Truncation.** Size-hinted truncation of long text + `--full`. (R2.4) | 2 |
| **A5** | **Content-first + disclosure.** Bare invocation prints live state; `help[]` next-step templates on results. (R2.6, R2.7) | 2 |
| **A6** | **TOON formatter.** `--format toon` for nested payloads, sharing one formatter with `--json`. (R2.8) | 2 |
| **A7** | **Ambient context.** Session-hook installer + packaged skill. (R2.9) | 2 |
| **A8** | **MCP right-sizing.** Measure, decide, ADR, execute. (R3.1, R3.2) | 3 |

## Fit Check — R × Part

| Req | Requirement | Status | Part |
|-----|-------------|--------|------|
| R1.1 | Product/repo/packages/UI/docs renamed | Must | ✅ N1 |
| R1.2 | CLI + MCP renamed | Must | ✅ N1 |
| R1.3 | `PANDAN_*` config + `KANBAN_*` fallback | Must | ✅ N1 |
| R1.4 | Skills renamed | Must | ✅ N1 |
| R1.5 | Deploy identity moved | Must → **deferred** | ⏸️ N2 — deferred to KAN-439 (k8s homelab); in-place subset = KAN-437 |
| R1.6 | Ticket prefixes unchanged | Must | ✅ N1 (explicit non-goal) |
| R2.1 | Identifier round-trip (shipped; pin it) | Must | ✅ A1 |
| R2.2 | Structured errors + exit codes | Must | ✅ A2 |
| R2.3 | Pre-computed aggregates | Must | ✅ A3 |
| R2.4 | Truncation + `--full` | Must | ✅ A4 |
| R2.5 | `--fields` | Must | ✅ A1 |
| R2.6 | Content-first bare invocation | Must | ✅ A5 |
| R2.7 | Contextual disclosure | Must | ✅ A5 |
| R2.8 | TOON for nested payloads | Nice | ✅ A6 |
| R2.9 | Ambient context | Nice | ✅ A7 |
| R2.10 | AXI 5/10 regression-guarded | Must | ✅ A1–A5 (tests ride each slice) |
| R2.11 | Release discipline + discriminating `--version` | Must | ✅ A0 |
| R3.1 | Measure MCP schema cost | Must | ✅ A8 |
| R3.2 | ADR + execute chosen surface | Nice | ✅ A8 |
| R4.1 | No API/schema/migration change | Must | ✅ (all parts) |
| R4.2 | Output-contract tests per principle | Must | ✅ (per-slice acceptance) |
| R4.3 | Demo-able slices behind CI | Must | ✅ |
| R4.4 | Sister app unblocked | Must | ✅ N1 (frees `KAN-304`) |

**Notes:** No ❌. M7 is demo-complete after Waves 1–2; `A8` (MCP right-sizing) is a *Nice-to-have*
tail whose measurement half is a Must. Slicing follows in [SLICES.md](SLICES.md).

---

## Detail — affordances

M7 invents almost no new places; it changes what existing places are called and what they say.

- **Rebrand** touches every surface but adds none. The one *visible* new affordance is the `pdn`
  alias. The UI change is title/nav text and the favicon story, not layout.
- **AXI** changes the CLI's **output contract**, which is its real UI: a trailing aggregate line, a
  truncation hint, a `help[]` block, and a bare-command dashboard. No new verbs except what `--fields`
  / `--full` / `--format` add as flags.
- **Ambient context** adds one installer command and a hook file outside the app.
- **MCP right-sizing** may *remove* affordances; if so, the ADR records what moved to the CLI.

Slicing + per-slice acceptance in [SLICES.md](SLICES.md).
