import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, createCard, createEpic, openFreshBoard, openView } from "./helpers";

// NR-5 follow-up — a narrow-viewport pass: the nav rail became a
// closed-by-default overlay, the topbar wraps instead of overflowing, and
// Board/Dashboard/Epics got mobile-specific handling. None of this had any
// e2e coverage at a narrow viewport before this spec (grep for
// setViewportSize/devices[ across e2e/ returned nothing).

test.use({ viewport: { width: 390, height: 844 } });

test.afterAll(async () => {
  await cleanupE2eBoards();
});

async function hasHorizontalOverflow(page: import("@playwright/test").Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
}

test("board view has no horizontal page overflow at a mobile width", async ({ page }) => {
  await openFreshBoard(page);
  await createCard(page, "Todo", "mobile overflow check");
  expect(await hasHorizontalOverflow(page)).toBe(false);
});

test("board columns scroll-snap horizontally and the dot indicator tracks + jumps", async ({
  page,
}) => {
  await openFreshBoard(page);

  const dots = page.getByRole("tab");
  await expect(dots).toHaveCount(3);
  await expect(dots.nth(0)).toHaveAttribute("aria-selected", "true");

  await dots.nth(1).click();
  await expect(page.getByRole("heading", { name: "In Progress", exact: true })).toBeVisible();
  await page.waitForTimeout(400); // smooth scroll settles before the observer re-checks position
  await expect(dots.nth(1)).toHaveAttribute("aria-selected", "true");
  await expect(dots.nth(0)).toHaveAttribute("aria-selected", "false");
});

test("dashboard view has no horizontal page overflow at a mobile width", async ({ page }) => {
  await openFreshBoard(page);
  await openView(page, "Dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  expect(await hasHorizontalOverflow(page)).toBe(false);
});

test("epics view has no horizontal page overflow at a mobile width, even with a long name", async ({
  page,
}) => {
  await openFreshBoard(page);
  await createEpic(
    page,
    "A very long epic name that must wrap instead of overflowing the card horizontally",
  );
  expect(await hasHorizontalOverflow(page)).toBe(false);
});

test("the nav rail overlay opens without shifting the board, and the topbar wraps instead of overflowing", async ({
  page,
}) => {
  await openFreshBoard(page);

  const board = page.locator(".board");
  const before = await board.boundingBox();

  await page.getByRole("button", { name: "Toggle menu" }).click();
  await expect(page.getByRole("navigation", { name: "Views" })).toBeVisible();

  const after = await board.boundingBox();
  expect(after!.x).toBe(before!.x);
  expect(after!.width).toBe(before!.width);

  expect(await hasHorizontalOverflow(page)).toBe(false);
});
