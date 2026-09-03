# Nav rail — Shaping

- **Status:** Shaping — sizing an already-agreed direction into real PRs. No implementation in this doc.
- **Date:** 2026-09-03
- **Traces to:** [nav-ia-audit.md](nav-ia-audit.md) (the audit + recommendation), EPIC-142, KAN-1148.

Unlike a milestone SHAPING.md, the design question here was already answered — the audit's
recommendation was checked against a visual proposal artifact and the maintainer aligned on direction.
**This document does not re-argue that direction; it turns it into slices** the way M9's SHAPING.md
turned an already-accepted ADR into V65–V70. Where the audit spent its length on *why* (the board/
account scope split), this spends its length on *order and boundaries* — specifically, two things the
audit's rough sketch (§4) left underspecified and that would have broken CI if shipped as written.

## Requirements (R)

- **R1.** Every board-scoped destination (Board, Dashboard, Epics, Labels, Backlog, Activity, Members,
  Trash) is reachable with a single click from a persistent, always-visible left rail, with the active
  one marked via `aria-current` — no hamburger click required.
- **R2.** Tokens and Teams move into the existing avatar dropdown (`avatarMenuItems` in `App.svelte`),
  matching the audit's account-scoped classification (§1). No new component for this.
- **R3.** Inbox keeps exactly one entry point — the top-bar bell (`Inbox.svelte`). The drawer's
  redundant "Inbox" row (audit §3 crease 4) is not carried into the rail.
- **R4.** No backend, schema, or API change in any slice — presentation-only, matching the audit's own
  scoping (§4).
- **R5.** Each slice ships as an independently deployable, e2e-tested PR behind CI — the same bar every
  other slice in this repo clears. No slice's safety-to-merge depends on a later slice already landing.
- **R6.** After the last slice, every destination has exactly one entry point: the rail for the 8
  board-scoped views, the avatar menu for Tokens/Teams, the bell for Inbox. Zero duplicates — this is
  what actually closes audit creases 1 and 4, not just crease 2 (already fixed, KAN-1146).

## Decisions log

