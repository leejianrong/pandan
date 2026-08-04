<!--
title: "Epics"
description: Group related cards under an epic, and read its progress and health.
-->

# Epics

An epic groups related cards. "Onboarding flow" with six stories under it, rather than six loose cards
you have to remember belong together.

## An epic is not a card

This is the thing to get straight, because it explains every difference that follows.

An epic has a name, a description, a lead and a target date. It does **not** have a column, a position,
an assignee, or story points. It never sits in `todo`. You cannot drag it. It is a separate kind of
thing stored in its own table, with its own numbering.

So epics get `EPIC-1`, `EPIC-2`, and cards get `KAN-1`, `KAN-2`, from independent sequences. `KAN-1` and
`EPIC-1` both existing is normal.

## Creating one

Open **Epics** from the menu and add one there.

```bash
pandan epic create "Onboarding flow" \
  --description "New-user first-run experience" \
  --lead claude \
  --target-date 2026-10-01
```

**Lead** is free text, like a card's assignee, so it holds a person or an agent handle.

**Target date** is what drives the health indicator below. Without one, an epic can be behind but cannot
be late.

## Linking cards

A card belongs to zero or one epic. Set it on the card, at creation or later:

```bash
pandan create "Landing page" --epic EPIC-7
pandan update KAN-601 --epic EPIC-7
```

In the UI, pick the epic from the card form. To see an epic's stories, filter the board by it, or open
the epic.

```bash
pandan list --epic EPIC-7
```

## Progress and health

Each epic reports **progress** as a count and a percentage: how many of its cards are `done` out of the
total. It is derived, so it is always current and there is nothing to update by hand.

**Health** is one of three values:

| Health | Meaning |
| --- | --- |
| `on_track` | Progressing, with time left before the target date |
| `at_risk` | The target date is close relative to how much is left |
| `overdue` | Past the target date with work outstanding |

Health depends on the target date. An epic without one has nothing to be measured against.

!!! tip "Health is a prompt, not a verdict"

    It compares remaining work against remaining time and nothing else. It does not know that the last
    two cards are trivial, or that one of them is blocked on a decision nobody has made. Treat `at_risk`
    as a reason to look, not as a fact about the project.

## Deleting an epic

Deleting an epic **detaches** its cards. It does not delete them.

```bash
pandan epic delete EPIC-7
```

The cards stay exactly where they are, with their epic link cleared. This is deliberate: deleting a
grouping should not destroy the things grouped, and the alternative (refusing to delete an epic that
still has cards) makes tidying up harder than it needs to be.

Deleted epics go to **Trash** and can be restored.

## Epics or labels?

Both group cards, so the distinction is worth stating.

An **epic** is a body of work with an end. It has a target date, tracks progress toward completion, and a
card belongs to at most one. Use it for "the thing we are building".

A **label** is a tag. It has no progress, no end, and a card can carry several. Use it for a property
that cuts across the work: `bug`, `needs-design`, `security`.

If you find yourself wanting two epics on one card, you wanted a label.

## Recap

- An epic has no column, position, assignee or points. It is not a card.
- `EPIC-` and `KAN-` numbers are independent.
- A card links to zero or one epic.
- Progress is derived. Health needs a target date to mean anything.
- Deleting an epic detaches its cards rather than deleting them.
- One thing per card means epic; several properties means labels.

Next: [organising](organising.md).
