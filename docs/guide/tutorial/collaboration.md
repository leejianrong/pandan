<!--
title: "Working together"
description: Comments, dependencies, work links, the needs-human flag, notifications, the activity trail, and the trash.
-->

# Working together

This is the part of the board that carries context rather than status: why a card is stuck, what it is
waiting on, and who needs to look at it. It matters most when some of the work is being done by agents,
because an agent cannot tap you on the shoulder.

## Comments

Notes on a card, in order.

```bash
pandan comment add KAN-591 --body "Confirmed against prod: the cursor round-trips, page 2 is new cards."
pandan comment list KAN-591
```

Comments are where an agent explains itself. A card that moved to `in_progress` and then sat there is a
mystery; the same card with "starting on this, PR shortly" and then "root cause is X" is a status report.

## Dependencies

Record that one card cannot proceed until another is finished.

```bash
pandan dep add KAN-601 --blocked-by KAN-591
pandan dep list KAN-601
pandan dep rm KAN-601 --blocked-by KAN-591
```

`dep list` shows both directions: what this card is **blocked by**, and what it **blocks**.

!!! tip "Dependencies change behaviour, not just appearance"

    A blocked card is skipped when an agent asks for the next thing to work on. So recording a blocker
    actually stops work being picked up, rather than just displaying a warning. It is the most useful
    single thing you can record on a card that is stuck.

Cards show a blocked indicator, so you can see at a glance which items in `todo` are not actually
available.

## Work links

Attach a labelled URL to a card: a pull request, a branch, a CI run, a design.

```bash
pandan link add KAN-591 --label "PR #266" --url https://github.com/leejianrong/pandan/pull/266
pandan link rm KAN-591 4
```

Both a label and a URL are required, because a bare URL on a card tells you nothing about why it is
there.

The habit worth building, for humans and agents alike: attach the link when the PR opens, not when the
work finishes. If a session dies halfway, the link is the only thing tying the card to the work.

## The needs-human flag

The most important thing on this page. It marks a card as waiting on a person, with a note saying what
the question is.

```bash
pandan needs-human KAN-591 --note "Two valid designs. Should list take --cursor like activity, or stay a one-shot query?"
pandan resolve KAN-591
```

![A card flagged as needing a human](../assets/images/v13-needs-human-light.png#only-light)
![A card flagged as needing a human](../assets/images/v13-needs-human-dark.png#only-dark)

Flagged cards are highlighted on the board and collect into a queue you can filter for:

```bash
pandan list --needs-human
```

`resolve` clears the flag once you have answered.

!!! tip "Write the note as a question"

    "Blocked on design" wastes the mechanism. "Should `list` take `--cursor` like `activity`, or stay a
    one-shot query?" can be answered in a sentence, and the card unblocks in a minute rather than after
    a meeting.

    This is the honest exit for an agent that has hit a judgement call. An agent that flags and explains
    is more useful than one that guesses, and much more useful than one that silently stops.

## Notifications

Your inbox, per user rather than per board.

```bash
pandan notify list
pandan notify list --unread
pandan notify read 42
```

Notifications are also the trigger for the outbound webhook, so if a board has one configured, creating
a notification fires a signed POST to your URL. That is how board events reach Slack or your own
service. See [boards](boards.md#board-settings).

!!! warning "The inbox is not paginated"

    `notify list` returns everything at once, which on a busy account is a large payload, over 14,000
    tokens in one measured case. Filter it:

    ```bash
    pandan notify list --unread --fields id,created_at,body
    ```

## Activity

The audit trail for a board, newest first.

```bash
pandan activity
pandan activity --actor claude
pandan activity --action moved
pandan activity --limit 50 --cursor <cursor from the previous page>
```

Each row is a timestamp, an actor, an action, and a summary:

```
2026-08-01T11:01:43Z	leejianrong2@gmail.com	moved	moved KAN-584 from in_progress to done
```

The actor is a person's email or an agent's handle, so the trail answers "who moved this" without
ambiguity about whether it was a human. When a card is in a state nobody expects, this is where you
look first.

Activity pages with a cursor, the same way [`pandan list`](../cli/reading.md#limiting-and-paging) does:
pass back the value from the previous page's cursor line.

## Trash

Deleted cards and epics land here rather than disappearing.

From **Trash** you can **restore**, which puts the item back with its ticket number intact, or **purge**,
which is permanent.

The exception is deleting a board, which takes its cards with it and does not go through the trash. See
[boards](boards.md#renaming-and-deleting).

## Recap

| To say | Use |
| --- | --- |
| Here is what I found | Comment |
| This cannot start until X is done | Dependency, which also stops agents picking it up |
| Here is the PR | Work link, attached as soon as it exists |
| I need a decision, and here it is | needs-human with a real question |
| Who changed this? | Activity |
| I deleted that by mistake | Trash |

Next: [dashboard](dashboard.md).
