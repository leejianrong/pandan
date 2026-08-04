<!--
title: "Dashboard"
description: Read throughput, cycle time and aging work in progress, and know what those numbers do and do not tell you.
-->

# Dashboard

The dashboard is four derived measurements. Nothing here is entered by hand, so nothing can be stale or
gamed by forgetting to update it.

![The dashboard](../assets/images/dashboard-light.png#only-light)
![The dashboard](../assets/images/dashboard-dark.png#only-dark)

The same numbers from the CLI:

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

## Throughput

How many cards reached `done`. A count, over the period shown.

Useful as a trend, close to meaningless as an absolute. Cards are not a uniform size, so 20 done this
week against 10 last week might mean twice the work or twice the splitting.

## Cycle time

How long cards took to get from started to done, as an average, a median, and a p90, with the sample
size in brackets.

Read the median first. The average is pulled around by one card that sat for three weeks, and on a small
board a single outlier moves it a lot. The gap between the median and the average tells you how lumpy
your flow is, and the p90 tells you what a bad case actually looks like, which is usually the number
worth quoting to someone waiting on an estimate.

!!! note "Watch the sample size"

    The `(n=83)` matters. Cycle time over five cards is an anecdote. The measurement is honest about how
    much it is based on, so use that.

## Aging work in progress

How long the cards currently in `in_progress` have been sitting there, as an average and a maximum.

This is the number to act on. Throughput and cycle time describe the past; aging WIP describes something
you can fix today. A card aging well past your typical cycle time is either bigger than it looked, or
blocked, or forgotten.

!!! tip "A high maximum usually means an abandoned claim"

    When agents work a board, the common cause is an agent that claimed a card and stopped, because its
    session ended. The card stays in `in_progress` with an assignee, and nothing is happening.

    Cross-reference with [activity](collaboration.md#activity) to see when it was last touched:

    ```bash
    pandan list --column in_progress --fields ticket,title,assignee
    pandan activity --actor <the assignee>
    ```

## By assignee

A done and in-progress count per person or agent handle.

Since assignee is free text, this is only as good as your naming. A board where the same agent has been
called `claude`, `agent:claude` and `claude-code` reports three contributors. Pick a convention early.

Read it for distribution, not for performance. Someone with a high in-progress count and a low done
count is either taking on too much at once or stuck, and either way that is worth asking about rather
than concluding.

## Scoping to a cycle

Whole-board metrics blur across every iteration. To ask how one went:

```bash
pandan cycle metrics 3
```

Same four measurements, restricted to that cycle's cards.

## Reading it honestly

The numbers describe flow, not value. They cannot see that the biggest card was thrown away, or that
`done` on this board means merged while on the next one it means deployed.

Two habits that keep the dashboard useful:

**Compare against yourself, not a benchmark.** There is no correct cycle time. There is only yours last
month.

**Treat every number as a prompt to look, not as a conclusion.** Aging WIP tells you which card to open.
It does not tell you what is wrong with it.

!!! warning "Metrics reads are rate limited"

    `metrics` is classed as expensive on the server, alongside full-text search, so it gets a tighter
    limit than ordinary reads. Do not poll it in a loop from a script.

## Recap

- Throughput counts cards, not effort. Read it as a trend.
- Prefer the median cycle time to the average, and check the sample size.
- Aging WIP is the actionable one, and a high maximum often means an abandoned agent claim.
- Per-assignee numbers are only as good as your naming convention.
- Scope to a cycle when whole-board numbers are too blurred to mean anything.

Next: [keyboard shortcuts](keyboard-shortcuts.md).
