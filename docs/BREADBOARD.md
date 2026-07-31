# BREADBOARD — Pandan (MVP)

Breadboarding (Shape Up) of the selected **Shape A — "Thin Slice"**. Sources: FRAME.md, SHAPING.md.
Built **piecemeal, one section per turn** to stay within token limits.

Breadboarding models the design as **Places**, **Affordances**, and **Connections** — deliberately
*without* visual layout. It answers "what can you do here, and where does it lead?" not "what does
it look like?".

---

## Notation & legend

- **Place** — a distinct location/state the user can be in (a screen, panel, modal, or meaningful
  UI state). Not a pixel layout.
- **Affordance** — something a user can act on in a Place (a button, field, link, draggable item)
  **or** a system capability behind it (an API call, a DB mechanism). We split these into
  **UI affordances** and **Non-UI affordances**.
- **Connection** — `A ──▶ B` means acting on affordance A leads to / triggers B (another Place, or
  a Non-UI affordance).
- **[button]** = clickable control · **(field)** = input · **‹item›** = draggable/interactive
  element · **/api/...** = a Non-UI (backend) affordance.

Section status: ✅ done · ⏳ this turn · ⬜ pending.

| # | Section | Status |
|---|---------|--------|
| 0 | Overview, notation & Places inventory | ✅ |
| 1 | Place: Board View — UI affordances & wiring | ✅ |
| 2 | Place: Create Card — UI affordances & wiring | ✅ |
| 3 | Place: Edit Card — UI affordances & wiring | ✅ |
| 4 | Place: Delete confirmation — UI affordances & wiring | ✅ |
| 5 | Interaction: Drag move / reorder — affordances & wiring | ✅ |
| 6 | Non-UI affordances (API, sequence, seed, migrations) & wiring | ✅ |
| 7 | Cross-cutting states (loading / empty / error) & full connection map | ⏳ (this turn) |

---

## Section 0 — Places inventory

The MVP is a single-page app; "places" are the meaningful states within it. There is no
navigation/router beyond the SPA fallback — places are surfaced in-page (board + overlays).

| Place | What it is | Entered from | Notes |
|-------|-----------|--------------|-------|
| **P1 · Board View** | The main screen: three columns (Todo / In Progress / Done) with their cards. The default and home state. | App load; closing any overlay | The hub — every other place returns here |
| **P2 · Create Card** | Form overlay to add a new card (title required; optional description, story points, assignee; target column). | [+ Add card] affordance on a column (P1) | Returns to P1 on save/cancel |
| **P3 · Edit Card** | Form overlay to edit an existing card's fields (not ticket #). | [edit] affordance on a card (P1) | Returns to P1 on save/cancel |
| **P4 · Delete Confirmation** | Small confirm prompt before a hard delete. | [delete] affordance on a card (P1 or P3) | Returns to P1 on confirm/cancel |
| **P5 · Transient states** | Not a screen but board sub-states: initial **loading**, **empty** (no cards), and **error** (API failure toast/banner). | Any API interaction | Overlaid on P1; detailed in Section 7 |

### Places map (high level)
```
                 ┌─────────────────────────┐
        ┌───────▶│      P1 · Board View     │◀────────┐
        │        └─────────────────────────┘         │
        │            │        │        │              │
   save/cancel   [+ Add]   [edit]   [delete]      save/cancel/
        │            │        │        │           confirm
        │            ▼        ▼        ▼              │
        │      ┌──────────┐ ┌────────┐ ┌────────────┐│
        └──────│ P2 Create│ │ P3 Edit│ │ P4 Delete  │┘
               └──────────┘ └────────┘ └────────────┘
   (P5 loading/empty/error states overlay P1 — see Section 7)
```

---

## Section 1 — Place: P1 · Board View

The home screen. On entry it loads all cards and renders three fixed columns, each listing its
cards in `position` order. This is the hub every other place returns to.

### Entry & load wiring
```
App load / return to P1 ──▶ /api/cards (GET)  ──▶ board state populated
                                              ──▶ (no cards) show empty state (P5)
                                              ──▶ (in flight) show loading state (P5)
                                              ──▶ (failure)   show error banner (P5)
```

### UI affordances

