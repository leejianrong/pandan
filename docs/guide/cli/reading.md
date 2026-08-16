<!--
title: "Reading the board"
description: Query cards with filters, full-text search and sorting, then read flow metrics, the activity feed, and your notification inbox.
-->

# Reading the board

Reading is where you will spend most of your time, and where the token cost lives if an agent is
doing the reading. This page covers what to ask for. [Output formats](output-formats.md) covers how to
ask for less of it.

## The whole board at a glance

```console
$ pandan overview
https://simple-kanban-jian.fly.dev · board 5 · open cards (todo, in_progress):
KAN-591	todo	pandan overview builds a list envelope in-handler	pts=2
KAN-595	todo	Bake the git revision into the app image	pts=2
help: pandan list --column todo
help: pandan next --claim
8 cards · 8 todo · 0 in_progress · 0 done · 1 needs-human
```

`overview` is what bare `pandan` prints. It shows only open work (`todo` and `in_progress`), which is
almost always the question you actually have.

## Listing and filtering cards

```bash
pandan list                          # every card on the default board
pandan list --column todo
pandan list --assignee claude
pandan list --priority high
pandan list --epic EPIC-4            # id or ticket both work
pandan list --cycle 3
pandan list --label 7
pandan list --needs-human            # flagged for a human
pandan list --overdue                # past due and not done
pandan list --due-before 2026-09-01
pandan list --board 7                # another board, ignoring the default
```

Filters combine, and they are ANDed:

```bash
pandan list --column in_progress --assignee claude --priority high
```

### Full-text search

`--q` searches titles and descriptions. It takes a small query grammar rather than a bare string:

```bash
pandan list --q "cursor pagination"      # both terms, ANDed
pandan list --q '"exact phrase"'         # quoted, as a phrase
pandan list --q 'webhook -github'        # webhook, excluding github
```

Results rank by relevance unless you pass `--sort`.

!!! note "Search is rate limited"

    Full-text search and `metrics` are classified as expensive on the server and get a tighter rate
    limit than ordinary reads. In a loop, prefer a filter over a search.

### Sorting

```bash
pandan list --sort -priority,position
pandan list --sort=-updated_at              # the equals form works too
```

Sort keys: `position`, `priority`, `due_date`, `created_at`, `updated_at`, `story_points`, `assignee`,
`title`, `column`, `id`. A `-` prefix reverses. Sort keys choose the **order of rows**; to choose which
**columns print**, use `--fields`.

### Limiting and paging

```bash
pandan list --column todo --limit 5
```

When there is more to read, the output ends with a cursor:

```
(more — next cursor: MjAyNi0wOC0wMVQwOTo1Mzo1My40ODA0OTYrMDA6MDB8NDM5)
```

Pass that value straight back as `--cursor` to get the next page, keeping the same filters:

```bash
pandan list --column todo --limit 5 --cursor MjAyNi0wOC0wMVQwOTo1Mzo1My40ODA0OTYrMDA6MDB8NDM5
```

Repeat until no cursor line is printed — that is the last page.

!!! note "Carry your filters forward"

    The cursor is a position in the result, not a saved query. Re-send the same `--column` / `--q` /
    `--limit` you used for the first page; a cursor pasted onto a different filter set pages through a
    different result.

!!! warning "`--cursor` needs the default ordering"

    Paging is a keyset over `(updated_at, id)`, so the API rejects `--cursor` alongside `--sort` or a
    full-text `--q` (both reorder the result), and alongside `--refs` (a batch read is already bounded
    by its 100-selector cap). Drop the flag or drop the cursor.

## One card in detail

```console
$ pandan get KAN-591
```

`get` returns everything: description, labels, dependencies both ways, work links, priority, due date,
the needs-human flag and its note, and timestamps. Long text is truncated by default. Add `--full`
for the whole thing.

```bash
pandan get KAN-591 --full
pandan get 591              # numeric id works as well as the ticket
```

