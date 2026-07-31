import { expect, test, type Page } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  column,
  createCard,
  openFreshBoard,
  openView,
  uniqueTitle,
} from "./helpers";

// V36 (KAN-300) keyboard shortcuts: drive the board by keyboard ONLY — focus a
// card, navigate between cards/columns, move a card to another column (which hits
// the real move endpoint and refetches — server-authoritative, no optimistic UI),
// create a card, and open the '?' help overlay. Also proves single-key shortcuts
// don't hijack typing into a form field.

test.afterAll(async () => {
  await cleanupE2eBoards();
});

// The focused card carries a persistent .kbd-focused ring.
function focusedCard(page: Page) {
  return page.locator(".board .card.kbd-focused");
}

test("navigate cards and move one to another column with the keyboard only", async ({
  page,
}) => {
  await openFreshBoard(page);
  const a = uniqueTitle("kbd-a");
  const b = uniqueTitle("kbd-b");
  await createCard(page, "Todo", a);
  await createCard(page, "Todo", b);

  // `j` seeds focus on the first card, then advances down the column.
  await page.keyboard.press("j");
  await expect(cardInColumn(page, "Todo", a).locator(".card")).toHaveClass(
    /kbd-focused/,
  );
  await page.keyboard.press("j");
  await expect(cardInColumn(page, "Todo", b).locator(".card")).toHaveClass(
    /kbd-focused/,
  );
  // `k` goes back up.
  await page.keyboard.press("k");
  await expect(cardInColumn(page, "Todo", a).locator(".card")).toHaveClass(
    /kbd-focused/,
  );

  // Shift+ArrowRight moves the focused card to the next column (In Progress).
  await page.keyboard.press("Shift+ArrowRight");
  await expect(cardInColumn(page, "In Progress", a)).toBeVisible();
  await expect(cardInColumn(page, "Todo", a)).toHaveCount(0);
  // It stays focused across the refetch, so the keyboard flow can continue.
  await expect(focusedCard(page)).toHaveText(/kbd-a/);
});

test("`o` opens the focused card, Escape closes it", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("kbd-open");
  await createCard(page, "Todo", title);

  await page.keyboard.press("j");
  await page.keyboard.press("o");
  await expect(page.getByRole("dialog", { name: new RegExp(title) })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: new RegExp(title) })).toBeHidden();
});

test("`n` starts an add-card form; typing shortcut letters is not hijacked", async ({
  page,
}) => {
  await openFreshBoard(page);

  // `n` opens the add-card form in the first (Todo) column.
  await page.keyboard.press("n");
  const todo = column(page, "Todo");
  const input = todo.getByPlaceholder("Title (required)");
  await expect(input).toBeVisible();

  // Type a title full of single-key shortcut letters (j/k/h/l/e/o/n/c). If the
  // guard leaked, these would navigate/move instead of landing in the field.
  const title = `${uniqueTitle("kbd")}-jklheonc`;
  await input.fill(title);
  await expect(input).toHaveValue(title);
  await todo.getByRole("button", { name: "Create" }).click();
  await expect(cardInColumn(page, "Todo", title)).toBeVisible();
});

test("`?` opens the shortcuts help overlay and lists the ⌘K palette", async ({
  page,
}) => {
  await openFreshBoard(page);

  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toBeVisible();
  await expect(help.getByText("Open command palette")).toBeVisible();

  // Esc closes it (Modal contract).
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
});

// KAN-392: the help overlay is discoverable without knowing '?' — a visible
// "Keyboard shortcuts" entry in the avatar dropdown menu opens the same overlay.
// The overlay mount moved to App.svelte (global), so it works from any view.
test("avatar menu 'Keyboard shortcuts' entry opens the help overlay", async ({
  page,
}) => {
  await openFreshBoard(page);

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Keyboard shortcuts" }).click();

  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toBeVisible();
  // The board's '?' block was removed from Board — confirm exactly one overlay
  // renders (no double-mount) when opened while on the board view.
  await expect(help).toHaveCount(1);
  await expect(help.getByText("Open command palette")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
});

test("avatar menu opens the help overlay from a NON-board view (Epics)", async ({
  page,
}) => {
  await openFreshBoard(page);

  // Navigate away from the board — the overlay used to be mounted only in Board,
  // so this is the case the App-level mount fixes.
  await openView(page, "Epics");
  await expect(page.getByRole("button", { name: "New epic" })).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Keyboard shortcuts" }).click();

  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toBeVisible();
  await expect(help).toHaveCount(1);

  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
});
