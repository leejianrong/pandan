<!--
title: "REST API"
description: The /api/v1 surface: authentication, the endpoint table, status codes, and how authorization works.
-->

# REST API

Everything in Pandan goes through this API. The web UI, the CLI and the MCP server are all clients of it,
and none of them has a private capability.

The authoritative, always-current reference is the OpenAPI schema on a running instance:

```
GET /docs          # interactive
GET /openapi.json  # the schema
```

This page is the map.

## Authentication

`/api/v1` requires authentication on **every** request. There is no anonymous read.

Two ways to authenticate, and they resolve to the same thing:

| Client | Mechanism |
| --- | --- |
| Browser | The session cookie set at login. Sends no token. |
| CLI, MCP, scripts | `Authorization: Bearer pandan_pat_…` |

Both resolve to a real user, and both are permission-checked identically. There is no shared service
token and no privileged bypass.

```bash
curl -H "Authorization: Bearer $PANDAN_TOKEN" \
  https://simple-kanban-jian.fly.dev/api/v1/boards
```

Tokens are stored as HMAC-SHA256 hashes peppered with the server's `AUTH_SECRET`, so the plaintext exists
only in the response that created it.

!!! note "Older token prefixes still work"

    Tokens minted before the rebrand start with `kanban_pat_` and authenticate indefinitely. Verification
    is a hash lookup over the whole token, not a prefix check, so nothing about the rename invalidated an
    issued token.

## Authorization

One layer, applied consistently: resolve the principal, then check their access to the board in question.

| Situation | Result |
| --- | --- |
| No credential, or a bad one | `401` |
| Valid credential, no access to that board | `403` |
| Valid credential, insufficient role for the action | `403` |
| Resource does not exist | `404` |

Roles are `viewer`, `editor` and `owner`. Reading needs `viewer` or above, writing cards needs `editor`
or above, and managing members or board settings is owner-only.

Lists are scoped to what you can reach, so `GET /api/v1/boards` returns your boards rather than everyone's.

## Endpoints

### Identity

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/v1/me` | Returns `{id, email}`. The one `/api/v1` route with no board, so it answers `200` or `401` and never `403`. |

`/api/v1/me` exists because the framework's own user endpoint sits on the cookie path and will not accept
a bearer token. It returns the minimum on purpose, because it is a cross-application contract.

### Boards

| Method | Path |
| --- | --- |
| `GET` | `/api/v1/boards` |
| `POST` | `/api/v1/boards` |
| `GET` | `/api/v1/boards/{board_id}` |
| `PATCH` | `/api/v1/boards/{board_id}` |
| `DELETE` | `/api/v1/boards/{board_id}` |
| `GET` | `/api/v1/boards/{board_id}/activity` |
| `GET` | `/api/v1/boards/{board_id}/metrics` |

Card and epic reads carry two board-local fields alongside `ticket_number`: **`board_seq`**, a
number that starts at 1 on each board and never repeats, and **`ref`**, the rendered form —
`ENG-14` for a card, `ENG-E7` for an epic. They are a *display* form. `ticket_number` remains the
identifier: globally unique, immutable, and the only form that means anything without knowing which
board you are on. `ref` is built from the board's key at read time, so changing the key re-labels
every ref at once and rewrites nothing.

Reach them from the CLI with `pandan list --fields ref,title`, or over MCP with
`list_cards(fields=["ref","title"])`. The web UI shows the board-local `ref` everywhere a ticket
appears — the card face, epic view, dashboard, trash, command palette — falling back to `ticket_number`
if a read hasn't attached one (M8 V54). The CLI's default human row does the same, but `--fields ticket`
stays mapped to the canonical `ticket_number` regardless — the two are meant to disagree.

`PATCH` is where auto-sync and outbound webhook settings live. The outbound secret is accepted here and
never returned by any read.

Every board carries a **`key`** — a short ref prefix like `ENG`, matching `^[A-Z][A-Z0-9]{1,9}$`. It is
unique **per owner**, not globally, so two users can each hold `ENG`. `POST` derives one from the name
when you omit it, so a create never fails on naming; supply one and a malformed or reserved
(`KAN`/`EPIC`) value is a `422` while a key you already use is a `409`. `PATCH` changes it, which is
safe — a card's `ticket_number` never moves.

### Cards

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/v1/cards` | Filter, search, sort, paginate. Also the batch read — see below. |
| `POST` | `/api/v1/cards` | |
| `GET` | `/api/v1/cards/{card_id}` | |
| `PATCH` | `/api/v1/cards/{card_id}` | Field edits only. Cannot move. |
| `DELETE` | `/api/v1/cards/{card_id}` | To trash. |
| `PATCH` | `/api/v1/cards/batch` | Atomic. |
| `POST` | `/api/v1/cards/{card_id}/move` | Column and position. |
| `POST` | `/api/v1/cards/{card_id}/needs-human` | |
| `POST` | `/api/v1/cards/{card_id}/resolve` | |
| `GET` | `/api/v1/cards/trash` | |
| `POST` | `/api/v1/cards/{card_id}/restore` | |
| `DELETE` | `/api/v1/cards/{card_id}/purge` | Permanent. |
| `POST` | `/api/v1/cards/{card_id}/dependencies` | |
| `DELETE` | `/api/v1/cards/{card_id}/dependencies/{blocker_id}` | |
| `POST` | `/api/v1/cards/{card_id}/links` | |
| `DELETE` | `/api/v1/cards/{card_id}/links/{link_id}` | |
| `GET` | `/api/v1/cards/{card_id}/comments` | |
| `POST` | `/api/v1/cards/{card_id}/comments` | |

