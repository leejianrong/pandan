<!--
title: "Cards"
description: Create and edit cards, and what each field on a card is actually for.
-->

# Cards

A card is one piece of work. Some people call it a story. It has a ticket number, lives in a column, and
carries whatever detail you give it.

## Creating one

Click **Add card** at the bottom of any column, or press ++n++ with a card focused to add to that
column, or ++ctrl+k++ and choose "Create card".

Only the title is required. Everything else can wait, and usually should. A card you cannot describe in
a title is usually two cards.

```bash
pandan create "Add a cursor flag to list"
```

## The fields

![The card detail view](../assets/images/v11-card-fields-light.png#only-light)
![The card detail view](../assets/images/v11-card-fields-dark.png#only-dark)

**Title.** Required, and the only required field. Keep it a statement of what needs to happen.

**Description.** Free text, as long as you like. Worth knowing: the CLI and MCP server truncate long
descriptions at 500 characters by default so a single card cannot flood an agent's context. The web UI
always shows the whole thing.

**Column.** `todo`, `in_progress`, or `done`. Change it by dragging or with ++shift+arrow-right++, not
by editing the field. See [moving work](moving-work.md).

**Story points.** One of `1`, `2`, `3`, `5`, `8`, `13`, or empty. A Fibonacci-ish scale, and the
allowed values are enforced by the server, so `4` is rejected rather than quietly stored. Leave it empty
if you do not estimate.

**Assignee.** Free text, not a user picker. That is deliberate: it holds `claude`, `agent:docs-rewrite`,
or an email, so an agent can own a card without needing an account. The cost is that there is no
validation and no autocomplete, so pick a convention and stick to it.

**Priority.** `none`, `low`, `medium`, `high`, or `urgent`. `none` is the default and means unranked
rather than unimportant. Priority decides what `pandan next` hands to an agent, so it does real work
beyond decoration.

**Due date.** A timestamp. Feeds the `--overdue` filter and the dashboard's aging view.

**Epic.** Links this card to one epic, or none. See [epics](epics.md).

**Cycle.** Assigns the card to an iteration. See [organising](organising.md).

**Labels.** Any number of the board's labels.

## Editing

Open a card and edit in place, or press ++e++ with it focused. From the CLI:

```bash
pandan update KAN-591 --priority high --points 3
```

!!! warning "Editing cannot move a card"

    Column and position are not editable fields. They change through a separate move operation, because
    moving a card has to renumber the cards around it in both the old and new column. The UI hides this
    from you by making the drag do the right thing; the API and CLI make it explicit.

## Ticket numbers

Every card gets one at creation: `KAN-1`, `KAN-2`, and so on. They come from a database sequence, which
means they are allocated atomically even if two people create a card at the same instant.

They are also never reused. Delete `KAN-42` and nothing else ever becomes `KAN-42`. So your numbers will
have gaps, and that is correct rather than a bug.

Anywhere the CLI wants a card, a ticket number works as well as the numeric id:

```bash
pandan get KAN-591
pandan get 591        # the same card
```

## Deleting and restoring

Deleting moves a card to the board's **Trash** rather than destroying it.

```bash
pandan delete KAN-591
```

From Trash you can restore it, which puts it back with its ticket number intact, or purge it, which is
permanent. Deleting a board is the one path with no trash, because the cards go with the board.

## What the server decides

Two things are worth knowing because they will surprise you otherwise.

**Validation happens server-side, and it is strict.** A story point value outside the allowed set, an
empty title, or a description past the column width comes back as a `422` with a reason. It never gets
half-stored.

**The board never shows you an unconfirmed value.** Every edit is sent, stored, and read back before the
interface updates. So a change appears a beat later than you clicked, and what you see afterwards is
what is actually in the database.

## Recap

- Title is the only required field.
- Story points are limited to `1`, `2`, `3`, `5`, `8`, `13`. The server enforces it.
- Assignee is free text on purpose, so agents can own cards.
- Priority drives what agents pick up next.
- Ticket numbers are permanent, and gaps are normal.
- Deleting is recoverable from Trash. Deleting a board is not.

Next: [moving work](moving-work.md).
