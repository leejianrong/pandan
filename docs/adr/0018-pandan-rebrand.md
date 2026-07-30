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
not a product pair. The sibling is imminent: [simple-markdown-vision](../simple-markdown-vision.md)
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

Mechanically, in **V40** (one PR — a half-renamed repo is worse to review than a large mechanical one):
package and directory names and import roots (`pandan_cli`, `pandan_client`, `pandan_mcp`); the UI
title, nav and landing copy; `README.md`, `CLAUDE.md` and `docs/**`; the Roadmap board's own name; and
the skills (`simple-kanban` → `pandan`, `project-manager-kanban` → `pandan-pm`).

Three of those deserve their own note:

- **The CLI is renamed: `kan` → `pandan`, with `pdn` as a short alias** (a second `[project.scripts]`
  entry on the same `main`). The initial recommendation was to *keep* `kan` — muscle memory, an
  already-distributed standalone binary, and every skill and `.mcp.json` referencing it — and it was
  overruled deliberately: the project is still single-user and still dogfooding, so the churn is paid
  once now instead of permanently shipping a command named after the retired brand. `pdn` exists so
  keystroke ergonomics don't regress.
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
  sequence definitions records this so nobody completes the rename later.
- **The config file's generic keys** — already brand-neutral.

### The PAT prefix: changed, and safe

`TOKEN_PREFIX` in [`backend/app/tokens.py`](../../backend/app/tokens.py) becomes `pandan_pat_`.
Verified by inspection rather than assumed: the prefix is used **only** at mint time
(`TOKEN_PREFIX + secrets.token_urlsafe(32)`) and to derive the non-secret display hint. Verification is
an HMAC hash lookup over the **whole raw token** with no `startswith` guard anywhere in the resolver.
So existing `kanban_pat_…` tokens keep authenticating indefinitely while newly minted ones carry the
new, greppable marker — no forced rotation, no migration. (Rotating `AUTH_SECRET` would invalidate
them, per §Configuration; the rebrand does not touch it.)

### The deploy identity: create-migrate-destroy (V41)

Two hosting facts force a sequenced ops slice rather than a config edit: **a Fly app cannot be
renamed**, and **a GitHub OAuth App permits exactly one callback URL** (ADR 0011 — which is already
why dev and prod use separate apps). So: create the new Fly app and set every secret on it (same Neon
database — this is not a data move); create a new prod OAuth App for the new origin; deploy and verify
on the new `*.fly.dev` hostname; move the cert/DNS, coordinating with the still-open Cloudflare setup
(`KAN-305`); retarget `fly.toml`, the deploy and keep-alive workflows, and the ghcr MCP image path;
and only then destroy `simple-kanban-jian`. Every step before the DNS cut is reversible because the
old app stays up.

## Consequences

- **Positive:** the family is nameable, so `KAN-304` (the `kaya` kickoff) unblocks the moment V40
  lands, and the sibling's identity contract can be designed against final names. The two apps imply
  each other, and the suite name comes free. The mechanical sweep also forces a pass over every
  brand-adjacent doc, which is where drift accumulates. Landing the rebrand *before* M7's AXI work
  means the CLI's rewritten help and output text is authored once.
- **Neutral:** ~52 files carry the brand string; the sweep is large but mechanical, and the grep for
  the old strings is the review's last step. `pdn` means two console scripts to keep working. The
  `KANBAN_*` fallback is dead weight carried on purpose, with a scheduled removal.
- **Negative / deferred:** the board permanently mixes a `KAN-` prefix with a `pandan` product name —
  accepted, and documented above as the lesser evil. The Fly cutover has a genuine window where DNS
  and the OAuth callback must land together; it is isolated in its own slice for that reason, and must
  not start until V40 is deployed. The distribution names on PyPI/npm need a suffix
  (`pandan-cli`, `kaya-notes`) until or unless the abandoned stubs are reclaimed. Any external
  reference to `mcp__kanban__*` tool names or the `kan` binary — including anything outside this repo
  — breaks at V40; acceptable while we are the only user, and the reason this ADR records the
  single-user justification explicitly.