| Affordance | Type | Location | Connection (what it leads to / triggers) |
|-----------|------|----------|-------------------------------------------|
| **Column header** ×3 | label | top of each column (Todo / In Progress / Done) | none (static); optionally shows card count |
| **[+ Add card]** ×3 | button | footer/header of each column | ──▶ **P2 · Create Card**, pre-set to that column |
| **‹Card›** | draggable item | within a column | drag ──▶ **Drag move/reorder** interaction (Section 5) |
| **Card: ticket #** | label | on each card | none (display only; e.g. `KAN-12`) |
| **Card: title** | label | on each card | none (display); truncates long titles |
| **Card: story points badge** | label | on each card | shown only when set; none |
| **Card: assignee** | label | on each card | shown only when set; none |
| **[edit]** (per card) | button/affordance | on each card (icon or click card body) | ──▶ **P3 · Edit Card** for that card |
| **[delete]** (per card) | button | on each card | ──▶ **P4 · Delete Confirmation** for that card |
| **[retry]** | button | on error banner (P5) | ──▶ re-issue `/api/cards` (GET) |

### What a card displays (read model)
`KAN-<n>` · **title** · story-points badge (if set) · assignee (if set). Description is *not* shown
on the board face — it appears in the Edit place (P3). Keeps the board scannable.

### Non-UI affordance touched here
- **`GET /api/cards`** — returns all cards; the client groups by `column` and sorts by `position`.
  Detailed in Section 6.

### Wiring summary
```
P1 ──[+ Add card]──▶ P2 (create, column preset)
P1 ──[edit]───────▶ P3 (edit that card)
P1 ──[delete]─────▶ P4 (confirm delete)
P1 ──‹drag card›──▶ move/reorder interaction (Section 5) ──▶ /api/cards/{id}/move ──▶ refetch ──▶ P1
P1  ◀── save/cancel/confirm ── P2 / P3 / P4
```

### Open notes for later sections
- Exact drop/positioning semantics on drag → **Section 5**.
- The move/create/edit/delete API contracts → **Section 6**.
- Loading/empty/error visuals & the refetch-after-mutation rule → **Section 7**.

---

## Section 2 — Place: P2 · Create Card

A form overlay for adding a new card. Opened from a column's **[+ Add card]**, which pre-selects
that column. Title is the only required field.

### Entry wiring
```
P1 [+ Add card on column X] ──▶ open P2 with (column)=X preset, other fields blank
```

### UI affordances

| Affordance | Type | Required | Connection / behavior |
|-----------|------|:--:|-----------------------|
| **(Title)** | text field | ✅ | non-empty; drives enable state of [Create] |
| **(Description)** | textarea | — | optional plain text |
| **(Story points)** | select | — | options: —(none), 1, 2, 3, 5, 8, 13; default —(null) |
| **(Assignee)** | text field | — | optional free text |
| **(Column)** | select | — | Todo / In Progress / Done; preset from the originating column, editable |
| **[Create]** | button (primary) | — | disabled until Title non-empty ──▶ `POST /api/cards` |
| **[Cancel]** | button | — | ──▶ discard, return to **P1** |
| **inline validation msg** | label | — | shows server/client validation errors (e.g. bad story points) |

### Submit wiring
```
[Create] ──▶ POST /api/cards { title, description?, story_points?, assignee?, column }
   ├─ 201 Created ──▶ close overlay ──▶ refetch GET /api/cards ──▶ P1 (new card visible in column,
   │                                    appended at end / highest position)
   └─ 4xx (validation) ──▶ stay on P2, show inline validation msg, keep entered values
```

### Notes / decisions
- **Position on create:** server appends the new card to the **end** of the target column
  (`position = current count`); no position chosen in the form. Matches Shape A's ordering rule.
- **Ticket number:** assigned by the server (sequence) — **not** an input; only visible after
  creation back on P1.
- **Client mirrors server validation:** required-title and story-point-set checks run client-side
  for snappy feedback, but the server is authoritative (Section 6).
- **No optimistic UI:** the card appears only after the post-create refetch succeeds (Shape A).

### Wiring summary
```
P1 ──[+ Add card]──▶ P2
P2 ──[Cancel]─────▶ P1
P2 ──[Create]─────▶ POST /api/cards ──(201)──▶ refetch ──▶ P1
                                     ──(4xx)──▶ P2 (inline error)
```

---

## Section 3 — Place: P3 · Edit Card

A form overlay for editing an existing card, opened via **[edit]** on a card in P1. Same field set
as Create, but **pre-filled** from the card and with the **ticket number shown read-only**. Column
is not changed here (moving is done by drag on the board — Section 5), keeping Edit purely about
field content.

