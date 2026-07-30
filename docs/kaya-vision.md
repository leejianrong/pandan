# kaya — vision (sister app to pandan)

> **Status: recorded intent, not started.** This is a *separate* product in its own git repo, not a
> pandan milestone. Kickoff is a human task (board card **KAN-304**), **unblocked** now that V40 has
> named the family (ADR 0018). This doc captures the vision, the ethos, and — most importantly — the
> **integration contract** with pandan, since that contract shapes both apps and should be settled
> before either commits to a schema.
>
> **Naming.** This app was called **`simple-markdown`** while it was an unnamed sibling of
> `simple-kanban`; that pairing named a tech demo, not a product pair, which is what triggered
> [ADR 0018](adr/0018-pandan-rebrand.md). The board app is now **`pandan`**, this app is **`kaya`**
> (pandan-infused kaya jam — the two names imply each other without either being the junior partner),
> and the suite, when it needs a name, is **`kayatoast`**. The old `simple-markdown` name is kept below
> only where it records history. The PyPI distribution name would be `kaya-notes` — bare `kaya` is
> taken by an abandoned stub, which matters only for a *distribution* name, not the CLI command
> (checked 2026-07-31; see ADR 0018 §Package-name reality).

## The one-liner

A cloud-hosted, Obsidian-like **markdown notes** app — API-first, agent-drivable — that is the
**docs half** of the `kayatoast` suite. Where pandan tracks *work*, kaya holds the *knowledge*:
specs, notes, runbooks, meeting notes — cross-linked to the board.

## Why it exists (strategic fit)

- **It's the proven pairing.** Jira has Confluence; Linear has Documents. A docs sibling to a tracker
  is a well-trodden, high-value combination.
- **It answers a gap we deliberately declined.** pandan chose *not* to add file attachments /
  rich documents (needs storage infra, off the "simple" line — see the M5 competitive delta and the
  M6 shaping). A *sibling* app answers "where does the rich content live?" without growing the board
  into Notion. Each app stays simple; the **integration** is the combined value.
- **It's agent-native, like its sibling.** An agent that drives the board with a PAT should, with the
  same identity, read and write the notes — maintaining a card's spec doc *as it works the card*.

## Ethos carried over from pandan

The point of a sibling (not a fork) is a shared philosophy. kaya inherits:

- **Cloud-only, last-write-wins, no real-time** (pandan ADR 0007). This is a *deliberate*
  simplification vs. Obsidian's local-first files and Notion's realtime CRDT collaboration — and it
  keeps the two apps consistent. A note is server-authoritative; concurrent edits are LWW, same as a
  card.
- **API-first** (ADR 0005): every UI action is a plain REST call; the SPA is a thin client.
- **MCP + CLI parity**: a `kaya` CLI + an MCP server, mirroring `pandan` + the pandan MCP, so agents
  drive notes exactly as they drive the board. Follow pandan's own console-script pattern — a full
  name plus a short alias (`pandan`/`pdn`) — rather than inventing an abbreviation like `smd`.
- **Single deployable artifact, one origin** (ADR 0003): FastAPI serves the built SPA; same
  single-origin CSP story.
- **Same stack**: FastAPI + SQLAlchemy (sync) + Postgres + Alembic; Svelte 5 runes SPA; `uv` + `npm`;
  the same CI shape (lint + unit + integration + build + e2e). Hosting: pandan runs on Fly.io + Neon
  today but is moving to a **self-hosted k8s homelab** (`KAN-439`) — settle where kaya lives against
  that target, not the current one.

## The integration contract (settle this FIRST)

This is the part that constrains both apps, so design it before schemas.

1. **Shared identity.** One account, one set of PATs, spanning both apps. Options, cheapest-first:
   - **Shared `AUTH_SECRET` + session/PAT format** — kaya validates the *same* cookie
     session and `pandan_pat_…` tokens pandan issues (a PAT resolves to the same `User`).
     Simplest; couples the two on a shared secret + a shared or replicated `user` table.
     Note pandan also still accepts pre-rebrand `kanban_pat_…` tokens via an accepted-prefix
     tuple, so **match on a hash lookup over the whole token, never on a prefix** — that exact
     assumption is what ADR 0018 had to correct.
   - **A tiny shared auth service / identity table** both apps read. Cleaner long-term; more infra.
   - Decision deferred to the shaping; **shared-secret PAT validation is the MVP lean.**
2. **Cross-linking, both directions.**
   - **Note → card:** `[[KAN-123]]` wikilinks in note text resolve to a board card (title, column,
     link out). The Obsidian `[[wikilink]]` idiom, spanning apps. Note the ticket prefix stays `KAN-`
     even under the pandan name — it comes from an immutable Postgres sequence (ADR 0018 §"What is
     deliberately NOT renamed"), so **parse `KAN-`/`EPIC-`, not `PAN-`.**
   - **Card → note:** a card's existing **work-links** (M4) already model "this card links to a URL";
     a note is just a first-class link target. Optionally a typed `spec` link.
   - **Embeds:** a note can embed a *live* board view (a saved-view query rendered read-only), so a
     project spec shows its own task list.
3. **Discovery.** Each app links to the other in its nav when the sibling origin is configured
   (an env var — no hard dependency; either runs standalone). Mirror pandan's env-var convention:
   a per-app prefix (`KAYA_*` / `PANDAN_*`), each key resolved independently.

## Shape sketch (for the eventual build-plan-product pass)

- **Data:** `note` (id, owner_id, title, `body` markdown text, folder/path, updated_at) + a
  `note_link` edge table for resolved `[[…]]` references (to notes and to `KAN-`/`EPIC-` tickets),
  enabling a backlinks panel and an eventual graph view. Text lives in Postgres — **markdown is just
  text**, no storage infra needed for the core.
- **Editor:** **CodeMirror 6** (what Obsidian uses) — live-preview markdown, wikilink autocomplete.
  **Do not hand-roll an editor.**
- **Surfaces:** a file/folder tree, the editor, a backlinks panel, full-text search (Postgres FTS,
  exactly like pandan V15), and a read-only "embed a board view" block.

## Deliberate non-goals (hold the line, like the sibling does)

- **No local-first sync / CRDTs.** Cloud-only LWW. Local-first is a different, much harder product.
- **No real-time multiplayer.** Poll/refresh, LWW (ADR 0007 parity).
- **Attachments are deferred.** Core is text-only markdown in Postgres. When images/files are truly
  needed, reach for object storage (Cloudflare R2) — *not* before, and *not* in the MVP.
- **No plugin ecosystem.** Obsidian's plugins are its moat and its complexity; kaya stays a
  focused core.

## First steps (when kicked off — KAN-304)

1. Decide the **identity contract** (shared-secret PAT validation vs. shared auth service).
2. New repo `kaya`; run **build-plan-product** → shaping, mirroring how pandan was
   planned (REQS → FRAME → PRD/CONTEXT → SHAPING → BREADBOARD → slices).
3. Thin vertical slice first: create/read/edit a note via API + a minimal SPA editor; then FTS; then
   `[[KAN-x]]` resolution against pandan; then the CLI + MCP.
