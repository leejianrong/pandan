import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createCard,
  openFreshBoard,
  uniqueTitle,
} from "./helpers";

// /api/v1 is owner-gated (M3 V8): each test opens a real session on a fresh board.
test.afterAll(() => cleanupE2eBoards());

// KAN-34: work-links + notes in the board UI. Add a work-link from a card's edit
// form and assert the link chip renders on the card face; post a note and assert
// it shows in the thread; then delete both. Server-authoritative throughout (a
// refetch/re-list after each mutation, no optimistic UI).
test("add a work-link chip and a comment, then delete both", async ({ page }) => {
  await openFreshBoard(page);

  const title = uniqueTitle("links-notes");
  await createCard(page, "Todo", title);
  const card = cardInColumn(page, "Todo", title);

  // No chips before any link exists.
  await expect(card.locator(".link-chip")).toHaveCount(0);

  // Open the edit form and add a work-link (label + url).
  await card.getByRole("button", { name: "Edit" }).click();
  const form = page.locator(".card-form");
  await expect(form).toBeVisible();
  await form.getByPlaceholder("Label (e.g. PR)").fill("PR");
  await form.getByPlaceholder("https://…").fill("https://example.com/pr/1");
  await form.locator(".link-add").getByRole("button", { name: "Add" }).click();

  // The link lands in the form's list immediately (server-authoritative refetch).
  await expect(form.locator(".link-item")).toContainText("PR");

  // Post a comment into the thread.
  await form.getByPlaceholder("Add a comment…").fill("first note");
  await form.getByRole("button", { name: "Post" }).click();
  await expect(form.locator(".comment-item")).toContainText("first note");

  // Close the form; the card face shows the link chip.
  await form.getByRole("button", { name: "Cancel" }).click();
  const chip = card.locator(".link-chip");
  await expect(chip).toBeVisible();
  await expect(chip).toContainText("PR");
  await expect(chip).toHaveAttribute("href", "https://example.com/pr/1");

  // Reopen: the note persisted (server-authoritative) and the link is still listed.
  await card.getByRole("button", { name: "Edit" }).click();
  await expect(form).toBeVisible();
  await expect(form.locator(".comment-item")).toContainText("first note");
  await expect(form.locator(".link-item")).toContainText("PR");

  // Delete the comment (our own — the delete affordance is shown for the author).
  await form.locator(".comment-item").getByRole("button", { name: "Delete comment" }).click();
  await expect(form.locator(".comment-item")).toHaveCount(0);
  await expect(form.locator(".comment-empty")).toBeVisible();

  // Remove the link.
  await form.getByRole("button", { name: "Remove link PR" }).click();
  await expect(form.locator(".link-item")).toHaveCount(0);

  // Close the form; the chip is gone, and it stays gone across a reload.
  await form.getByRole("button", { name: "Cancel" }).click();
  await expect(card.locator(".link-chip")).toHaveCount(0);

  await page.reload();
  await expect(cardInColumn(page, "Todo", title).locator(".link-chip")).toHaveCount(0);
});
