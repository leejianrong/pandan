# ADR 0018 — Rebrand: `simple-kanban` → `pandan`, with `kaya` as the notes sibling

- **Status:** Accepted
- **Date:** 2026-07-31
- **Context source:** Cards **KAN-423** (rebrand sweep) + **KAN-424** (deploy identity), epic
  **EPIC-66**, shaped in [milestone-7](../milestone-7/SHAPING.md). Triggered by **KAN-304** — the
  human-owned kickoff of the notes sibling — which cannot start until the family is named. Builds on
  ADR 0006/0009 (immutable ticket numbers), ADR 0011 (GitHub OAuth callback constraint), ADR 0014
  (PAT format) and ADR 0004 (Fly + Neon hosting) without changing any of them.

## Context

`simple-kanban` was an honest name for one app. It becomes a liability the moment there are two,
because the sibling would have to be `simple-markdown` — and a `simple-X` scheme names a tech demo,
not a product pair. The sibling is imminent: [kaya-vision](../kaya-vision.md)
already commits both apps to a shared identity contract (one account, one PAT namespace spanning
both) and bidirectional cross-links. Whatever names exist when that shaping starts get baked into a
schema and a token format, so naming is a **prerequisite**, not a later polish pass.

Three constraints shaped the decision:

1. **The names must read as a family**, without either being subordinate. "simple-kanban and its
   markdown thing" is the failure mode.
2. **The rename cannot break the running system mid-flight.** The app is live on Fly + Neon with real
   PATs, a live `.mcp.json`, a GitHub OAuth App, a keep-alive workflow and a deployed board that is
   itself the project's task list. Several identifiers in that list are *not* renameable in place.
3. **Some identifiers must not change at all**, and the ADR has to say which, or a future contributor
   will "finish" the rename and damage data.

The maintainer proposed **pandan** / **pandan-kanban** for this app and **lotus** / **lotus-notes**
for the sibling. `pandan` was adopted; `lotus` was rejected on investigation.

## Decision

### The names

- **This app is `pandan`.** Not `pandan-kanban` — the suffix survives only where disambiguation is
  needed (repo description, tagline, a PyPI distribution name). It near-rhymes with "kanban", is
  unclaimed as a developer-tool name, is six characters, and pandan-green already sits beside the
  existing Zinc/Teal palette.
- **The notes sibling is `kaya`.** Pandan and kaya are the canonical Southeast Asian pairing —
  pandan-infused kaya jam — so the two names imply each other without either being the junior partner.
- **The suite, when it needs a name, is `kayatoast`.** The dish the two ingredients make. This
  resolves the `kaya` vs `kayatoast` question by using both: `kayatoast` names the *family*, `kaya`
  names the *app*, and neither carries a compound-noun product name.

**`lotus` / `lotus-notes` is rejected.** Lotus Notes is IBM's, now HCL's, groupware product — still
actively sold as HCL Notes/Domino — which puts the collision **in the same category** as the proposed
app (notes and collaboration), not at a safe distance like Lotus Cars or Lotus 1-2-3. Three
consequences, any one of which is disqualifying: a live in-category trademark conflict; unwinnable
search ranking against 35 years of enterprise documentation; and a connotation — Lotus Notes is the
standing punchline for clunky enterprise software — precisely inverted from what this project is.
Bare `lotus` sheds the "Notes" collision but keeps the HCL lineage and now also collides with a
well-known LLM/dataframe library in the same audience's namespace.

**Package-name reality, checked rather than assumed** (2026-07-31): `pandan`, `lotus` and `kaya` are
all taken on PyPI by abandoned single-release stubs (`pandan` 0.1; `lotus` 0.0.2; `kaya` 0.0.1.dev1),
and `pandan`/`lotus`/`kaya` are taken on npm. This is close to irrelevant: the **console-script** name
is unaffected by PyPI ownership, and only the *distribution* name would need a suffix
(`pandan-cli` / `kaya-notes`, both free). PEP 541 reclamation of the dead stubs is possible but slow
and not on the critical path.

### What gets renamed

Mechanically, in **V40**: package and directory names and import roots (`pandan_cli`, `pandan_client`,
`pandan_mcp`); distribution names; the UI title, nav and landing copy; `README.md`, `CLAUDE.md` and
`docs/**`; the Roadmap board's own name; and the skills (`simple-kanban` → `pandan`,
`project-manager-kanban` → `pandan-pm`).

