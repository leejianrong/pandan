// Sprint-scoped board view (PAN-235) + the 14-day Done hide (PAN-236). Pure so the
// rules live in one place and are unit-checkable: the store feeds it the loaded
// cards + cycles and renders whatever comes back. Sprints are optional per board —
// a board with no cycles is never sprint-scoped, it just gets the Done hide.
import type { Card, Cycle } from "./api";

export type SprintSelection = "active" | "all" | number;

// A Done card with no sprint stays on the board this long after completion.
export const DONE_VISIBLE_DAYS = 14;
const DAY_MS = 24 * 60 * 60 * 1000;

export interface ScopeResult {
  visible: Card[];
  // Done cards hidden only by the 14-day rule (what "Show all" would reveal).
  hiddenDone: number;
}

// The open cycle whose [starts_on, ends_on) window contains `now`. Dates are
// optional on a cycle: a missing bound is treated as open-ended on that side.
export function activeCycle(cycles: Cycle[], now: number): Cycle | null {
  for (const c of cycles) {
    if (c.closed_at) continue;
    const start = c.starts_on ? Date.parse(c.starts_on) : -Infinity;
    const end = c.ends_on ? Date.parse(c.ends_on) : Infinity;
    if (start <= now && now < end) return c;
  }
  return null;
}

function doneTooOld(card: Card, now: number): boolean {
  if (card.column !== "done") return false;
  const when = Date.parse(card.done_at ?? card.updated_at);
  return Number.isFinite(when) && now - when > DONE_VISIBLE_DAYS * DAY_MS;
}

export function scopeCards(
  cards: Card[],
  opts: {
    cycles: Cycle[];
    selection: SprintSelection;
    showAllDone: boolean;
    now: number;
  },
): ScopeResult {
  const { cycles, selection, showAllDone, now } = opts;

  // An explicit past/future sprint shows exactly its cards — the whole point of
  // opening it is to see what was done, however long ago.
  if (typeof selection === "number") {
    return { visible: cards.filter((c) => c.cycle_id === selection), hiddenDone: 0 };
  }
  if (selection === "all") return { visible: cards, hiddenDone: 0 };

  const active = cycles.length > 0 ? activeCycle(cycles, now) : null;
  const scoped = cycles.length > 0;
  let hiddenDone = 0;
  const visible = cards.filter((c) => {
    if (scoped && c.cycle_id != null && c.cycle_id !== active?.id) return false;
    if (c.cycle_id == null && !showAllDone && doneTooOld(c, now)) {
      hiddenDone += 1;
      return false;
    }
    return true;
  });
  return { visible, hiddenDone };
}
