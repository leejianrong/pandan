import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, createCard, openFreshBoard, openView, uniqueTitle } from "./helpers";

// KAN-18 activity feed: the panel renders recent, newest-first activity for the
// active board, and honours the read API. Also captures light + dark screenshots
// as per-test output artifacts (testInfo.outputPath — CI-safe on any runner).

test.afterAll(async () => {
  await cleanupE2eBoards();
});

async function setTheme(page: import("@playwright/test").Page, theme: "light" | "dark") {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("kanban.theme", t);
    } catch {
      /* ignore */
    }
  }, theme);
}

test("activity panel renders recorded activity, newest first", async ({ page }) => {
  await openFreshBoard(page);

  // Generate a few activity rows: two creates + one move.
  const a = uniqueTitle("activity-a");
  const b = uniqueTitle("activity-b");
  await createCard(page, "Todo", a);
  await createCard(page, "Todo", b);

  // Open the Activity view via the top-bar nav.
  await openView(page, "Activity");

  await expect(page.getByRole("heading", { name: "Activity", exact: true })).toBeVisible();
  const feed = page.locator(".feed");
  await expect(feed).toBeVisible();

  // At least the two card-created rows (plus the board-created row) show up, and
  // the newest (the second card created) leads the list.
  const rows = feed.locator(".feed-row");
  await expect(rows.first()).toContainText(b);
  expect(await rows.count()).toBeGreaterThanOrEqual(3);
});

test("activity panel screenshots — light + dark", async ({ page }, testInfo) => {
  await setTheme(page, "light");
  await openFreshBoard(page);
  await createCard(page, "Todo", uniqueTitle("shot"));
  await openView(page, "Activity");
  await expect(page.locator(".feed")).toBeVisible();
  // testInfo.outputPath resolves under the per-test output dir, which exists on
  // any runner (local or CI) — no hardcoded absolute path.
  await page.screenshot({ path: testInfo.outputPath("activity-light.png"), fullPage: true });

  // Flip to dark via the top-bar theme toggle and re-shoot the same panel.
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator(':root[data-theme="dark"]')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("activity-dark.png"), fullPage: true });
});
