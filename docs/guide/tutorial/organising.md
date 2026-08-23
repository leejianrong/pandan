<!--
title: "Organising"
description: Labels, saved views, cycles and card templates, and when each one is the right tool.
-->

# Organising

Four tools for keeping a board legible once it has more than a screenful of cards.

## Labels

A label is a coloured tag, scoped to one board. A card can carry any number.

```bash
pandan label create "bug" --color '#dc2626'
pandan label list
pandan create "Fix the warmup message" --label 3 --label 7
```

Labels attach by id rather than by name, which is awkward by hand and deliberate for scripts. `label
list` gives you the ids, and how many cards carry each one.

### Managing labels in the browser

Open the menu and choose **Labels** to see the board's labels, create one, rename or recolour an
existing one, and delete one. Each row shows how many cards carry the label, because deleting it
removes it from all of them.

Renaming and recolouring are safe: the label keeps every card it was attached to. Only deleting
detaches it. From the command line the same edit is:

```bash
pandan label update 3 --name "defect"      # rename, colour untouched
pandan label update 3 --color '#0ea5e9'    # recolour, name untouched
```

Pass only what you want to change — omitting a field leaves it alone.

!!! warning "Updating labels replaces the whole set"

    On a card update, the labels you pass become the card's labels. They are not added to what is
    already there.

    ```bash
    pandan update KAN-601 --label 3          # card now has ONLY label 3
    pandan update KAN-601 --label 3 --label 7  # pass the full set you want
    ```

Use labels for properties that cut across work: `bug`, `security`, `needs-design`, `good-first-card`.
Use an [epic](epics.md) for a body of work with an end.

## Saved views

A view is a named query. Anything you can filter the board by, you can save and come back to.

```bash
pandan view create "My urgent work" --assignee claude --priority urgent --sort -due_date
pandan view list
pandan view delete 2
```

In the UI, filter the board how you like, then save it from the view switcher.

Views worth having on almost any board:

- **Needs a human**, filtered on the needs-human flag. The queue of things waiting on you.
- **Overdue**, for anything past its due date and not done.
- **Mine**, filtered by assignee.
- **Unestimated**, if you use story points and care that they are filled in.

A view is a query, not a container. It has no contents of its own, so deleting one never touches a
card, and a card can show up in as many views as match it.

## Cycles

A cycle is a time-boxed iteration. A sprint, if that is your word for it.

```bash
pandan cycle create "Sprint 12" --starts-on 2026-08-11 --ends-on 2026-08-25
pandan cycle list
pandan create "Ship the docs" --cycle 3
pandan list --cycle 3
```

A card belongs to zero or one cycle, the same way it belongs to zero or one epic. The two are
independent: a card can be in Sprint 12 and under the Onboarding epic at once, which is usually what you
want, because an epic spans cycles.

Cycles get their own metrics, so you can ask how one iteration went rather than reading whole-board
numbers:

```bash
pandan cycle metrics 3
```

!!! info "Nothing happens automatically at the end of a cycle"

    A cycle ending does not move, close or roll over its unfinished cards. The dates are there to scope
    reporting, not to enforce a process. Carrying work forward is a decision you make, not one the board
    makes for you.

## Templates

A template is a named set of cards you can stamp onto a board repeatedly. Good for a checklist that
recurs.

```bash
pandan template create "Release checklist" --cards '[
  {"title": "Bump the version"},
  {"title": "Run the full suite"},
  {"title": "Tag the release"},
  {"title": "Verify production"}
]'

pandan template list
pandan template apply 3      # creates all four cards on the board
pandan template delete 3
```

Applying a template creates real, independent cards. There is no ongoing link back to the template, so
editing the template later does not touch cards you already created, and editing those cards does not
change the template.

Templates are capped at 200 cards, checked when you create one and again when you apply it.

## Picking the right one

| You want to | Use |
| --- | --- |
| Tag a property that cuts across work | Label |
| Track a body of work toward completion | [Epic](epics.md) |
| Scope reporting to a time box | Cycle |
| Recreate the same set of cards repeatedly | Template |
| Come back to a filter you use often | View |

## Recap

- Labels attach by id, and a *card* update replaces the whole set — while a *label* update
  (`pandan label update`, or the browser's Labels screen) only changes the fields you pass.
- Views are saved queries with no contents; deleting one is safe.
- A card has at most one cycle and at most one epic, independently.
- Cycles scope reporting. They do not enforce anything at the end date.
- Applied templates create independent cards with no link back.

Next: [working together](collaboration.md).