#### Reading many cards by id or ticket

`GET /api/v1/cards` doubles as a batch read, so resolving a known set of references costs one request
rather than one per card:

```
GET /api/v1/cards?ids=12,45,67
GET /api/v1/cards?refs=KAN-12,KAN-45
```

Both are comma-separated, order-preserving and de-duplicated. They OR with each other and AND with
every other filter, so `?refs=…&column=done` asks which of those cards are done.

Selectors that resolve to nothing are **omitted from the body and named in the
`X-Unresolved-Selectors` response header**, comma-separated, in the order given. The header appears
only when something missed, so its absence means you got everything you asked for.

Unknown, trashed and not-yours all report identically — distinguishing them would reveal whether a row
exists on a board the caller cannot see. Malformed input is a different case and returns `422`:
`ids=abc`, or a `refs` token that is not a reference at all. A well-formed `EPIC-3` parses and then
resolves to nothing, since it is a real ticket that is not a card.

`refs` takes **board-local references too** (`ENG-14`, and `ENG-E7` which parses and resolves to
nothing) — but only alongside `board_id`, and a board-local ref without one is a `422`. That is not a
limitation of this endpoint; it is what board-local means. Keys are unique per owner, so `ENG-14` names
a different card for different people, and resolving it across every board you can see would silently
return two cards for one selector. When you have no board in mind, the canonical `KAN-955` is the form
to use — that is what it is for. An owner-qualified `alice/ENG-14` is also a `422` here, since
`board_id` already determines the owner; the CLI resolves that form.

Two limits, both `422` rather than silent:

- At most **100 selectors** per request (`MAX_CARD_SELECTORS`), counted across `ids` and `refs`
  together.
- `ids`/`refs` **cannot be combined with `limit` or `cursor`**, because a truncated page would report
  visible cards as unresolved.

!!! warning "Move is a separate endpoint from edit"

    `PATCH` handles title, description, points, assignee, priority, due date, epic, cycle and labels.
    Column and position go through `POST …/move`, because a move has to renumber positions in the source
    and target columns. This split is deliberate and the API will not accept a column change on `PATCH`.

### Epics

| Method | Path |
| --- | --- |
| `GET` | `/api/v1/epics` |
| `POST` | `/api/v1/epics` |
| `GET` | `/api/v1/epics/{epic_id}` |
| `PATCH` | `/api/v1/epics/{epic_id}` |
| `DELETE` | `/api/v1/epics/{epic_id}` |
| `GET` | `/api/v1/epics/trash` |
| `POST` | `/api/v1/epics/{epic_id}/restore` |
| `DELETE` | `/api/v1/epics/{epic_id}/purge` |

Deleting an epic detaches its cards rather than cascading to them.

### Members, labels, views, cycles, templates

