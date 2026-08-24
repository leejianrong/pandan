# ADR 0020 — Board keys: a short ref prefix, unique per owner

- **Status:** Accepted — and the first half is **executed**. `board.key` exists, is derived at create,
  is editable, and is returned by every board read. Nothing *renders* a board-local ref yet: that is
  V52–V54, and it is deliberately not this slice.
- **Date:** 2026-08-25
- **Context source:** Milestone 8 ("Legible at Scale"), slice **V51** / **KAN-972**, from
  [issue #280](https://github.com/leejianrong/pandan/issues/280) and the shape's decisions
  [D1–D7](../milestone-8/SHAPING.md). Builds on ADR 0006 (per-table ticket sequences, whose promise
  this leaves untouched), ADR 0009 (the epic as a separate entity with its own sequence — the shape
  this mirrors), and ADR 0012/0013 (boards as first-class, owner-gated entities, which is what makes
  "per owner" a meaningful scope). **Retires nothing, renames nothing, renumbers nothing.**

## Context

Ticket numbers come from two installation-wide Postgres sequences (ADR 0006/0009). That was right when
there was one board. With several users and several boards each, the numbers a person reads on their
own board have two defects at once, measured against the live instance on 2026-08-23:

| Board | Cards | Ticket range | Density |
|---|---:|---|---:|
| Engine Room | 41 | KAN-48 → KAN-209 | 25% |
| kaya — Notes (MVP) | 77 | KAN-530 → KAN-971 | 17% |
| kopicode | 100+ | KAN-768 → KAN-960 | ~52% |

They are **large** (a global pool) and **non-local** (they jump, because the gaps are other boards'
cards). Both worsen linearly with users. A 77-card board should read `1…77`.

## Decision

Add `board.key` — a short prefix, `^[A-Z][A-Z0-9]{1,9}$` — and make it **unique per owner**:
`UniqueConstraint("owner_id", "key")`. A board-local reference (`ENG-14`, arriving in V52–V54) is
rendered from this key plus a per-board sequence number. The canonical `KAN-955` is **kept, stored and
immutable**.

Five things follow, and each is a decision rather than an implementation detail.

### 1. The canonical ticket is not backward compatibility — it is the cross-board addressing mode

`ticket_number` is never touched (SHAPING D1). Rewriting it in place would break every stored activity
summary, every external link and the autosync contract, and it would buy nothing the additive design
does not. But the deeper reason is the next point: once keys are per-owner, a board-local ref is *not*
globally meaningful, so something has to be. `KAN-955` is that something.

### 2. Per owner, not global — and the consequence is the important half

At a hundred users a global key namespace has people fighting over `ENG`, and every good short key is
gone within the first dozen signups (SHAPING D2). So keys are scoped to the owner.

**That makes a board-local ref ambiguous across users, which is why board-local refs resolve
board-locally** (D3). Boards are shareable, so a user who owns an `ENG` may also be a member of someone
else's `ENG`:

| Form | Scope | Resolves from | Stored as |
|---|---|---|---|
| `KAN-955` / `EPIC-7` | **global**, canonical, immutable | anywhere, no board context | `ticket_number`, as today |
| `ENG-14` / `ENG-E7` | **board-local**, display | only within a known board | `board.key` + `board_seq` |

Given no board context and more than one accessible match, V53 fails with an `ambiguous_ref` error
naming the candidates — a menu, never a silent pick.

`owner_id` is nullable (a board is unclaimed until someone claims it on login), and Postgres treats
NULLs as **distinct** in a unique index. So unclaimed boards can never collide with each other and the
constraint needs no partial index. That is a property of the database rather than of this design, so it
is written down in the model and in the migration rather than assumed.

### 3. No hyphens in a key, and `KAN`/`EPIC` are reserved

Both are load-bearing (D5). A hyphen-free key means a reference splits unambiguously on its **first**
hyphen: head is the key, an all-digit tail is a card, an `E`+digits tail is an epic. Reserving the two
canonical prefixes case-insensitively means a board key can never shadow the global form, so the table
above stays decidable by inspection rather than by precedence rules.

### 4. Creating a board never blocks on naming; asking for a key can fail

Two paths with deliberately different failure behaviour (R1.4):

| | Key omitted | Key named |
|---|---|---|
| Malformed / reserved | impossible — derivation only produces legal keys | **422** (schema) |
| Already used by this owner | suffixed: `ENG` → `ENG2` | **409** (router) |

The asymmetry is the point: not asking should never fail, and asking for `ENG` and silently getting
`ENG2` would be worse than an error. **422 versus 409 is also a decision, not an accident** — a
malformed key is a fact about the request, a taken key is a fact about the database, and a caller
deciding whether to fix the argument or pick a different key needs to be told which.

Derivation is deliberately dumb, and therefore predictable: ASCII alphanumerics of the name,
uppercased, leading digits dropped, first three characters, padded to two, `BRD` if nothing is usable.
`"Engine Room"` → `ENG`. A user who dislikes the result changes it in one call. Reserved keys walk the
*same* collision path as taken ones — a board named "Kanban" derives `KAN`, finds it reserved and lands
on `KAN2` — so there is one mechanism for "you cannot have this key", not two.

### 5. A key is editable, and that is safe precisely because of decision 1

`PATCH /boards/{id}` accepts `key`. Renaming it re-labels every board-local ref on the board at once,
and nothing breaks: no card stores a rendered ref, and `ticket_number` does not move. A key is
therefore a *display* choice, which is the property that makes auto-derivation acceptable in the first
place. It cannot be cleared — every board has a key, because V52's refs cannot render without one.

## Consequences

- **A migration, landing alone** (M8 R4.4): add nullable → backfill from names, deduplicated per owner
  → `NOT NULL` + the unique constraint + a shape `CHECK`. The derivation is **copied into the
  migration rather than imported** from `app.board_keys`: a migration is a historical record and must
  keep producing the same result years from now, which importing live application code forfeits. The
  two copies may drift after this revision, and no invariant depends on their agreeing.
- **The shape lives in four places**, the same pattern `card.column` established (ADR 0008): the
  `BOARD_KEY_PATTERN` regex, the Pydantic validators, a Postgres `CHECK`, and the CLI's `--help`. The
  regex and the CHECK are the two that matter; a test pins the derivation's *output* rather than its
  agreement, because unlike the V62 palette there is no rendering layer that could disagree.
- **Read-then-write is not atomic**, so two concurrent creates can pick the same derived key. The
  loser retries (up to three times, re-reading and suffixing past the winner); a lost race on a
  *named* key becomes the 409 it would have been a moment earlier, rather than a 500 from an
  `IntegrityError`. This is a bound on pathology, not a locking strategy — consistent with ADR 0007's
  last-write-wins stance.
- **+215 resident MCP tokens**, measured: the surface reads **8,426** compact before this slice and
  **8,641** after, for the `key` argument on `create_board` and `update_board`. ADR 0019's freeze is on
  the tool *count*, which is unchanged at 49; arguments are explicitly permitted. (Note that the
  figure quoted in `CLAUDE.md` was **8,391** — stale, exactly as that file warns. Re-run
  `mcp/scripts/measure_tool_schema_tokens.py` rather than quoting prose.)
- **Nothing renders a board-local ref yet.** `key` is returned by every board read and typed in the
  SPA, and no UI shows it. V52 adds the numbers, V53 teaches every resolver both forms, and only then
  does V54 render — so a user never sees a reference that some part of the system cannot parse.

## Alternatives rejected

- **Rewriting `ticket_number` per board.** Breaks stored history, external links and the autosync
  contract, and forfeits the cross-board address (D1).
- **A globally unique key.** Simpler to resolve — a board-local ref would need no board context — and
  rejected on scaling: it makes the good keys a land grab and forces every later user into `ENG2`.
  This is the trade that creates the `ambiguous_ref` case, and it is worth it.
- **A workspace/organisation tier above the user**, which would give keys a natural non-global scope.
  Out of scope for M8; per-owner is what today's ownership model supports and is deliberately
  compatible with a workspace tier later.
- **One shared per-board sequence across cards and epics** (the Jira model, where an epic *is* an
  issue). Reads more cleanly, but collapses a separation ADR 0009 deliberately created. Epics get
  their own per-board sequence in V52 (D4).
- **Asking the user for a key at creation time.** Rejected by R1.4: creation must not block on naming.
  A derived key is editable in one call, which makes the prompt pure friction.
- **A key per board via a Postgres sequence object.** That is V52's question, not this one, and it is
  answered there (D6): a counter column on `board`, because gapless is the property issue #280 asked
  for and a sequence is exactly the thing that leaves gaps.

## Open

- **Ownership transfer across a key collision** (shape Q2). Moot today — ownership is not reassignable
  through the API — and the lean is auto-suffix plus an activity-log entry, decided when transfer
  exists.
