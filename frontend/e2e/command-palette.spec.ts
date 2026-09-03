import { expect, test, type Page } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  column,
  createCard,
  openFreshBoard,
  uniqueTitle,
} from "./helpers";

// V35 (KAN-299) ⌘K command palette: a fuzzy menu over EXISTING API actions. These
// specs open the palette via the global chord, run a command that MUTATES the board
// through an existing endpoint, and assert the board reflects it after refetch
// (server-authoritative — no optimistic UI).

test.afterAll(async () => {
  await cleanupE2eBoards();
});

// The palette mounts in the shared Modal (role=dialog, aria-label "Command palette").
function palette(page: Page) {
  return page.getByRole("dialog", { name: "Command palette" });
}

// Open with the ⌘/Ctrl-K global chord (deliberate global — fires even while a field
// is focused). ControlOrMeta maps to Ctrl on Linux CI, ⌘ on macOS.
async function openPalette(page: Page) {
  await page.keyboard.press("ControlOrMeta+KeyK");
  await expect(palette(page)).toBeVisible();
}

test("⌘K → move a card to Done moves it (server-authoritative)", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("palette-move");
  await createCard(page, "Todo", title);
  await expect(cardInColumn(page, "Todo", title)).toBeVisible();

  await openPalette(page);

  // Step 1: pick "Move card…".
  await page.keyboard.type("Move card");
  await palette(page).getByRole("option", { name: /Move card/ }).click();

  // Step 2: the search now filters the board's cards — find ours, pick it.
  await page.keyboard.type(title);
  await palette(page).getByRole("option", { name: new RegExp(title) }).click();

  // Step 3: choose the target column.
  await palette(page).getByRole("option", { name: /to Done/ }).click();

  // The palette closes and the board reflects the move after refetch.
  await expect(palette(page)).toBeHidden();
  await expect(cardInColumn(page, "Done", title)).toBeVisible();
  await expect(cardInColumn(page, "Todo", title)).toHaveCount(0);
});

test("⌘K → create card adds it to Todo", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("palette-create");

  await openPalette(page);

  // Step 1: select "Create card" (keyboard — the natural palette flow keeps the
  // search input focused). The search box then becomes the new card's title.
  await page.keyboard.type("Create card");
  await page.keyboard.press("Enter");

  // Step 2: type the title, then run the create action (the sole item, Enter).
  await page.keyboard.type(title);
  await expect(
    palette(page).getByRole("option", { name: new RegExp(`Create card "${title}"`) }),
  ).toBeVisible();
  await page.keyboard.press("Enter");

  await expect(palette(page)).toBeHidden();
  await expect(cardInColumn(page, "Todo", title)).toBeVisible();
});

// Regression guard for a drift where VIEWS (this file's navigable destinations) fell out
// of sync with SideNav.svelte's drawer items — Labels and Backlog were addable via the
// drawer but not ⌘K for a while. Covers both rather than asserting the full VIEWS list
// against SideNav's, since there's no shared grammar module to diff (unlike the backend's
// ref grammar / test_ref_grammar.py) — this just proves the two newest destinations work.
test("⌘K → go to view reaches Labels and Backlog", async ({ page }) => {
  await openFreshBoard(page);

  await openPalette(page);
  // "Jump vi" rather than "Jump to view" — the underlying cmdk-style fuzzy
  // filter (unrelated to this fix) scores "to" adjacent to "view" as no
  // match, so this dodges that quirk instead of asserting on it.
  await page.keyboard.type("Jump vi");
  await palette(page).getByRole("option", { name: /Jump to view/ }).click();
  await page.keyboard.type("Labels");
  await palette(page).getByRole("option", { name: "Labels" }).click();
  await expect(palette(page)).toBeHidden();
  await expect(page.getByRole("heading", { name: "Labels" })).toBeVisible();

  await openPalette(page);
  await page.keyboard.type("Jump vi");
  await palette(page).getByRole("option", { name: /Jump to view/ }).click();
  await page.keyboard.type("Backlog");
  await palette(page).getByRole("option", { name: "Backlog" }).click();
  await expect(palette(page)).toBeHidden();
  await expect(page.getByRole("heading", { name: "Backlog" })).toBeVisible();
});

test("⌘K → toggle theme flips the theme, Escape closes", async ({ page }) => {
  await openFreshBoard(page);

  const before = await page.evaluate(() =>
    document.documentElement.getAttribute("data-theme"),
  );

  await openPalette(page);
  await page.keyboard.type("theme");
  await palette(page).getByRole("option", { name: /theme/i }).click();

  await expect(palette(page)).toBeHidden();
  const after = await page.evaluate(() =>
    document.documentElement.getAttribute("data-theme"),
  );
  expect(after).not.toBe(before);

  // Escape closes the palette without running anything.
  await openPalette(page);
  await page.keyboard.press("Escape");
  await expect(palette(page)).toBeHidden();
  // The board is still there (Escape was a no-op mutation-wise).
  await expect(column(page, "Todo")).toBeVisible();
});
