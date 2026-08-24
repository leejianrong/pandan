---
shaping: true
---

# Milestone 8 — Shaping ("Legible at Scale")

M7 finished the *edges*: the product is named, the CLI is AXI-conformant, the MCP surface is measured
and frozen. It changed no API, no schema and ran no migration — that was its defining constraint
(R4.1), and it expired with the milestone.

M8 is the first milestone since M6 that touches the **data model**, and it does so for one reason: the
board works well for one person with one board, and every one of the three problems below is a
**consequence of that assumption breaking**. They arrived as three unrelated-looking GitHub issues
([#280](https://github.com/leejianrong/pandan/issues/280),
[#279](https://github.com/leejianrong/pandan/issues/279),
[#278](https://github.com/leejianrong/pandan/issues/278)) filed by the maintainer over four days in
August 2026. Read together they are one theme: **the board is no longer legible at the scale it is
now being used at** — twelve boards, four of them active, ~1,000 cards, several projects, and a
stated intent to support many users.

Three legibility failures, in the order they bite:

1. **Identity.** A card's number tells you nothing about which board it is on and does not count from
   one. `KAN-` numbers are drawn from a single global sequence, so the *kaya* board's 77 cards are
   spread over the range KAN-530…KAN-971. At 10 users the numbers are meaningless; at 100 they are
   also enormous.
2. **Time.** Cycles exist and work, but there is no backlog, no grouping above the cycle, no cadence,
   and no defined behaviour when a cycle ends. And the maintainer's sharper question underneath:
   **agents and humans do not experience a sprint the same way**, and nothing in the system helps an
   agent estimate.
3. **Colour.** Labels render as coloured dots on a card — but there is no UI anywhere in the app to
   *create* a label, the colour field accepts any string, and epics have no colour at all.

This records a single **shape-of-record**. The maintainer settled the two load-bearing scope
questions directly (epics get board-local refs; board keys are scoped per user), which is recorded in
the decisions log below with the consequences those choices force.

## Why these requirements

### Identity — the numbers stopped meaning anything

Measured against the live board on 2026-08-23:

| Board | Cards | Ticket range | Density |
|---|---:|---|---:|
| Engine Room | 41 | KAN-48 → KAN-209 | 25% |
| kaya — Notes (MVP) | 77 | KAN-530 → KAN-971 | 17% |
| kopicode | 100+ | KAN-768 → KAN-960 | ~52% |

A 77-card board displaying four-digit tickets scattered over a 441-wide range is the whole complaint
in one row. Two distinct defects hide in it: the numbers are **large** (a global pool shared by every
board of every user) and they are **non-local** (they jump, because the gaps are other boards' cards).
Both get worse linearly with users. Neither is fixable by tuning; the identifier is global by
construction.

The fix is the one Linear and Jira both landed on: **the number a human reads is scoped to the
container** (`ENG-14`, `PROJ-14`), not to the installation. Linear scopes to a team, Jira to a
project; pandan's equivalent container is the board.

What makes this affordable here is that **pandan already has a global identifier and it is
load-bearing**. `card.ticket_number` is a `varchar` populated at INSERT by a Postgres sequence via a
column `server_default` ([`backend/app/models.py:425`](../../backend/app/models.py)), and
[ADR 0006](../adr/0006-data-model-and-domain-decisions.md)/[0009](../adr/0009-epic-as-first-class-entity.md) promise it is
immutable and never reused. That promise is not an obstacle to this work — **it is the mechanism that
makes it safe**. Keep `KAN-955` exactly as it is, add a board-local ref beside it, and no history
splits, no stored string lies, and cross-board addressing keeps working.

The expensive half is not storage, it is **resolution**. `KAN-<n>` is parsed in at least five places
that must learn a second form:

- [`backend/app/routers/cards.py`](../../backend/app/routers/cards.py) — the `refs=KAN-12,KAN-45` batch
  read (issue #254) and its `X-Unresolved-Selectors` report
- [`backend/app/autosync.py:53`](../../backend/app/autosync.py) — `_TICKET_RE = re.compile(r"KAN-(\d+)")`,
  which reads GitHub branch names and PR titles (ADR 0016)
- [`pandan-cli/pandan_cli/cli.py:1797,1830`](../../pandan-cli/pandan_cli/cli.py) — `_resolve_card` /
  `_resolve_epic` gate on `startswith("KAN-")` / `startswith("EPIC-")`
- The SPA — `Card.svelte`, `BoardTable.svelte`, `EpicItem.svelte`, `CommandPalette.svelte`,
  `dashboard.svelte.ts`
- **Stored prose.** Activity summaries and notification bodies embed the ticket as literal text
  (`f"created {card.ticket_number}: {card.title}"`), and `metrics.py` still parses pre-KAN-260
  summaries. These are history. **They are not rewritten** — see the decisions log.

### Time — cycles are built, the calendar around them is not

The sprint half of [#279](https://github.com/leejianrong/pandan/issues/279) is **mostly already
shipped**, which is why this milestone's time work is smaller than the issue's title suggests.
`Cycle` has been a first-class board-scoped entity since V33 (KAN-297): `starts_on` / `ends_on`, a
nullable `card.cycle_id` mirroring `epic_id`, burndown + velocity via `pandan cycle metrics`, a
dashboard panel, and CRUD-lite from both adapters. "Two weeks per sprint" is expressible today.

Five gaps remain. Four were named in the issue's triage comment; the fifth was found while shaping
this milestone:

1. **No `PATCH /cycles/{id}`.** [`backend/app/routers/cycles.py`](../../backend/app/routers/cycles.py)
   has list, create, get, metrics and delete — nothing else. A sprint cannot be renamed and a
   mistyped date cannot be corrected. The only recovery is delete-and-recreate, which detaches every
   card in it (`ON DELETE SET NULL`). This is the cheapest and most obviously wrong gap in the
   milestone.
2. **Backlog is implicit.** A card with no `cycle_id` is "the backlog", but there is no view to groom
   it and no way to say *deliberately parked* rather than *not yet scheduled*.
3. **No grouping above the cycle.** The maintainer's "6 sprints per planning interval" has no entity.
4. **No cadence.** Cycles are created one at a time, by hand.
5. **No defined end-of-cycle behaviour.** An unfinished card keeps a stale `cycle_id` forever, which
   quietly corrupts the velocity `cycle metrics` already reports.

Underneath these sits the more interesting question the maintainer raised in the issue thread:

> Humans work in two week sprints naturally. However, coding agents can code much faster than humans
> […] claude is notoriously bad at estimating time frames because it is unaware of how fast it can
> write code.

The instinct in the thread was a second point scale — "1 agent story point = 3 or 5 human story
points." **This milestone deliberately does not build that**, and the reasoning is in the decisions
log: a declared multiplier is a number nobody trusts and everybody re-argues, and the same thread
states the governing constraint — *"priority should be human readability"* — which a dual scale
violates. The data needed to answer the question honestly is **already in the database**.

### Colour — the picker has nowhere to live

Tracing [#278](https://github.com/leejianrong/pandan/issues/278) moved the problem. Labels *already*
render as a coloured dot plus name on every card
([`Card.svelte:163-167`](../../frontend/src/lib/components/Card.svelte)), so the issue's "maybe as
little coloured circles" is shipped. Three things are actually missing, and the first one is the
blocker:

- **There is no label management UI at all.** `createLabel` and `deleteLabel` exist in
  [`frontend/src/lib/api.ts:453,463`](../../frontend/src/lib/api.ts) — and **no component calls
  either one**. Labels can only be created from the CLI or MCP. A colour picker cannot be added
  because the screen it belongs on does not exist.
- **`color` is unvalidated.** [`schemas.py:219`](../../backend/app/schemas.py) accepts any non-empty
  string ≤32 chars. `"banana"` is a valid label colour today; it renders as nothing.
- **Epics have no colour field.** The model carries `name`, `description`, `target_date`, `lead`.

There is a further constraint the issue could not have known. M6's design system
([`frontend/src/app.css`](../../frontend/src/app.css)) defines every colour token **twice**, once for
light and once for dark. A raw `<input type="color">` producing a user-chosen hex has no dark variant,
so roughly half of all picks will be unreadable in one of the two themes. This is why the shape below
specifies a palette rather than a picker.

## Requirements (R)

**R1 — Identity (issue #280)**

- **R1.1** A card and an epic each display a **board-local** reference that counts from 1 within its
  board and contains no gaps caused by other boards.
- **R1.2** `card.ticket_number` / `epic.ticket_number` remain **exactly as they are** — same values,
  same sequences, same immutability promise (ADR 0006/0009). No migration rewrites them.
- **R1.3** Both forms resolve, everywhere a reference is accepted today: API path params, the `refs=`
  batch read, both CLI resolvers, and the autosync branch/PR-title regex.
- **R1.4** A board carries a short human **key** (`ENG`), unique **per owner**, editable, and derived
  automatically at board creation so onboarding never blocks on naming it.
- **R1.5** The design holds at 100 users and many boards each: no per-board DDL, no global lock, no
  key namespace that a second user's boards can exhaust.
- **R1.6** Stored historical prose (activity summaries, notification bodies) is **not** rewritten.

**R2 — Time (issue #279)**

- **R2.1** A cycle can be edited after creation.
- **R2.2** The backlog is a first-class thing you can look at, filter and groom, and *deliberately
  parked* is distinguishable from *not yet scheduled*.
- **R2.3** Cycles can be grouped into a **planning interval**, with rolled-up metrics.
- **R2.4** A run of cycles on a fixed cadence can be generated in one call.
- **R2.5** Ending a cycle is an **explicit act** with defined consequences for unfinished cards, and
  velocity is computed against what the cycle committed to, not its live membership.
- **R2.6** The board reports **observed** throughput separately for agent and human assignees, so an
  estimate can be calibrated against evidence rather than a declared multiplier.

**R3 — Colour (issue #278)**

- **R3.1** Labels are fully manageable from the SPA — create, rename, recolour, delete.
- **R3.2** Label and epic colours come from a bounded palette that is defined for **both** themes.
- **R3.3** `color` is validated at the schema layer; an unrenderable value is a `422`, not a blank dot.
- **R3.4** Epics carry a colour, shown on the epic and on its member cards.
- **R3.5** A label can carry a second, non-colour visual dimension for at-a-glance distinction.

**R4 — Constraints**

- **R4.1** API-first (ADR 0005): every capability lands as an endpoint before any UI uses it.
- **R4.2** Every schema change is **additive**, with a backfill; no destructive migration.
- **R4.3** CLI ↔ MCP parity is maintained in both directions and stays pinned by
  `pandan-cli/tests/test_parity.py`.
- **R4.4** Any migration-carrying PR lands **alone** (the standing deploy rule).

## Decisions log

**D1 — The canonical ticket stays; the board-local ref is added beside it.**
`KAN-955` remains stored, immutable and globally unique. `ENG-14` is a second, *board-local* rendering
built from `board.key` + a per-board sequence number. Rejected alternative: rewriting `ticket_number`
in place. It would break every stored activity summary, every external link, the autosync contract and
ADR 0006's promise, and it buys nothing the additive design does not.

**D2 — Board keys are unique per owner, not globally.** *(maintainer decision, 2026-08-23)*
A `UniqueConstraint("owner_id", "key")`. Postgres treats NULLs as distinct, so the nullable
`board.owner_id` (`ON DELETE SET NULL`) needs no partial index and orphaned boards can never collide.
This scales: at 100 users a global namespace would have users fighting over `ENG`, and the good short
keys would be gone within the first dozen signups.

**D3 — …which makes a board-local ref ambiguous across users, so board-local refs resolve
board-locally.**
This is the consequence D2 forces, and it is the most important sentence in this document. Boards are
shareable (`BoardMember`, viewer/editor/owner), so a user who owns `ENG` may also be a member of
someone else's `ENG`. Therefore:

| Form | Scope | Resolves from | Stored |
|---|---|---|---|
| `KAN-955` / `EPIC-7` | **global**, canonical, immutable | anywhere, no board context needed | yes, as today |
| `ENG-14` / `ENG-E7` | **board-local**, display | only within a known board | as `key` + `board_seq` |

`pandan get ENG-14` resolves against the active board (`PANDAN_BOARD_ID`). Given no board context and
more than one accessible match, it fails with a new `ambiguous_ref` error naming the candidate boards
— never a silent pick. **This is the payoff for keeping the canonical ticket**: it is not merely
backward compatibility, it is the cross-board addressing mode, and it is why D1 and D2 fit together
instead of fighting.

**D4 — Epics get board-local refs too, as a second independent per-board sequence.**
*(maintainer decision, 2026-08-23)*
`ENG-E7`, from `epic.board_seq` + `board.next_epic_seq`. This mirrors today's design exactly — two
independent sequences, two distinct prefixes, `KAN-1` and `EPIC-1` coexisting — merely scoped to a
board instead of the installation, so the migration is symmetric and the mental model is unchanged.
Rejected alternative: one shared per-board sequence across cards and epics (the Jira model, where an
epic *is* an issue). It reads more cleanly (`ENG-7` for either) but collapses a separation ADR 0009
deliberately created.

**D5 — Board keys match `^[A-Z][A-Z0-9]{1,9}$`, and `KAN`/`EPIC` are reserved.**
No hyphens in a key means a ref splits unambiguously on its **first** hyphen: the head is the key, an
all-digit tail is a card, an `E`+digits tail is an epic. Reserving the two canonical prefixes
case-insensitively means a board key can never shadow the global form, so D3's table stays decidable
by inspection.

**D6 — Per-board numbering uses a counter column on `board`, not a sequence per board.**
`UPDATE board SET next_card_seq = next_card_seq + 1 WHERE id = :id RETURNING next_card_seq`, run
inside the insert transaction. One statement, row-locked by Postgres, no DDL per board (which would
not survive R1.5 — 100 users × several boards is hundreds of sequence objects).

The tradeoff is worth stating plainly because it inverts the usual advice: **a Postgres sequence never
blocks and always leaves gaps on rollback; a counter column briefly serialises writers to one board
and is gapless.** Gapless is precisely what issue #280 asked for — *"the numbers jump and are not
sequential (locally)"* — so the property normally treated as a sequence's advantage is, here, the
defect being fixed. Batch creates take the whole range in one statement
(`… + :n RETURNING next_card_seq`) rather than N round trips.

**D7 — Soft-deleted cards are numbered too.**
The backfill partitions over **all** rows including `deleted_at IS NOT NULL`, and the counter is not
decremented on delete. Skipping trashed cards would renumber the live ones around them and make
restoring a card a collision.

**D8 — Backlog is derived from `cycle_id IS NULL`, not a fifth column.**
Rejected alternative: adding `backlog` to the `column` CHECK. The varchar+CHECK design (ADR 0008)
exists exactly so a new column value costs no `ALTER TYPE`, so this was genuinely available — but it
double-models scheduling. A card could sit in the `backlog` column *and* be assigned to a cycle, which
is incoherent, and it would ripple through the three-places-in-sync rule (`VALID_COLUMNS`,
`ColumnEnum`, `api.ts`), the dnd zones, metrics and the e2e specs. Backlog is a question about
*scheduling*, and this board already models scheduling as cycles. What is genuinely missing is one
nullable field to mark *deliberately parked*, plus a view.

**D9 — Rollover is an explicit verb; nothing moves on its own.**
`POST /cycles/{id}/close` moves unfinished cards to a named target (another cycle, or the backlog) and
stamps the cycle closed. Auto-rollover on the `ends_on` date is rejected: it silently rewrites history
that `cycle metrics` has already reported, which is the standard regret in sprint tooling and
un-diagnosable after the fact. Closing also fixes the committed set, so velocity stops being
recomputed from live membership.

**D10 — Agent time is *measured*, not declared. No second point scale.**
The dual-scale proposal from the issue thread is not built. Instead, `metrics` reports **observed
points-per-day split by assignee class** — `agent:*` prefixes versus human emails — derived from data
already present in the activity log and `card.assignee`. Three reasons:

1. The maintainer's own stated constraint in the same comment is *"priority should be human
   readability"*, and two point scales on one card is the opposite of that.
2. A declared multiplier is unfalsifiable and gets re-argued every planning session. A measured one
   improves on its own as the board runs, and is board-specific.
3. The stated root problem — *"claude is […] unaware of how fast it can write code"* — is a
   **feedback** problem, not a **units** problem. Give the agent its own historical throughput and the
   estimate calibrates itself; give it a new unit and it guesses in the new unit.

"Agent sprints are a day" then needs no new time model at all: it is a cycle whose `starts_on` and
`ends_on` are a day apart, which is expressible today.

**D11 — Colours come from a bounded palette, not a free hex picker.**
Every token in `app.css` is defined twice, once per theme. A user-picked hex has one value and will be
unreadable in one theme roughly half the time. The palette ships named tokens, each with a light and a
dark value; the picker is a swatch grid. **It shipped as seven, not the ~12 estimated here** — the
disjointness requirement in Q5 turned out to exclude most of the hue wheel once the priority dots were
counted and once "disjoint" was measured rather than judged by name; the numbers are in Q5 and in
`backend/tests/unit/test_palette.py`. Existing free-string colours keep rendering as-is
(there is no migration of stored values) — only *new* picks are constrained. Accepting this means the
column stays `varchar(32)` and validation is "a palette token **or** a well-formed hex", with the UI
offering only the former.

**D12 — The second visual dimension is an emoji, not a shape enum.**
Issue #278 floated shapes (square, triangle, star, crescent) *or* emoji. Emoji wins on four counts: it
is one grapheme so it needs no new render code; it extends without a schema change; it is already
accessible by its own name; and it survives into the CLI's human output, where an SVG shape is simply
invisible. `label.emoji`, nullable, grapheme-count validated. Known cost: wide glyphs break
tab-alignment in the CLI's human rows, so it is opt-in via `--fields`.

## Open questions (resolve during slicing)

- **Q1** Board-key derivation on collision — numeric suffix (`ENG`, `ENG2`) or ask the user? Lean
  suffix, because R1.4 says creation must never block.
- **Q2** Ownership transfer across a key collision in the new owner's namespace. Auto-suffix and
  record it in the activity log? (Edge case today; certain at 100 users.)
- **Q3** ~~A per-user toggle between canonical and board-local display?~~ **Settled: no toggle.**
  Board-local is simply what a board shows, and the collision case is handled by qualification
  rather than by a mode — see *Detail — when two accessible boards share a key* below.
- **Q4** Does `planning_interval` need its own metrics endpoint, or does `cycle metrics` grow a
  `planning_interval_id` filter? Lean the filter.
- **Q5** ~~Do the existing semantic tokens participate?~~ **Settled 2026-08-23: the label palette is
  DISJOINT from the semantic tokens** (`--accent`, `--agent`, `--danger`, `--success`, `--warning`), so a
  label can never accidentally read as a status. ~~Which twelve hues is still a V62 call.~~
  **V62 settled it at SEVEN**, and in doing so found the decision bites harder than expected: the
  exclusion set also has to cover `Card.svelte`'s **priority dots** (amber, orange, `--danger`,
  `--muted`), which are the same visual primitive as a label dot in the same card. Measuring ΔE
  instead of eyeballing hue then rejected three of a hand-picked nine — `slate` at 6.9 from `--muted`
  (what priority "low" paints), `indigo` at 14.4 from `--agent`, `brown` at 14.8 from `--warning` —
  and with green/violet/red/orange/grey out, the remaining blues and magentas cannot field nine that
  separate from each other (mutual ΔE 11.2 vs 21.4 at seven). See D11.

## Shape — "Legible at Scale"

Three parts, sequenced so the cheap self-contained one de-risks the expensive one.

**Part C — Colour (ships first).** No schema risk, no resolution surface, and its first slice closes a
gap agents hit weekly (labels unmanageable from the UI). Ships while Part A's migration design is
still being reviewed.

**Part A — Identity.** The milestone's centre of gravity and the only part carrying a non-trivial
migration. Four slices, deliberately ordered so that **nothing is visible until everything resolves**:
add the key, add the numbers, teach every resolver, *then* render. A user never sees a ref that
something cannot parse.

**Part B — Time.** Begins with the one-afternoon `PATCH` fix, then builds outward. Its last slice
(observed velocity) is the milestone's most interesting deliverable and depends on nothing else in it.

## Fit Check — R × Part

| Requirement | Part A (Identity) | Part B (Time) | Part C (Colour) |
|---|:---:|:---:|:---:|
| R1.1 board-local refs | ✅ V52/V54 | | |
| R1.2 canonical unchanged | ✅ D1, pinned by test | | |
| R1.3 both forms resolve | ✅ V53 | | |
| R1.4 board key | ✅ V51 | | |
| R1.5 holds at 100 users | ✅ D2/D6 | | |
| R1.6 history not rewritten | ✅ D1 | | |
| R2.1 editable cycle | | ✅ V55 | |
| R2.2 backlog | | ✅ V56 | |
| R2.3 planning intervals | | ✅ V57 | |
| R2.4 cadence | | ✅ V58 | |
| R2.5 explicit close | | ✅ V59 | |
| R2.6 observed agent throughput | | ✅ V60 | |
| R3.1 label CRUD in the SPA | | | ✅ V61 |
| R3.2 dual-theme palette | | | ✅ V62 |
| R3.3 colour validated | | | ✅ V62 |
| R3.4 epic colour | | | ✅ V63 |
| R3.5 second dimension | | | ✅ V64 |
| R4.1 API-first | ✅ | ✅ | ✅ |
| R4.2 additive migrations | ✅ | ✅ | ✅ |
| R4.3 CLI ↔ MCP parity | ✅ | ✅ | n/a (UI) |
| R4.4 migrations land alone | ✅ | ✅ | ✅ |

Every requirement is covered by exactly one part. No requirement needs two parts to land before it is
demonstrable, which is what makes the three shippable in any order after V51.

## Detail — affordances

**A board-local ref, end to end.** A board named "Engine Room" is created; its key derives to `ENGI`
and the owner edits it to `ENG`. The next card created is `ENG-42`, and its canonical `ticket_number`
is whatever the global sequence gave it — say `KAN-1013`. The SPA renders `ENG-42`. `pandan get ENG-42`
works with `PANDAN_BOARD_ID` set; `pandan get KAN-1013` works from anywhere. A branch named
`eng-42-fix-the-thing` is matched by autosync. A card moved between boards keeps `KAN-1013` and takes a
new board-local ref on arrival.

**When two accessible boards share a key.** Per-owner uniqueness (D2) means Alice can own an `ENG`
and Bob can own an `ENG`. If Alice shares hers with Bob, Bob now sees two `ENG` boards. This is the
one case per-user keys create, and it resolves on a single observation:

> **A key collision is a property of the *viewer*, not of the board.**

Alice never has one — she owns exactly one `ENG`. Only Bob does. So the collision is **computed per
viewer at display time and never stored**, and in particular **no board is ever renamed because
someone shared another board with you**. A share event mutating the sharer's data would be indefensible;
it is also unnecessary.

Three rules follow, and together they are the whole UX:

1. **Inside a board, nothing is ever qualified.** You are in one board, the header names it, and
   `ENG-14` means this board's 14. This is where most reading happens, so most reading is unaffected.
2. **Across boards, qualify — but only on collision.** The cross-board surfaces are the dashboard, the
   notification inbox, the command palette, search results, the activity feed and the board switcher.
   There a colliding ref renders as **`alice/ENG-14`**, borrowing GitHub's `owner/repo` idiom that every
   user already reads fluently. A shared board whose key does *not* collide stays bare — qualification
   appears exactly where it is needed and nowhere else.
3. **The canonical ticket is always one hover away.** `KAN-955` is shown in the title attribute and is
   what click-to-copy yields, because it is the form that is unambiguous everywhere — in a message to a
   colleague, in a branch name, in a PR title. The escape hatch is not a new feature; it is the
   identifier D1 declined to remove.

**The qualified form must be accepted as input, not merely printed.** This is a hard constraint rather
than a nicety: `pandan-cli/tests/test_cli.py:3371` (V42 / KAN-425) takes the identifier out of every
printed row and feeds it back verbatim, on the standing rule that *the CLI accepts every identifier it
prints*. So `pandan get alice/ENG-14` resolves, and V53 owes a third accepted form, not two.

**And the error is a menu, not a refusal.** Given a board-local ref with no board context that matches
more than one accessible board, `ambiguous_ref` lists the candidates with their owner and canonical
ref, so the next command is visible rather than guessable:

```
error	ambiguous_ref	'ENG-14' matches 2 accessible boards	ENG-14
  board 5  ENG  Engineering   (alice)  → KAN-955
  board 6  ENG  Engine Room   (you)    → KAN-207
help: pandan get KAN-207
help: pandan --board 6 get ENG-14
```

Two consequences worth noticing, both of which fall out for free. If Alice later re-keys her board to
`ACME`, Bob's collision simply disappears — nothing to migrate, because nothing was stored. And a
viewer-local nickname for someone else's board (Bob calling Alice's `ACME` in his own view) stays
available as a later escape hatch if qualification proves insufficient; it is deliberately **not** built
now, because it is per-user-per-board state and a setting nobody finds.

**Closing a cycle.** `pandan cycle close 7 --rollover-to 8` reports what moved:
`closed Sprint 12 · 9/13 done · 4 rolled over to Sprint 13`. `pandan cycle metrics 7` afterwards still
reports 13 committed and 9 completed, because closing froze the committed set. Nothing happened on the
`ends_on` date itself.

**Calibrating an estimate.** `pandan metrics --by-assignee-class` reports
`agent: 6.2 pts/day (n=143)` and `human: 1.4 pts/day (n=38)`. An agent planning a one-day cycle now has
an evidence-backed budget instead of a guess, and nobody had to invent an "agent point".

**Managing a label.** A Labels screen lists the board's labels with their swatch and emoji. Creating
one opens a 7-swatch grid (each swatch a token that is already defined for both themes) and an
optional emoji field. The card chip renders emoji + dot + name; `pandan list --fields ticket,labels`
shows the emoji in the terminal.

## Out of scope for M8

Recorded so it does not creep in:

- **Renaming or renumbering `ticket_number`.** D1. The canonical identifier is untouched, forever.
- **Rewriting stored activity summaries or notification bodies** to use the new refs (R1.6).
- **A second story-point scale for agents.** D10 — measured, not declared.
- **Auto-rollover on the `ends_on` date.** D9 — closing is a verb.
- **A free-hex colour picker.** D11 — the palette is the picker.
- **Shape glyphs for labels.** D12 — emoji covers it.
- **Board-level or user-level renumbering.** Issue #280 asks about boards "maybe in the future"; a
  board's human identifier is its **key**, which V51 delivers. Board *ids* stay as they are.
- **Multi-tenant org/workspace entities.** D2 scopes keys to a user, which is what today's ownership
  model supports. A workspace tier above the user is a later milestone's decision, and D2 is
  deliberately compatible with one.