- **D1 — the rail ships without "Board" until the pill is retired, in the same PR.** The audit's own
  wording bundles these as one step ("Move Board out of the top-bar pill *and* into the rail as its
  first item; retire the pill") — checking why matters: `frontend/e2e/epic-story.spec.ts:50` and
  `trash.spec.ts:65` both do `getByRole("button", { name: "Board", exact: true })`. If an earlier slice
  shipped a rail that *already* includes a "Board" item while the top-bar pill (`.board-tab`, also
  text "Board") still exists, that locator becomes ambiguous — two buttons with the identical
  accessible name — and Playwright's strict mode fails both specs on the slice that was supposed to be
  the safe, additive one. So the slice that ships the rail (NR-1) deliberately ships **without** a
  Board item (7 items: Dashboard, Epics, Labels, Backlog, Activity, Members, Trash), and the slice that
  adds Board to the rail (NR-2) removes the pill in the same PR — the two changes are atomic precisely
  so there is never a moment with two "Board" buttons on screen.

  **Correction, found while building NR-1:** this reasoning was scoped too narrowly at shaping time —
  it only checked "Board" because that's the audit's own wording, but the *same* ambiguity applies to
  **all 7 of NR-1's items**, since the rail deliberately duplicates the drawer's labels for the whole
  NR-1–NR-3 coexistence window (D3). `frontend/e2e/helpers.ts`'s `openView(page, name)` — used by
  `activity`/`backlog`/`dashboard`/`epic-story`/`epic-rollup`/`keyboard`/`labels`/`trash`/`ui-polish`
  .spec.ts — did an unscoped `page.getByRole("button", { name, exact: true })`, which broke the moment
  the rail existed alongside the drawer (3 specs failed on the first NR-1 test run). Fixed by scoping
  that helper to the drawer specifically (`getByRole("complementary")`, the `<aside>`'s implicit role,
  vs. the rail's `<nav>` = role `navigation`) rather than by changing NR-1's item set — the helper's own
  intent was always "use the drawer," so scoping it preserves that intent instead of working around it.
  No slice boundary changed; this was a test-infra gap in the coexistence window, not a re-shape.
- **D2 — Tokens/Teams are never added to the rail, at any point.** They're account-scoped (audit §1),
  so the rail's final item set is fixed at 7→8 (D1) from the start; NR-3 only adds them to the avatar
  menu and removes them from the old drawer. No slice does throwaway work adding-then-removing a rail
  item.

  **Correction, found while building NR-3:** removing Tokens/Teams from the drawer breaks any e2e
  helper that reached them *through* the drawer, which two did — `frontend/e2e/tokens.spec.ts` (via
  `openView(page, "Tokens")`) and `helpers.ts`'s own `createTeam()` (via `openView(page, "Teams")`,
  used by both `teams.spec.ts` tests). Same shape of gap as D1's correction: a slice's *removal* half
  breaks a test path shaping didn't enumerate, because "existing test exposure" was checked for the
  drawer's *deletion* (NR-4) but not for individual items dropping out of it earlier. Fixed by adding
  `openAccountMenuView(page, name)` (opens the avatar menu, clicks the named `menuitem`) and switching
  both call sites to it — the fix is additive (a new helper), not a rewrite of `openView`, since the
  drawer's remaining items still need exactly what `openView` already does.
- **D3 — the rail and the old hamburger+drawer run in parallel for slices NR-1 through NR-3.** Two
  paths to (most of) the same destinations for a few PRs is accepted as a deliberate, harmless
  intermediate state — the same tradeoff the audit itself already made in choosing 4-5 small slices
  over one big PR. NR-4 is what removes the second path.
- **D4 — a new `app-shell` wrapper is part of NR-1, not a separate slice.** Today `<header class="topbar">`
  and `<main>` are direct top-level siblings in `App.svelte` (`SideNav` is a fixed-position overlay, not
  a layout participant) — there is no flex/grid shell for a rail to sit inside as a layout column. The
  audit flagged this as something the rail "likely touches" (§4); confirmed by reading `App.svelte` and
  `app.css`'s `main { padding: 1.5rem; }` rule. NR-1 has to introduce the wrapper to exist at all, so
  it's sized into that slice rather than treated as a later surprise.
- **D5 — `NavRail.svelte` is a new component, not a repurposed `SideNav.svelte`.** It borrows
  `SideNav`'s existing item list, icons, and `aria-current` pattern verbatim (per audit §4 — "the
  starting point for the new rail component, not a from-scratch design"), but is a separate file with a
  smaller prop surface (`{ view, onNavigate }` — no `open`/`onClose`/scrim/`onOpenInbox`, since it's
  always visible and never shows Inbox). `SideNav.svelte` itself is deleted whole in NR-4 rather than
  incrementally hollowed out, so there's no half-migrated component to review at any point.
- **D6 — no responsive/narrow-viewport redesign.** The app has no dedicated mobile layout today (the
  only `@media (max-width: 720px)` rule in `app.css` reflows a modal grid, not the top-level chrome) —
  the hamburger+drawer was a desktop declutter mechanism (EPIC-49), not a mobile pattern. A fixed-width
  rail column is therefore no more or less mobile-friendly than what exists today. Explicitly out of
  scope, so it isn't quietly reopened mid-slice; a responsive nav is a separate future concern if one
  ever gets filed.
- **D7 — dependency chain is recorded on the board, not just here** (mirrors M9 SHAPING's own framing):
  NR-2 is `blocked_by` NR-1, NR-3 by NR-2, NR-4 by NR-3. Strict chain, not parallel — each slice's diff
  assumes the previous one already landed (e.g. NR-2 assumes `NavRail.svelte` already exists to add
  "Board" into).

## Existing test exposure (why NR-4 is cheap)

Grepped `frontend/e2e/*.spec.ts` for anything that asserts on the drawer's *contents* or navigation
behavior: there isn't one. Only three specs reference the hamburger or avatar menu at all
(`command-palette.spec.ts`, `login.spec.ts`, `keyboard.spec.ts`), and none of them assert what's
*inside* the drawer — they open the avatar menu for unrelated reasons (keyboard-shortcuts help,
logout). So deleting `SideNav.svelte` in NR-4 has no existing spec to migrate or delete alongside it —
the risk in NR-4 is regressing rail coverage, not breaking drawer tests, since there are none.

## Out of scope

- A responsive/collapsible rail for narrow viewports (D6).
- Any further ⌘K `CommandPalette.svelte` change — its `VIEWS` list keys off the same `view` id strings
  regardless of which chrome renders them, and is already correct (KAN-1146). Not reopened here.
- Backend/schema/API changes of any kind (R4).
- Renaming or restyling anything beyond the four slices below — a broader visual pass (if wanted) is
  separate work that should land *after* this, per the audit's own sequencing note (§4): "land this
  before any nav-chrome restyling pass, so tokens/colors aren't applied twice to a drawer about to be
  deleted."

Next: [Slices](nav-rail-slices.md).
