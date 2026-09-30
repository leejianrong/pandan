# Competitive research and long-term vision for pandan and kaya

> **Status: research summary and vision, 2026-09-30, with the maintainer's first decisions recorded
> below.** The ADRs that make them binding are Accepted as of 2026-09-30
> ([0027](adr/0027-agent-token-scopes.md), [0028](adr/0028-approval-policy.md), and kaya ADR 0015).
> A diagram-led version is published as a private artifact.

## Summary

Small teams now work next to agents, and most trackers have bolted agents on as an assistant, a
metered add-on or a chat mention. The products that took it seriously (Linear, and to a lesser degree
Plane and Notion) share a pattern: the human stays accountable, the agent is a clearly labelled actor
with its own identity, and everything it does lands somewhere a person can review.

Pandan and kaya already have a strong agent surface (CLI, MCP, atomic claim, `needs-human`, token-lean
output). What they lack is the layer above it: **who acted, what they are doing right now, and how a
human reviews it.** That layer is where the long-term value is, and it is also where the biggest open
gap in the self-hostable, small-team market sits.

The proposed direction, in one line: **a light, self-hostable board and notes pair where humans own the
work, agents are named contributors, and every agent action is attributable, visible and reviewable.**

## Decisions taken (2026-09-30)

| Topic | Decision | Follow-up |
|---|---|---|
| Agent identity | **Labelled agent tokens**, not a new principal type. ADR 0014 stays true. | [ADR 0027](adr/0027-agent-token-scopes.md) |
| Review | **Flexible, not one rule.** A board rule (moves into chosen columns need approval) plus a per-card `requires_approval` flag, combined with scoped permissions on who may move cards. A protected move becomes a pending request, not a `403`. | [ADR 0028](adr/0028-approval-policy.md) |
| Who approves | **Humans only in v1.** The `approve` scope can never be held by an agent token, so an agent cannot approve its own request. | ADRs 0027 and 0028 |
| Kaya MCP | **Expand to about 15 tools** so an agent can run knowledge management, with safety rails first (actor on versions, a trash, paging, token presets) and the CLI-first parity rule kept. | kaya-notes ADR 0015 |
| Live collaboration (pandan) | **Yes.** Starting scale is about **5 concurrent agents on one board**. That is small enough for optimistic concurrency plus a server-sent change ping, with no new infrastructure. | ADR needed later (supersedes 0007) |
| Card move starts an agent | **No.** | none |
| Card move as an event | Keep the activity log as the source. Outbound Slack, email or Telegram messages are a low-priority nice-to-have. | none yet |
| Suite story | **None.** Pandan and kaya each stand alone. | none |
| Integration | Wanted, later: pasted links unfurl in both apps, and a pandan workspace can connect to a kaya workspace. Needs its own planning session. | planning session |

Why approvals are humans-only: an approval gate only means something if the requester cannot pass it.
Because an agent token resolves to its owning user, the rule has to be enforced on the token, not on the
user: `approve` is refused to any token of kind `agent`, even when its owner could approve.

Why 5 agents is a good place to start: at that scale the failure to prevent is two writers clobbering
each other, not throughput. A version check on cards (a `409` instead of a silent overwrite) plus a
"board changed" ping that triggers a refetch keeps the "server state is authoritative" rule and needs no
change to the single Fly machine. Pub/sub can stay in-process for now; running more than one machine
would need Postgres `LISTEN/NOTIFY` or similar, which is worth noting in the ADR.

## How this was researched

Five research passes ran on 2026-09-30, each limited to web docs and changelogs:
incumbent PM tools (Linear, Jira/Rovo, Trello, TOW), docs and notes tools (Confluence, Obsidian,
Notion, Outline, Logseq, Anytype), agent-native work tools (Linear for Agents, GitHub, Devin, Cursor,
Claude Code, Beads and others), open-source PM tools (Plane, OpenProject, Taiga, Vikunja, Focalboard,
WeKan, Kanboard, Kaneo, Backlog.md), and a read-only audit of both repos.

Caveats worth keeping in mind:

- Nothing was tested hands-on. Token costs, idempotency and bulk behaviour were not measured for any
  competitor.
- Several claims are from secondary sources and are marked below as **unverified**.
- Human-UX findings are thin for most tools. Only Linear, Jira and Confluence have sourced complaints.
- TOW (tow.dev) has almost no public documentation beyond marketing, pricing and a docs landing page.
  Its agent API, CLI and MCP surface could not be confirmed.
- The repo audit read code and docs, not production. Two suspected kaya-to-pandan breakages (below) are
  inferred from code and need a runtime check.

## What the competitors do

### Work trackers

