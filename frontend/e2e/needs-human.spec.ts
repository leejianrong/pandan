import { copyFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  column,
  docsImagePath,
  openFreshBoard,
  uniqueTitle,
} from "./helpers";

// M5 V13 (KAN-246): the needs-human handoff flag. An agent flags a card as needing
// a human (the flag + note are the agent/CLI/MCP surface in this slice — full
// "needs attention" surfacing is V16), and the card face renders a needs-human
// badge. We flag via the API (mirroring how card-fields creates labels), then
// assert the badge renders and survives a reload (server-authoritative).
test.afterAll(() => cleanupE2eBoards());

test("a card flagged needs-human renders the needs-human badge", async ({ page }, testInfo) => {
  await openFreshBoard(page);

  const boardId = await page.evaluate(() => localStorage.getItem("kanban.activeBoardId"));
  expect(boardId).toBeTruthy();

  // Create the card + raise the flag via the API (the V13 agent surface).
  const title = uniqueTitle("handoff");
  const created = await page.request.post("/api/v1/cards", {
    data: { title, board_id: Number(boardId) },
  });
  expect(created.ok()).toBeTruthy();
  const card = await created.json();
  const flagged = await page.request.post(`/api/v1/cards/${card.id}/needs-human`, {
    data: { attention_note: "need a decision on the auth flow" },
  });
  expect(flagged.ok()).toBeTruthy();

  // Reload so the SPA refetches; the badge should render on the card face.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();
  const face = cardInColumn(page, "Todo", title);
  await expect(face).toBeVisible();
  await expect(face.locator(".needs-human-badge")).toBeVisible();
  await expect(face.locator(".needs-human-badge")).toContainText("Needs human");

  // Resolving via the API clears the flag → the badge disappears after a reload.
  const resolved = await page.request.post(`/api/v1/cards/${card.id}/resolve`);
  expect(resolved.ok()).toBeTruthy();

  // Light + dark screenshots BEFORE resolving would be gone — capture the flagged
  // state first by re-flagging, then take shots (CI-safe path via outputPath).
  const reflag = await page.request.post(`/api/v1/cards/${card.id}/needs-human`, {
    data: { attention_note: "need a decision on the auth flow" },
  });
  expect(reflag.ok()).toBeTruthy();
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => localStorage.setItem("kanban.theme", t), theme);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const themed = cardInColumn(page, "Todo", title);
    await expect(themed.locator(".needs-human-badge")).toBeVisible();
    const out = testInfo.outputPath(`v13-needs-human-${theme}.png`);
    await page.screenshot({ path: out });
    // Refresh the published docs screenshot in place. Never in CI: it must not
    // rewrite a committed asset, and it keeps its own copy above.
    if (!process.env.CI) {
      copyFileSync(out, docsImagePath(`v13-needs-human-${theme}.png`));
    }
  }

  // Verify the resolve path too: clear it and confirm the badge is gone.
  await page.request.post(`/api/v1/cards/${card.id}/resolve`);
  await page.reload();
  await expect(column(page, "Todo")).toBeVisible();
  await expect(cardInColumn(page, "Todo", title).locator(".needs-human-badge")).toHaveCount(0);
});
