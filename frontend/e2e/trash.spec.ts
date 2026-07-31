import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createCard,
  openFreshBoard,
  openView,
  uniqueTitle,
} from "./helpers";

// KAN-20 trash & restore: deleting a card tombstones it (KAN-19); the Trash view
// lists it, restores it back to the board, or purges it permanently. Also captures
// light + dark screenshots as per-test output artifacts (testInfo.outputPath —
// CI-safe on any runner, no hardcoded absolute paths).

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

// Soft-delete a card from the board via its face's Delete affordance (icon → confirm).
async function deleteCard(page: import("@playwright/test").Page, title: string) {
  const card = cardInColumn(page, "Todo", title);
  await card.getByRole("button", { name: "Delete", exact: true }).click(); // icon → confirm
  // Confirm mode embeds the title in a sentence, so the title-filtered locator no
  // longer matches — target the confirm dialog directly (one card deleting at a time).
  await page
    .locator(".card.confirm")
    .getByRole("button", { name: "Delete", exact: true })
    .click();
  await expect(cardInColumn(page, "Todo", title)).toBeHidden();
}

function trashRow(page: import("@playwright/test").Page, title: string) {
  return page.locator(".trash-row", { has: page.getByText(title, { exact: true }) });
}

async function openTrash(page: import("@playwright/test").Page) {
  await openView(page, "Trash");
  await expect(page.getByRole("heading", { name: "Trash", exact: true })).toBeVisible();
}

test("trash lists a deleted card, restores it, then purges it", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("trash");
  await createCard(page, "Todo", title);

  // Delete → it leaves the board and lands in the Trash view.
  await deleteCard(page, title);
  await openTrash(page);
  await expect(trashRow(page, title)).toBeVisible();

  // Restore → gone from trash, back on the board.
  await trashRow(page, title).getByRole("button", { name: "Restore" }).click();
  await expect(trashRow(page, title)).toBeHidden();
  await page.getByRole("button", { name: "Board", exact: true }).click();
  await expect(cardInColumn(page, "Todo", title)).toBeVisible();

  // Delete again, then purge permanently → gone from the trash for good.
  await deleteCard(page, title);
  await openTrash(page);
  const row = trashRow(page, title);
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Delete permanently" }).click();
  await row.getByRole("button", { name: "Delete", exact: true }).click(); // confirm
  await expect(trashRow(page, title)).toBeHidden();
});

test("trash view screenshots — light + dark", async ({ page }, testInfo) => {
  await setTheme(page, "light");
  await openFreshBoard(page);
  const title = uniqueTitle("shot");
  await createCard(page, "Todo", title);
  await deleteCard(page, title);
  await openTrash(page);
  await expect(trashRow(page, title)).toBeVisible();
  // testInfo.outputPath resolves under the per-test output dir (exists on any runner).
  await page.screenshot({ path: testInfo.outputPath("trash-light.png"), fullPage: true });

  // Flip to dark via the top-bar theme toggle and re-shoot the same view.
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator(':root[data-theme="dark"]')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("trash-dark.png"), fullPage: true });
});
