<!--
title: "Writing to the board"
description: Create and edit cards, run the agent claim flow, and manage epics, labels, cycles, templates, dependencies, links and comments.
-->

# Writing to the board

Every write goes through the same API the web UI uses, so nothing you do here is second-class. The
server is authoritative: a write returns the stored row, and that is what you should trust rather than
what you sent.

## Cards

### Create

The title is positional. Everything else is a flag.

```bash
pandan create "Add a cursor flag to list"
pandan create "Add a cursor flag to list" \
  --description "list prints next_cursor but cannot consume it" \
  --column todo \
  --points 2 \
  --priority high \
  --assignee claude \
  --epic EPIC-4 \
  --due 2026-09-01
```

Story points are constrained to `1`, `2`, `3`, `5`, `8`, `13`, or unset. Anything else is rejected with
a `422` before it reaches the database.

Labels attach by id, and the flag repeats:

```bash
pandan create "Fix the warmup message" --label 3 --label 7
```

### Edit

```bash
pandan update KAN-591 --priority high
pandan update KAN-591 --title "A clearer title" --points 3
pandan update KAN-591 --assignee claude --due 2026-09-15
```

`--label` on `update` **replaces** the card's labels rather than adding to them, so pass the full set
you want.

!!! warning "`update` cannot move a card"

    Column and position changes go through `move`, not `update`. This split is deliberate: moving a
    card has to renumber the positions in both the source and target columns, which is a different
    operation from editing a field.

### Move

```bash
pandan move KAN-591 in_progress
pandan move KAN-591 done
pandan move KAN-591 todo --position 0     # to the top of the column
```

Without `--position` the card is appended to the end of the target column. With one, it is clamped
into that index and the surrounding cards renumber.

The three columns are `todo`, `in_progress` and `done`.

### Delete

```bash
pandan delete KAN-591
```

Deleted cards go to the board's trash rather than vanishing, and can be restored from the web UI.

## The agent flow

Four verbs exist because an agent picking up work needs to do it without racing another agent.

### Take the next card

```bash
pandan next                       # what should I work on?
pandan next --claim               # take it, atomically
pandan next --claim --assignee claude
pandan next --priority high --label 3
```

`next` picks the highest-priority ready card, skipping anything blocked by an unfinished dependency.
With `--claim` it moves the card to `in_progress` and assigns it in one call, so two agents running
`next --claim` at the same time cannot both get the same card.

### Claim a specific card

```bash
pandan claim KAN-591 --assignee claude
```

`--assignee` is required here. There is no default, on purpose: a claim with no owner is not a claim.

### Hand it back to a human

```bash
pandan needs-human KAN-591 --note "Needs a decision on whether to break the flag contract"
pandan resolve KAN-591
```

`needs-human` flags the card and records the note. The card shows up in `pandan list --needs-human`
and is highlighted in the web UI. `resolve` clears the flag once a human has dealt with it.

This is the honest exit for an agent that has hit a judgement call. It is better than guessing, and
better than silently stopping.

## Bulk writes

```bash
pandan batch-create '[{"title":"First"},{"title":"Second","points":3}]'
pandan batch-update '[{"id":591,"priority":"high"},{"id":595,"assignee":"claude"}]'
```

Both take a JSON array, and `-` reads it from stdin:

```bash
jq -n '[{title:"From a pipeline"}]' | pandan batch-create -
```

!!! danger "They behave differently on failure"

    `batch-create` is **fail-fast and not atomic**. If item 4 of 6 is invalid, the first three are
    already created. `batch-update` **is** atomic: either every patch applies or none does.

    Check `batch-create` results before retrying, or you will create duplicates.

Defaults cap a batch at 500 items.

## Epics

An epic groups stories. It has no column, no position and no points, because an epic is not a card.

```bash
pandan epic list
pandan epic get EPIC-4
pandan epic create "Onboarding flow" \
  --description "New-user first-run experience" \
  --lead claude \
  --target-date 2026-10-01
pandan epic update EPIC-4 --name "Onboarding"
pandan epic delete EPIC-4
```

