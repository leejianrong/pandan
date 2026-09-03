import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, openFreshBoard } from "./helpers";

// NR-1/NR-2 (KAN-1148/KAN-1149, docs/design-reviews/nav-rail-slices.md): the
// persistent left rail that replaces the hamburger+drawer's board-scoped
// items AND (since NR-2) the top-bar Board pill. No existing spec asserted
// drawer navigation (there was nothing to assert against — the drawer had
// never been covered), so this is new coverage, not a migration.

test.afterAll(async () => {
  await cleanupE2eBoards();
});

function rail(page: import("@playwright/test").Page) {
  return page.getByRole("navigation", { name: "Views" });
}

const RAIL_ITEMS: { label: string; heading: string }[] = [
  { label: "Dashboard", heading: "Dashboard" },
  { label: "Epics", heading: "Epics" },
  { label: "Labels", heading: "Labels" },
  { label: "Backlog", heading: "Backlog" },
  { label: "Activity", heading: "Activity" },
  { label: "Members", heading: "Members" },
  { label: "Trash", heading: "Trash" },
];

for (const { label, heading } of RAIL_ITEMS) {
  test(`nav rail → ${label} navigates and marks itself current`, async ({ page }) => {
    await openFreshBoard(page);

    const item = rail(page).getByRole("button", { name: label });
    await item.click();

    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(item).toHaveAttribute("aria-current", "page");
  });
}

test("nav rail highlights exactly one item at a time", async ({ page }) => {
  await openFreshBoard(page);

  await rail(page).getByRole("button", { name: "Epics" }).click();
  await expect(rail(page).getByRole("button", { name: "Epics" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await rail(page).getByRole("button", { name: "Members" }).click();
  await expect(rail(page).getByRole("button", { name: "Members" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(rail(page).getByRole("button", { name: "Epics" })).not.toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("nav rail's Board item is current on load and returns from another view", async ({
  page,
}) => {
  await openFreshBoard(page);

  const boardItem = rail(page).getByRole("button", { name: "Board", exact: true });
  await expect(boardItem).toHaveAttribute("aria-current", "page");

  await rail(page).getByRole("button", { name: "Trash" }).click();
  await expect(boardItem).not.toHaveAttribute("aria-current", "page");

  await boardItem.click();
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();
  await expect(boardItem).toHaveAttribute("aria-current", "page");
});

test("the old top-bar Board pill is gone (NR-2 retired it atomically)", async ({ page }) => {
  await openFreshBoard(page);
  // Only the rail's Board button should exist now — no second "Board" button
  // in the top bar, which would make this locator ambiguous if the pill
  // still existed.
  await expect(page.getByRole("button", { name: "Board", exact: true })).toHaveCount(1);
});
