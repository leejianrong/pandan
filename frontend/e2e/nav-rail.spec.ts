import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, openFreshBoard } from "./helpers";

// NR-1..NR-4 (KAN-1148..KAN-1151, docs/design-reviews/nav-rail-slices.md):
// the persistent left rail that replaces the hamburger+drawer's board-scoped
// items, the top-bar Board pill (NR-2), and — as of NR-4 — the hamburger and
// SideNav.svelte drawer themselves, now deleted outright. No existing spec
// asserted drawer navigation (there was nothing to assert against — the
// drawer had never been covered), so this is new coverage, not a migration.

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

// NR-3 (KAN-1150): Tokens + Teams fold into the avatar menu.
test("Tokens + Teams live in the avatar menu", async ({ page }) => {
  await openFreshBoard(page);

  await page.getByRole("button", { name: "Account menu" }).click();
  const avatarMenu = page.getByRole("menu");
  await expect(avatarMenu.getByRole("menuitem", { name: "Tokens" })).toBeVisible();
  await expect(avatarMenu.getByRole("menuitem", { name: "Teams" })).toBeVisible();
});

test("selecting Tokens/Teams from the avatar menu navigates there", async ({ page }) => {
  await openFreshBoard(page);

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Tokens" }).click();
  await expect(page.getByRole("heading", { name: "Agent tokens", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Teams" }).click();
  await expect(page.getByRole("heading", { name: "Teams", exact: true })).toBeVisible();
});

// NR-4 (KAN-1151): the hamburger + SideNav.svelte drawer are gone entirely —
// the rail is now the only way to reach a board-scoped view.
test("no hamburger menu button exists — the rail is the only board nav", async ({ page }) => {
  await openFreshBoard(page);
  await expect(page.getByRole("button", { name: "Open menu" })).toHaveCount(0);
  // role "complementary" was the drawer's <aside>; nothing should claim it now.
  await expect(page.getByRole("complementary")).toHaveCount(0);
});
