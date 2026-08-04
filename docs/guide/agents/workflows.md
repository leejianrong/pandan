<!--
title: "Agent workflows"
description: The patterns worth handing an agent: taking work atomically, recording a blocker, attaching a PR, and handing a card back to a human.
-->

# Agent workflows

These are the patterns that make an agent useful on a board rather than just able to write to one. Each
is shown as MCP tool calls, with the CLI equivalent underneath.

## Take a card and start

```
dispatch(assignee="claude")
add_comment(card_id, body="Starting on this, will open a PR shortly.")
```

```bash
pandan next --claim --assignee claude
pandan comment add KAN-601 --body "Starting on this, will open a PR shortly."
```

`dispatch` finds the highest-priority ready card, skips anything blocked, and claims it atomically.

!!! warning "Do not use `next` then `claim_card`"

    They are two calls with a gap between them. Two agents polling `next` at the same moment both see
    the same card, and both claim it. `dispatch` closes that window; use it whenever more than one
    agent runs against a board.

The comment is not ceremony. It is the thing a human reads when they wonder why a card moved.

## Record what you found

```
add_link(card_id, label="PR #267", url="https://github.com/leejianrong/pandan/pull/267")
add_comment(card_id, body="Root cause: list prints next_cursor but has no --cursor flag to consume it.")
```

```bash
pandan link add KAN-601 --label "PR #267" --url https://github.com/…/267
pandan comment add KAN-601 --body "Root cause: …"
```

Attach the PR as soon as it exists, not at the end. If the agent's session dies mid-task, the link is
the only thing connecting the card to the work.

## Handle a blocker

When an agent discovers that a card cannot proceed until another one lands:

```
add_dependency(card_id, blocker_id)
add_comment(card_id, body="Blocked: needs the cursor flag from KAN-591 first.")
```

```bash
pandan dep add KAN-601 --blocked-by KAN-591
pandan comment add KAN-601 --body "Blocked: needs the cursor flag from KAN-591 first."
```

This changes behaviour rather than just recording a fact. A blocked card is skipped by `dispatch`, so
neither this agent nor another one picks it up again until the blocker is done.

Clear it when the blocker lands:

```
remove_dependency(card_id, blocker_id)
```

## Hand it back to a human

The most important pattern here. An agent that hits a real judgement call should stop and say so.

```
needs_human(card_id, note="Two valid designs. Adding --cursor to list matches activity, but the flag
contract says list is a one-shot query. Needs a call on which one wins.")
```

```bash
pandan needs-human KAN-601 --note "Two valid designs. …"
```

The card gets flagged, the note is stored, and it shows up in `list_cards(needs_human=true)` and in the
web UI's awareness view. A human answers, then:

```
resolve(card_id)
```

!!! tip "Write the note as a question, not a status"

    "Blocked on design" tells a human nothing. "Should `list` take `--cursor`, matching `activity`, or
    stay a one-shot query?" can be answered in one line. The quality of the note decides how fast the
    card unblocks.

## Finish

```
move_card(card_id, column="done")
```

```bash
pandan move KAN-601 done
```

If the card had a blocker recorded that turned out not to apply, clear it first. A `done` card with a
live blocker is confusing to read later.

## Plan a chunk of work

An agent asked to break down a feature should create the epic and hang stories off it, rather than
producing a flat pile of cards:

```
create_epic(name="Onboarding flow", description="New-user first-run experience")
create_card(title="Landing page", column="todo", epic_id=<id>)
create_card(title="GitHub login button", column="todo", epic_id=<id>)
create_card(title="Token minting UI", column="todo", epic_id=<id>)
```

```bash
pandan epic create "Onboarding flow" --description "New-user first-run experience"
pandan create "Landing page" --epic EPIC-7
pandan create "GitHub login button" --epic EPIC-7
```

Use `create_cards` (or `batch-create`) when the whole set is known up front, but remember it is
fail-fast and not atomic, so check what got created before retrying.

## Start a session knowing the state

```
warmup()
list_cards(column="in_progress", fields=["ticket_number", "title", "assignee"])
list_cards(needs_human=true, fields=["ticket_number", "title", "attention_note"])
```

Three cheap calls that answer: is the API awake, what is in flight, and what is waiting on a human.
That is usually enough context to decide what to do next, and it costs a fraction of an unnarrowed
`list_cards`.

Better still, install the context hook so this happens automatically:

```bash
pandan context install
```

## A full cycle

```bash
pandan warmup
pandan next --claim --assignee claude                        # take it
pandan comment add KAN-601 --body "Starting on this"
# … do the work …
pandan link add KAN-601 --label "PR #267" --url https://…    # record it
pandan needs-human KAN-601 --note "Needs a call on X"        # if stuck
# … human answers …
pandan resolve KAN-601
pandan move KAN-601 done                                     # finish
```

## What not to do

**Do not poll in a tight loop.** Writes and searches are rate limited per tier. Over the limit you get
a `429` with a `Retry-After` header. Read once and filter locally.

**Do not read the whole board to answer a narrow question.** Filter server-side and pass `fields`. See
[token budget](token-budget.md).

**Do not guess when you are stuck.** `needs_human` exists for this. A flagged card with a clear note is
a better outcome than a wrong commit.

**Do not leave a card in `in_progress` when the session ends.** Either move it or flag it. A card
claimed by an agent that is no longer running is invisible work, and `metrics` will show it as aging
WIP without saying why.

## Recap

| Situation | Call |
| --- | --- |
| Need work | `dispatch` |
| Found the cause | `add_comment` |
| Opened a PR | `add_link` |
| Cannot proceed until X | `add_dependency` |
| Need a decision | `needs_human` with a real question |
| Human answered | `resolve` |
| Done | `move_card` to `done` |

Next: [token budget](token-budget.md).
