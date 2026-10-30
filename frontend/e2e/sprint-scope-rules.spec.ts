import { expect, test } from "@playwright/test";
import { activeCycle, scopeCards } from "../src/lib/sprintScope";
import type { Card, Cycle } from "../src/lib/api";

// The pure rules behind the sprint-scoped board (PAN-235) and the 14-day Done hide
// (PAN-236). No browser: backdating a done_at isn't possible through the API, so the
// age cut-off is exercised here directly.

const DAY = 24 * 3600 * 1000;
const NOW = Date.parse("2026-11-01T12:00:00Z");
const iso = (offsetDays: number) => new Date(NOW + offsetDays * DAY).toISOString();

function cycle(id: number, startDays: number, endDays: number, closed = false): Cycle {
  return {
    id,
    board_id: 1,
    name: `Sprint ${id}`,
    starts_on: iso(startDays),
    ends_on: iso(endDays),
    created_at: iso(-30),
    planning_interval_id: null,
    closed_at: closed ? iso(endDays) : null,
  };
}

function card(
  id: number,
  column: Card["column"],
  cycleId: number | null,
  doneDaysAgo: number | null = null,
): Card {
  return {
    id,
    column,
    cycle_id: cycleId,
    done_at: doneDaysAgo == null ? null : iso(-doneDaysAgo),
    updated_at: iso(-1),
  } as Card;
}

const ids = (cards: Card[]) => cards.map((c) => c.id).sort((a, b) => a - b);

test("activeCycle picks the open cycle containing now, never a closed one", () => {
  const cycles = [cycle(1, -20, -6, true), cycle(2, -6, 8), cycle(3, 8, 22)];
  expect(activeCycle(cycles, NOW)?.id).toBe(2);
  expect(activeCycle([cycle(1, -6, 8, true)], NOW)).toBeNull();
});

test("no sprints: nothing is sprint-scoped, only old done cards are hidden", () => {
  const cards = [card(1, "todo", null), card(2, "done", null, 3), card(3, "done", null, 20)];
  const r = scopeCards(cards, { cycles: [], selection: "active", showAllDone: false, now: NOW });
  expect(ids(r.visible)).toEqual([1, 2]);
  expect(r.hiddenDone).toBe(1);
});

test("done exactly at the 14-day boundary stays; just past it is hidden", () => {
  const cards = [card(1, "done", null, 14), card(2, "done", null, 14.01)];
  const r = scopeCards(cards, { cycles: [], selection: "active", showAllDone: false, now: NOW });
  expect(ids(r.visible)).toEqual([1]);
});

test("Show all reveals old unsprinted done cards", () => {
  const cards = [card(1, "done", null, 90)];
  const r = scopeCards(cards, { cycles: [], selection: "active", showAllDone: true, now: NOW });
  expect(ids(r.visible)).toEqual([1]);
  expect(r.hiddenDone).toBe(0);
});

test("active sprint: its cards plus unscheduled open work; other sprints are hidden", () => {
  const cycles = [cycle(1, -20, -6, true), cycle(2, -6, 8), cycle(3, 8, 22)];
  const cards = [
    card(1, "done", 1, 10), // finished in a closed sprint — off the board
    card(2, "in_progress", 2), // current sprint
    card(3, "done", 2, 1), // current sprint, done
    card(4, "todo", 3), // future sprint
    card(5, "todo", null), // unscheduled open work stays visible
    card(6, "done", null, 30), // old unsprinted done — hidden by the 14-day rule
  ];
  const r = scopeCards(cards, { cycles, selection: "active", showAllDone: false, now: NOW });
  expect(ids(r.visible)).toEqual([2, 3, 5]);
  expect(r.hiddenDone).toBe(1);
});

test("a done card in a sprint is never age-hidden", () => {
  const cycles = [cycle(2, -6, 8)];
  const r = scopeCards([card(1, "done", 2, 60)], {
    cycles,
    selection: "active",
    showAllDone: false,
    now: NOW,
  });
  expect(ids(r.visible)).toEqual([1]);
});

test("choosing a past sprint shows exactly its cards, however old", () => {
  const cycles = [cycle(1, -20, -6, true), cycle(2, -6, 8)];
  const cards = [card(1, "done", 1, 40), card(2, "todo", 2), card(3, "todo", null)];
  const r = scopeCards(cards, { cycles, selection: 1, showAllDone: false, now: NOW });
  expect(ids(r.visible)).toEqual([1]);
});

test("All cards shows everything", () => {
  const cycles = [cycle(1, -20, -6, true), cycle(2, -6, 8)];
  const cards = [card(1, "done", 1, 40), card(2, "todo", 2), card(3, "done", null, 90)];
  const r = scopeCards(cards, { cycles, selection: "all", showAllDone: false, now: NOW });
  expect(ids(r.visible)).toEqual([1, 2, 3]);
});
