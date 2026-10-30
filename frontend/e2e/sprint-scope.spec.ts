import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  login,
  pickSelect,
  uniqueTitle,
} from "./helpers";

// Sprint-scoped board view (PAN-235): on a board with sprints, the board defaults
// to the current sprint; cards in another sprint leave it but stay one selector
// away. Sprints are optional — a board with none is untouched (every other spec).

test.afterAll(() => cleanupE2eBoards());

test("board defaults to the current sprint and a selector reaches the others", async ({
  page,
}) => {
  await login(page);
  const board = await (
    await page.request.post("/api/v1/boards", { data: { name: uniqueTitle("sprint-board") } })
  ).json();
  const day = 24 * 3600 * 1000;
  const mk = async (name: string, startDays: number, endDays: number) =>
    (
      await page.request.post(`/api/v1/boards/${board.id}/cycles`, {
        data: {
          name,
          starts_on: new Date(Date.now() + startDays * day).toISOString(),
          ends_on: new Date(Date.now() + endDays * day).toISOString(),
        },
      })
    ).json();
  const current = await mk(uniqueTitle("current"), -1, 13);
  const next = await mk(uniqueTitle("next"), 13, 27);

  const inCurrent = uniqueTitle("in-current");
  const inNext = uniqueTitle("in-next");
  const loose = uniqueTitle("unscheduled");
  for (const [title, cycle_id] of [
    [inCurrent, current.id],
    [inNext, next.id],
    [loose, null],
  ] as const) {
    await page.request.post("/api/v1/cards", { data: { title, board_id: board.id, cycle_id } });
  }

  await page.addInitScript((id) => {
    try {
      localStorage.setItem("kanban.activeBoardId", String(id));
    } catch {
      /* ignore */
    }
  }, board.id);
  await page.goto("/");

  await expect(cardInColumn(page, "Todo", inCurrent)).toBeVisible();
  await expect(cardInColumn(page, "Todo", loose)).toBeVisible();
  await expect(cardInColumn(page, "Todo", inNext)).toHaveCount(0);

  await pickSelect(page, page, "Sprint", next.name);
  await expect(cardInColumn(page, "Todo", inNext)).toBeVisible();
  await expect(cardInColumn(page, "Todo", inCurrent)).toHaveCount(0);

  await pickSelect(page, page, "Sprint", "All cards");
  await expect(cardInColumn(page, "Todo", inNext)).toBeVisible();
  await expect(cardInColumn(page, "Todo", inCurrent)).toBeVisible();
});
