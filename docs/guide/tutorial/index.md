<!--
title: "User guide"
description: A walkthrough of the Pandan board in a browser, from your first card to epics, cycles and keyboard-driven navigation.
-->

# User guide

This is the browser side of Pandan. It goes in order, and each page builds on the one before it, so
working straight through gets you to a board you can drive without touching the mouse.

If you would rather drive from a terminal, go to the [CLI guide](../cli/index.md) instead. Everything
here has a command-line equivalent, and the pages mention it where it helps.

## Before you start

Log in at [simple-kanban-jian.fly.dev](https://simple-kanban-jian.fly.dev) with GitHub, or at your own
instance. Your first login gives you a board, so there is nothing to set up.

!!! note "The first request after a while is slow"

    The hosted board scales to zero when nobody is using it, so the first page load after an idle
    period takes about a second while the server and database wake up. That is expected, not a fault.

## The words this guide uses

Pandan is fussy about a few terms, because the API is. Getting them straight now saves confusion later.

| Term | What it means |
| --- | --- |
| **Board** | A container for work. Has one owner, and optionally members. Your cards and epics belong to exactly one board. |
| **Card** | A single piece of work. Also called a **story**. Lives in a column, has a position within it, and carries a ticket number like `KAN-123`. |
| **Column** | Where a card is in its life: `todo`, `in_progress`, or `done`. Only these three. |
| **Epic** | A grouping of related cards. Has a name, a lead and a target date, but no column and no points, because an epic is not a card. Numbered `EPIC-4`. |
| **Cycle** | A time-boxed iteration, with a start and end date. A sprint, if you use that word. |
| **Label** | A coloured tag on a card. Per board. |
| **View** | A saved query. Any filter you can apply, you can name and keep. |

!!! info "Ticket numbers never change and never get reused"

    A card is `KAN-123` from creation until deletion. The numbers come from a database sequence, so
    they are allocated atomically and there are gaps where cards were deleted. Cards and epics number
    independently, which is why `KAN-1` and `EPIC-1` can both exist.

    The `KAN-` prefix is a leftover from the project's old name. It stays because renaming it would
    break every ticket reference in the board's own history.

## What the interface gives you

Seven places, reachable from the menu or the command palette:

| Place | What it is for |
| --- | --- |
| **Board** | The columns and cards. Where you spend most of your time. |
| **Dashboard** | Throughput, cycle time, and what is aging. |
| **Epics** | Epics with their progress and health. |
| **Activity** | The audit trail: who changed what, and when. |
| **Tokens** | Create and revoke personal access tokens for the CLI and agents. |
| **Members** | Who else is on this board, and what they can do. |
| **Trash** | Deleted cards and epics, restorable. |

## One thing to know up front

Pandan never shows you a value the server has not confirmed. Every change you make is sent, stored, and
read back before the interface updates.

The trade-off is that a change takes a moment to appear rather than snapping instantly. What you get in
exchange is that the board never lies to you, and two people editing at once cannot end up looking at
different truths. The last write wins, and everyone sees the same thing.

## Where to go

<div class="grid cards" markdown>

-   **[Boards](boards.md)**

    Create one, switch between them, and share with a teammate.

-   **[Cards](cards.md)**

    Every field on a card and what it is for.

-   **[Moving work](moving-work.md)**

    Columns, dragging, the table view, and reordering.

-   **[Epics](epics.md)**

    Grouping stories, with progress and health.

-   **[Organising](organising.md)**

    Labels, saved views, cycles and templates.

-   **[Working together](collaboration.md)**

    Comments, dependencies, links, the needs-human flag, and notifications.

-   **[Dashboard](dashboard.md)**

    Reading the metrics honestly.

-   **[Keyboard shortcuts](keyboard-shortcuts.md)**

    The full list, and the command palette.

</div>
