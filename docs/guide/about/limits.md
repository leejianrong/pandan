<!--
title: "Current limits"
description: What Pandan does not do yet, stated plainly, so you can tell whether it fits before you commit to it.
-->

# Current limits

An honest list of what Pandan does not do. Better to know now than to find out after you have moved your
work onto it.

## Collaboration

**A board has exactly one owner.** Ownership does not transfer from the interface. If the owner's account
goes away, the board's `owner_id` is cleared rather than reassigned.

**Members are invited by email or user id, and they need an account on the same instance.** On the hosted
board that means they have to have logged in with GitHub at least once before you can add them.

**There are three roles and no finer control.** `viewer`, `editor`, `owner`. You cannot grant write access
to one column, or hide a specific card, or make someone an editor who cannot delete.

**Membership is visible to all members.** A viewer can see the full member list. It is not secret.

## Cards and boards

**A card cannot move between boards.** There is no move-to-board operation, and adding one is not trivial,
because ticket numbers come from per-table sequences rather than per board. Recreating the card is the
current answer, and it gets a new number.

**Three columns only.** `todo`, `in_progress`, `done`, with no way to add a fourth from the interface. The
storage would allow it; the product does not expose it.

**Assignee is free text with no validation.** Convenient for agent handles, and it means `claude`,
`Claude` and `agent:claude` are three different assignees as far as reporting is concerned.

**No subtasks.** A card has no children. Use an [epic](../tutorial/epics.md) for a grouping, or
[dependencies](../tutorial/collaboration.md#dependencies) for ordering.

**No attachments.** You can attach a labelled URL, but not a file.

**No recurring cards.** [Templates](../tutorial/organising.md#templates) let you stamp a set out again by
hand, which is the closest thing.

## Concurrency and real-time

**Last write wins, with no warning.** Two people editing the same card both succeed and the later write
persists. Nothing tells either of them it happened.

**No live updates.** The board does not push changes. You see someone else's edit when you next load or
act. There is no websocket and no polling.

## Notifications

**The inbox is not paginated.** `list_notifications` and `pandan notify list` return everything, which on a
busy account is a large payload. Filter with `--unread` and `--fields`.

**The outbound webhook has no retry queue.** One attempt by default, fired after commit, and a failure is
logged and dropped. Treat it as a notification channel rather than a reliable event log. For an audit trail
use [activity](../tutorial/collaboration.md#activity).

## The CLI

**A cursor does not carry your filters.** `pandan list --cursor …` resumes a position in the result, not
a saved query, so every page has to re-send the same filters. It also needs the default ordering: the
API rejects `--cursor` alongside `--sort`, a full-text `--q`, or `--refs`.

**There is no `pandan me`.** The API has `GET /api/v1/me`, and the CLI has no verb for it. Use `pandan
config show` to confirm your configuration, or `pandan board list` to confirm your token works.

**A fresh install points at `localhost:8000`.** With no configuration, commands fail against a server that
is not there. `warmup` names the origin it tried and exits `7` rather than calling it a cold start, but
every other verb still reports a plain transport failure. Set `--api-url` first.

## Operations

**Rate limit counters are per process and in memory.** They reset on restart and are not shared between
instances, so several replicas each enforce their own limits.

**Migrations are not run automatically.** Applying them is a separate step you own.

**No backup mechanism.** Everything is in Postgres; back up the database.

**The content security policy is report-only.** It reports violations and blocks nothing, because the
interactive API docs would break under a strict policy. Enforcing it is a rename of one header plus
self-hosting that bundle.

## Scale

Pandan is built for a board a person or a small team can read, running as a single process against one
Postgres database. It has not been designed or tested for thousands of cards, hundreds of concurrent users,
or multi-region deployment.

That is a positioning statement, not a benchmark. If you need those things, you need something else.

## What this list is for

Everything here is a current state rather than a permanent stance. Some of it is on the roadmap, some was a
deliberate trade recorded in [design decisions](design-decisions.md), and some is simply not built.

If one of these blocks you, the board is public and the repository takes issues:
**[github.com/leejianrong/pandan/issues](https://github.com/leejianrong/pandan/issues)**