### Many cards at once

When you already know which cards you want, `--refs` reads them in **one** request instead of one
`get` each. Ids and tickets can be mixed freely:

```bash
pandan list --refs KAN-12,45,KAN-9
```

This matters when something resolves a list of references — rendering the `[[KAN-12]]` links in a
note, building a report, or an agent following up on a handful of tickets. Forty refs is one request
rather than forty.

A selector that matches nothing is left out of the results and listed separately, so one bad
reference never blanks the whole answer:

```console
$ pandan list --refs KAN-12,KAN-404
KAN-12	todo	Cursor pagination	pts=3
(unresolved: KAN-404)
```

`unresolved` covers every reason a card did not come back — it never existed, it is in the trash, or
it belongs to someone else. Those are deliberately not distinguished: saying "that one exists but is
not yours" would tell you something about a board you cannot see.

A few limits worth knowing:

- **100 selectors** per request. Over that is an error, not a quietly shortened list.
- **`--refs` cannot be combined with `--limit`.** A truncated page would make real cards look
  missing, and you would have no way to tell.
- A malformed selector (`--refs oops`) is an error rather than an unresolved one, so a typo cannot
  masquerade as a deleted card.

Combine it with filters to ask narrower questions:

```bash
pandan list --refs KAN-12,KAN-45,KAN-9 --column done   # which of these are finished?
```

## Flow metrics

```console
$ pandan metrics
board 5  (since: all time)
throughput:  90 done
cycle time:  avg 48m47s  median 21m7s  p90 39m23s  (n=83)
aging WIP:   0 in progress  avg -  max -
by assignee:
  agent:cli-ergonomics	done 4	wip 0
  agent:cli-readme	done 2	wip 0
```

Four things, all derived server-side:

- **throughput**, how many cards reached `done`
- **cycle time**, how long they took, as average, median and p90, with the sample size
- **aging WIP**, how long the cards currently in progress have been sitting there
- **by assignee**, a done and in-progress count per person or agent

Useful for a standup, and useful for spotting an agent that claimed something and stalled.

## Activity feed

```console
$ pandan activity --limit 4
2026-08-01T11:02:34Z	leejianrong2@gmail.com	created	created KAN-596: ci.yml declares an 'app' paths-filter output…
2026-08-01T11:01:43Z	leejianrong2@gmail.com	moved	moved KAN-584 from in_progress to done
(more — next cursor: MjAyNi0wOC0wMVQxMDozNzowNy43ODY3MzErMDA6MDB8MTM4MA==)
4 activity rows
```

Newest first. Filter by who or what:

```bash
pandan activity --actor claude
pandan activity --action moved
pandan activity --limit 50 --cursor MjAyNi0wOC0wMVQxMDoz…
```

`--cursor` works the same way it does on [`list`](#limiting-and-paging): pass back the value from the
previous page's cursor line.

This is the audit trail. When a card is in a state nobody expects, the activity feed says who put it
there, whether that was a person or an agent.

## Notification inbox

Notifications are per user, not per board, so these commands take no `--board`.

```bash
pandan notify list              # unread and read
pandan notify list --unread
pandan notify read 42           # mark one as read
```

!!! tip "The inbox is not paginated"

    `notify list` returns everything, and on a busy account that is a large payload. Use `--unread`,
    and `--fields` to cut it down:

    ```bash
    pandan notify list --unread --fields id,created_at,body
    ```

## Recap

```bash
pandan overview                                  # open work
pandan list --column todo --sort -priority       # a filtered, ordered query
pandan list --q '"cold start"'                   # search
pandan get KAN-591 --full                        # one card, complete
pandan metrics                                   # throughput and cycle time
pandan activity --actor claude                   # who did what
pandan notify list --unread                      # your inbox
```

Reads are cheap to shape and expensive to leave raw. Next: [output formats](output-formats.md), which
is where you cut a read down to the fields you actually need.
