import { expect, test } from "@playwright/test";
import { cleanupE2eBoards, createCard, openFreshBoard, uniqueTitle } from "./helpers";

// PAN-238: sprints are optional per board and opted into from the browser. A board
// with none offers "Start sprints"; doing it creates the run and the Sprint
// selector replaces the button, with open work still on the board.

test.afterAll(() => cleanupE2eBoards());

test("start sprints from the board, then the sprint selector appears", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("keeps-showing");
  await createCard(page, "Todo", title);

  await expect(page.getByLabel("Sprint", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Start sprints" }).click();

  const dialog = page.getByRole("dialog", { name: "Start sprints" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("How many sprints").fill("3");
  await dialog.getByRole("button", { name: "Start sprints" }).click();

  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Sprint", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start sprints" })).toHaveCount(0);
  // Unscheduled open work stays on a sprint-scoped board.
  await expect(page.getByText(title, { exact: true })).toBeVisible();

  const boardId = Number(await page.evaluate(() => localStorage.getItem("kanban.activeBoardId")));
  const cycles = await (await page.request.get(`/api/v1/boards/${boardId}/cycles`)).json();
  expect(cycles.map((c: { name: string }) => c.name)).toEqual(["Sprint 1", "Sprint 2", "Sprint 3"]);
});
