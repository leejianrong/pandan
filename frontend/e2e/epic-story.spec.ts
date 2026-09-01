import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createEpic,
  createStoryUnder,
  epicItem,
  openFreshBoard,
  openView,
  uniqueTitle,
} from "./helpers";

// /api/v1 is owner-gated (M3 V8): open a real session on a fresh board.
test.afterAll(() => cleanupE2eBoards());

// Milestone 2 V1 demo (ADR 0009): epics live in their own view with an EPIC-
// ticket; the board shows stories, each tagged with its epic's name. One board
// owns many epics, one epic groups many stories (all on that board). Create an
// epic, link a story to it, and assert the tag + rollup render and survive reload.
test("create an epic (own view), link a story, tag + rollup persist", async ({ page }) => {
  await openFreshBoard(page);

  const epicName = uniqueTitle("epic");
  const storyTitle = uniqueTitle("story");

  // The epic list shows the epic's BOARD-LOCAL ref since V54 (KAN-975): `<KEY>-E<n>`,
  // on the epics' own per-board sequence, so `ENG-1` (a card) and `ENG-E1` (an epic)
  // coexist the way `KAN-1` and `EPIC-1` do. The canonical `EPIC-<n>` is the element's
  // title attribute — asserted here so this spec still pins that it did not vanish.
  const epicTicket = await createEpic(page, epicName);
  expect(epicTicket).toMatch(/^[A-Z][A-Z0-9]{1,9}-E\d+$/);
  const epicCanonical = await epicItem(page, epicName)
    .locator(".ticket")
    .getAttribute("title");
  expect(epicCanonical).toMatch(/^EPIC-\d+$/);

  // Link a story to the epic from the board.
  await createStoryUnder(page, "Todo", storyTitle, epicTicket, epicName);

  // The story card shows the epic's name as a tag.
  const storyCard = cardInColumn(page, "Todo", storyTitle);
  await expect(storyCard.locator(".epic-tag")).toHaveText(epicName);

  // The Epics view rolls the story up under its epic.
  await openView(page, "Epics");
  await expect(epicItem(page, epicName).locator(".epic-stories")).toContainText(storyTitle);

  // Server-authoritative: the link survives a full reload.
  await page.reload();
  await page.getByRole("button", { name: "Board", exact: true }).click();
  await expect(cardInColumn(page, "Todo", storyTitle).locator(".epic-tag")).toHaveText(epicName);
});
