<!--
title: "Glossary"
description: The exact meaning of every Pandan term, including the ones that look interchangeable but are not.
-->

# Glossary

Pandan uses these terms precisely, because the API does. Where two words look interchangeable, the entry
says why they are not.

## Core objects

**Board**
: A container for cards and epics. Has exactly one owner, plus any number of members with roles. A card
belongs to exactly one board and cannot move between boards.

**Card**
: One piece of work. Interchangeable with **story**. Lives in a column, holds a position within it, and
carries a permanent ticket number like `KAN-123`.

**Story**
: The same thing as a card. The API calls it a card; people usually say story.

**Epic**
: A grouping of related cards with a name, description, lead and target date. Has **no** column,
position, assignee or story points, because an epic is not a card. Stored separately and numbered
separately, as `EPIC-4`. A card links to zero or one epic.

**Column**
: Where a card is in its life: `todo`, `in_progress`, or `done`. Only these three. Stored as text guarded
by a database check rather than an enum, so a fourth could be added without a schema migration.

**Position**
: A card's sort key within its board and column. Not contiguous, not a global rank. Deletes leave gaps on
purpose; a move renumbers only the columns it touched.

**Ticket number**
: The permanent identifier printed on a card or epic: `KAN-123`, `EPIC-4`. Allocated from a database
sequence at creation, so it is atomic under concurrent creates. Never changes and never gets reused, which
is why gaps are normal. Cards and epics number independently.

## Organising

**Label**
: A coloured tag scoped to one board. A card can carry several. Use for a property that cuts across work.
Attaches by id, and an update replaces the card's whole label set rather than adding to it.

**View**
: A saved query. Has no contents of its own, so deleting one never touches a card and a card appears in
every view it matches.

**Cycle**
: A time-boxed iteration, with optional start and end dates. A sprint. A card belongs to zero or one
cycle, independently of its epic. Nothing happens automatically when a cycle ends.

**Template**
: A named set of cards you can stamp onto a board. Applying it creates independent cards with no ongoing
link back to the template.

## Work state

**Assignee**
: Who owns a card. Free text, not a user reference, specifically so an agent handle like
`agent:docs-rewrite` can own a card without an account. Nothing validates it, so a naming convention is
on you.

**Priority**
: `none`, `low`, `medium`, `high`, or `urgent`. `none` means unranked, not unimportant. Priority decides
which card an agent is handed next, so it affects behaviour.

**Story points**
: An estimate, restricted to `1`, `2`, `3`, `5`, `8`, `13`, or empty. The server rejects anything else.

**Dependency**
: A recorded statement that one card cannot proceed until another finishes. Read in both directions:
`blocked_by` and `blocks`. A blocked card is skipped when an agent asks for work, so this changes
behaviour rather than only appearance.

**Work link**
: A labelled URL attached to a card, typically a pull request, branch or CI run. Both label and URL are
required.

**needs-human**
: A flag marking a card as waiting on a person, with a note saying what the question is. Set by an agent
that has hit a judgement call, cleared with **resolve**. The intended honest exit for an agent that should
not guess.

**Trash**
: Where deleted cards and epics go. Restorable with their ticket numbers intact, or purgeable permanently.
Deleting a **board** does not go through the trash; its cards go with it.

## People and access

**Owner**
: The single user who owns a board. Only an owner manages members and board settings.

**Member**
: A user granted access to a board they do not own, with a role of `viewer`, `editor` or `owner`.

**Role**
: `viewer` reads, `editor` reads and writes cards, `owner` also manages members and settings.

**Principal**
: Whoever is making a request, once resolved. A cookie session and a personal access token both resolve to
a real user, so there is no separate class of agent identity.

**Personal access token**, **PAT**
: A `pandan_pat_…` credential that authenticates as the user who created it, with exactly that user's
access. Stored as a peppered HMAC hash, so the plaintext exists only in the response that created it.
Revocable individually.

## Clients and integration

**MCP server**
: A [Model Context Protocol](https://modelcontextprotocol.io) adapter exposing the API as 49 tools, for
agents that speak MCP. Holds no state of its own.

**CLI**
: The `pandan` command. A thin client over the same API, roughly one subcommand per endpoint.

**Auto-sync**
: Inbound GitHub integration. A signed webhook matches a `KAN-<n>` reference in a branch name or PR title
to a card, then attaches the PR and optionally moves the card to `done` on merge. Off by default, per
board.

**Outbound webhook**
: A signed POST to a URL of yours whenever a notification is created on a board. Best-effort, fired after
commit, with no retry queue.

**Warmup**
: A call to the unauthenticated health endpoint that wakes a scaled-to-zero deployment, so the cold start
is paid before real work rather than inside it. Needs no token.

## Output and cost

**Envelope**
: The object a list read returns: the rows under a named key, plus `next_cursor` and `summary`. So it is
`.cards[]`, not a bare array.

**Summary**
: The pre-computed counts at the end of every list read. Describes the rows **returned**, not the whole
board, so a filtered or limited query summarises what came back.

**TOON**
: A compact output format that prints a uniform array's field names once in a header rather than per row.
Cheaper than JSON on nested payloads, while plain human output stays cheapest for flat lists.

**Truncation**
: Cutting long free text at 500 characters by default, with a hint saying the true size, so one card
cannot fill an agent's context. Overridden per call with `--full`, or globally with
`PANDAN_MAX_TEXT_CHARS`.

## Names that look like leftovers

They are, and they are staying.

**`KAN-` and `EPIC-` prefixes**
: From the project's original name. Immutable, because they come from database sequences and renaming them
would break every ticket reference in the board's own history. Read `KAN` as "kanban".

**`simple-kanban-jian.fly.dev`**
: The hosted origin still carries the old name. Renaming it needs a create-migrate-destroy cutover that was
deliberately deferred.

**`KANBAN_*` environment variables, `kanban_pat_` tokens**
: Deprecated fallbacks that still work, read after their `PANDAN_*` equivalents, with a notice on stderr.
Carried on purpose and scheduled for removal.

**`kanbanauth` cookie, `kanban.*` log names, `kanban.theme` storage keys**
: Wire and storage identifiers. Renaming them would log everyone out or reset local state for no gain.
