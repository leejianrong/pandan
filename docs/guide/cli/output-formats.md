<!--
title: "Output formats"
description: Choose between human, json and toon output, cut a read down with --fields, and control text truncation.
-->

# Output formats

Three formats, and two flags that change how much comes back. If an agent is doing the reading, this
page is the one that matters, because an unshaped read is where the tokens go.

## human, the default

Tab-separated rows with no keys. It is the cheapest output the CLI produces, and it is designed to be
readable by a person and `cut`-able by a script.

```console
$ pandan list --column todo --limit 2
KAN-305	todo	(human) Cloudflare edge setup for prod	pts=-
KAN-424	todo	V41 · Rebrand deploy identity	pts=5
2 cards · 2 todo · 0 in_progress · 0 done
```

Because the fields are tab-separated, `cut -f1` gets you ticket numbers and nothing else:

```bash
pandan list --column todo | cut -f1
```

## json

```console
$ pandan list --column todo --limit 1 --json
{
  "cards": [
    {
      "id": 305,
      "ticket_number": "KAN-305",
      "board_id": 5,
      "title": "(human) Cloudflare edge setup for prod",
      "column": "todo",
      "position": 0,
      "story_points": null,
      "assignee": "leejianrong2@gmail.com",
      "epic_id": 46,
      "priority": "medium",
      "needs_human": false,
      "labels": [],
      "blocked_by": [],
      "blocks": [],
      "blocked": false,
      "links": []
    }
  ],
  "next_cursor": "MjAyNi0wOC0wMVQwOTo1Mzo1My40ODA0OTYrMDA6MDB8MzA1",
  "summary": { "count": 1, "todo": 1, "in_progress": 0, "done": 0, "needs_human": 0 }
}
```

This is the raw API envelope, indented. `--json` is a permanent alias for `--format json`, and if you
pass both, `--format` wins.

!!! warning "List verbs return an envelope, not a bare array"

    The cards live under a `cards` key alongside `next_cursor` and `summary`. So it is:

    ```bash
    pandan list --json | jq -r '.cards[].ticket_number'
    ```

    not `jq '.[]'`. The same applies to the other list verbs with their own key.

## toon

TOON prints a uniform array's field names once in a header instead of repeating them on every row, so
it costs much less than JSON on nested payloads while staying structured.

```console
$ pandan get KAN-591 --format toon
id: 591
ticket_number: KAN-591
board_id: 5
title: "pandan overview builds a list envelope in-handler"
column: todo
position: 4
story_points: 2
assignee: null
priority: none
needs_human: false
labels: []
blocked_by: []
blocks: []
```

Reach for it on the payloads that nest: `get`, `metrics`, `activity`, `epic list`, `dep list`, and
template or view reads. On a flat list, plain `human` output is still cheaper, because it has no keys
at all.

Rough guide:

| Payload | Cheapest | Why |
| --- | --- | --- |
| A flat list of cards | `human` | No keys, one row per card |
| One card in detail | `toon` | Structured, no repeated keys |
| `metrics`, `activity` | `toon` | Nested, uniform rows |
| Anything a program parses | `json` | Only format with a stable schema |

## --fields

Print only the columns you need. This is the single biggest saving on a list read.

```console
$ pandan list --column todo --fields ticket,title,priority --limit 3
KAN-305	(human) Cloudflare edge setup for prod	medium
KAN-424	V41 · Rebrand deploy identity	low
KAN-439	(human) Migrate off Fly+Neon to a self-hosted k8s homelab	low
```

Values print bare and tab-separated, in the order you asked for them.

!!! note "`--fields` shapes human output only"

    It has no effect under `--format json` or `--format toon`, which always return the full envelope.
    Sorting is separate: `--sort` chooses the order of rows, `--fields` chooses which columns print.

## Truncation

Long free-text fields are cut at **500 characters** by default, with a hint saying how much was
dropped:

```
description: "Found by the KAN-583 agent as the FOURTH instance of the envelope family…
(truncated, 3127 chars total — use --full to see complete body)"
```

This applies to card and epic descriptions, comment and notification bodies, and attention notes. It
exists so that one `get` on a card with a long write-up cannot blow an agent's context window.

Turn it off for one command:

```bash
pandan get KAN-591 --full
```

Or change the limit globally:

```bash
export PANDAN_MAX_TEXT_CHARS=2000
export PANDAN_MAX_TEXT_CHARS=0      # unlimited
```

Truncation applies to `human`, `json` and `toon` alike, so a script that needs complete text has to
pass `--full` rather than assuming JSON is exempt.

## The summary line

Every list verb ends with a pre-computed aggregate:

```
42 cards · 12 todo · 5 in_progress · 25 done · 3 needs-human
```

`needs-human` appears only when it is non-zero. Under `--format json` or `toon` the same numbers ride
the payload as a `summary` object.

!!! info "It counts the rows returned, not the board"

    Under a filter or a `--limit`, the summary describes what came back. `pandan list --column todo
    --limit 3` reports `3 cards`, not the size of your `todo` column.

## Recap

```bash
pandan list --fields ticket,title,assignee        # cheapest useful read
pandan get KAN-591 --format toon                  # structured, no key repetition
pandan list --json | jq -r '.cards[].id'          # for a program
pandan get KAN-591 --full                         # complete text
```

Shape the read before you widen it. `--fields` on a list and `toon` on a detail read cover almost
every case.
