import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, epicItem, openFreshBoard, openView, uniqueTitle } from "./helpers";

// V32 (KAN-296): the Epics view surfaces a server-authoritative progress bar
// (% done over non-deleted children) + a health pill (on_track / at_risk /
// overdue) derived from target_date vs. remaining work. This drives the card's
// demo — an epic at 60% with a near deadline reads "At risk" — and captures
// light + dark screenshots of the bar/pill.
test.afterAll(() => cleanupE2eBoards());

test("epic progress bar + health pill render (60% → at risk)", async ({ page }, testInfo) => {
  const boardName = await openFreshBoard(page);

  // Find the fresh board's id (openFreshBoard just created + switched to it).
  const boards = await (await page.request.get("/api/v1/boards")).json();
  const board = boards.find((b: { name: string }) => b.name === boardName);
  expect(board, "fresh board should exist").toBeTruthy();

  // Seed via the API (server-authoritative): an epic with a near target_date, then
  // 5 child stories, 3 of them done → 60%, deadline soon → at_risk.
  const target = new Date(Date.now() + 2 * 24 * 3600 * 1000).toISOString();
  const epicName = uniqueTitle("epic");
  const epic = await (
    await page.request.post("/api/v1/epics", {
      data: { name: epicName, board_id: board.id, target_date: target },
    })
  ).json();

  for (let i = 0; i < 5; i++) {
    await page.request.post("/api/v1/cards", {
      data: {
        title: uniqueTitle("story"),
        board_id: board.id,
        epic_id: epic.id,
        column: i < 3 ? "done" : "todo",
      },
    });
  }

  // Open the Epics view (reload so the store fetches the seeded state).
  await page.reload();
  await openView(page, "Epics");

  const item = epicItem(page, epicName);
  await expect(item).toBeVisible();

  // Progress: server-authoritative 60%, 3/5 done.
  await expect(item.locator(".progress .pct")).toContainText("3 / 5 done · 60%");
  await expect(item.locator(".progress .bar i")).toHaveAttribute("style", /width:\s*60%/);

  // Health pill reads "At risk".
  const pill = item.locator(".health-pill");
  await expect(pill).toBeVisible();
  await expect(pill).toHaveText(/At risk/);
  await expect(pill).toHaveClass(/at_risk/);

  // --- Screenshots: light then dark (via the persisted theme + reload) --------
  await page.evaluate(() => localStorage.setItem("kanban.theme", "light"));
  await page.reload();
  await openView(page, "Epics");
  await expect(epicItem(page, epicName)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("epics-light.png"), fullPage: true });

  await page.evaluate(() => localStorage.setItem("kanban.theme", "dark"));
  await page.reload();
  await openView(page, "Epics");
  await expect(epicItem(page, epicName)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("epics-dark.png"), fullPage: true });
});
