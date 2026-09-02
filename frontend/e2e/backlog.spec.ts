import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, createCard, openFreshBoard, openView, uniqueTitle } from "./helpers";

// The backlog view (M8 V56, KAN-977): "a place you can open" (SHAPING R2.2), not a
// filter toggle bolted onto the board. The backlog itself is *derived* — a card
// with no cycle assigned — so a plain card created via the board UI (which has no
// cycle-assignment affordance at all) lands in it by construction. `parked` is the
// one real, stored field this slice adds: distinguishes *deliberately* parked from
// simply not yet scheduled.

test.afterAll(() => cleanupE2eBoards());

function backlogRow(page: import("@playwright/test").Page, title: string) {
  return page.locator(".backlog-view tbody tr", { has: page.getByText(title, { exact: true }) });
}

test("a plain card (no cycle) shows up in the backlog", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("unscheduled");
  await createCard(page, "Todo", title);

  await openView(page, "Backlog");
  await expect(backlogRow(page, title)).toBeVisible();
});

test("marking a card parked toggles it without removing it from the backlog", async ({
  page,
}) => {
  await openFreshBoard(page);
  const title = uniqueTitle("park-me");
  await createCard(page, "Todo", title);

  await openView(page, "Backlog");
  const row = backlogRow(page, title);
  await expect(row).toBeVisible();
  const checkbox = row.getByRole("checkbox");
  await expect(checkbox).not.toBeChecked();

  await checkbox.click();
  await expect(checkbox).toBeChecked();
  // Still in the backlog — parked is independent of cycle assignment (SHAPING D8).
  await expect(row).toBeVisible();

  await checkbox.click();
  await expect(checkbox).not.toBeChecked();
});

test("opening a backlog card's modal shows the same card the board would", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("open-modal");
  await createCard(page, "Todo", title);

  await openView(page, "Backlog");
  await backlogRow(page, title).click();
  await expect(page.getByRole("dialog", { name: new RegExp(title) })).toBeVisible();
});
