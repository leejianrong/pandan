import { expect, test } from "@playwright/test";
import {
  cleanupE2eBoards,
  createEpic,
  createStoryUnder,
  openFreshBoard,
  openView,
  uniqueTitle,
} from "./helpers";

// .epic-grid used a bare `repeat(2, 1fr)` — a bare 1fr track's default
// minimum is its content's min-content width, so one card with an unbroken
// long token (a pasted URL, a no-space name) could force that track wider
// than its fair share: both overflowing the page AND making the Active and
// Completed sections (two independent grids, each sized only by its own
// content) render differently-sized cards. Fixed with minmax(0, 1fr) +
// overflow-wrap on .epic-name.

test.afterAll(async () => {
  await cleanupE2eBoards();
});

async function hasHorizontalOverflow(page: import("@playwright/test").Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
}

test("an unbroken long epic name wraps instead of overflowing the page, at any width", async ({
  page,
}) => {
  await openFreshBoard(page);

  const longName = `${uniqueTitle("epic")}withaverylongunbrokentokenxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`;
  await createEpic(page, longName);
  await createEpic(page, "short");

  for (const width of [1400, 900, 600, 400]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await hasHorizontalOverflow(page)).toBe(false);
  }
});

test("Active and Completed sections render equal-width cards", async ({ page }) => {
  await openFreshBoard(page);
  await page.setViewportSize({ width: 900, height: 900 });

  const longName = `${uniqueTitle("epic")}withaverylongunbrokentokenxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`;
  await createEpic(page, longName);

  const completedName = "completed-epic";
  const completedTicket = await createEpic(page, completedName);
  await createStoryUnder(page, "Done", uniqueTitle("story"), completedTicket, completedName);
  await openView(page, "Epics");

  const widths = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".epic-card")).map(
      (el) => el.getBoundingClientRect().width,
    ),
  );
  expect(widths.length).toBeGreaterThanOrEqual(2);
  for (const w of widths) {
    expect(w).toBeCloseTo(widths[0], 0);
  }
});
