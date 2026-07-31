import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createCard,
  openFreshBoard,
  pickSelect,
  uniqueTitle,
} from "./helpers";

// /api/v1 is owner-gated (M3 V8): each test opens a real session on a fresh board.
test.afterAll(() => cleanupE2eBoards());

// KAN-30: dependencies in the board UI. Add a blocker to a card from its edit
// form (picking a same-board card), assert the "blocked" badge + blocked-by
// reference render on the card face, then remove it and assert they clear. The
// refetch after each edge makes it server-authoritative (no optimistic UI).
test("add a blocker, see the blocked badge, then remove it", async ({ page }) => {
  await openFreshBoard(page);

  const blockerTitle = uniqueTitle("blocker");
  const blockedTitle = uniqueTitle("blocked");
  await createCard(page, "Todo", blockerTitle);
  await createCard(page, "Todo", blockedTitle);

  // The blocker's ticket number drives the Add-blocker option label + the
  // blocked-by reference we assert later.
  const blockerCard = cardInColumn(page, "Todo", blockerTitle);
  const blockerTicket = (await blockerCard.locator(".ticket").innerText()).trim();
  expect(blockerTicket).toMatch(/^KAN-\d+$/);

  // No badge before any dependency exists.
  const blockedCard = cardInColumn(page, "Todo", blockedTitle);
  await expect(blockedCard.locator(".blocked-badge")).toHaveCount(0);

  // Open the blocked card's edit form and add the blocker via the picker.
  await blockedCard.getByRole("button", { name: "Edit" }).click();
  const form = page.locator(".card-form");
  await expect(form).toBeVisible();
  await pickSelect(page, form, "Add blocker", `${blockerTicket} · ${blockerTitle}`);

  // The edge takes effect immediately (server-authoritative refetch): the form's
  // blocker list now lists it.
  await expect(form.locator(".blocker-item")).toContainText(blockerTicket);

  // Close the form; the card face now shows the blocked badge + the blocked-by ref
  // (the blocker is in Todo, i.e. unfinished).
  await form.getByRole("button", { name: "Cancel" }).click();
  await expect(blockedCard.locator(".blocked-badge")).toBeVisible();
  await expect(blockedCard.locator(".deps")).toContainText("Blocked by");
  await expect(blockedCard.locator(".dep-ref")).toContainText(blockerTicket);

  // Reopen the form and remove the blocker.
  await blockedCard.getByRole("button", { name: "Edit" }).click();
  await expect(form).toBeVisible();
  await form.getByRole("button", { name: `Remove blocker ${blockerTicket}` }).click();
  await expect(form.locator(".blocker-item")).toHaveCount(0);

  // Close the form; the badge and reference are gone.
  await form.getByRole("button", { name: "Cancel" }).click();
  await expect(blockedCard.locator(".blocked-badge")).toHaveCount(0);
  await expect(blockedCard.locator(".deps")).toHaveCount(0);

  // Server-authoritative: the cleared state survives a full reload.
  await page.reload();
  await expect(cardInColumn(page, "Todo", blockedTitle).locator(".blocked-badge")).toHaveCount(0);
});
