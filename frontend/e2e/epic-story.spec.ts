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

  // Epic is created in the Epics view and gets an EPIC- ticket (not KAN-).
  const epicTicket = await createEpic(page, epicName);
  expect(epicTicket).toMatch(/^EPIC-\d+$/);

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