| Tool | Best idea for us | Weak point |
|---|---|---|
| Linear | Agents are app users. Assigning sets the agent as **delegate** while the human stays assignee. Typed activity stream (`thought`, `response`, `elicitation`, `error`), 10 second acknowledgement, read-only MCP endpoint, team-level agent guidance in markdown. | Cloud only. No verified formal audit log of agent actions. Rate limits return HTTP 400 rather than 429. Coding sessions use paid AI credits. |
| Jira and Rovo | Four ways to invoke an agent, including a **status transition** or a board column. Agent edits recorded in work item history. | Agent output is private to whoever triggered it until published. Metered by credits. Undocumented MCP limits. Heavy configuration. |
| Trello | Official MCP cannot permanently delete anything. Named rate-limit errors with headers. | Agents act as the human, so attribution is lost. Views and automation runs are paywalled. |
| TOW | AI output is always a draft that a person accepts. Air-gapped self-hosting, free up to 20 users, bring-your-own AI key. | No verified agent API. Young product with no independent feedback. |
| GitHub Projects | Live agent session state on the card: queued, working, waiting for review, completed. | Single repo per task, GitHub only. |
| Plane (OSS) | First-party MCP (30 tools), agents as mentionable members with a run object, signed and retried webhooks. | Open-core split with a closed commercial fork. Heavy stack. |
| Vikunja (OSS) | MCP token presets: read-only, typed read and write, full. Tokens limited to projects the user can see. | Official MCP needs 2.7 or later. Webhooks are not retried. |
| Beads and Backlog.md | `ready` query, atomic claim, hash IDs, memory decay for old closed tasks. Tasks as markdown in git. | Single-user, local. Beads needs Dolt. Vibe Kanban lost its hosted features when its company shut down in April 2026. |

### Notes and docs

| Tool | Best idea for us | Weak point |
|---|---|---|
| Obsidian | Plain markdown. Local REST plugin PATCHes by **heading, block or frontmatter field**, and exposes a document map. Official CLI whose `move` rewrites links. | Agent access needs the desktop app running. No attribution or revert story for agents. |
| Notion | Markdown-first agent API (Notion-flavoured markdown) to cut tool calls and tokens. Per-run agent audit: what changed and who triggered it. External agents assignable from a shared board. | Agents are metered by credits. Audit features are enterprise-tier. |
| Outline | Breadcrumbs and summaries in every read response. WebMCP with destructive tools excluded. Markdown plus YAML frontmatter export. | Hosted API limits undocumented. Attribution and revert not found. |
| Confluence | Read and write MCP scopes. A template-read tool. | Whole-page update only, as far as the tool list shows. Editor lag is documented in Atlassian's own tracker. |
| Anytype | ETags and idempotency keys on writes. Compact write receipts. Headless bot accounts. | Opaque object model, weak markdown export. |
| Logseq | A one-way markdown mirror of a database store. | Moving the canonical store to a database was disruptive for its users. |

### Cross-cutting patterns

1. **Delegate, not assignee.** The human owns the outcome. The agent contributes.
2. **A typed activity stream on the card.** Separate from editable comments, and immutable.
3. **Asking is a first-class state.** Linear's `elicitation` and MCP's elicitation spec both give the
   agent a structured way to stop and ask, rather than guess.
4. **Review is the bottleneck, not generation.** Secondary sources report AI-authored PRs waiting far
   longer for review (unverified figures; treat as direction, not data). Every serious product ends up
   with a review lane, a diff, or a draft-then-accept step.
5. **Scoped identity and limits.** Team-scoped agents, read-only presets, delete-disabled modes,
   per-run turn, time and spend caps, and a guard against bot-triggered loops.
6. **Lean agent interfaces.** Concise and detailed response modes, small default pages, names not
   UUIDs, errors that say what to do next, and few consolidated tools.
7. **Metering is a tax on small teams.** Credits for agent calls (Rovo, Notion, Linear sessions) are the
   most consistent complaint-shaped gap.

## Where pandan and kaya stand today

Facts from the repo audit (source paths are in the audit notes; the installed `pandan` binary is 0.19.1
while source is 0.48.0, so check the source for the current surface).

**Pandan strengths.** Cards with epics, cycles, planning intervals, labels, templates, dependencies,
saved views, workspaces and board roles. Atomic claim (`next --claim`, `dispatch`) that skips blocked
cards, `needs-human` with a note, agent-versus-human throughput in metrics, GitHub PR autosync,
signed outbound webhooks, an append-only activity feed, hosted OAuth MCP, and a token-lean CLI with
`--fields`, `--full` and TOON output.

