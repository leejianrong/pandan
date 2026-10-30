import { expect, test } from "@playwright/test";
import { cardInColumn, cleanupE2eBoards, createCard, openFreshBoard, uniqueTitle } from "./helpers";

// Searching by ticket: the top-bar box sends `q` to the API, which treats a query
// that is exactly a card reference as an exact match — in the board-local form on
// screen (`ENG-2`) or the canonical `KAN-<n>` carried in the ticket's title attr.

test.afterAll(async () => {
  await cleanupE2eBoards();
});

test("top-bar search finds a card by its board-local or canonical ticket", async ({ page }) => {
  await openFreshBoard(page);
  const first = uniqueTitle("byref-first");
  const second = uniqueTitle("byref-second");
  await createCard(page, "Todo", first);
  await createCard(page, "Todo", second);

  const ticket = cardInColumn(page, "Todo", second).locator(".ticket");
  const local = (await ticket.innerText()).trim();
  const canonical = (await ticket.getAttribute("title"))!;
  const box = page.getByRole("searchbox", { name: "Search cards" });

  for (const ref of [local, local.toLowerCase(), canonical]) {
    await box.fill(ref);
    await expect(cardInColumn(page, "Todo", second)).toBeVisible();
    await expect(cardInColumn(page, "Todo", first)).toHaveCount(0);
  }
});
