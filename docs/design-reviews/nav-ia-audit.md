# Nav/IA audit — Board as a first-class tab, everything else hidden

- **Status:** Proposal — audit + recommendation only. No implementation in this doc. Aligned on
  2026-09-03 (a visual proposal artifact was built from this doc's recommendation and reviewed); sized
  into 4 real PRs in [nav-rail-shaping.md](nav-rail-shaping.md) / [nav-rail-slices.md](nav-rail-slices.md).
- **Date:** 2026-09-03
- **Context source:** [KAN-1089](https://github.com/leejianrong/pandan/issues/278) / PAN-192, epic
  EPIC-142 "Frontend UX: navigation & IA audit", filed against
  [issue #278](https://github.com/leejianrong/pandan/issues/278). Grounded against the running app
  (`main` @ this branch's base) via Playwright — screenshots and source reads, not just the card
  description, since the card itself warned its own "current structure" section could have drifted.

## Summary

Ten destinations exist beyond the board. One (**Board**) is a pill in the top bar; the other nine
live behind a hamburger icon in a slide-out drawer titled "VIEWS," with no visible signal from the
top bar that they exist. That much matches the card's framing. But the card's own guess at *why* —
that the hidden nine split cleanly into "board-scoped" (Epics, Labels, Backlog, Activity) vs.
"account-scoped" (Tokens, Members, Teams, Trash, Dashboard, Inbox) — turns out to be **wrong when
checked against the live code**: Members, Trash and Dashboard are board-scoped too. Only three
destinations (Tokens, Teams, Inbox) are genuinely account-scoped. That changes the shape of the fix:
this isn't "split the drawer into two menus of similar size," it's "promote a persistent board-scoped
rail for the eight destinations that are actually about the current board, and leave a small account
menu — which mostly already exists as the avatar dropdown — for the three that aren't."

**Recommendation in one line:** replace the hamburger+drawer with a persistent left rail listing
Board + the seven other board-scoped views (Epics, Labels, Backlog, Activity, Dashboard, Members,
Trash), fold Tokens/Teams into the existing avatar account menu, and leave Inbox exactly where it
already is (the top-bar bell) since it's the one destination already surfaced correctly.

## 1. Board-scoped vs. account-scoped — the actual split

Verified by reading each component's own scoping comment and by screenshotting each view (the
account/board scope was often stated in-file, e.g. Members.svelte: *"Members are board-scoped:
(re)load whenever the active board changes"*; Trash.svelte: *"Board-scoped… Mirrors Activity /
Members"*). Rendered proof: the Members view literally reads "People with access to **Default
Board**," Trash reads "Deleted cards and epics on **Default Board**," and Dashboard reads "Mission
control for **Default Board**" — none of those are account-level despite the card's initial guess.

| Destination | Scope | Evidence |
|---|---|---|
| Board | board | the primary view |
| Epics | board | `epicStore` keyed to `boardStore.activeBoardId` |
| Labels | board | `Labels.svelte`, board's label palette (V61/V62) |
| Backlog | board | `backlogStore`, `cycle_id IS NULL` on the active board |
| Activity | board | `$effect` on `boardStore.activeBoardId` reloads |
| **Dashboard** | **board** (card guessed account) | heading reads "Mission control for **Default Board**" |
| **Members** | **board** (card guessed account) | heading reads "People with access to **Default Board**" — this is `BoardMember`, not org membership |
| **Trash** | **board** (card guessed account) | heading reads "Deleted cards and epics on **Default Board**" |
| Tokens | **account** | agent PATs, user-scoped, loaded lazily once opened |
| Teams | **account** | `teamStore`, code comment: *"Teams are user-scoped (not board-scoped)… loaded once at login"* |
| Inbox | **account** | notification poll runs "independent of the active board" |

Eight of the ten hidden-or-tabbed destinations are board-scoped; only three are account-scoped. The
drawer's flat list — and the card's own initial split — treats this as roughly 50/50. It isn't.

## 2. Proposed nav structure

**A persistent left rail for the eight board-scoped destinations** (Board, Epics, Labels, Backlog,
Activity, Dashboard, Members, Trash), always visible once a board is open, with the current one
highlighted (`aria-current`, which `SideNav.svelte`'s drawer items already set — that part carries
over unchanged). Board is simply the first rail item, not a chrome-level pill anymore, which is what
actually fixes the card's headline complaint: Board and Epics become peers in the UI the way they
already are peers in the domain model.

**The account-scoped trio folds into the existing avatar dropdown**, which today only holds
Settings / Keyboard shortcuts / Log out. Add Tokens and Teams there (two more `MenuItem`s in
`App.svelte`'s `avatarMenuItems` — no new component). **Inbox stays exactly where it is** — the
top-bar bell is already the right pattern for a cross-board, frequently-checked, notification-style
destination, and it's the one existing entry point that already gets this right. (Its second, redundant
entry point inside the current drawer should simply not be recreated in the rail — see §3.)

**Why a rail over a copy of one competitor:**

| Product | Pattern | Why it doesn't map 1:1 onto pandan |
|---|---|---|
| **Linear** | persistent left sidebar (Issues/Projects/Cycles/Views) with workspace switcher on top; the board is *one view* of Issues, not a separate destination | pandan's board isn't a view over a bigger "Issues" surface — it's the primary object, and its siblings (Epics, Labels…) are genuinely separate entities, not saved queries. Copying Linear's collapse-board-into-a-view model would be a bigger, riskier change than this audit's scope |
| **GitHub Projects** | view tabs (Table/Board/Roadmap) live inline atop project content; project-level settings sit behind a "…" menu | closest in spirit to pandan's *existing* board/table toggle (`ViewSwitcher.svelte`) — but GitHub Projects has no sibling entities like Epics/Backlog needing their own destinations, so its tab-only model has nothing to say about where those go |
| **Jira** | a persistent left rail (Backlog, Board, Reports…) per project, plus a separate top-level nav for cross-project concerns | closest match to pandan's actual shape once the real scope split (§1) is applied — Jira's rail is per-project (≈ per-board) and its top nav is cross-project (≈ account-scoped). This is the model this proposal borrows from, but pandan has fewer per-board destinations than Jira, so the rail can be flat with no need for Jira's per-section grouping |
| **Trello** | deliberately board-only, no sibling views | counter-example, confirms pandan shouldn't collapse everything back into the board — pandan already has more entity types than Trello has views of one |

The rail is closest to Jira's shape because pandan's board/account split (§1) is structurally closest
to Jira's project/cross-project split — but flatter, since eight items is short enough not to need
Jira's grouping into sections.

**What doesn't change:** the board/table view-mode toggle and saved-view picker in `ViewSwitcher.svelte`
(a *different* "view" — see §3), the ⌘K command palette (still useful as an accelerator once the rail
exists, the same way GitHub/Linear keep a palette alongside persistent nav), and the "no client-side
router, conditional render on a `view` string" implementation pattern noted throughout `App.svelte` —
this proposal is about which destinations are reachable and how, not about introducing routing.

## 3. Other navigation/workflow creases found along the way

This audit surfaced four additional creases beyond the headline gripe, all confirmed against source:

1. **"View" means three different things in the same app.** The hamburger drawer is titled "VIEWS"
   (`SideNav.svelte`: `aria-label="Views"`, `drawer-title`) and names navigation *destinations*
   (Epics, Labels, …). Separately, `ViewSwitcher.svelte` implements **saved views** — a named,
   persisted card *query* (`SavedView` in `api.ts`, "Save view" button, a bookmark icon) that's a
   board-toolbar feature, unrelated to navigation. And a third meaning, **view mode**, toggles the
   board between kanban columns and a sortable table (`setViewMode`, the `Columns3`/`Table` icons in
   the same toolbar). A user asking "which view am I in?" could reasonably mean any of the three, and
   the UI's own vocabulary doesn't disambiguate. Renaming the drawer (this proposal replaces it with a
   rail anyway) removes one of the three collisions for free; the saved-view/view-mode overlap is
   independent and worth a naming pass on its own.

2. **The ⌘K command palette has drifted out of sync with the drawer.** `CommandPalette.svelte`'s
   navigable `VIEWS` list is `board, dashboard, epics, activity, tokens, members, teams, trash,
   settings` — it is **missing Labels and Backlog**, both added after the palette's `VIEWS` list was
   last touched (Backlog: M8 V56/KAN-977; Labels: M8 V61/KAN-982). Today there is no way to jump to
   either view via ⌘K; a user has to know to use the hamburger instead. This is a plain omission, not
   a design decision — worth a one-line fix independent of the rail work, and worth pinning with a
   test (the repo already has a precedent for this shape of guard, e.g. `test_ref_grammar.py` proving
   two independent copies of a grammar agree) so a tenth destination doesn't repeat the drift.

3. **No breadcrumb or persistent "where am I" signal outside the Board pill.** `SideNav.svelte`'s own
   header comment says as much: *"No breadcrumb / persistent indicator of which non-Board view is
   currently open."* Confirmed visually — on the Trash/Tokens/Members/etc. screenshots, the top bar's
   "Board" pill is simply unhighlighted; nothing in the chrome names the current view except the page's
   own `<h1>` in the body. A rail (§2) fixes this structurally, since a rail item can carry
   `aria-current` the way `SideNav.svelte`'s drawer items already do — the affordance exists today, it
   just isn't visible until the drawer is open.

4. **Inbox has two entry points that do the same thing, asymmetrically.** The top-bar bell
   (`Inbox.svelte`) opens the notification popover directly. The drawer *also* has an "Inbox" row
   (`SideNav.svelte`), but it doesn't navigate anywhere — its `onclick` calls `onOpenInbox()`, which
   opens the very same bell popover and closes the drawer as a side effect. It's a legitimate
   affordance for a hamburger-only layout (put every destination in one drawer, even ones that aren't
   really "views"), but it stops making sense once Inbox already has its own top-bar icon — carrying
   it into a rail (§2) would be a third redundant copy of the same entry point. The rail proposal
   drops it rather than relocating it, since the bell already covers the need.

## 4. What implementing this would touch

Scoped as a rough shape for slicing, not a spec — sizing is for the shaping pass that follows this
audit.

**Components:**
- `frontend/src/App.svelte` — owns `view` state, the top bar markup, and `avatarMenuItems`; the
  hamburger button + `<SideNav>` mount are removed, a rail component takes its place, and
  Tokens/Teams entries move into `avatarMenuItems`.
- `frontend/src/lib/components/SideNav.svelte` — retired as a drawer; its item list, icons, and
  `aria-current` logic are the starting point for the new rail component (new file, e.g. `NavRail.svelte`),
  not a from-scratch design.
- `frontend/src/lib/components/CommandPalette.svelte` — `VIEWS` list gets Labels + Backlog added
  regardless of the rail (crease 2, independently shippable) and stays as an accelerator once the
  rail exists.
- Top-bar layout CSS in `App.svelte`'s `<style>` block (the `.topbar`/`.board-tab` rules) shrinks —
  Board stops being a bespoke pill once it's a rail item — and the app's overall grid gains a fixed
  left-rail column, which likely touches `frontend/src/app.css`'s layout-level rules too.
- No backend, schema, or API change — this is presentation-only; every destination already resolves
  data the same way, just through different chrome.

**Rough slicing (four to five, each independently shippable and testable via the existing Playwright
e2e suite):**
1. Ship the rail alongside the drawer (feature-flag or just add it; low risk, additive).
2. Move Board out of the top-bar pill and into the rail as its first item; retire the pill.
3. Fold Tokens + Teams into the avatar menu; retire their drawer rows.
4. Remove `SideNav.svelte`/the hamburger once the rail covers everything (drawer's `aria-current`
   pattern already ports over, so this is deletion, not new logic).
5. (Independent, can land anytime, including before the rail) Fix the ⌘K `VIEWS` list (crease 2).

Sequencing note carried over from the card: land this before any nav-chrome restyling pass, so
tokens/colors aren't applied twice to a drawer about to be deleted.

## Alternatives considered

- **Keep the drawer, just reorganize its contents into two labeled sections** (board-scoped vs.
  account-scoped) rather than building a rail. Cheaper, but doesn't fix the headline complaint — Board
  would still be the only destination promoted to the top bar, and the drawer would still require a
  click-to-discover step for content that's core to using the board day-to-day (Epics, Backlog,
  Activity). Rejected because the actual scope split (§1) shows most of what's hidden is exactly the
  content a rail is for.
- **Move everything into top-bar tabs (GitHub Projects-style).** Doesn't scale to eight board-scoped
  destinations without wrapping or a "more" overflow, which reintroduces a hidden-menu problem one
  level down.
- **Copy Linear's model of collapsing Board into "one view of Issues."** Would be a genuine, larger
  redesign of the domain-to-UI mapping (board/epic/backlog stop being separate top-level destinations
  and become filtered views of one list), not a nav-chrome change. Out of scope for this audit; noted
  as a bigger idea worth its own shaping pass if the team wants to go further than "make existing
  peers look like peers."

## Method

Backend (`uv run uvicorn`) and frontend (`npm run dev`) run locally against an ephemeral worktree
Postgres; logged in via the `E2E_AUTH_BYPASS` test-login route. Driven with Playwright
(`npx playwright`, per this repo's standing permission to drive it freely) to screenshot the top bar,
the open drawer, and all nine drawer destinations plus the avatar menu and command palette, and to
read each view's own on-screen copy (e.g. "People with access to **Default Board**") as ground truth
for scope rather than inferring it from naming. Source read: `App.svelte`, `SideNav.svelte`,
`ViewSwitcher.svelte`, `CommandPalette.svelte`, and the board/account-scoping comments already present
in `Dashboard.svelte`, `Members.svelte`, `Trash.svelte`, `Activity.svelte`, `Backlog.svelte`,
`Teams.svelte`, `Tokens.svelte`, and `Inbox.svelte`.