> **Amendment: V40 shipped as two sequential PRs, not one.** This ADR originally argued for a single
> PR on the grounds that "a half-renamed repo is worse to review than a large mechanical one". In
> practice the slice split cleanly along a seam that argument missed: a **structural** PR (directory /
> package / import-root / distribution-name moves, plus every path that references them) is verifiable
> almost entirely *by CI* — if the `dorny/paths-filter` globs, the `uv.lock`s, the Dockerfile `COPY`
> and the release workflows are right, the jobs run and pass — whereas a **semantic** PR (command
> names, env vars, the PAT prefix, UI copy, prose) can only be verified *by reading*. Mixing them
> would have buried the second kind in ~700 lines of the first. Splitting also surfaced the
> `startswith` bug below before any user-visible change shipped. The "don't leave it half-renamed"
> concern was handled by landing them back-to-back, with the structural PR carrying **no** user-visible
> string change at all. Prefer this split next time a rename is this large.

Three of those deserve their own note:

- **The CLI is renamed: `kan` → `pandan`, with `pdn` as a short alias** (a second `[project.scripts]`
  entry on the same `main`). The initial recommendation was to *keep* `kan` — muscle memory, an
  already-distributed standalone binary, and every skill and `.mcp.json` referencing it — and it was
  overruled deliberately: the project is still single-user and still dogfooding, so the churn is paid
  once now instead of permanently shipping a command named after the retired brand. `pdn` exists so
  keystroke ergonomics don't regress.

  > **Amendment (2026-07-31): the `pdn` alias is WITHDRAWN.** It was never deliverable on the install
  > path this project's own docs lead with. `[project.scripts]` entries are generated by a packaging
  > installer, but the release is a PyInstaller `--onefile` build that produces exactly **one**
  > executable per platform — so `pdn` materialised only for `uv tool install` users and never for
  > anyone who downloaded the release asset (reported as **KAN-442**, verified at
  > `pandan-cli/pyproject.toml` and `.github/workflows/release-cli.yml`'s `--onefile --name` step).
  >
  > Three options were weighed: document the gap and tell people to symlink; have the release workflow
  > lay down both names; or drop the alias. **Dropping it was chosen** — a promised command that half
  > the install paths don't provide is worse than no promise, and "run one `ln -s` if you want a short
  > name" is honest, discoverable, and costs the project nothing to maintain. The second
  > `[project.scripts]` entry is removed accordingly, so the code and this record agree.
  >
  > **Nothing is taken away from anyone in practice.** A short name remains one symlink away
  > (`ln -sf ~/.local/bin/pandan ~/.local/bin/pdn`), which is what `pandan-cli/README.md` now
  > documents, and it works identically on both install paths — which the alias never did. The same
  > trick is what keeps the retired `kan` name working for muscle memory. The lesson generalises and is
  > worth carrying into future packaging decisions: **a console-script alias is an
  > install-method-dependent feature; verify it on the path your docs lead with, not the one your tests
  > use.**
- **Config becomes `PANDAN_API_URL` / `PANDAN_TOKEN` / `PANDAN_BOARD_ID`, and the `KANBAN_*` names
  remain a deprecated fallback** — read second, with a one-line notice on stderr. Not for third-party
  compatibility (there are none): for *us*, so the cutover cannot brick the live `.mcp.json`, the CLI
  config, or CI while the sweep is in flight. They are deleted in a later milestone once nothing reads
  them. The config file's own keys (`api_url`/`token`/`board_id`) were already brand-free and are
  unchanged; the config **directory** moves to `~/.config/pandan/`, migrating an existing file.
- **The MCP server name changes, which changes tool names.** The `mcpServers` key is what MCP tool
  names are namespaced with, so `mcp__kanban__*` becomes `mcp__pandan__*`. Anything referencing those
  identifiers by name — skills, prompts, allowlists in `settings.json` — must be updated in the same
  change.

### What is deliberately NOT renamed

- **The `KAN-` and `EPIC-` ticket prefixes.** Ticket numbers are generated by per-table Postgres
  `SEQUENCE`s via a column `server_default` — atomic at INSERT, **immutable, never reused** (ADR 0006,
  ADR 0009). There is no correct way to renumber history, so a prefix change would leave `KAN-1…432`
  beside `PAN-433…` on a board whose entire purpose is being the project's own record. A legacy prefix
  is strictly better than a split one. `KAN` is retconned as simply "kanban". A comment at the
  sequence definitions ([`backend/app/models.py`](../../backend/app/models.py), module docstring +
  both `server_default`s) and at `TOKEN_PREFIX` records this so nobody completes the rename later.
- **The config file's generic keys** — already brand-neutral. (The config file's *table* moved
  `[kan]` → `[pandan]` and its *directory* `~/.config/kan/` → `~/.config/pandan/`, migrating an
  existing file; a legacy `[kan]` table is still read.)
