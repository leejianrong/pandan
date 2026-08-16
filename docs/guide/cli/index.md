<!--
title: "Using the CLI"
description: What the pandan CLI is, how its commands are organised, and where to go for each task.
-->

# Using the CLI

`pandan` is a thin client over the REST API. Each subcommand maps to roughly one API call, which keeps
the API the single source of truth and stops the CLI from growing its own ideas about how a board
works.

It uses only `argparse` from the standard library, so the binary starts fast and has nothing to
configure beyond the three settings from [first steps](../first-steps.md).

## How the commands are organised

Card verbs are top level, because cards are what you touch most:

```bash
pandan list                  # query cards
pandan get KAN-12
pandan create "A new story"
pandan update KAN-12 --priority high
pandan move KAN-12 done
pandan delete KAN-12
```

Everything else is a nested group, so its verbs cannot collide with the card verbs:

```bash
pandan board list
pandan epic create --name "Onboarding"
pandan label list
pandan view list
pandan cycle list
pandan template list
pandan dep add KAN-12 KAN-9
pandan link add KAN-12 --label "PR #57" --url https://…
pandan comment add KAN-12 --body "Looked into this"
pandan notify list
pandan config show
pandan context status
```

One more top-level verb sits outside both groups, because it is about you rather than about a board:

```bash
pandan me                    # who your token authenticates as
```

Run `pandan --help` for the full list, or `pandan <group> --help` for one group.

## The full command map

| Group | Verbs | Covered in |
| --- | --- | --- |
| Cards | `list`, `get`, `create`, `update`, `move`, `delete` | [Reading](reading.md), [writing](writing.md) |
| Agent flow | `next`, `claim`, `needs-human`, `resolve` | [Writing](writing.md) |
| Bulk | `batch-create`, `batch-update` | [Writing](writing.md) |
| Boards | `board list/get/create/update/delete` | [Writing](writing.md) |
| Epics | `epic list/get/create/update/delete` | [Writing](writing.md) |
| Organising | `label`, `view`, `cycle`, `template` | [Writing](writing.md) |
| Card detail | `dep`, `link`, `comment` | [Writing](writing.md) |
| Reporting | `overview`, `metrics`, `activity` | [Reading](reading.md) |
| Inbox | `notify list/read` | [Reading](reading.md) |
| Setup | `login`, `config`, `context`, `warmup` | [Configuration](configure.md) |
| Identity | `me` | [Configuration](configure.md) |

## Two flags on every verb

**`--format {human,json,toon}`**, with `--json` as an alias for `--format json`. Both parse before or
after the subcommand, so `pandan --json list` and `pandan list --format json` are the same thing.

**`--full`** prints long free-text fields instead of truncating them at 500 characters.

Both are explained in [output formats](output-formats.md).

## What makes it agent-friendly

A few deliberate choices, which matter as much to a shell script as to an agent:

**Errors go to stdout, machine-readable.** One tab-separated row, or an `{"error": {…}}` object under
`--format json`. Nothing important is written to stderr, so a script never has to merge two streams.

**Exit codes distinguish causes.** `3` for unauthorized, `4` for forbidden, `5` for not-found, `6` for
conflict. See [errors and exit codes](errors-and-exit-codes.md).

**Every list ends with a summary.** Counts come pre-computed with the rows, so asking "how many are in
progress" never costs a second request.

**Commands suggest what comes next.** The `help:` lines in the output point at plausible follow-up
commands.

**Nothing ever prompts when stdin is not a terminal.** A verb that would ask a question fails instead
of hanging a CI job.

## Next

<div class="grid cards" markdown>

-   **[Configuration](configure.md)**

    Where settings come from, `login`, and the ambient context hook for agent sessions.

-   **[Reading the board](reading.md)**

    Filters, full-text search, sorting, metrics, and the activity feed.

-   **[Writing to the board](writing.md)**

    Creating and editing cards, epics, labels, cycles, dependencies, and comments.

-   **[Output formats](output-formats.md)**

    `human`, `json`, `toon`, plus `--fields` and truncation.

-   **[Errors and exit codes](errors-and-exit-codes.md)**

    The full code table and how to branch on it.

-   **[In CI](ci.md)**

    Warmup loops, tokens in CI, and patterns that do not wedge a pipeline.

</div>
