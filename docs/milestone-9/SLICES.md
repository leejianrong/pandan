---
shaping: true
---

# Milestone 9 — Slices ("Teams")

Vertical increments of the [M9 shape](SHAPING.md), turning [ADR 0021](../adr/0021-organization-team-tier.md)
into a working `/api/v1/teams`. Each ends in **observable behaviour** and ships as its own PR behind CI,
matching the M1–M8 cadence.

Numbering continues the **global V-series** (M8 was V51–V64). **M9 is V65–V70.**

The whole milestone traces to one epic and one issue:

| Epic | Issue | Theme |
|---|---|---|
| [EPIC-138](https://simple-kanban-jian.fly.dev) | [#322](https://github.com/leejianrong/pandan/issues/322) | Team as the tenant tier above a user |

## Order of build

**V65–V68 run as a strict chain** — schema, then membership, then board-linking, then the authorization
rung that actually makes team membership *mean* something. Each is individually demoable (unlike M8 Part
A's ref-rendering chain, nothing here is invisible until the last slice), but each genuinely needs the
one before it: you cannot link a board to a team before teams exist, and you cannot test the access
default before a board can be linked. The chain is recorded on the board itself (`dep list`), not just
here.

**V65 carries the migration and lands alone**, per the standing deploy rule (R4.4) — it is this
milestone's only schema change. V66–V70 are pure application code against that schema.

**V69 and V70 both depend only on V68**, not on each other, and can ship in either order — or V70 can
slip to a later pass entirely (SHAPING D5). V69 is ordered first because it is what actually unblocks
kaya, which talks to `/api/v1` directly and never touches the SPA.

| Slice | What | Card | Pts | Ends in (demo) |
|-------|------|------|:---:|----------------|
| **V65 · Team schema + minimal CRUD** | `team`/`team_member` tables, `board.team_id` 🗄️ | KAN-1054 | 5 | Create a team via the API; you're listed as its owner |
| **V66 · Team membership management** | add/remove/re-role a member, rename/delete a team | KAN-1055 | 3 | An owner adds a teammate as `editor`, then removes them; renaming doesn't touch the team's boards |
| **V67 · Board↔team linking** | optional `team_id` on board create/update | KAN-1056 | 2 | Create a board under a team; `GET` shows its `team_id` |
| **V68 · Team-default board access** | the `_effective_access` rung | KAN-1057 | 5 | A team `editor` with no explicit share can edit a team board; leaving the team removes that default, explicit shares untouched |
| **V69 · CLI + MCP team surface** | `pandan team …`, `list_teams`/`create_team`/… | KAN-1058 | 5 | `pandan team create "Platform"` and `pandan board create --team ENG` work end to end |
| **V70 · Teams SPA view** | a Teams screen, a Team picker on board settings | KAN-1059 | 8 | A human creates a team and adds a board to it from the browser, no CLI needed |

**28 points total.** V69 carries an extra precondition beyond writing the code: ADR 0019 froze the MCP
surface at 49 tools, so adding team tools is an ADR *amendment* (`mcp/tests/test_schema.py` pins the
count) — run `mcp/scripts/measure_tool_schema_tokens.py` before/after and record the delta the way V51
did (+215 tokens for `board.key`), rather than treating "it's additive" as a free pass past the freeze.

## What each slice does not do

Carried over from [ADR 0021 §Alternatives rejected / §Open](../adr/0021-organization-team-tier.md) and
[SHAPING's Out of scope](SHAPING.md#out-of-scope-for-m9) — none of these are quietly reopened by a slice
above:

- No `organization` tier above `team`.
- No team-scoped key uniqueness — `board.key` stays unique per owner.
- No notification fan-out to team members; a board event still reaches only `board.owner_id`.
- No many-to-many board↔team — a board belongs to at most one team.
- `GET /api/v1/me` is untouched by every slice in this milestone.

## Testing notes

- **V65** is additive-only: every existing board test should pass unmodified with `team_id IS NULL`
  meaning exactly what it means today. No backfill logic to test, unlike M8's board-key migration —
  every row simply gets `NULL`.
- **V68 is the slice that needs the full matrix**, not V65: owner / explicit-BoardMember-override /
  team-default / neither, crossed with viewer/editor/owner at each layer, plus the "removed from team
  loses the default but keeps an explicit share" case named directly in ADR 0021. Write this as its own
  parametrized suite rather than folding it into the existing board-authz tests, so a future change to
  `_effective_access` can't silently drop a case.
- **V69**'s CLI/MCP parity test (`pandan-cli/tests/test_parity.py`, per ADR 0019/KAN-502) should gain the
  team verbs on both sides in the same PR — this repo already pins CLI↔MCP parity mechanically, and there
  is no reason team tools should be the first exception.

Next: pick up V65.