- **Session, wire and client-storage identifiers.** Each of these is a *live compatibility surface*
  where a rename costs something real and buys nothing:

  | Identifier | Where | Cost of renaming |
  |---|---|---|
  | `kanbanauth` | session cookie name ([`backend/app/users.py`](../../backend/app/users.py)) | logs every signed-in user out |
  | `X-Kanban-Event` | outbound webhook header ([`backend/app/outbound.py`](../../backend/app/outbound.py)) | breaks any configured consumer, silently |
  | `kanban.access` / `kanban.ratelimit` / `kanban.health` | logger names ([`backend/app/observability.py`](../../backend/app/observability.py) et al.) | invalidates `LOG_LEVEL` docs and any log-based alerting |
  | `kanban.theme`, `kanban.activeBoardId` | browser `localStorage` keys | resets every user's theme + active board |
  | `kanban:kanban@…/kanban` | local Postgres role/db (`docker-compose.yml`, `Makefile`) | breaks every existing dev volume and worktree DB |

- **The CI job *display* names** (`Kanban client (lint + tests)`, `CLI (lint + tests)`). Branch
  protection matches required status checks on the job name string, so renaming them makes the
  required checks unresolvable and blocks every PR until the protection rule is edited in the same
  breath. That makes it **ops work, sequenced with KAN-437** — not a code change.
- **The `KanbanClient` class name was renamed** to `PandanClient` (with `KanbanApiError` →
  `PandanApiError`); noted here only because it is the one *public symbol* rename, and it is safe
  precisely because the only consumers are in-repo (the CLI and the MCP server).

### The PAT prefix: changed, and safe — but only because of an accepted-prefix tuple

`TOKEN_PREFIX` in [`backend/app/tokens.py`](../../backend/app/tokens.py) becomes `pandan_pat_`, and a
sibling `LEGACY_TOKEN_PREFIXES = ("kanban_pat_",)` is added. The resolver's fast-path guard tests the
**union** of the two, so tokens minted before the rename keep authenticating indefinitely while newly
minted ones carry the new, greppable marker — no forced rotation, no migration. (Rotating
`AUTH_SECRET` *would* invalidate them, per §Configuration; the rebrand does not touch it.)

**Correction — an earlier revision of this ADR got this wrong, and the error is worth recording.** It
claimed the prefix was used "only at mint time and for the non-secret display hint", and that
verification was "an HMAC hash lookup over the whole raw token with **no `startswith` guard anywhere
in the resolver**". That was false. The guard exists, at
[`backend/app/authz.py:85`](../../backend/app/authz.py) in `_resolve_pat`:

```python
    # Fast-path skip: only strings minted by us can match, so a stray bearer never
    # triggers a DB round-trip.
    if not raw.startswith(TOKEN_PREFIX):
        return None
```

It is a deliberate load-shedding measure — a stray `Authorization` header must not cost a DB
round-trip — but it made the prefix load-bearing at *verification* time, not just at mint time. A
bare `TOKEN_PREFIX` flip would therefore have returned `401` for **every already-issued
`kanban_pat_…` token** before the hash lookup ran: precisely the forced rotation this section
promised to avoid. The fix is the accepted-prefix tuple above, pinned by an integration test that
seeds a legacy-shaped token through `hash_token` and asserts it still resolves, plus one asserting an
unrecognised prefix still short-circuits before any hash lookup (so the load-shedding intent doesn't
silently regress).

