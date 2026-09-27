import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, openFreshBoard } from "./helpers";

// NR-1..NR-4 (KAN-1148..KAN-1151, docs/design-reviews/nav-rail-slices.md) made
// the rail a persistent, always-visible layout column and deleted the old
// hamburger+SideNav.svelte drawer outright. NR-5 (a follow-up UI pass —
// nav-rail-shaping.md D6 explicitly deferred "collapsible/responsive rail" as
// future work rather than ruling it out) turned the rail back into a
// closed-by-default overlay, opened via a topbar toggle button, that never
// shifts `main`/`.board` when it opens — that's the whole point.

test.afterAll(async () => {
  await cleanupE2eBoards();
});

function rail(page: import("@playwright/test").Page) {
  return page.getByRole("navigation", { name: "Views" });
}

function railToggle(page: import("@playwright/test").Page) {
  return page.getByRole("button", { name: "Toggle menu" });
}

async function openRail(page: import("@playwright/test").Page): Promise<void> {
  await railToggle(page).click();
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

test("the rail is closed by default and opens via the topbar toggle", async ({ page }) => {
  await openFreshBoard(page);

  // Closed: aria-hidden, so it's absent from the accessibility tree entirely.
  await expect(rail(page)).toHaveCount(0);
  await expect(railToggle(page)).toHaveAttribute("aria-expanded", "false");

  await openRail(page);
  await expect(rail(page)).toBeVisible();
  await expect(railToggle(page)).toHaveAttribute("aria-expanded", "true");
});

for (const { label, heading } of RAIL_ITEMS) {
  test(`nav rail → ${label} navigates, marks itself current, and closes the rail`, async ({
    page,
  }) => {
    await openFreshBoard(page);
    await openRail(page);

    await rail(page).getByRole("button", { name: label }).click();

    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    // Picking an item closes the transient overlay (NavRail.svelte's pick()).
    await expect(rail(page)).toHaveCount(0);

    // Reopen to confirm the pick stuck.
    await openRail(page);
    await expect(rail(page).getByRole("button", { name: label })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
}

test("nav rail highlights exactly one item at a time", async ({ page }) => {
  await openFreshBoard(page);

  await openRail(page);
  await rail(page).getByRole("button", { name: "Epics" }).click();

  await openRail(page);
  await expect(rail(page).getByRole("button", { name: "Epics" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await rail(page).getByRole("button", { name: "Members" }).click();

  await openRail(page);
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

  await openRail(page);
  const boardItem = rail(page).getByRole("button", { name: "Board", exact: true });
  await expect(boardItem).toHaveAttribute("aria-current", "page");

  await rail(page).getByRole("button", { name: "Trash" }).click();

  await openRail(page);
  await expect(boardItem).not.toHaveAttribute("aria-current", "page");

  await boardItem.click();
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();

  await openRail(page);
  await expect(boardItem).toHaveAttribute("aria-current", "page");
});

test("the old top-bar Board pill is gone (NR-2 retired it atomically)", async ({ page }) => {
  await openFreshBoard(page);
  await openRail(page);
  // Only the rail's Board button should exist now — no second "Board" button
  // in the top bar, which would make this locator ambiguous if the pill
  // still existed.
  await expect(page.getByRole("button", { name: "Board", exact: true })).toHaveCount(1);
});

// NR-3 (KAN-1150): Tokens + Workspaces fold into the avatar menu.
test("Tokens + Workspaces live in the avatar menu", async ({ page }) => {
  await openFreshBoard(page);

  await page.getByRole("button", { name: "Account menu" }).click();
  const avatarMenu = page.getByRole("menu");
  await expect(avatarMenu.getByRole("menuitem", { name: "Tokens" })).toBeVisible();
  await expect(avatarMenu.getByRole("menuitem", { name: "Workspaces" })).toBeVisible();
});

test("selecting Tokens/Workspaces from the avatar menu navigates there", async ({ page }) => {
  await openFreshBoard(page);

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Tokens" }).click();
  await expect(page.getByRole("heading", { name: "Agent tokens", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Workspaces" }).click();
  await expect(page.getByRole("heading", { name: "Workspaces", exact: true })).toBeVisible();
});

// NR-5: the whole reason for the overlay — opening the rail must never move
// main/.board. Compare the board's bounding box before and after opening.
test("opening the rail does not shift the board (overlay, not a layout column)", async ({
  page,
}) => {
  await openFreshBoard(page);

  const board = page.locator(".board");
  const before = await board.boundingBox();
  expect(before).not.toBeNull();

  await openRail(page);
  await expect(rail(page)).toBeVisible();

  const after = await board.boundingBox();
  expect(after).not.toBeNull();
  expect(after!.x).toBe(before!.x);
  expect(after!.width).toBe(before!.width);
});

test("the rail closes on Escape and on clicking the scrim", async ({ page }) => {
  await openFreshBoard(page);

  await openRail(page);
  await expect(rail(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(rail(page)).toHaveCount(0);

  await openRail(page);
  await expect(rail(page)).toBeVisible();
  // The scrim sits behind the rail and covers the rest of the viewport —
  // click far enough right that it can't land on the rail itself.
  await page.mouse.click(page.viewportSize()!.width - 5, 5);
  await expect(rail(page)).toHaveCount(0);
});
