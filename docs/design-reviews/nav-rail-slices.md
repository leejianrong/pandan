# Nav rail — Slices

Vertical increments of the [nav rail shape](nav-rail-shaping.md), turning [nav-ia-audit.md](nav-ia-audit.md)'s
recommendation into a shipped `NavRail.svelte`. Each ends in **observable behaviour** and ships as its
own PR behind CI, matching every other slice in this repo.

Numbered locally (**NR-1..NR-4**) rather than joining the milestone V-series — EPIC-142 is a one-off
audit epic, not a numbered milestone (M8 is V51–V64, M9 is V65–V70; this is neither).

| Epic | Traces to |
|---|---|
| EPIC-142 | [nav-ia-audit.md](nav-ia-audit.md), the [proposal artifact](nav-rail-shaping.md) aligned on 2026-09-03 |

## Order of build

**Strict chain, NR-1 → NR-2 → NR-3 → NR-4** — each assumes the diff before it already landed (D7).
Recorded as real dependencies on the board (`pandan dep add`), not just here. Unlike M9's V65–V68
chain, every slice here is independently *safe to merge* (R5) — the chain is about which diff exists
to build on, not about earlier slices being unsafe alone.

| Slice | What | Card | Pts | Ends in (demo) |
|-------|------|------|:---:|----------------|
| **NR-1 · Ship the rail (7 items, no Board yet)** | New `NavRail.svelte` + `app-shell` layout wrapper; mounted always-visible alongside the existing hamburger+drawer | KAN-1148 | 5 | The rail is visible on every board screen; clicking Epics/Labels/Backlog/Activity/Dashboard/Members/Trash in it navigates and highlights via `aria-current` — the hamburger+drawer still work too |
| **NR-2 · Board joins the rail, the pill retires** | Add "Board" as the rail's first item; remove `.board-tab` and its wiring, atomically (D1) | KAN-1149 | 3 | The top bar has no Board pill; clicking the rail's Board item returns to the board; `epic-story.spec.ts`/`trash.spec.ts`'s existing `"Board"` button locator still resolves to exactly one element |
| **NR-3 · Tokens + Teams fold into the avatar menu** | Two new `avatarMenuItems` entries (`KeyRound`/`UsersRound`, already used in `SideNav.svelte`); their rows removed from the drawer | KAN-1150 | 2 | Opening the avatar menu shows Tokens and Teams; the drawer no longer lists either |
| **NR-4 · Remove the hamburger & `SideNav.svelte`** | Delete the component, the hamburger button, `drawerOpen` state, and drawer-only CSS | KAN-1151 | 3 | No hamburger icon anywhere in the top bar; the rail is the only way to reach any board-scoped view |

**13 points total.**

## What each slice does not do

Carried over from [SHAPING's Decisions/Out of scope](nav-rail-shaping.md) — none of these are quietly
reopened by a slice above:

- No slice adds Tokens or Teams to the rail (D2) — they go straight to the avatar menu in NR-3.
- No slice touches `CommandPalette.svelte` — its `VIEWS` list is already correct (KAN-1146).
- No slice changes the backend, schema, or `/api/v1` (R4).
- No slice adds a responsive/narrow-viewport rail collapse (D6).
- NR-1 does **not** include a "Board" rail item — that's specifically NR-2, atomically with the pill's
  removal (D1). Shipping it early would make `getByRole("button", { name: "Board", exact: true })`
  ambiguous in two existing specs and fail their CI run.

## Testing notes

- **NR-1** is the one slice that needs a genuinely new e2e spec (`nav-rail.spec.ts` or similar) — none
  of the four board-scoped destinations it makes rail-navigable have an existing "reached via nav"
  test, since the drawer itself was never asserted on (see SHAPING's *Existing test exposure*). Cover:
  each of the 7 items navigates to its view, and the active one carries `aria-current`.
- **NR-2** is a regression check first, a feature second: confirm `epic-story.spec.ts:50` and
  `trash.spec.ts:65` pass unmodified (they should — same accessible name, now sourced from the rail
  instead of the pill), then add coverage for the rail's Board item specifically if the NR-1 spec
  didn't already parametrize over all 8 items.
- **NR-3** should assert both halves in one spec: the avatar menu gains Tokens/Teams (extend
  `keyboard.spec.ts`'s existing avatar-menu tests or add alongside them), and the drawer's remaining
  item list no longer includes either — a spec that only checks the addition could miss a forgotten
  drawer row.
- **NR-4** has no drawer spec to delete (there isn't one), but should confirm nothing else references
  `SideNav` — `grep -rn "SideNav" frontend/src` should return only the deleted file's own history in
  git, not a lingering import.

Next: pick up NR-1 (already filed as KAN-1148 — retitle/resize it per the table above, then start).