**Kaya strengths.** Standalone accounts and hosted MCP, wikilinks to notes, cards and epics, backlinks,
graph, version history with restore, optimistic concurrency (`if_updated_at`, 409 with both bodies),
Obsidian-compatible export and import, and a deliberately narrow, pinned MCP surface (six tools).

**The gaps, in priority order.**

1. **No agent identity or attribution.** Every principal is a real user (ADR 0014). An agent using a PAT
   shows in the activity feed as its owner's email. Comments store only `author_id`. The only agent
   marker is a free-text `assignee` convention (`agent:<slug>`), which the docs admit makes `claude`,
   `Claude` and `agent:claude` three assignees. Kaya versions have no actor at all.
2. **No live view of agent work.** A card is `todo`, `in_progress` or `done`. There is no "agent is
   working", "waiting for review" or "blocked on a question" state, and no activity stream from the
   agent. Notifications go to the board owner only.
3. **Claims have no lease.** `dispatch` claims a card atomically, but nothing releases it if the agent
   dies. (No competitor documents claim timeouts either, so this is ours to design.)
4. **Review is manual and invisible.** Nothing distinguishes an agent's change from a human's, and kaya
   has no way to propose an edit for review. Writes are last-write-wins in pandan (ADR 0007) and
   whole-body in kaya.
5. **Board and notes are barely connected.** Kaya can link to `[[KAN-12]]`, but a card cannot point at a
   note. The typed `spec` link in `kaya-vision.md` was never built.
6. **Kaya's agent surface is narrow.** No section-scoped edit, no document map, no delete, move,
   versions or export in MCP, and `GET /notes` has no paging.
7. **Suspected integration breakage (unverified, needs a runtime check).** Kaya's card resolver still
   forwards a kaya bearer to pandan, and kaya's team resolver calls `/api/v1/teams`, which pandan no
   longer serves. Both should degrade gracefully, so team-shared notes may simply appear unresolved.
8. **Doc drift.** `kaya-notes/README.md` still describes the pre-ADR-0012 shared identity, and
   pandan's `limits.md` says there is no `pandan me`.

## Vision

### Positioning

The open gap the OSS research found: agent access is either paywalled (OpenProject), bolted on by
third parties (Kanboard, Taiga, WeKan), or single-user and local (Backlog.md, Vibe Kanban). Only Plane
has a first-party agent model, and it sits inside a heavy open-core product. There is room for a
**light, self-hostable, shared board and notes pair where the CLI and MCP are equal citizens to the UI,
free, with agents as accountable contributors.** Plane and Kaneo are the two nearest competitors and
should be tried hands-on before we lean on this claim.

### Principles

1. **Humans own outcomes, agents contribute.** Every card and note has a human accountable for it.
2. **Attribution is not optional.** For any change we can answer which human, which agent, which token.
3. **Agent work is visible where the human already looks.** On the card, in the inbox, not in a log.
4. **Review is designed in.** Agent changes to notes arrive as proposals. Card work has a visible
   review stage.
5. **Ask, don't guess.** Blocking on a human is a structured, answerable state.
6. **Free and lean agent access.** No metering. Small responses by default.
7. **Portable and self-hostable.** Markdown out, git-friendly, one deploy target we can run ourselves.

### Roadmap themes

**Now (foundation, small and unblocking).**

- *Agent attribution.* Record the acting token or OAuth client in activity rows and comments, and show
  an "agent" marker in the UI. Needs an ADR amendment to 0014, because "every principal is a real user"
  stays true while the credential and its label become visible.
- *Actor on kaya versions* (`note_version` gets who and via what), plus a version diff in the UI.
- *Fix the two suspected kaya-to-pandan breakages* and the doc drift.
- *Kaya MCP expansion, safety rails first* (kaya ADR 0015): actor on versions, a trash, paging on
  `GET /notes`, token presets. Then about nine new tools, including a document map, section edits,
  move with link rewriting, versions and a health check.

**Next (the human-plus-agent loop).**

- *Token scopes and the approval policy* ([ADR 0027](adr/0027-agent-token-scopes.md),
  [ADR 0028](adr/0028-approval-policy.md)): scoped agent tokens, then protected moves that become
  pending requests.
- *Live collaboration, first step.* A version check on cards (`409` on a stale write) and a server-sent
  "board changed" ping that triggers a refetch. Sized for about 5 concurrent agents per board.
- *Delegate versus assignee.* A `delegate` on a card, with the human as assignee and views filtered by
  delegate. Replaces the `agent:` string convention.
- *Agent run state on the card.* Queued, working, waiting for review, blocked on question, with a link
  to the activity. Probably a sub-state rather than new columns, to keep the three-column model.
