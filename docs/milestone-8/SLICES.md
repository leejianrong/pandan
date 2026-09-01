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
| **V55 · `PATCH /cycles/{id}`** ✅ | a sprint you can edit | B | KAN-976 | 1 | `pandan cycle update 7 --name 'Sprint 12'` works and the cards stay attached |
| **V51 · Board keys** ✅ | `board.key`, unique per owner 🗄️ | A | KAN-972 | 3 | A board has a key; two users can each own an `ENG`; keying a board `KAN` is a clean `422` |
| **V52 · Per-board sequences** ✅ | `board_seq` + backfill 🗄️ | A | KAN-973 | 5 | Every card and epic carries a gapless board-local ref in its payload |
| **V53 · Resolution** ✅ | both forms, everywhere | A | KAN-974 | 5 | `pandan get ENG-42` and `pandan get KAN-1013` return the same card |
| **V54 · Render** ✅ | SPA + CLI show the ref | A | KAN-975 | 3 | The board reads `PAN-1…PAN-77` instead of `KAN-530…KAN-971`; `--fields ticket` still gives the canonical form |
| **V62 · Dual-theme palette** ✅ | + colour validation | C | KAN-983 | 3 | Every label is readable in both themes; a bad colour is a `422` |
| **V63 · Epic colour** | 🗄️ | C | KAN-984 | 2 | An epic's stories are recognisable on the board without reading them |
| **V64 · Label emoji** | 🗄️ | C | KAN-985 | 2 | Two labels sharing a colour are still distinguishable at a glance |
| **V56 · Backlog** | derived, groomable | B | KAN-977 | 3 | The backlog is a place you can open; parked ≠ never scheduled |
| **V57 · Planning intervals** | 🗄️ | B | KAN-978 | 5 | Six cycles roll up into one PI with a single committed-vs-completed number |
| **V58 · Cadence** | generate N cycles | B | KAN-979 | 2 | "Two weeks per sprint, six sprints" is one command |
| **V59 · Explicit close** | + rollover | B | KAN-980 | 3 | Closing is deliberate and reported; past velocity numbers stop moving |
| **V60 · Observed throughput** | agent vs human | B | KAN-981 | 3 | `agent: 6.2 pts/day (n=143)` — a budget backed by evidence, not a multiplier |

🗄️ = carries a migration, lands alone. ✅ = shipped.

Total: **40 points across 14 slices**, plus one standalone bug (KAN-986) found while tracing #280 —
**now landed**.

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

### V51 · Board keys — KAN-972 ✅ 🗄️

`board.key`, `^[A-Z][A-Z0-9]{1,9}$`, `UniqueConstraint(owner_id, key)`. Postgres treats NULLs as
distinct, so the nullable `owner_id` needs no partial index and orphaned boards cannot collide.
`KAN` and `EPIC` are reserved case-insensitively. Derived automatically at board creation with a
numeric suffix on collision, because creation must never block on naming (R1.4).

No hyphens in a key is load-bearing: it means a ref splits unambiguously on its **first** hyphen —
head is the key, all-digit tail is a card, `E`+digits tail is an epic.

**Shipped with [ADR 0020](../adr/0020-board-keys.md).** Four notes worth keeping:

- **The migration marker was missing from the table above.** V51 adds a column, so it always carried
  one; the intro's "five of these fourteen slices carry a migration" was right and the table listed
  four. Corrected, and worth remembering as the failure mode this file is most prone to — a count in
  prose that no longer matches the rows under it.
- **Two failure codes, chosen rather than defaulted.** Malformed or reserved is a `422` (a fact about
  the request); a key already used by that owner is a `409` (a fact about the database). A caller
  deciding whether to fix the argument or pick another key needs to know which. Auto-derivation cannot
  hit either — it suffixes.
- **The derivation is duplicated into the migration on purpose**, not imported from
  `app.board_keys`. A migration is a historical record and must keep producing the same result years
  from now, which importing live code forfeits. The copies may drift after that revision and no
  invariant depends on their agreeing.
- **+215 resident MCP tokens** (8,426 → 8,641 compact, measured both ways) for the `key` argument on
  `create_board` and `update_board`. ADR 0019's freeze is on the tool *count*, unchanged at 49.

### V52 · Per-board sequences — KAN-973 ✅ 🗄️

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

**Shipped.** Five notes worth keeping:

- **The counter columns are named `next_*` but hold the *last* number issued.** A board
  with 77 cards holds 77, and `SET next_card_seq = next_card_seq + 1 … RETURNING
  next_card_seq` is what makes the returned value the next one. The shape pins both the
  name and the statement, so the discrepancy is recorded in the model's own comment
  rather than silently renamed. Storing the true next value and returning
  `next_card_seq - 1` would have made the name honest; it was not worth deviating from a
  twice-written decision, and this note is the alternative.