### Entry wiring
```
P1 [edit on card C] ──▶ open P3 pre-filled from C's current values (title, description,
                        story_points, assignee); ticket_number shown read-only
```
> Data source: the card already lives in board state from the last `GET /api/cards`, so P3 opens
> instantly with no extra fetch. (A per-card `GET /api/cards/{id}` exists in the API for external
> clients but the UI doesn't need it here.)

### UI affordances

| Affordance | Type | Editable | Connection / behavior |
|-----------|------|:--:|-----------------------|
| **ticket # display** | label | ❌ | read-only (e.g. `KAN-12`); immutable |
| **(Title)** | text field | ✅ | non-empty; gates [Save] |
| **(Description)** | textarea | ✅ | optional plain text |
| **(Story points)** | select | ✅ | —(none) / 1 / 2 / 3 / 5 / 8 / 13 |
| **(Assignee)** | text field | ✅ | optional free text |
| **[Save]** | button (primary) | — | disabled until Title non-empty & something changed ──▶ `PATCH /api/cards/{id}` |
| **[Cancel]** | button | — | ──▶ discard changes, return to **P1** |
| **[Delete]** | button (danger) | — | ──▶ **P4 · Delete Confirmation** for this card |
| **inline validation msg** | label | — | shows validation errors from client/server |

### Submit wiring
```
[Save] ──▶ PATCH /api/cards/{id} { changed fields only }
   ├─ 200 OK ──▶ close overlay ──▶ refetch GET /api/cards ──▶ P1 (card shows updated values)
   └─ 4xx    ──▶ stay on P3, inline validation msg, keep edits
[Delete] ──▶ P4 (confirm) ── confirm ──▶ DELETE ──▶ refetch ──▶ P1  (see Section 4)
[Cancel] ──▶ P1 (no change)
```

### Notes / decisions
- **No column field here.** Column changes happen via drag on the board (Section 5); PATCH does not
  move cards. This keeps a clean split: **PATCH = field edits**, **/move = placement** (ADR 0006).
- **ticket_number and position are never editable** via this form.
- **PATCH sends changed fields only**; `updated_at` is bumped server-side.
- **No optimistic UI:** updated values appear after the post-save refetch (Shape A).
- **Delete reachable from two places:** the card's [delete] on P1 and [Delete] here on P3 — both
  route to the single P4 confirmation.

### Wiring summary
```
P1 ──[edit]──▶ P3
P3 ──[Cancel]─▶ P1
P3 ──[Save]───▶ PATCH /api/cards/{id} ──(200)──▶ refetch ──▶ P1
                                       ──(4xx)──▶ P3 (inline error)
P3 ──[Delete]─▶ P4 ──▶ (Section 4)
```

---

## Section 4 — Place: P4 · Delete Confirmation

A small confirm prompt guarding the irreversible hard-delete. Reachable from the card's **[delete]**
on P1 and from **[Delete]** on P3 (Edit). Both entries target the same card and the same prompt.

### Entry wiring
```
P1 [delete on card C] ──▶ open P4 for card C
P3 [Delete]           ──▶ open P4 for the card being edited
```

### UI affordances

| Affordance | Type | Connection / behavior |
|-----------|------|-----------------------|
| **confirm message** | label | e.g. "Delete `KAN-12` — “<title>”? This can't be undone." |
| **[Delete]** | button (danger) | ──▶ `DELETE /api/cards/{id}` |
| **[Cancel]** | button | ──▶ dismiss, return to the caller (P1, or P3 if opened from Edit) |

### Confirm wiring
```
[Delete] ──▶ DELETE /api/cards/{id}
   ├─ 204 No Content ──▶ close prompt (and P3 if open) ──▶ refetch GET /api/cards ──▶ P1
   │                    (card gone; its column keeps its order — remaining positions may have a gap)
   └─ 4xx/5xx        ──▶ show error (Section 7); card remains
[Cancel] ──▶ return to caller (P1 or P3), no change
```

### Notes / decisions
- **Hard delete**, no soft-delete/archive (ADR 0006). One confirmation is enough friction for MVP.
- **Position gaps are expected (Q-A2.1):** deleting a card leaves a hole in the column's `position`
  values (…0,1,3…). This is intentional — `position` is a *relative sort key*, so the visible order
  is unaffected; no renumber-on-delete is performed. A later move/reorder re-sequences naturally.
- **Ticket numbers are not reused** after delete (sequence is monotonic — ADR 0006).
- **Return target depends on entry:** cancel/confirm returns to P1 when opened from the board, or
  collapses P3→P1 when opened from Edit (the edited card no longer exists after a successful delete).
- **No optimistic UI:** the card disappears only after the post-delete refetch (Shape A).

### Wiring summary
```
P1 ──[delete]──▶ P4
P3 ──[Delete]──▶ P4
P4 ──[Cancel]──▶ caller (P1 / P3)
P4 ──[Delete]──▶ DELETE /api/cards/{id} ──(204)──▶ refetch ──▶ P1
                                         ──(err)──▶ error state (Section 7)
```

---

## Section 5 — Interaction: Drag move / reorder

Not a Place — an in-place interaction on **P1** that satisfies the Core drag requirements
(R2.1 between columns, R2.2 within a column). Implemented with `svelte-dnd-action` (HTML5-DnD
fallback per SHAPING). Two outcomes share one backend action: `POST /api/cards/{id}/move`.

### Affordances

| Affordance | Type | Connection / behavior |
|-----------|------|-----------------------|
| **‹Card› grab** | drag source | pointer-down on a card begins a drag |
| **‹Column› drop zone** ×3 | drop target | a column accepts a dragged card; highlights while hovered |
| **drop insertion marker** | visual | shows the index where the card will land between siblings |
| **dropped card** | — | on release ──▶ compute {column, position} ──▶ `POST /api/cards/{id}/move` |
| **[Esc] / drop outside** | cancel | aborts the drag; board returns to its pre-drag order (no API call) |

### Drop → position semantics
On release, the client determines the **target column** (drop zone) and the **target index** (slot
between siblings from the insertion marker), then calls move with that absolute index:

```
release ──▶ POST /api/cards/{id}/move { column: <target>, position: <target index> }
```
Server (`ordering.renumber_column`, one transaction):
1. Load target column's cards (excluding the moved card) ordered by `position`.
2. Clamp `position` to `[0, len]`; insert the moved card at that index.
3. Reassign `position = 0..n` across the target column (contiguous).
4. If the source column differs, re-sequence the **source** column too (closes the vacated gap).
5. Set `column` on the moved card; bump `updated_at`.

### Cases covered
- **Reorder within a column (R2.2):** source == target column; only that column re-sequenced.
- **Move to another column (R2.1):** source ≠ target; both columns re-sequenced; card's `column`
  changes. Story points / assignee / ticket # unchanged.
- **Drop into an empty column:** target index 0; card becomes the sole entry (position 0).
- **No-op drop** (same column, same slot): still safe — renumber yields the identical order; a
  redundant `/move` is acceptable, or the client may skip the call when index is unchanged.

### Wiring
```
P1 ‹drag card› ──▶ over ‹Column drop zone› ──▶ insertion marker at index
   ├─ release  ──▶ POST /api/cards/{id}/move {column, position}
   │                 ├─ 200 OK ──▶ refetch GET /api/cards ──▶ P1 (new order authoritative)
   │                 └─ err    ──▶ error state (Section 7) ──▶ refetch ──▶ P1 (revert to server order)
   └─ Esc / drop-outside ──▶ cancel, P1 unchanged (no API call)
```

### Notes / decisions
- **Absolute-index move** (Shape A) — client sends the numeric target index; server renumbers.
  (Shape B's neighbor-relative `before_id/after_id` was deferred; noted in SHAPING for future
  agent-friendliness.)
- **No optimistic UI** — after release we call `/move` then **refetch**; the server's order is
  authoritative. On error, the refetch restores the true order, so a failed drag can't leave the
  board visually wrong.
- **Last-write-wins** — concurrent moves by two users are not reconciled (ADR 0007); the later
  refetch simply reflects whatever the server last stored.
- **Board face vs move:** dragging never edits card fields; field edits stay in P3 (clean split).

### Wiring summary
```
‹drag›+‹drop zone›+insertion index ──▶ POST /api/cards/{id}/move ──(200)──▶ refetch ──▶ P1
                                                                  ──(err)──▶ §7 ──▶ refetch ──▶ P1
Esc / outside ──▶ P1 (unchanged)
```

---

## Section 6 — Non-UI affordances (API, sequence, seed, migrations)

The backend affordances every UI action wires to. All live under `/api`; the same surface is what
future MCP/CLI/agent clients will use (ADR 0005). OpenAPI docs at `/docs`.

### API endpoints (contract)

| Endpoint | Request body | Success | Errors | UI wiring |
|----------|-------------|---------|--------|-----------|
| **GET `/api/cards`** | — | `200` `[CardRead, …]` (all cards) | — | P1 load; every post-mutation refetch |
| **POST `/api/cards`** | `{ title!, description?, story_points?, assignee?, column?=todo }` | `201` `CardRead` | `422` validation | P2 [Create] |
| **GET `/api/cards/{id}`** | — | `200` `CardRead` | `404` | (external clients; UI uses cached state) |
| **PATCH `/api/cards/{id}`** | `{ title?, description?, story_points?, assignee? }` (changed only) | `200` `CardRead` | `404`, `422` | P3 [Save] |
| **DELETE `/api/cards/{id}`** | — | `204` | `404` | P4 [Delete] |
| **POST `/api/cards/{id}/move`** | `{ column, position? }` (position optional → append) | `200` `CardRead` | `404`, `422` | Drag drop (§5) |

`CardRead` = `{ id, ticket_number, title, description, column, position, story_points, assignee,
created_at, updated_at }`.

### Validation rules (server-authoritative)
| Rule | Applies to | Failure |
|------|-----------|---------|
| `title` non-empty | POST, PATCH | `422` |
| `column` ∈ {todo,in_progress,done} | POST, move | `422` |
| `story_points` ∈ {1,2,3,5,8,13} ∪ null | POST, PATCH | `422` |
| `position` optional; if given, integer ≥ 0 (clamped to column length); omitted → append | move | `422` if non-int |
| card exists | GET/PATCH/DELETE/move `{id}` | `404` |
| `ticket_number`, `position` not directly settable | POST, PATCH | ignored/rejected |

Error shape: FastAPI standard JSON — `{ "detail": … }` (422 carries field-level detail). This is
the "standard JSON error" of R4.4.

### Backend mechanisms (non-endpoint affordances)

| Mechanism | Trigger | Behavior | Wires to |
|-----------|---------|----------|----------|
| **Ticket sequence** `card_ticket_seq` | any card INSERT | column `server_default = 'KAN-' \|\| nextval(seq)` → atomic, immutable, no reuse | POST result's `ticket_number` |
| **`renumber_column()`** | move (§5), create (append) | transactional re-sequence of a column's `position` to 0..n | move / create ordering |
| **Seed data migration** | `alembic upgrade` on a fresh DB | insert ~4–6 demo cards across columns when `card` is empty | first P1 load shows a lively board (R0.4) |
| **Alembic migrations** | Fly `release_command` per deploy; CI before tests | `alembic upgrade head` brings schema (+seed) current | deploy pipeline (§ next), CI |
| **Static + SPA fallback** | any non-`/api`,non-`/docs` GET | serve built assets; return `index.html` for unknown paths | serves P1–P4 SPA (Q-A2.3) |

### Wiring summary (UI action → backend affordance)
```
P1 load / any refetch      ──▶ GET    /api/cards
P2 [Create]                ──▶ POST   /api/cards        ──▶ ticket seq + append(renumber)
P3 [Save]                  ──▶ PATCH  /api/cards/{id}
P4 [Delete]                ──▶ DELETE /api/cards/{id}
§5 drag drop               ──▶ POST   /api/cards/{id}/move ──▶ renumber_column (target [+source])
fresh DB (deploy/CI)       ──▶ alembic upgrade ──▶ schema + seed
any SPA route              ──▶ static/index.html fallback
```

### Notes / decisions
- **UI never bypasses the API** (R4.1): even cached reads originate from `GET /api/cards`.
- **`GET /api/cards/{id}`** exists for parity/external clients though the UI reads from cached
  board state (noted in §3).
- **All mutations are followed by a client refetch** (Shape A, no optimism) — the API responses
  could be used to patch state later as an optimization, but MVP refetches for simplicity.

---

## Section 7 — Cross-cutting states (P5) & full connection map

### P5 · Transient states (overlay P1)

| State | When | UI affordance | Wiring |
|-------|------|---------------|--------|
| **Loading** | a `GET /api/cards` is in flight (initial load; may include a Neon cold-start delay) | skeleton/spinner over the board | resolves ──▶ Board / Empty / Error |
| **Empty** | load succeeds, zero cards | "No cards yet — add one" prompt with a visible **[+ Add card]** | [+ Add card] ──▶ **P2** |
| **Error** | any API call fails (network/5xx) | non-blocking banner/toast: message + **[retry]** | [retry] ──▶ re-issue the failed call (or `GET /api/cards`) ──▶ back to P1 |
| **Saving/moving** | a mutation is in flight | affected control disabled / subtle busy hint | on resolve ──▶ refetch ──▶ P1 |

Notes:
- **Neon cold start (Q-A2.2):** first request after idle may take ~1s; surfaced as normal Loading,
  not an error. Documented so it isn't mistaken for a bug.
- **Empty is expected only after a seed-less/emptied DB** — a fresh deploy seeds demo cards (R0.4),
  so the very first load is normally non-empty.

### The one rule that ties it together
> **Every successful mutation (create / edit / delete / move) is followed by `GET /api/cards`, and
> the refetched server state is authoritative.** No optimistic UI (Shape A). On failure, the board
> is left/reverted to the last known server state via a refetch, so it can never display an order
> or value the server didn't confirm.

### Full connection map
```
                         ┌───────────────── P5 states overlay ─────────────────┐
                         │  Loading ─▶ Empty ─▶ Error[retry] ─▶ Saving/moving   │
                         └──────────────────────┬───────────────────────────────┘
                                                │ (all resolve to)
                                                ▼
   ┌───────────────────────────────────  P1 · BOARD VIEW  ───────────────────────────────────┐
   │  GET /api/cards (load + every refetch)                                                    │
   │                                                                                           │
   │   [+ Add card]        [edit]           [delete]              ‹drag card› + ‹drop zone›     │
   │       │                 │                 │                          │                     │
   │       ▼                 ▼                 ▼                          ▼                     │
   │   ┌────────┐        ┌────────┐        ┌──────────┐          POST /api/cards/{id}/move      │
   │   │P2 CREATE│       │P3 EDIT │        │P4 DELETE │          (renumber target[+source])     │
   │   └────────┘        └────────┘        └──────────┘                  │                     │
   │     │   │            │  │  │              │   │                      │                     │
   │  Cancel Create    Cancel Save [Delete] Cancel Delete                 │                     │
   │     │   │            │  │     │          │    │                      │                     │
   │     │   ▼            │  ▼     └────▶ P4 ─┘    ▼                       │                     │
   │     │  POST          │ PATCH             DELETE /api/cards/{id}       │                     │
   │     │  /api/cards    │ /api/cards/{id}        │                      │                     │
   │     │   │            │  │                     │                      │                     │
   │     └───┴────────────┴──┴──── all (2xx) ──────┴──────────────────────┘                     │
   │                              │                                                             │
   │                              ▼                                                             │
   │                    refetch GET /api/cards ──▶ (re-render P1)                                │
   └───────────────────────────────────────────────────────────────────────────────────────────┘

   Backend mechanisms feeding the above:
     INSERT ─▶ ticket seq (KAN-<n>)          move/create ─▶ renumber_column()
     deploy/CI ─▶ alembic upgrade (schema+seed)     any non-/api route ─▶ index.html (SPA fallback)
```

### Coverage check (breadboard → requirements)
| Requirement | Covered by |
|-------------|-----------|
| R0 Board view / seed / stable order | §1 (P1), §6 (seed), §7 (states) |
| R1 CRUD | §2 (create), §3 (edit), §4 (delete), §6 (endpoints) |
| R2 Move & reorder | §5 (drag), §6 (`/move` + renumber) |
| R3 Ticket numbering | §6 (sequence) |
| R4 REST API + OpenAPI + move + validation | §6 (contract, validation, `/docs`) |
| R5 Persistence (PG + Alembic) | §6 (migrations) |
| R6 Packaging & deploy (single artifact, SPA fallback) | §6 (static/SPA), deploy noted in SHAPING |
| R7 CI/CD | §6 (alembic on CI/deploy); pipeline detailed in SHAPING |
| R8 Testing | pytest + Playwright smoke (SHAPING §Detailed) |

**Every requirement maps to at least one breadboard affordance/mechanism. Breadboard complete.**

---

## Breadboard complete ✅

All 8 sections done. Places (P1–P5), UI affordances, the drag interaction, and non-UI/backend
affordances are defined with explicit wiring, and every requirement (R0–R8) is covered. Ready for
step E (final grill: extract/update ADRs, PRD, CONTEXT; check inconsistencies).