Hang a story off an epic at creation or later:

```bash
pandan create "Landing page" --epic EPIC-4
pandan update KAN-601 --epic EPIC-4
```

Deleting an epic detaches its stories rather than deleting them.

## Boards

```bash
pandan board list
pandan board get 5
pandan board create "Q4 planning"
pandan board create "Engineering" --key ENG
pandan board update 5 --name "Pandan Roadmap"
pandan board update 5 --key PDN
pandan board delete 5
```

Every board has a **key** — a short prefix like `ENG`, two to ten characters, an uppercase letter
followed by uppercase letters and digits. Omit `--key` and one is derived from the name, so a create
never fails on naming. Keys are unique among *your* boards, not globally: another user can hold `ENG`
too. `KAN` and `EPIC` are reserved, and a key you already use is a `409`.

!!! danger "Deleting a board deletes its cards"

    Cards and epics cascade with the board. There is no undo.

## Labels, views and cycles

**Labels** are per board, with an optional colour:

```bash
pandan label list
pandan label create "bug" --color mulberry   # a palette token
pandan label update 7 --name "defect"        # rename; colour untouched
pandan label update 7 --color sky            # recolour; name untouched
pandan label delete 7
```

A colour is either a **palette token** — `sky`, `blue`, `cyan`, `fuchsia`, `mulberry`, `pink`, `ink` —
or a hex like `#0ea5e9`. Anything else is a `422`, and the error lists the tokens. Prefer a token:
each one is defined separately for the light and the dark theme, so it stays readable in both, which
a single hex cannot do. Omit `--color` and you get `ink`.

**Views** are saved queries. Anything you can pass to `list` you can save:

```bash
pandan view create "My urgent work" --assignee claude --priority urgent --sort -due_date
pandan view list
pandan view delete 2
```

**Cycles** are iterations or sprints:

```bash
pandan cycle create "Sprint 12" --starts-on 2026-08-11 --ends-on 2026-08-25
pandan cycle list
pandan cycle update 3 --name "Sprint 12 (extended)" --ends-on 2026-09-05
pandan create "Ship the docs" --cycle 3
```

`cycle update` is a partial edit: pass only what changes, and the cycle keeps its cards. Deleting a
cycle detaches them.

## Templates

A template is a named set of cards you can stamp out repeatedly, which is useful for a checklist that
recurs.

```bash
pandan template create "Release checklist" \
  --cards '[{"title":"Bump the version"},{"title":"Tag the release"},{"title":"Verify prod"}]'
pandan template list
pandan template apply 3      # creates all of its cards on the board
pandan template delete 3
```

Templates are capped at 200 cards by default, enforced when you create one and again when you apply
it.

## Dependencies, links and comments

**Dependencies** record that one card is blocked by another. `next` respects them.

```bash
pandan dep add KAN-591 --blocked-by KAN-439
pandan dep list KAN-591                     # both blocked_by and blocks
pandan dep rm KAN-591 --blocked-by KAN-439
```

**Links** attach a URL to a card, which is how an agent records the pull request it opened:

```bash
pandan link add KAN-591 --label "PR #266" --url https://github.com/leejianrong/pandan/pull/266
pandan link rm KAN-591 4
```

**Comments** are notes on a card:

```bash
pandan comment add KAN-591 --body "Confirmed: activity takes --cursor, list does not."
pandan comment list KAN-591
```

## Recap

A complete agent cycle, start to finish:

```bash
pandan next --claim --assignee claude                      # take work
pandan comment add KAN-601 --body "Starting on this"
pandan link add KAN-601 --label "PR #267" --url https://…  # record the PR
pandan needs-human KAN-601 --note "Needs a call on X"      # if stuck
pandan resolve KAN-601                                     # human answered
pandan move KAN-601 done                                   # finish
```

Next: [output formats](output-formats.md) to control how much comes back, or
[errors and exit codes](errors-and-exit-codes.md) to handle failure in a script.
