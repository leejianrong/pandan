import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createBoardViaSwitcher,
  createCard,
  login,
  pickSelect,
  uniqueTitle,
} from "./helpers";

// M3 V7 demo (owner-gated in V8): create two boards, add a card to one, and confirm
// the other is unaffected — across a reload. Everything hits the real backend under
// a real session; both boards are owned by the e2e user and cleaned up afterwards
// (their cards cascade away with them).
test.afterAll(() => cleanupE2eBoards());

test("a card on one board does not appear on another, across reload", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();

  // Two owned boards; creating each switches to it.
  const boardA = await createBoardViaSwitcher(page, uniqueTitle("boardA"));
  const boardB = await createBoardViaSwitcher(page, uniqueTitle("boardB"));

  // Add a card on board B (currently active).
  const cardTitle = uniqueTitle("bcard");
  await createCard(page, "Todo", cardTitle);
  await expect(cardInColumn(page, "Todo", cardTitle)).toBeVisible();

  // Switch to board A — board B's card must not appear.
  await pickSelect(page, page, "Switch board", boardA);
  await expect(cardInColumn(page, "Todo", cardTitle)).toHaveCount(0);

  // Reload: server-authoritative + persisted selection keeps us on board A, still
  // without the other board's card.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();
  await expect(cardInColumn(page, "Todo", cardTitle)).toHaveCount(0);

  // Switch to board B — its card is there and survived the reload.
  await pickSelect(page, page, "Switch board", boardB);
  await expect(cardInColumn(page, "Todo", cardTitle)).toBeVisible();
});
