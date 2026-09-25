# ADR 0023 — Rename the Team tier to Workspace

- **Status:** Accepted
- **Date:** 2026-09-25
- **Context source:** Maintainer planning session on CLI/MCP/agent authentication (2026-09-25); ADR
  0021 (organization/team tier); Milestone 9 (`docs/milestone-9/SLICES.md`). Tracked as
  [EPIC-280](https://simple-kanban-jian.fly.dev) on the Pandan Roadmap board (KAN-1721..1725).

## Context

M9 shipped V65–V69: `team`/`team_member` tables, a nullable `board.team_id`, membership roles
(viewer/editor/owner), and the CLI/MCP surface (`pandan team ...`, 5 MCP tools). Only **V70 — the
Teams SPA view** remains unbuilt.

While planning the next round of auth work (CLI/MCP device-login, and a "Workspaces" grouping
feature requested independently), it became clear the requested "Workspaces" feature **is** the Team
tier — a named container that groups several boards and can hold more than one user — not a new,
additional concept. "Team" also undersells the shape: a solo user with ten personal boards wants to
group them too, with no second member in sight, which reads oddly as a "team" of one.

Renaming now, before V70 exists, avoids shipping a Teams UI and relabeling it a release later.

## Decision

**Rename the tier from `Team` to `Workspace` end to end.** No new entity, no schema redesign — same
membership model (viewer/editor/owner), same board-linking shape, same authorization rules. Purely a
rename, landed as one slice per surface so each stays independently revertable:

- **Schema:** `team` → `workspace`, `team_member` → `workspace_member`, `board.team_id` →
  `board.workspace_id`. Table/column renames via `ALTER TABLE ... RENAME`, not a drop-and-recreate, so
  existing rows and FKs survive untouched.
- **CLI:** `pandan team {list,get,create,update,delete,member add/rm/list/update-role}` becomes
  `pandan workspace {...}` with the same verbs. No deprecated-alias period — Teams shipped days ago
  with no SPA exposure, so the blast radius of a clean rename is small (mirrors this ADR's own
  reasoning for not treating the MCP rename as a breaking-change deprecation cycle).
- **MCP:** the 5 team tools (`list_teams`/`create_team`/`get_team`/`update_team`/`delete_team`) become
  `list_workspaces`/`create_workspace`/`get_workspace`/`update_workspace`/`delete_workspace`. This is a
  **rename** to the ADR 0019-frozen surface, not an addition — recorded as an ADR 0019 amendment
  alongside this one, on the same reasoning: pre-GA, no external client has scripted against the old
  names yet.
- **Docs:** ADR 0021 is retitled/updated in place (it documents the tier's design, which is unchanged;
  only the name changes) rather than superseded. CLAUDE.md's M9 section and every `pandan team` mention
  are updated in the same PR that lands the rename.
- **V70 is built directly as the Workspace SPA view** — membership management + the board list for a
  workspace — so no UI ever ships under the old name.

## Consequences

- **Positive:** one rename, landed once, before any UI exists to double-rename. "Workspace" reads
  correctly for both the multi-user and solo-user cases, which "Team" didn't.
- **Neutral:** every `pandan team` invocation a user has already scripted breaks. Acceptable now
  (days-old feature, no SPA yet); would not be acceptable after V70 ships, which is exactly why this
  ADR lands first.
- **Negative / deferred:** `KAN-`/`EPIC-` ticket text and any already-filed cards that say "Team" in
  their title are left as historical record, not retroactively edited — matching the standing
  convention (ADR 0018 §"What is deliberately NOT renamed") that ticket history is never rewritten for
  a rename.
