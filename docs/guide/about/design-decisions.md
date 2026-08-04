<!--
title: "Design decisions"
description: The choices behind Pandan's behaviour, in brief, with pointers to the architecture decision records in the repository.
-->

# Design decisions

Pandan behaves the way it does on purpose, and some of those choices are surprising until you know the
reason. This page covers the ones you are likely to bump into.

The full reasoning, including the alternatives that were rejected, lives in the architecture decision
records in the repository. They are engineering documents rather than user documentation, so they are not
rendered on this site:

**[github.com/leejianrong/pandan/tree/main/docs/adr](https://github.com/leejianrong/pandan/tree/main/docs/adr)**

## The API comes first

The rule is that the web UI may never do anything the API cannot. When a feature is added, the endpoint
comes first and the UI is wired to it afterwards.

This is why the CLI and MCP server are thin, and why an agent has genuine parity with a human rather than
a reduced subset. It is also why there is no hidden capability behind the browser.

## Last write wins

There is no locking, no version token, and no real-time push. Two people editing the same card both
succeed, and the later write persists.

The alternative for a board this size means either locking, which frustrates people, or conflict
resolution UI, which nobody enjoys, or websockets, which adds a whole class of failure. For a small team
board where genuine simultaneous edits are rare, last write wins is the honest trade.

The consequence is that clients re-read after writing rather than trusting their local copy, which is why
the UI refetches on every mutation and never shows an unconfirmed value.

## The server is authoritative, so there is no optimistic UI

Every change is sent, stored, and read back before the interface updates. Changes appear a beat later than
you clicked.

What you get for that beat is a board that cannot show you a value the database does not have. Given last
write wins, an optimistic UI would sometimes show you your own write after someone else's had already
replaced it.

## Moving is not editing

Column and position changes go through their own endpoint rather than a field update, because a move has to
renumber the cards around it in both the source and target columns. Editing a title does not. Collapsing
the two into one operation would mean every field edit carries move semantics it does not need.

## An epic is not a card

Epics live in a separate table with their own numbering, and have no column, position, assignee or points.

The alternative was one table with a type flag, which is tempting until every card query has to remember
to exclude epics, and every epic has nullable columns that mean nothing.

## Every principal is a real user

There is no service token and no agent credential type. A personal access token resolves to the user who
created it and is permission-checked identically.

Earlier versions did have a shared token list with a privileged bypass. It was removed, because a
credential that is not a user is a credential nobody can audit. The cost is that an agent's token carries
your access to every board you can reach, so mint one per agent and scope it with a default board.

## Three columns

`todo`, `in_progress`, `done`, and no way to add a fourth from the interface.

The storage does not impose this. The column is text with a database check rather than a rigid enum,
specifically so a value can be added later without a schema migration. The limit is a product decision
about keeping a board readable, and it is reversible.

## Reads truncate by default

Long text is cut at 500 characters with a size hint unless you ask for more.

This is the default rather than an option because the failure it prevents is expensive and silent: one card
with a long write-up filling an agent's context window on a single read. Making the safe behaviour the
default and the complete read explicit is the right way round.

## Breadth in the MCP surface, frozen

The MCP server has 49 tools, which sounds like a lot to keep resident in every session.

It was measured against two alternatives, a consolidated verb set and a single tool that shells out to the
CLI. The finding was that resident schema is the smaller cost, at around 8,162 tokens per session, while a
single unnarrowed read costs roughly 45,000. So breadth was kept and the effort went into making reads
shapeable, which cut about 82% off a representative set for 552 resident tokens.

The count is now frozen by a test. Adding a tool means amending the decision record, not editing a fixture.
Numbers and method are in [token budget](../agents/token-budget.md).

## Names that were deliberately not changed

The product was renamed from simple-kanban to pandan. Three categories were left alone:

**Ticket prefixes.** `KAN-` and `EPIC-` come from database sequences. Renaming them would split the board's
own history across two naming schemes.

**The deployed identity.** The hosted board still answers on `simple-kanban-jian.fly.dev`, because renaming
a deployment means a create-migrate-destroy cutover that was deferred rather than paid twice.

**Wire and storage identifiers.** The session cookie name, the outbound webhook header, logger names, and
browser storage keys. Each would log users out, break a consumer, or reset local state for nothing.

The old environment variable names and token prefix still work as deprecated fallbacks, read after the
current ones, with a notice on stderr. That is dead weight carried on purpose, and it is scheduled for
removal.

## Where to read more

The decision records cover the tech stack, the data model, authentication and authorization as they
evolved, the MCP scoping rules, observability, the rebrand, and the MCP sizing analysis. Several
supersede or amend earlier ones, which is the point of numbering them.

**[github.com/leejianrong/pandan/tree/main/docs/adr](https://github.com/leejianrong/pandan/tree/main/docs/adr)**