Two process lessons, adopted going forward:

- **"Verified by inspection" must cite the `file:line` it inspected.** The original claim was reached
  by grepping `kanban_pat` and `TOKEN_PREFIX` *within `tokens.py` only*, so a guard in another module
  that imported the constant was invisible. A citation forces the grep to be repo-wide.
- **An ADR asserting a property of the code is a claim to be checked, not a fact.** This is the
  inverse of the usual drift (docs lagging code): here a doc asserted something the code never did.

### The deploy identity: DEFERRED, not executed (V41 / KAN-424)

Two hosting facts mean the deployed identity cannot be renamed by editing config: **a Fly app cannot
be renamed**, and **a GitHub OAuth App permits exactly one callback URL** (ADR 0011 — which is already
why dev and prod use separate apps). The original plan was a sequenced create-migrate-destroy ops
slice: stand up a new Fly app on the same Neon database, create a new prod OAuth App for the new
origin, verify on the new `*.fly.dev` hostname, move the cert/DNS alongside the still-open Cloudflare
setup (`KAN-305`), retarget `fly.toml` + the deploy and keep-alive workflows, and only then destroy
`simple-kanban-jian`.

**That slice is deferred.** The project is moving to a **self-hosted k8s homelab** (`KAN-439`), which
replaces the Fly deployment outright. Doing a Fly→Fly cutover first would pay the same migration
twice — two new OAuth Apps, two DNS cuts, two verification passes — for an interim hostname with a
short remaining life. So `KAN-424` is deferred and marked `blocked-by` `KAN-439`; the identity rename
happens **once**, as part of standing up the homelab.

Consequently, and on purpose:

- **The origin stays `simple-kanban-jian.fly.dev`**, on the Fly app `simple-kanban-jian`, with the
  **existing GitHub OAuth App** and the **existing `AUTH_SECRET`** (rotating it would invalidate every
  PAT and session for no benefit). No URL in the docs or the SPA is rewritten.
- **The renames that *can* happen in place are carved out as `KAN-437`**: the GitHub repository name,
  the OAuth App's display name, and the ghcr image path
  (`ghcr.io/…/simple-kanban-mcp` → `…/pandan-mcp`). Those are cheap and reversible, but they still
  move URLs (repo, docs site, image pull), so they are their own change — which is why the repo URL,
  the `github.io/simple-kanban/` docs URL and the ghcr path still read `simple-kanban` after V40.
- **Nothing blocks on this.** V40 gave the product, CLI, packages and docs their new name; the
  hostname is the one place the old name remains user-visible, and it is a label on
  infrastructure that is itself scheduled for replacement.

## Consequences

- **Positive:** the family is nameable, so `KAN-304` (the `kaya` kickoff) unblocks the moment V40
  lands, and the sibling's identity contract can be designed against final names. The two apps imply
  each other, and the suite name comes free. The mechanical sweep also forces a pass over every
  brand-adjacent doc, which is where drift accumulates. Landing the rebrand *before* M7's AXI work
  means the CLI's rewritten help and output text is authored once.
- **Neutral:** ~52 files carry the brand string; the sweep is large but mechanical, and the grep for
  the old strings is the review's last step. The
  `KANBAN_*` fallback is dead weight carried on purpose, with a scheduled removal. (`pdn` was
  originally listed here as "two console scripts to keep working" — it is now withdrawn, see the
  amendment above, so there is exactly one.)
- **Negative / deferred:** the board permanently mixes a `KAN-` prefix with a `pandan` product name —
  accepted, and documented above as the lesser evil. **The deployed hostname keeps the old name
  indefinitely** (`simple-kanban-jian.fly.dev`) because the Fly cutover is deferred behind the k8s
  migration (`KAN-439`); a user reaching the app sees `pandan` everywhere except the URL bar, which is
  the ugliest surviving seam of this rebrand and is accepted knowingly. The distribution names on PyPI/npm need a suffix
  (`pandan-cli`, `kaya-notes`) until or unless the abandoned stubs are reclaimed. Any external
  reference to `mcp__kanban__*` tool names or the `kan` binary — including anything outside this repo
  — breaks at V40; acceptable while we are the only user, and the reason this ADR records the
  single-user justification explicitly.