- *Structured asks.* Extend `needs-human` so an agent can attach a question with answer options, and
  the inbox shows it for a one-click reply. Notifications go to more than the board owner (assignee,
  delegate, mentioned).
- *Claim leases.* A claim expires unless the agent heartbeats, and a stale claim returns to `todo`
  with a comment.
- *Ticket readiness.* A lint for problem statement, acceptance criteria and file pointers, offered
  before a card is claimed by an agent, plus a marker for work that should not be delegated.
- *Card to note link.* A typed `spec` link and a card-side "notes that mention this" panel.

**Later (team scale and trust).**

- *Proposed edits in kaya.* Agents submit a change that a human accepts, edits or rejects, with a
  diff. Direct writes stay available under a permission the human grants per agent.
- *Scoped agent tokens.* Presets like read-only, cards only, notes only, no delete, plus per-run turn
  and time caps, and a loop guard for bot-triggered events.
- *Card moves as events.* Decided against starting agents from a column move. The activity log stays
  the source of truth, and a later, low-priority step can forward moves ("KAN-1234 moved from todo to
  in progress by agent alex") to Slack, email or Telegram through the existing outbound webhook.
- *Live collaboration, later steps.* Activity grouping and a "hide agent activity" toggle, a per-agent
  view, and a pub/sub that survives more than one machine.
- *Signed webhooks with retries and delivery IDs* for both apps, and a kaya event stream.
- *Card and note links in both directions*, and a workspace-to-workspace connection. See the
  integration planning session below.
- *Agent memory.* A convention for `AGENTS.md`-style project conventions and durable agent notes in
  kaya, with a way to summarise or expire stale entries.

### What to avoid

- Metering agent calls or gating MCP behind a paid tier.
- Agent output that only the triggering person can see (Jira).
- Agents acting under a human's identity with no separate marker (Trello).
- A proprietary rich-content format agents must learn (Confluence).
- A database-canonical store with no markdown route back out (Logseq).
- A hosted-only agent product with no self-host story (Vibe Kanban).
- Non-standard error semantics such as rate limits returned as 400 (Linear). Keep 429 with
  `Retry-After`.
- Letting untrusted issue or note text act as instructions for a privileged agent.

## Integration planning session (later)

Not a priority now, but the shape is worth fixing so nothing built meanwhile blocks it. The proposal is
to keep the apps independent by giving each a small public contract instead of a shared dependency:

- **Stable link formats** for a card, epic and board in pandan, and for a note in kaya.
- **An unfurl endpoint** in each app that turns one of its links into a title, status and icon, so a
  pasted link renders as a rich card in the other app. Neither app imports the other.
- **A workspace connection.** Kaya has its own accounts (ADR 0012) and pandan already runs an OAuth
  server, so the likely model is kaya as an OAuth client of pandan, replacing the pasted-token link.

To decide in that session: how a workspace connection maps members and roles, how a note avoids
revealing a card title to someone who cannot see that card (pandan's batch read already refuses to act
as an existence oracle), and what happens to the two suspected breakages listed under the gaps.

## Still open

Nothing blocking. Answered on 2026-09-30 and folded into the ADRs: approvers are the board owner
and editors (no named list for now), a board rule can name a source column, `agent` tokens default to
90 days, kaya's `health_check` is read-only with a `dry_run` on `move_note`, an agent sees a
`pending_approval` object and gets an idempotent answer while it waits, rejected requests never count in
throughput, OAuth-connected apps always count as `agent`, and rate limits are keyed by token (120 a
minute is a starting proposal to tune). The one remaining question is whether kaya needs `export` over
MCP, in kaya ADR 0015.

## Unverified or unchecked

- TOW's agent API, CLI, MCP, webhooks and audit trail.
- Whether Linear has a formal audit log of agent actions, and whether its CLI is first-party.
- Confluence and Notion editor UX, version history internals and real complaints.
- Jira's data model and keyboard UX, and Rovo credit allowance dates.
- Review-bottleneck statistics (Faros, LinearB, and similar), which came from a secondary blog.
- Star counts and release cadences are as of 2026-09-30 from the GitHub API. Taiga's star count is for
  a repo that may be a fork.
- Kaneo, Plane and Huly agent and CLI depth.
- Both suspected kaya-to-pandan breakages.

## Suggested next steps

1. Done: ADRs 0027, 0028 and kaya 0015 are Accepted; the "Now" cards are KAN-1797 to KAN-1799 (pandan) and KAN-1800 to KAN-1804 (kaya).
2. Try Plane and Kaneo hands-on for an hour each, and Linear's MCP if there is a trial workspace.
3. Turn the "Now" items into board cards on boards 5 and 18.
4. Write the live-collaboration ADR (superseding 0007) once the version check and change ping are shaped.
