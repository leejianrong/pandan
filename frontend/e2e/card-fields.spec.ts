import { copyFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  column,
  openFreshBoard,
  pickSelect,
  uniqueTitle,
} from "./helpers";

// M5 V11 (KAN-244): card fields — priority, labels, due date. A card created with
// a priority + a (pre-existing, board-scoped) label + a past due date renders the
// priority badge, the colored label chip, and the overdue due pill on its face.
// Labels are created via the API (their CRUD is the agent/CLI surface); the UI's
// create form attaches an existing one. Server-authoritative throughout.
test.afterAll(() => cleanupE2eBoards());

test("a card with priority + label + due renders badge, chip, and overdue pill", async ({
  page,
}, testInfo) => {
  await openFreshBoard(page);

  // The active board id is persisted per-browser; read it to create a label via
  // the API (label creation is the API/CLI/MCP surface in this slice).
  const boardId = await page.evaluate(() => localStorage.getItem("kanban.activeBoardId"));
  expect(boardId).toBeTruthy();
  const labelName = uniqueTitle("bug");
  const created = await page.request.post(`/api/v1/boards/${boardId}/labels`, {
    data: { name: labelName, color: "#ef4444" },
  });
  expect(created.ok()).toBeTruthy();

  // Reload so the SPA's label store picks up the new label for the picker.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();

  // Create a card with a priority, a past due date (→ overdue while in Todo), and
  // the label attached — all via the create form.
  const title = uniqueTitle("fields");
  const col = column(page, "Todo");
  await col.getByRole("button", { name: "Add card" }).click();
  await col.getByPlaceholder("Title (required)").fill(title);
  await pickSelect(page, col, "Priority", "high");
  await col.getByLabel("Due date").fill("2020-01-01");
  await col.getByRole("button", { name: labelName }).click(); // toggle the label on
  await col.getByRole("button", { name: "Create" }).click();

  const card = cardInColumn(page, "Todo", title);
  await expect(card).toBeVisible();

  // Priority badge.
  await expect(card.locator(".priority-badge")).toContainText("High");
  // Colored label chip.
  const chip = card.locator(".label-chip");
  await expect(chip).toBeVisible();
  await expect(chip).toContainText(labelName);
  // Overdue due pill (past due + not done).
  await expect(card.locator(".due-pill.overdue")).toBeVisible();

  // All three survive a reload (server-authoritative).
  await page.reload();
  const reloaded = cardInColumn(page, "Todo", title);
  await expect(reloaded.locator(".priority-badge")).toContainText("High");
  await expect(reloaded.locator(".label-chip")).toContainText(labelName);
  await expect(reloaded.locator(".due-pill.overdue")).toBeVisible();

  // Light + dark screenshots (CI-safe path via testInfo.outputPath — never a
  // hardcoded absolute path), with review copies at the worktree root.
  const root = resolve(process.cwd(), "..");
  await expect(page.locator("html")).toHaveAttribute("data-theme", /light|dark/);

  for (const theme of ["light", "dark"] as const) {
    // Set the theme deterministically via the persisted key + reload.
    await page.evaluate((t) => localStorage.setItem("kanban.theme", t), theme);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(cardInColumn(page, "Todo", title)).toBeVisible();
    const out = testInfo.outputPath(`v11-card-fields-${theme}.png`);
    await page.screenshot({ path: out });
    copyFileSync(out, resolve(root, `v11-card-fields-${theme}.png`));
  }
});
