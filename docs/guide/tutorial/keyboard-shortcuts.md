<!--
title: "Keyboard shortcuts"
description: Every keyboard shortcut on the Pandan board, plus the command palette and the rules about when single-key shortcuts fire.
-->

# Keyboard shortcuts

The board is built to be driven without a mouse. Press ++question++ at any time to see this list in the
app.

## Navigate

| Keys | Action |
| --- | --- |
| ++j++ or ++arrow-down++ | Next card in the column |
| ++k++ or ++arrow-up++ | Previous card in the column |
| ++l++ or ++arrow-right++ | Next column |
| ++h++ or ++arrow-left++ | Previous column |

Focus follows the same order the cards are in: down a column, then on to the next one. Moving between
columns keeps your place in the list where it can, and skips empty columns rather than leaving you
stranded in one.

Nothing is focused when you first arrive. The first navigation key focuses the first card on the board.

## Act on the focused card

| Keys | Action |
| --- | --- |
| ++enter++ or ++o++ | Open the card |
| ++e++ | Edit the card |
| ++shift+arrow-right++ | Move the card to the next column |
| ++shift+arrow-left++ | Move the card to the previous column |

Moving keeps the card focused afterwards, so ++shift+arrow-right++ twice takes something from `todo` to
`done` without reaching for the mouse.

The move is a real server write, the same one a drag performs, so the card is where you left it when you
reload.

## Create and search

| Keys | Action |
| --- | --- |
| ++n++ or ++c++ | New card in the focused card's column |
| ++ctrl+k++ | Open the command palette |

++n++ opens the add-card form in the column of whatever is focused, or the first column if nothing is.

On macOS the palette is ++cmd+k++, and the in-app help labels it for whichever you are on.

## General

| Keys | Action |
| --- | --- |
| ++question++ | Show or hide the shortcuts help |
| ++esc++ | Close a dialog, or the help |

## The command palette

++ctrl+k++ opens a searchable list of everything you can do. Type to filter.

**Actions**

- Create card
- Move card, then pick the target column
- Switch between the light and dark theme

**Jump to**

- A view: Board, Dashboard, Epics, Activity, Tokens, Members, Trash, Settings
- A board
- An epic, which filters the board to it

**Filter**

- By column
- Needs human
- Overdue
- Clear all filters

The palette is the fastest route to anything that is not a card you can already see, and it is worth
learning before the individual shortcuts. Typing a card's ticket number or part of its title finds it
directly.

## When single-key shortcuts fire

Single-key shortcuts like ++j++ and ++n++ are convenient and would be infuriating if they fired at the
wrong moment, so there are three guards.

**Never while you are typing.** Any input, textarea, select or rich-text field swallows the keys. Typing
"job" in a card title does not navigate anywhere.

**Never while a dialog is open.** With a card open, the command palette showing, or a menu expanded, that
overlay owns the keyboard. ++esc++ closes it and hands the keys back.

**Navigation needs the board view.** The `hjkl` card navigation applies to the board presentation. In the
[table view](moving-work.md#table-view), use normal tab and scroll behaviour.

!!! note "Modifier chords are never card shortcuts"

    Anything held with ++ctrl++, ++cmd++ or ++alt++ is ignored by the board handler. So ++ctrl+k++
    reaches the palette, and your browser's own shortcuts keep working.

## A worked example

Triage a board without touching the mouse:

1. ++j++ ++j++ to reach the third card in `todo`
2. ++o++ to open it, read it, ++esc++ to close
3. ++shift+arrow-right++ to start it
4. ++n++ to add the follow-up card you just thought of
5. ++ctrl+k++, type "needs human", to see what is waiting on you

## Recap

- ++question++ shows the list in the app.
- ++j++ ++k++ ++h++ ++l++ to move focus, ++shift+arrow-left++ and ++shift+arrow-right++ to move the card.
- ++enter++ or ++o++ to open, ++e++ to edit, ++n++ to create.
- ++ctrl+k++ for the command palette, which reaches everything else.
- Single keys never fire while you are typing or while a dialog is open.

That is the end of the user guide. From here, [set up the CLI](../cli/index.md) to drive the same board
from a terminal, or [wire up an agent](../agents/index.md).