| Method | Path |
| --- | --- |
| `GET` `POST` | `/api/v1/boards/{board_id}/members` |
| `PATCH` `DELETE` | `/api/v1/boards/{board_id}/members/{member_id}` |
| `GET` `POST` | `/api/v1/boards/{board_id}/labels` |
| `PATCH` `DELETE` | `/api/v1/labels/{label_id}` |
| `GET` `POST` | `/api/v1/boards/{board_id}/views` |
| `GET` `DELETE` | `/api/v1/boards/{board_id}/views/{view_id}` |
| `GET` `POST` | `/api/v1/boards/{board_id}/cycles` |
| `GET` `PATCH` `DELETE` | `/api/v1/boards/{board_id}/cycles/{cycle_id}` |
| `GET` | `/api/v1/boards/{board_id}/cycles/{cycle_id}/metrics` |
| `GET` `POST` | `/api/v1/boards/{board_id}/templates` |
| `GET` `DELETE` | `/api/v1/boards/{board_id}/templates/{template_id}` |
| `POST` | `/api/v1/boards/{board_id}/templates/{template_id}/apply` |

### Tokens and notifications

| Method | Path |
| --- | --- |
| `GET` `POST` | `/api/v1/tokens` |
| `DELETE` | `/api/v1/tokens/{token_id}` |
| `GET` | `/api/v1/notifications` |
| `PATCH` | `/api/v1/notifications/{notification_id}` |

Both are per user rather than per board. `POST /api/v1/tokens` is the only place a token's plaintext is
ever returned.

### Webhooks and health

| Method | Path | Auth |
| --- | --- | --- |
| `POST` | `/api/v1/webhooks/github` | HMAC signature, not a token |
| `GET` | `/api/health` | None. Readiness, checks the database. |
| `GET` | `/api/health/live` | None. Liveness. |
| `GET` | `/api/health/version` | None. The git revision this build was made from. |

The health endpoints are deliberately unversioned and unauthenticated, so a probe or a `warmup` call needs
no credential.

## Field constraints

| Field | Constraint |
| --- | --- |
| `title`, `name` | Non-empty, with a maximum length matching the column width |
| `column` | `todo`, `in_progress`, `done` |
| `story_points` | `1`, `2`, `3`, `5`, `8`, `13`, or `null` |
| `priority` | `none`, `low`, `medium`, `high`, `urgent` |
| `role` | `viewer`, `editor`, `owner` |
| `position` | A sort key within a board and column. Not contiguous. |

Validation happens in the request schema, before anything touches the database, so a bad value is a `422`
with a reason rather than a `500`.

## Status codes

| Code | Meaning |
| --- | --- |
| `200` | Success |
| `201` | Created |
| `204` | Deleted, no body |
| `401` | No credential, or a bad one |
| `403` | Authenticated, but not allowed |
| `404` | No such resource |
| `413` | Body larger than `MAX_REQUEST_BODY_BYTES` |
| `422` | Validation failure, with the offending field |
| `429` | Rate limited. Carries `Retry-After`. |
| `503` | Database unreachable (`/api/health`), or webhook secret unset |

## Concurrency

Last write wins. There is no locking, no optimistic concurrency token, and no real-time push.

Two clients editing the same card both succeed, and the later write is what persists. Clients are expected
to re-read after writing rather than assume their local copy is current, which is what the UI does on
every mutation.

This is a deliberate choice for a board of this size, not an oversight. See
[design decisions](../about/design-decisions.md).

## Stability

`/api/v1` only grows — new endpoints, new optional fields, new response fields. Removing or renaming
something, or tightening validation on existing input, is treated as breaking and goes to a new prefix
rather than changing `v1` underneath you; a shape being phased out is marked with `Deprecation` and
`Sunset` response headers before it's ever removed. See
[ADR 0022](https://github.com/leejianrong/pandan/blob/main/docs/adr/0022-api-stability-policy.md) for
the full policy, including how long a deprecated shape is guaranteed to keep working.

## Recap

- Every `/api/v1` request needs a cookie session or a bearer token, and both resolve to a real user.
- `401` no credential, `403` no access, `404` no resource, `422` bad value.
- `PATCH` edits fields. `POST …/move` moves cards.
- Last write wins.
- `/docs` on a running instance is the authoritative reference.
