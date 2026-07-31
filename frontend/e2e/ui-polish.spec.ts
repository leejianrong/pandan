import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createCard,
  createEpic,
  createStoryUnder,
  epicItem,
  login,
  openFreshBoard,
  openView,
  pickSelect,
  uniqueTitle,
} from "./helpers";

// UI polish (KAN-65/66/67): card + epic detail modals, Epics Active/Completed
// grouping, and the persistent theme toggle. Owner-gated API, so each test that
// touches board data opens a real session on a fresh board.
test.afterAll(() => cleanupE2eBoards());

// KAN-65: clicking a card opens the detail modal; editing a field + Save persists.
test("card modal opens on click; edit a field and save persists across reload", async ({
  page,
}) => {
  await openFreshBoard(page);
  const title = uniqueTitle("modal");
  await createCard(page, "Todo", title);

  // Click the card face (title, not a control) → the modal opens.
  await cardInColumn(page, "Todo", title).locator(".card-title").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByPlaceholder("Title (required)")).toHaveValue(title);

  // Edit the assignee, then Save.
  await dialog.getByPlaceholder("Assignee").fill("Ada L");
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // Server-authoritative: the edit is on the card face and survives a reload.
  await expect(cardInColumn(page, "Todo", title)).toContainText("Ada L");
  await page.reload();
  await expect(cardInColumn(page, "Todo", title)).toContainText("Ada L");
  await cardInColumn(page, "Todo", title).locator(".card-title").click();
  await expect(page.getByRole("dialog").getByPlaceholder("Assignee")).toHaveValue("Ada L");
});

// KAN-65: the modal's Status control moves the card via the move endpoint.
test("card modal status select moves the card to another column", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("statusmove");
  await createCard(page, "Todo", title);

  await cardInColumn(page, "Todo", title).locator(".card-title").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await pickSelect(page, dialog, "Status", "Done");

  // Move is server-authoritative (refetch): the card leaves Todo for Done.
  await expect(cardInColumn(page, "Done", title)).toBeVisible();
  await expect(cardInColumn(page, "Todo", title)).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.reload();
  await expect(cardInColumn(page, "Done", title)).toBeVisible();
});

// KAN-66: epics split into Active (≥1 story not done, incl. no stories) and
// Completed (≥1 story, all done), with a per-epic progress rollup.
test("epics page groups Active vs Completed", async ({ page }) => {
  await openFreshBoard(page);

  const activeName = uniqueTitle("epic-active");
  const activeTicket = await createEpic(page, activeName);
  await createStoryUnder(page, "Todo", uniqueTitle("story-a"), activeTicket, activeName);

  const doneName = uniqueTitle("epic-done");
  const doneTicket = await createEpic(page, doneName);
  const doneStory = uniqueTitle("story-b");
  await createStoryUnder(page, "Todo", doneStory, doneTicket, doneName);

  // Move the done epic's only story to Done via the card modal.
  await cardInColumn(page, "Todo", doneStory).locator(".card-title").click();
  await pickSelect(page, page.getByRole("dialog"), "Status", "Done");
  await expect(cardInColumn(page, "Done", doneStory)).toBeVisible();
  await page.keyboard.press("Escape");

  // Open the Epics view and assert the two grouped sections.
  await openView(page, "Epics");
  await expect(page.locator(".section-label", { hasText: "Active" })).toBeVisible();
  await expect(page.locator(".section-label", { hasText: "Completed" })).toBeVisible();

  // The all-done epic is grouped as completed (and shows a full rollup); the
  // other stays active.
  await expect(epicItem(page, doneName)).toHaveClass(/completed/);
  await expect(epicItem(page, doneName)).toContainText("1 / 1 done");
  await expect(epicItem(page, activeName)).not.toHaveClass(/completed/);
});

// KAN-66: the epic detail modal edits name in place, server-authoritatively.
test("epic modal opens on click; edit name and save persists across reload", async ({
  page,
}) => {
  await openFreshBoard(page);
  const name = uniqueTitle("epic-edit");
  await createEpic(page, name);

  await epicItem(page, name).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  const renamed = `${name}-renamed`;
  await dialog.getByLabel("Epic name").fill(renamed);
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await expect(epicItem(page, renamed)).toBeVisible();
  await page.reload();
  await openView(page, "Epics");
  await expect(epicItem(page, renamed)).toBeVisible();
});

// KAN (theme): the top-bar toggle sets data-theme on <html> and persists it.
test("theme toggle switches and persists across reload", async ({ page }) => {
  await login(page);
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /Switch to (dark|light) theme/ });
  await expect(toggle).toBeVisible();

  const before = await page.locator("html").getAttribute("data-theme");
  await toggle.click();
  const after = await page.locator("html").getAttribute("data-theme");
  expect(after).not.toBe(before);
  expect(after === "light" || after === "dark").toBeTruthy();

  // Persisted (localStorage) → the choice survives a reload.
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", after!);
});
