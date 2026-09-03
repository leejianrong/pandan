import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, openFreshBoard } from "./helpers";

// NR-1 (KAN-1148, docs/design-reviews/nav-rail-slices.md): the persistent left
// rail that replaces the hamburger+drawer's board-scoped items. No existing
// spec asserted drawer navigation (there was nothing to assert against — the
// drawer had never been covered), so this is new coverage, not a migration.
//
// Deliberately excludes "Board" (see NavRail.svelte's own comment / D1 in
// nav-rail-shaping.md) — that's NR-2's job, atomically with retiring the
// top-bar pill.

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

test("nav rail has no 'Board' item yet (NR-2's job)", async ({ page }) => {
  await openFreshBoard(page);
  await expect(rail(page).getByRole("button", { name: "Board", exact: true })).toHaveCount(0);
});