- **Allocation happens after validation**, so a create that `422`s consumes no number.
  Gaplessness has to survive failed writes, and nothing gives a number back.
- **`apply_template` is the only server-side batch create**, so it is the only place the
  range allocation applies. The MCP's `create_cards` is a client-side loop over N HTTP
  posts and allocates one at a time by construction — worth knowing before looking for a
  batch endpoint that does not exist.
- **`ref` is attached, not stored**, which is what makes `board.key` editable: changing a
  key re-labels every ref on the board at once and rewrites nothing. It is optional on
  the schema so a route that forgets to attach it returns null rather than a 500 — and a
  test that walks every card- and epic-returning route is what actually holds the
  promise. The trash listing was the one gap found that way; it now attaches refs (and
  still, deliberately, not labels/links, which it never did).
- **The payload grows by two keys per row**, which is a real per-read MCP cost given
  ADR 0019's finding that breadth is where the tokens are. Estimated at
  `"board_seq":14,"ref":"ENG-14"` ≈ 12 tokens × 121 rows ≈ **+1.5k** on an un-narrowed
  `list_cards` — an estimate from arithmetic, not a measurement; re-run
  `mcp/scripts/measure_read_payload_tokens.py` once it is deployed. The `fields`
  narrowing KAN-501 added is the mitigation, and `ref` is selectable through it with no
  code change, because both adapters derive their valid field names from the payload.

**One trap this slice sprang, worth remembering.** V51's backfill test downgraded with
`command.downgrade(cfg, "-1")`, which meant "undo the board-keys migration" only while
that migration was head. Adding this one silently changed what `-1` meant and the test
failed on assumptions that were no longer true. Any migration-bracketing test must name
its revision.

### V53 · Resolution — KAN-974 ✅

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

**Shipped, with three deliberate departures from the sketch above and one addition.**

1. **The menu is one row, not a block.** The CLI's error line is four tab-separated
   columns and a consumer greps `cut -f2` (V43/AXI 6), so candidate lines under it would
   either break that contract or need a second, parallel rendering. Every fact in the
   sketch survives, semicolon-separated inside the message: board id, key, name, owner,
   and the canonical ticket that makes the next command copyable.
2. **The API requires `board_id` for a board-local ref rather than resolving across every
   visible board.** Both alternatives were worse: resolving broadly returns two cards for
   one selector *silently*, and failing the whole request on one ambiguous selector
   contradicts the batch read's own design, where a miss is reported and not fatal.
   Requiring the board is what "board-local" already means (D3). `ambiguous_ref` is
   therefore a **CLI** code — which is where V43's contract lives anyway — and the API's
   answer is a `422` naming the missing `board_id`.
3. **Auto-sync resolves the two forms in opposite directions**, and this is the sharpest
   consequence of D3 anywhere in the codebase. Canonical: find the card, the board
   follows. Board-local: a webhook has *no board context of its own*, so the board is
   found first — from the boards that opted into auto-sync — and the card follows. That
   opt-in flag stops being a convenience filter and becomes the thing that supplies the
   missing context, which is what makes board-local refs safe in a global endpoint. Two
   opted-in boards sharing a key are **skipped and logged**, never guessed: a webhook
   cannot ask.
4. **`board.owner_email` was added** (a transient field on `BoardRead`, like `role`),
   because `alice/ENG-14` is unresolvable and unprintable without it — `owner_id` is a
   UUID, not a handle a human types. The privacy question is answered rather than
   assumed: every board a caller can read is one they own or are a member of, and
   `MemberRead.email` already shows a board's members their addresses.

**And one behaviour change worth knowing about.** Widening the grammar necessarily
shrinks the set of strings that are malformed *by shape*: `TASK-1` used to be an argparse
usage error (exit 2) and is now a well-formed reference to a board that does not exist
(exit 5, `not_found`). A test that asserted the old behaviour was rewritten to pin where
it went, rather than deleted.

**The grammar exists in two packages and is proven equal, not trusted.** The CLI must not
import the backend (that would invert ADR 0005 and break a PyInstaller build), so
`backend/tests/unit/test_ref_grammar.py` reads `cli.py` as *text* and compares its
regexes and reserved-key set to `app/board_seq.py`'s — the technique `test_palette.py`
uses for the palette's four copies. One of those checks is behavioural rather than
textual, because the two patterns are deliberately different strings (a stored key is
uppercase; a reference parses case-insensitively): what it asserts is the equivalence,
that a reference can name exactly the keys a board can hold.

