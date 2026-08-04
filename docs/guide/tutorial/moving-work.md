<!--
title: "Moving work"
description: Move cards between columns by dragging or with the keyboard, reorder within a column, and switch to the table view.
-->

# Moving work

Three columns, and a position within each one. That is the whole model.

## The columns

`todo`, `in_progress`, `done`. There are only these three and you cannot add a fourth from the
interface.

That is a real constraint, so it is worth saying why: the column is stored as plain text guarded by a
database check rather than a rigid enum, specifically so a new value can be added later without a
schema migration. The limit is a product decision, not a technical wall. Today, three.

## Dragging

Pick a card up and drop it in another column. It lands where you drop it, and the cards around it
renumber.

Dropping within the same column reorders it.

## With the keyboard

Faster once it is in your fingers. Focus a card by clicking or tabbing to it, then:

| Keys | Action |
| --- | --- |
| ++j++ / ++k++ | Next / previous card in the column |
| ++h++ / ++l++ | Previous / next column |
| ++shift+arrow-right++ | Move the focused card to the next column |
| ++shift+arrow-left++ | Move the focused card to the previous column |

Arrow keys work everywhere `hjkl` does, so ++arrow-down++ is ++j++ if you prefer.

The card keeps focus across the move, which means you can move something from `todo` to `done` with two
presses of ++shift+arrow-right++ without touching the mouse.

Navigation skips empty columns rather than stranding you in one. The full list is in
[keyboard shortcuts](keyboard-shortcuts.md).

!!! note "Card navigation needs the board view"

    The `hjkl` navigation applies to the board presentation. In the table view, use normal tab and
    scroll behaviour.

## Position, and why there are gaps

A card's position is a sort key within its board and column. It is not a contiguous index, and it is not
a global rank.

Deleting a card leaves a gap in the sequence on purpose, because closing every gap on every delete means
rewriting a whole column for no visible benefit. A move renumbers only the columns it touched, the source
and the target.

You will not normally see any of this. It matters if you drive the API directly, where you can ask for a
specific index and get clamped into range rather than rejected.

```bash
pandan move KAN-591 todo --position 0     # to the top
pandan move KAN-591 done                  # appended to the end
```

## Table view

The board is one of two presentations. The other is a table, which is better when you want to compare
many cards on their fields rather than see their flow.

![The table view](../assets/images/v14-table-light.png#only-light)
![The table view](../assets/images/v14-table-dark.png#only-dark)

Switch with the view toggle in the top bar. The table shows more per card and sorts by column heading,
which makes it the right place to answer "what is overdue" or "who has the most in flight".

## Filtering what you see

The filter controls narrow the board to a subset. Everything you can filter on:

column, epic, cycle, assignee, priority, label, due date, overdue, needs-human, and full-text search
over titles and descriptions.

Filters combine, and they narrow rather than widen, so adding one never brings more cards into view.

Reach them fastest through the command palette: ++ctrl+k++, then "Set filter". It also has shortcuts
straight to the two filters you want most often, needs-human and overdue, plus "Clear all filters" for
when you have lost track.

Once a filter earns its keep, save it as a [view](organising.md#saved-views).

## Recap

- Three columns: `todo`, `in_progress`, `done`.
- Drag, or ++shift+arrow-right++ and ++shift+arrow-left++ with a card focused.
- ++j++ ++k++ ++h++ ++l++ to move focus around.
- Position gaps after a delete are normal.
- Table view for comparing fields, board view for flow.
- ++ctrl+k++ then "Set filter" is the quickest way to narrow the board.

Next: [epics](epics.md).
