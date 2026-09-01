---
shaping: true
---

# Milestone 9 — Shaping ("Teams")

Traces to [EPIC-125](https://simple-kanban-jian.fly.dev) and
[issue #322](https://github.com/leejianrong/pandan/issues/322). Unlike M2–M8, the design work here was
already done as a standalone ADR before this shaping pass existed — kaya's 2026-09-01 roadmap session
filed the issue as an ADR-level question ("before any code"), and [ADR 0021](../adr/0021-organization-team-tier.md)
answered it. **This document does not re-derive that design; it translates an already-accepted decision
into requirements and slices.** Where M8's SHAPING.md spends most of its length on *why*, this one
mostly points at the ADR and spends its length on *order*.

## Why now

kaya's own KAN-1048 spike (kaya board 18) has been blocked since 2026-09-01 on an ADR-level answer to
"what sits above a user." ADR 0021 gave that answer. The gap between an accepted ADR and a usable API is
this milestone — kaya cannot actually call a `team` endpoint until one exists.

## Requirements (R)

- **R1.** A user can create a team, see the teams they belong to, and manage its membership (add/
  remove/change a member's role) without touching another user's boards.
- **R2.** A board can optionally belong to one team. Creating or updating a board lets its creator (a
  member of that team) attach it; a board with no team behaves exactly as every board does today.
- **R3.** Team membership grants a **default** board access — reusing the existing `viewer`/`editor`/
  `owner` role vocabulary, per ADR 0021 §Decision — that an explicit per-board `BoardMember` row still
  overrides. Removing someone from a team removes only the default; explicit shares are untouched.
- **R4.** Nothing about a PAT or `GET /api/v1/me` changes. A token's reachable boards grow automatically
  through the authorization layer, with zero change to token issuance, scope, or the identity endpoint
  kaya depends on.
- **R5.** Every existing board keeps working unmodified — `team_id IS NULL` is indistinguishable from
  today's behaviour, so the migration needs no judgment calls about existing data (unlike M8's board-key
  backfill, there is nothing to derive or backfill here; every row just gets `NULL`).
- **R6.** The CLI and MCP surfaces gain team verbs/tools only after the API chain (R1–R3) is stable —
  kaya and the CLI are downstream of the same authorization change, not a separate design.

## Decisions log

This milestone's decisions are ADR 0021's, not new ones. Restated only where it affects slicing:

- **D1 (= ADR 0021 §Decision, "Team is the top-level tenant").** No `organization` table this
  milestone. If that need ever becomes real, it is a later milestone that adds `team.org_id`, not a
  redesign of anything built here.
- **D2 (= ADR 0021 §"Interaction with the existing board-role model").** `_effective_access` checks
  owner → explicit `BoardMember` → team default → none, in that order. This ordering is what makes an
  explicit share an override rather than a conflict, and it is the one piece of application logic every
  slice in Part B below has to get right — it is worth its own slice (V68) rather than folding it into
  the schema slice, so it can be tested in isolation against the full 401/403/200 matrix.
- **D3 (= ADR 0021 §"New surface").** A board belongs to **at most one** team (no join table). Upgrading
  to many-to-many later needs no migration of existing data — a nullable FK becomes a join table without
  touching the column's existing meaning — so this milestone doesn't build for a need nobody has asked
  for yet.
- **D4 — new for this milestone: CLI/MCP is its own gated slice, not bundled with the API.** ADR 0019
  froze the MCP surface at 49 tools; adding `list_teams`/`create_team`/etc. is an ADR *amendment*, not a
  fixture edit (`mcp/tests/test_schema.py` pins the count). V69 below is scoped to include running
  `mcp/scripts/measure_tool_schema_tokens.py` before/after and stating the token delta the way V51
  (ADR 0020) did for `board.key` (+215 tokens) — this milestone does not get to skip that measurement
  just because the tools are additive.
- **D5 — new for this milestone: the SPA slice ships last and can slip.** kaya is the consumer actually
  blocked; it talks to `/api/v1` directly, never the SPA. A human self-hoster wanting a Teams *screen* is
  real but not blocking anything the way kaya is, so V70 is ordered after — and is the one slice in this
  milestone that could ship in a later pass without re-opening anything upstream of it.

## Shape

One epic, one part, run as a strict chain through V68 (schema → membership → board-linking →
authorization), then two independent tails (CLI/MCP, SPA) that can ship in either order once the chain
lands. This mirrors M8 Part A's "nothing is visible until everything resolves" instinct for the chain,
but the membership CRUD in V65–V66 is itself demoable — unlike M8's ref-rendering chain, there's no
"invisible until V54" phase here.

## Out of scope for M9

Named explicitly in [ADR 0021 §Alternatives rejected / §Open](../adr/0021-organization-team-tier.md) and
not reopened here:

- An `organization` tier above `team`.
- Team-scoped board-key uniqueness (keys stay unique per owner).
- Notification fan-out to team members beyond the board owner.
- Many-to-many board↔team.
- Growing `GET /api/v1/me` to carry team memberships.

Next: [Slices](SLICES.md).