**There is deliberately no shared `resolve_ref(db, ref)`.** An earlier draft had one and
it was deleted unused: each call site resolves against a different scope — the caller's
visible boards, the auto-sync-enabled boards, the configured board — and a shared helper
would take that scope as a parameter, which is to say it would be a wrapper around the two
lines each caller already writes. The *grammar* is what must not be duplicated.

### V54 · Render — KAN-975 ✅

**One helper, both sides.** `frontend/src/lib/tickets.ts` gained `displayRef(entity)` — `ref ?? ticket_number`
— and every display site was routed through it. The 2026-08-23 site list undercounted: the app had grown
`CardModal.svelte`, `EpicModal.svelte`, `Dashboard.svelte`, `Trash.svelte` and `CardForm.svelte` since
that note was written, none of them in the original enumeration. All ten SPA files now show the
board-local ref: `Card.svelte`, `CardModal.svelte`, `BoardTable.svelte`, `EpicItem.svelte`,
`EpicForm.svelte`, `EpicModal.svelte`, `CommandPalette.svelte`, `Dashboard.svelte`, `Trash.svelte`,
`CardForm.svelte`. The CLI got the mirror: `cli.py`'s `_display_ref` for `_card_line`/`_epic_line`, and
the same fallback duplicated (not imported — `context.py` cannot circularly import `cli`) into
`context.py`'s `_card_row` for the `pandan context show` ambient block.

