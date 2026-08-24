---
shaping: true
---

# Milestone 8 — Slices ("Legible at Scale")

Vertical increments of the [M8 shape](SHAPING.md). Each ends in **observable behaviour** and ships as
its own PR behind CI, matching the M1–M7 cadence.

Numbering continues the **global V-series** (M2 = V1–V5, M3 = V6–V10, M5 = V11–V19, M6 = V26–V39,
M7 = V40–V50; M4 was tracked directly as EPIC-3…EPIC-17). **M8 is V51–V64.**

M8 is the **first milestone since M6 to change the schema**. M7's defining constraint — no API, no
schema, no migration (its R4.1) — expired with it. Five of these fourteen slices carry a migration,
every one of them additive with a backfill (R4.2), and each lands **alone** per the standing deploy
rule (R4.4).

The three parts trace to three GitHub issues, and each part is an epic on the roadmap board:

| Part | Epic | Issue | Theme |
|---|---|---|---|
| **A — Identity** | [EPIC-122](https://simple-kanban-jian.fly.dev) | [#280](https://github.com/leejianrong/pandan/issues/280) | Board-local ticket refs |
| **B — Time** | EPIC-123 | [#279](https://github.com/leejianrong/pandan/issues/279) | Sprints, backlog, planning intervals |
| **C — Colour** | EPIC-124 | [#278](https://github.com/leejianrong/pandan/issues/278) | Epic & label visual identity |

## Order of build

**Part C ships first**, despite being last alphabetically and least ambitious. It carries no schema
risk and no resolution surface, and its first slice closes a gap agents hit weekly — so it ships while
Part A's migration design is still under review. **V55 follows immediately** as a one-afternoon fix to
a hole nobody had noticed. Part A is the milestone's centre of gravity and runs as a strict chain.

Within Part A the four slices are ordered so that **nothing is visible until everything resolves**:
add the key, add the numbers, teach every resolver, *then* render. A user must never see a reference
that some part of the system cannot parse. The dependency chain is recorded on the board
(V52 blocked-by V51, and so on), not just here.

| Slice | What | Part | Card | Pts | Ends in (demo) |
|-------|------|:----:|------|:---:|----------------|
| **V61 · Label management UI** ✅ | the screen that did not exist | C | KAN-982 | 5 | A human creates and recolours a label without touching a terminal |
| **V55 · `PATCH /cycles/{id}`** | a sprint you can edit | B | KAN-976 | 1 | `pandan cycle update 7 --name 'Sprint 12'` works and the cards stay attached |
| **V51 · Board keys** | `board.key`, unique per owner | A | KAN-972 | 3 | A board has a key; two users can each own an `ENG`; keying a board `KAN` is a clean `422` |
| **V52 · Per-board sequences** | `board_seq` + backfill 🗄️ | A | KAN-973 | 5 | Every card and epic carries a gapless board-local ref in its payload |
| **V53 · Resolution** | both forms, everywhere | A | KAN-974 | 5 | `pandan get ENG-42` and `pandan get KAN-1013` return the same card |
| **V54 · Render** | SPA + CLI show the ref | A | KAN-975 | 3 | The board reads `ENG-1…ENG-77` instead of `KAN-530…KAN-971` |
| **V62 · Dual-theme palette** ✅ | + colour validation | C | KAN-983 | 3 | Every label is readable in both themes; a bad colour is a `422` |
| **V63 · Epic colour** | 🗄️ | C | KAN-984 | 2 | An epic's stories are recognisable on the board without reading them |
| **V64 · Label emoji** | 🗄️ | C | KAN-985 | 2 | Two labels sharing a colour are still distinguishable at a glance |
| **V56 · Backlog** | derived, groomable | B | KAN-977 | 3 | The backlog is a place you can open; parked ≠ never scheduled |
| **V57 · Planning intervals** | 🗄️ | B | KAN-978 | 5 | Six cycles roll up into one PI with a single committed-vs-completed number |
| **V58 · Cadence** | generate N cycles | B | KAN-979 | 2 | "Two weeks per sprint, six sprints" is one command |
| **V59 · Explicit close** | + rollover | B | KAN-980 | 3 | Closing is deliberate and reported; past velocity numbers stop moving |
| **V60 · Observed throughput** | agent vs human | B | KAN-981 | 3 | `agent: 6.2 pts/day (n=143)` — a budget backed by evidence, not a multiplier |

🗄️ = carries a migration, lands alone. ✅ = shipped.

Total: **40 points across 14 slices**, plus one standalone bug (KAN-986) found while tracing #280.

## Part A — Identity (EPIC-122, issue #280)

The problem, measured against the live board on 2026-08-23:

| Board | Cards | Ticket range | Density |
|---|---:|---|---:|
| Engine Room | 41 | KAN-48 → KAN-209 | 25% |
| kaya — Notes (MVP) | 77 | KAN-530 → KAN-971 | 17% |
| kopicode | 100+ | KAN-768 → KAN-960 | ~52% |

Two defects in one row: the numbers are **large** (a global pool shared by every board of every user)
and they are **non-local** (they jump, because the gaps are other boards' cards). Both worsen linearly
with users.

**The design in one table** — this is the thing to remember about Part A:

| Form | Scope | Resolves from | Stored as |
|---|---|---|---|
| `KAN-955` / `EPIC-7` | **global**, canonical, immutable | anywhere, no board context | `ticket_number`, exactly as today |
| `ENG-14` / `ENG-E7` | **board-local**, display | only within a known board | `board.key` + `board_seq` |

Keeping the canonical ticket is not backward compatibility — **it is the cross-board addressing
mode**, and it is the reason per-user board keys are safe (SHAPING D3). Two users may each own an
`ENG`; a board-local ref only ever resolves inside a board.

### V51 · Board keys — KAN-972

`board.key`, `^[A-Z][A-Z0-9]{1,9}$`, `UniqueConstraint(owner_id, key)`. Postgres treats NULLs as
distinct, so the nullable `owner_id` needs no partial index and orphaned boards cannot collide.
`KAN` and `EPIC` are reserved case-insensitively. Derived automatically at board creation with a
numeric suffix on collision, because creation must never block on naming (R1.4).

No hyphens in a key is load-bearing: it means a ref splits unambiguously on its **first** hyphen —
head is the key, all-digit tail is a card, `E`+digits tail is an epic.

**Deliverable includes ADR 0020.**

### V52 · Per-board sequences — KAN-973 🗄️

`card.board_seq`, `epic.board_seq`, and counter columns `board.next_card_seq` / `next_epic_seq`.
Assignment is one statement inside the insert transaction:

```sql
UPDATE board SET next_card_seq = next_card_seq + 1 WHERE id = :id RETURNING next_card_seq
```

**The tradeoff, stated because it inverts the usual advice:** a Postgres sequence never blocks and
always leaves gaps on rollback; a counter column briefly serialises writers to one board and is
**gapless**. Gapless is exactly what issue #280 asked for — *"the numbers jump and are not sequential
(locally)"* — so the property normally counted as a sequence's advantage is, here, the defect being
fixed. Batch creates take the whole range in one statement rather than N round trips.

Backfill with `row_number() OVER (PARTITION BY board_id ORDER BY id)` over **all** rows, soft-deleted
included — skipping trashed cards would renumber the live ones around them and turn a restore into a
collision (SHAPING D7).

Epics get a **second, independent** sequence rather than sharing the cards' one, mirroring the
existing two-sequence design that ADR 0009 deliberately created (SHAPING D4).

A test pins that `ticket_number` values are unchanged across the migration (R1.2).

### V53 · Resolution — KAN-974

Every site that parses `KAN-<n>` learns the second form. All verified 2026-08-23:

- `backend/app/routers/cards.py` — the `refs=` batch read (issue #254) and its
  `X-Unresolved-Selectors` report, which must still not become an existence oracle
- `backend/app/autosync.py:53` — `_TICKET_RE`; a branch named `eng-42-fix-the-thing` must match
- `pandan-cli/pandan_cli/cli.py:1797,1830` — `_resolve_card` / `_resolve_epic`
- any API path param accepting an id-or-ticket

**Three accepted forms, not two.** Alongside `KAN-955` and `ENG-14`, the owner-qualified
**`alice/ENG-14`** must resolve — because V54 *prints* it on the cross-board surfaces, and
`pandan-cli/tests/test_cli.py:3371` (V42 / KAN-425) feeds every printed identifier back on the standing
rule that the CLI accepts what it prints. Printing a form the CLI rejects would fail that suite, which
is exactly the guard working as intended.

New error code **`ambiguous_ref`**, slotting into V43's error contract. It is a **menu, not a
refusal** — a board-local ref with no board context matching more than one accessible board lists the
candidates with owner and canonical ref, so the next command is visible rather than guessable:

```
error	ambiguous_ref	'ENG-14' matches 2 accessible boards	ENG-14
  board 5  ENG  Engineering   (alice)  → KAN-955
  board 6  ENG  Engine Room   (you)    → KAN-207
help: pandan get KAN-207
help: pandan --board 6 get ENG-14
```

### V54 · Render — KAN-975

SPA: `Card.svelte`, `BoardTable.svelte`, `EpicItem.svelte`, `EpicForm.svelte`, `CommandPalette.svelte`
(which searches by ticket and must match **both** forms), `dashboard.svelte.ts`. CLI: the human row
shows the board-local ref, `--fields ticket` keeps the canonical form reachable.

Fold in KAN-986 if it has not already landed. Board-local refs make that sort bug **more** visible,
not less: a 77-card board goes from a sparse `KAN-530…971` to a solid `1…77`, where lexicographic
misordering is obvious.

**Qualification is a client concern, computed per viewer.** A key collision is a property of the
*viewer*, not the board (SHAPING, *Detail — when two accessible boards share a key*): only a user who
can see two `ENG` boards has one, and nothing is stored. Inside a board nothing is ever qualified;
across boards a colliding ref renders `alice/ENG-14` and a non-colliding one stays bare. The canonical
`KAN-955` is the title attribute and the click-to-copy value everywhere.

Deliberately last, so a user never sees a ref that something cannot parse.

## Part B — Time (EPIC-123, issue #279)

**Most of the sprint machinery already exists**, which is why this part is smaller than the issue's
title suggests. `Cycle` has been first-class since V33 (KAN-297) with `starts_on`/`ends_on`, a
nullable `card.cycle_id`, burndown and velocity via `pandan cycle metrics`, a dashboard panel, and
CRUD-lite from both adapters. "Two weeks per sprint" is expressible today. Part B builds the calendar
*around* it.

### V55 · `PATCH /cycles/{id}` — KAN-976

Found while shaping M8; not named in the issue. `routers/cycles.py` has list, create, get, metrics and
delete — and nothing else. A sprint cannot be renamed and a mistyped date cannot be corrected; the
only recovery is delete-and-recreate, which detaches every card in it. One afternoon, and the
milestone's clearest bug.

### V56 · Backlog — KAN-977

Derived from `cycle_id IS NULL`, **not** a fifth `column` value. The varchar+CHECK design (ADR 0008)
would have made a new column value free of `ALTER TYPE`, so it was genuinely on the table — and it is
rejected because it double-models scheduling: a card could sit in the `backlog` column *and* belong to
a cycle (SHAPING D8). Ships a `--backlog` filter, a grooming view, and one nullable field marking
*deliberately parked* as distinct from *not yet scheduled*.

### V57 · Planning intervals — KAN-978 🗄️

A new board-scoped `planning_interval` table plus `cycle.planning_interval_id` — structurally the
identical move V33 made for cycles, down to the flat no-ticket_number shape and the
`ON DELETE SET NULL` detach.

### V58 · Cadence — KAN-979

`POST /boards/{id}/cycles/generate`. Pure convenience over existing create, no new state, which is why
it is cheap and late. Guards against generating cycles that overlap existing ones.

### V59 · Explicit close — KAN-980

`POST /cycles/{id}/close {rollover_to}` moves unfinished cards, stamps the cycle closed, and **freezes
its committed set** so velocity stops being recomputed from live membership.

Auto-rollover on the `ends_on` date is rejected (SHAPING D9): it silently rewrites history that
`cycle metrics` has already reported, which is the standard regret in sprint tooling and
un-diagnosable after the fact.

### V60 · Observed throughput — KAN-981

**The most interesting slice in the milestone, and the one that answers the issue's hardest question
by refusing its proposal.** The thread suggested a second point scale — "1 agent story point = 3 or 5
human story points." That is deliberately not built (SHAPING D10):

1. The same comment sets the governing constraint — *"priority should be human readability"* — and two
   point scales on one card is the opposite of that.
2. A declared multiplier is unfalsifiable and gets re-argued every planning session. A measured one
   improves on its own and is board-specific.
3. The stated root problem — *"claude is notoriously bad at estimating time frames because it is
   unaware of how fast it can write code"* — is a **feedback** problem, not a **units** problem. Give
   an agent its own historical throughput and the estimate calibrates itself; give it a new unit and
   it guesses in the new unit.

`metrics.py` already derives cycle time from the activity log and every card carries an `assignee`
that is either `agent:*` or a human email, so the split costs **no schema change**. Sample size is
reported alongside each figure so a thin sample is visibly thin.

"Agent sprints are a day" then needs no new time model at all: that is a cycle whose bounds are a day
apart, expressible today.

## Part C — Colour (EPIC-124, issue #278)

Tracing this issue **moved the problem**, and the finding is worth keeping:

> `createLabel` and `deleteLabel` exist in `frontend/src/lib/api.ts:453,463` — and **no component
> calls either one**.

Labels can only be created from the CLI or MCP. `CardForm.svelte` only *selects* among labels that
already exist. So the issue's request for a colour picker had nowhere to live: the screen it belongs
on has never been built. Meanwhile the issue's other ask — "maybe as little coloured circles" — is
already shipped at `Card.svelte:163-167`.

### V61 · Label management UI — KAN-982

The missing CRUD screen: list with swatch, name and usage count; create, rename, recolour, delete.
Prerequisite for the rest of Part C, and the reason Part C ships first.

### V62 · Dual-theme palette + validation — KAN-983

Two defects, one fix. `schemas.py:219` accepts any non-empty string ≤32 chars, so `"banana"` is a
valid colour that renders as a blank dot. And `app.css` defines every token **twice**, once per theme
— a raw `<input type="color">` yields one hex with no dark variant, so roughly half of all user picks
would be unreadable in one theme.

**The palette is the picker** (SHAPING D11): named tokens, each with a light and dark value, shown as
a swatch grid. The palette is **disjoint from the semantic tokens** (`--accent`, `--agent`,
`--danger`, `--success`, `--warning`) — settled 2026-08-23 — so a label can never accidentally read as
a status. Validation becomes "a palette token **or** a well-formed hex", so existing stored
free-string colours keep rendering and no value migration is needed.

**Shipped as SEVEN tokens, not "~12", and the reason is worth keeping.** Two things made the
disjointness constraint far more binding than the shape assumed. The exclusion set is *wider* than the
five semantic tokens: `Card.svelte` renders **priority** as a coloured dot + text — the same visual
primitive as a label dot, in the same card — using amber, orange, `--danger` and `--muted`. And once
"disjoint" was **measured** (CIE Lab ΔE to every status colour, in both themes) rather than eyeballed,
the first hand-picked nine lost three members: `slate` scored **6.9** against `--muted`, which is
literally what priority "low" paints, `indigo` **14.4** against `--agent`, and `brown` **14.8** against
`--warning`. All three read as clean hues by name and are nothing of the kind on screen.

With green, violet, red, orange and grey excluded, only blues and magentas remain — a narrow arc — so
the survivors also have to separate from *each other*. Nine cannot (mutual ΔE falls to 11.2); seven
hold at **21.4**. The measurement lives in `backend/tests/unit/test_palette.py`, so a future tenth hue
has to clear the same bar rather than argue for itself.

The list is duplicated in **four** places by necessity — Python validates, CSS renders, `api.ts` draws
the grid, the CLI prints it in `--help` — and unlike the app's other three-places rules, that
agreement is **proven, not trusted**: the test parses the CSS, the TypeScript and the CLI and names
whichever one you forgot.

### V63 · Epic colour — KAN-984 🗄️

`epic.color`, nullable, same palette. Rendered on the epic chip **and on its member cards** — the
point of an epic colour is recognising an epic's stories on the board at a glance, so the
`Card.svelte` treatment is part of the slice, not a follow-up.

### V64 · Label emoji — KAN-985 🗄️

Issue #278 floated shapes *or* emoji. Emoji wins on four counts (SHAPING D12): one grapheme so no new
render code; extends without a schema change; already accessible by its own name; and it survives into
the CLI's human output, where an SVG shape is simply invisible.

`label.emoji`, nullable `varchar(8)`, validated as **one grapheme cluster** — not one codepoint, since
flags and ZWJ sequences are multi-codepoint. Known cost, accepted explicitly: wide glyphs break
tab-alignment in the CLI's human rows, so it is opt-in via `--fields` and never in the default row.

## Loose card

**KAN-986 — ticket sort is lexicographic.** `dashboard.svelte.ts:225` sorts with
`localeCompare(ticket_number)`, so `KAN-100` orders before `KAN-9`; `BoardTable.svelte`'s ticket sort
key appears to share the defect. Found while tracing #280, independent of M8, and either landed first
or folded into V54.

## Open questions (carried from the shape)

| | Question | Lean |
|---|---|---|
| **Q1** | Board-key collision — numeric suffix or ask the user? | Suffix; R1.4 says creation must never block |
| **Q2** | Ownership transfer across a key collision in the new owner's namespace | Auto-suffix + record it in the activity log |
| **Q3** | ~~A per-user toggle between canonical and board-local display?~~ | **Settled: no toggle** — collisions are handled by qualification, not a mode |
| **Q4** | Does `planning_interval` need its own metrics endpoint? | No — a filter on `cycle metrics` |
| **Q5** | ~~Do the semantic tokens participate?~~ | **Settled: disjoint** — and V62 then settled the hues: **seven**, chosen by measured ΔE, because three of the first nine were status colours under other names |

## Out of scope for M8

See the [shape](SHAPING.md)'s full list. The four worth repeating:

- **Renaming or renumbering `ticket_number`** — the canonical identifier is untouched, forever.
- **A second story-point scale for agents** — measured, not declared.
- **Auto-rollover on the `ends_on` date** — closing is a verb.
- **A workspace/org tier above the user** — D2 scopes board keys per user, which is what today's
  ownership model supports, and is deliberately compatible with a workspace tier later.
