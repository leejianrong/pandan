<!--
title: "MCP tool reference"
description: All 49 Pandan MCP tools, grouped by what they touch, plus the fields and full arguments that control payload size.
-->

# MCP tool reference

49 tools, one per API capability. Names below are unprefixed. Your client sees them namespaced by your
`mcpServers` key, so `list_cards` is `mcp__pandan__list_cards` with the recommended key.

Every board-scoped tool takes an optional `board_id`. Omit it and it falls back to `PANDAN_BOARD_ID`.

## Boards

| Tool | What it does |
| --- | --- |
| `list_boards` | Boards you can reach, with ids. Run this first. |
| `get_board` | One board, including its auto-sync and webhook settings. |
| `create_board` | New board, owned by you. |
| `update_board` | Rename, or change board settings. |
| `delete_board` | Deletes the board **and its cards and epics**. |

## Cards

| Tool | What it does |
| --- | --- |
| `list_cards` | Query cards. Filter by column, epic, cycle, assignee, priority, label, due date, needs-human, or full text. `refs` reads a known set of cards in one call — see below. |
| `get_card` | One card in full: description, labels, dependencies both ways, links, priority, due date. |
| `create_card` | Create one card. |
| `create_cards` | Create several. Fail-fast, **not** atomic. |
| `update_card` | Edit fields. Cannot move a card. |
| `update_cards` | Patch several. **Atomic**, unlike `create_cards`. |
| `move_card` | Change column and position. |
| `claim_card` | Assign and move to `in_progress` in one call. |
| `delete_card` | Move a card to the board's trash. |

!!! warning "`update_card` does not move cards"

    Column and position go through `move_card`. Moving renumbers positions in both the source and
    target column, which is a different operation from editing a field.

## Epics

| Tool | What it does |
| --- | --- |
| `list_epics` | Epics on the board, with progress and health. |
| `get_epic` | One epic. Authorized through its own board, so no `board_id` needed. |
| `create_epic` | Create an epic. Takes a lead and a target date. |
| `update_epic` | Edit it. |
| `delete_epic` | Delete it. Its stories are **detached**, not deleted. |

Link a story to an epic with `epic_id` on `create_card` or `update_card`.

## Dependencies, links and comments

| Tool | What it does |
| --- | --- |
| `add_dependency` | Record that this card is blocked by another. |
| `remove_dependency` | Clear a blocker. |
| `list_dependencies` | Both directions: `blocked_by` and `blocks`. |
| `add_link` | Attach a labelled URL, for a PR, branch or CI run. |
| `remove_link` | Detach one. |
| `add_comment` | Add a note to a card. |
| `list_comments` | Read a card's notes. |

Dependencies are not decoration. `next` and `dispatch` skip a card whose blockers are unfinished, so
recording one actually changes what an agent picks up.

## Agent flow

| Tool | What it does |
| --- | --- |
| `next` | The highest-priority ready card, skipping blocked ones. Read-only. |
| `dispatch` | `next` plus an atomic claim. Two agents calling it cannot get the same card. |
| `needs_human` | Flag a card for a human, with a note explaining the question. |
| `resolve` | Clear the flag once a human has answered. |

Use `dispatch` rather than `next` followed by `claim_card`. The two-call version has a race between
them; `dispatch` does not.

## Organising

| Tool | What it does |
| --- | --- |
| `list_labels`, `create_label`, `delete_label` | Per-board labels with optional colours. |
| `list_views`, `create_view`, `delete_view` | Saved queries. Anything `list_cards` accepts can be saved. |
| `list_cycles`, `create_cycle`, `delete_cycle` | Iterations, with start and end dates. |
| `cycle_metrics` | Flow metrics scoped to one cycle. |
| `list_templates`, `create_template`, `delete_template` | Named sets of cards. |
| `apply_template` | Stamp a template's cards onto the board. |

## Reporting and inbox

| Tool | What it does |
| --- | --- |
| `metrics` | Throughput, cycle time (average, median, p90), aging WIP, and a per-assignee breakdown. |
| `activity` | The board's audit trail, newest first, filterable by actor and action. Paginated. |
| `list_notifications` | Your inbox. Per user, not per board. |
| `mark_read` | Mark a notification read. |

## Health

`warmup` pings the unauthenticated health endpoint and needs no token. Call it first in a session to
pay the cold start up front.

## Shaping the output

Two arguments control how much a read returns, and they are the difference between a cheap read and one
that eats a context window.

**`fields`** takes a list of field names and returns only those. Available on:

`list_cards`, `get_card`, `list_boards`, `list_epics`, `list_comments`, `list_notifications`,
`activity`, `metrics`, `cycle_metrics`

**`full`** returns untruncated free text instead of cutting it at 500 characters with a size hint.
Available on:

`get_card`, `get_epic`, `list_cards`, `list_epics`, `list_comments`, `list_notifications`, `activity`

```json
{
  "name": "list_cards",
  "arguments": { "column": "todo", "fields": ["ticket_number", "title", "priority"] }
}
```

!!! danger "Narrow `list_cards` or it will hurt"

    One unnarrowed `list_cards` against a real board returns roughly 45,000 tokens, which is about
    five times the entire tool schema surface. Passing `fields` on the reads that matter cuts about
    82% across a representative set. Always pass a filter, and pass `fields` when you know what you
    need.

The other reads are deliberately left unshaped, because they return between 7 and 474 tokens each and
adding arguments to shape a small payload costs more schema than it saves.

### Reading a known set of cards

When you already hold the references, `refs` fetches them all in one call rather than N `get_card`
round trips:

```json
{
  "name": "list_cards",
  "arguments": { "refs": "KAN-12,45,KAN-9", "fields": ["ticket_number", "title", "column"] }
}
```

Ids and tickets mix freely in the one string. Combined with `fields` this is the cheapest way to
resolve a list of references, which is why it exists: an agent following up on a handful of tickets
was previously paying a full round trip each.

Anything that matches nothing comes back under `unresolved` instead of failing the call, so one stale
reference does not cost you the other thirty-nine:

```json
{ "cards": [ … ], "unresolved": ["KAN-404"] }
```

Capped at 100 selectors, and not combinable with `limit`/`cursor` — a truncated page would report
real cards as unresolved.

## Why 49 tools

The surface was measured against two alternatives, a consolidated verb set and a single tool that just
executes the CLI, and kept as it is. The reasoning: resident schema turned out to be the small half of
the cost, at roughly 8,162 tokens per session, while a single careless read costs five times that. So
breadth stays and payload shaping got the attention instead.

The count is frozen by a test. Adding a tool means amending the decision record, not editing a fixture.
Details in [design decisions](../about/design-decisions.md).

## Recap

- `list_boards` first, then set `PANDAN_BOARD_ID`.
- `dispatch` to take work, not `next` plus `claim_card`.
- `move_card` to move, `update_card` to edit.
- `fields` and `full` on the reads that support them.
- `warmup` once per session.

Next: [agent workflows](workflows.md).