**Search matches both forms; sort follows the displayed one.** `CommandPalette.svelte`'s `keywords`
carry the board-local `ref` alongside `ticket_number`, so a search matches **either** form — its own
instruction, read literally — while `value` (the list's own React-style key) stays on the concatenated
canonical string, since changing an internal identity key was out of scope for a rendering slice.

Sorting originally stayed on `ticket_number` on the reasoning that it orders rows rather than displaying
them, and that `board_seq` tracks creation order identically. The follow-up pass moved
`BoardTable.svelte` and `dashboard.svelte.ts` to `compareTicketRefs(displayRef(a), displayRef(b))`: a
user sorts the column they can *see*, and a table headed `ENG-14` that ordered itself by a hidden
`KAN-955` reads as broken. The original reasoning holds *within* one board — both keys track creation
order, so the orders coincide and nothing changes — which is precisely why the switch is safe; it only
differs across boards, and that is the case where the old behaviour was inexplicable rather than merely
invisible.

**`--fields ticket` still means `ticket_number`, on purpose.** The default row and the explicit field
selector are supposed to disagree now: the row is a display choice, the field is the one that resolves
from anywhere. Documented in `reference/api.md`, `pandan-cli/README.md`, and
`docs/guide/cli/reading.md` — the ADR 0018-style "notice on the wire" pattern (here: `--fields ticket`
does not silently start meaning something new) applies exactly.

**The one known gap is now closed (follow-up pass).** `GET .../metrics`' `aging_wip.items`
(`AgingWipItem`) shipped without a `ref` field, because that is a backend/schema change and V54 was a
pure-rendering slice — so the dashboard's aging-WIP bars were briefly the one surface still showing the
canonical `ticket_number` while the board beside them showed the board-local form. A follow-up added
`ref` to `AgingWipItem`, rendered in `routers/boards.py`'s metrics endpoint from this board's key
(`card_ref(board_key, row.board_seq)`, the same `if key else None` guard the card and epic reads use)
and passed through `metrics.py`, which stays a pure function of the dicts it is handed and derives
nothing itself. `Dashboard.svelte`'s bars and `aria-label`s now go through `displayRef`. Pinned by
`test_metrics.py`, which asserts the item's `ref` equals the card read's own — not merely that it is
non-null.

KAN-986 **already landed**, so nothing to fold in — `compareTicketRefs` is board-local-ref-aware by
construction (see *Loose card* below). The ordering was worth fixing before this slice rather than
inside it: board-local refs make that sort bug **more** visible, not less, since a 77-card board goes
from a sparse `KAN-530…971` to a solid `1…77`, where lexicographic misordering is obvious.

**Two e2e specs pinned a display shape that stopped being true.** `dependencies.spec.ts` and
`epic-story.spec.ts` asserted a rendered `.ticket` matched `/^KAN-\d+$/` / `/^EPIC-\d+$/` — true only
because every e2e board used to render the canonical form. First loosened to accept either shape, then
**tightened again in the follow-up pass** to require the board-local form only, now that the canonical
ticket is separately asserted on the element's `title` attribute. An e2e board always derives its own
key from a random name and can never be `KAN` or `EPIC` (both reserved), so the permissive alternation
could only ever have passed by accident — pinning both halves says more than accepting either.

**The canonical ticket stays reachable: hover, don't guess.** Every display site renders the
board-local ref as its text and carries `title={…ticket_number}`, so `KAN-955` is one hover away and
still selectable/copyable for anyone quoting a card outside its board. `Trash.svelte` carries it as a
`canonical` field on its merged card+epic `Entry`, since a trashed item is exactly the one you may need
to reference elsewhere. Pinned by `board-local-refs.spec.ts`, which asserts the shown text and the
`title` **disagree** — the cheapest possible proof that both forms are actually present.

**Qualification is a client concern, computed per viewer.** A key collision is a property of the
*viewer*, not the board (SHAPING, *Detail — when two accessible boards share a key*): only a user who
can see two `ENG` boards has one, and nothing is stored. Inside a board nothing is ever qualified;
across boards a colliding ref renders `alice/ENG-14` and a non-colliding one stays bare. The canonical
`KAN-955` is the title attribute and the click-to-copy value everywhere.

Deliberately last, so a user never sees a ref that something cannot parse. CLI behaviour changed, so
`pandan-cli` bumped 0.36.0 → 0.37.0 per the standing version-bump guard.

## Part B — Time (EPIC-123, issue #279)

**Most of the sprint machinery already exists**, which is why this part is smaller than the issue's
title suggests. `Cycle` has been first-class since V33 (KAN-297) with `starts_on`/`ends_on`, a
nullable `card.cycle_id`, burndown and velocity via `pandan cycle metrics`, a dashboard panel, and
CRUD-lite from both adapters. "Two weeks per sprint" is expressible today. Part B builds the calendar
*around* it.

### V55 · `PATCH /cycles/{id}` — KAN-976 ✅

Found while shaping M8; not named in the issue. `routers/cycles.py` had list, create, get, metrics and
delete — and nothing else. A sprint could not be renamed and a mistyped date could not be corrected;
the only recovery was delete-and-recreate, which detaches every card in it. One afternoon, and the
milestone's clearest bug.

**Shipped as the endpoint + the CLI, and the MCP tool was deliberately declined.** The card asked for
`update_cycle` on both adapters; ADR 0019 freezes the MCP surface at 49 tools and
`mcp/tests/test_schema.py` pins that by name *and* count, so a 50th tool is an ADR amendment and a bug
fix is not the change that should be spending one. The decline is recorded where R4.3 is actually
enforced — a `CLI_ONLY` reason-2 entry in `pandan-cli/tests/test_parity.py`, the same disposition
`label update` got in V61 — and the entry states plainly that the agent case here is the **stronger**
of the two, since agents do drive cycles. What it is not is blocked: the MCP surface was already
CRUD-lite on cycles by design, and the cycle mutation an agent makes most often is
`update_card(cycle_id=…)`.

Three field-level decisions worth keeping, all in `CycleUpdate`'s own docstring:

- `name` rejects an explicit `null` (a cycle with no name cannot be referred to); `starts_on` /
  `ends_on` accept one, because a cycle with no bounds is already valid and `null` there genuinely
  means *unschedule*.
- **Bounds are not order-checked.** `CycleCreate` never checked them, and enforcing the rule on the
  edit path alone would let an already-stored value refuse the one operation that exists to fix it.
- The CLI cannot send a `null` — `_clean` drops it, as it does for `epic update --target-date` — so
  unscheduling is reachable from the API and not the CLI. Left as the existing convention rather than
  special-cased for one field.

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

**KAN-986 — ticket sort is lexicographic.** ✅ **Landed first**, ahead of V54. `dashboard.svelte.ts`
sorted with `localeCompare(ticket_number)`, so `KAN-100` ordered before `KAN-9`, and
`BoardTable.svelte`'s ticket sort key did share the defect — verified, not assumed. Both now route
through one comparator, `frontend/src/lib/tickets.ts`.

The parse is **structural rather than a `KAN-`/`EPIC-` special case** — split off the trailing digit
run, compare what precedes it as text and the digits as a number — which is why V54 gets `ENG-14` for
free and why `ENG-E7` keeps its `E` in the prefix, so epics sort as their own run instead of
interleaving into the card numbers. **V54 therefore has nothing left to fold in.**

Its test is a pure-logic spec in the **e2e** suite (`frontend/e2e/ticket-sort.spec.ts`), and that
placement is deliberate rather than lazy: the frontend has no unit-test runner, and adding one
(vitest + a script + a CI job) is a larger change than the bug deserved. Playwright already compiles
TypeScript and already runs in CI. If a frontend unit runner ever arrives, the file moves there
unchanged.

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
