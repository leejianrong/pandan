import { expect, test } from "@playwright/test";
import {
  cleanupE2eBoards,
  cleanupE2eTeams,
  createTeam,
  login,
  pickSelect,
  teamItem,
  uniqueTitle,
} from "./helpers";

// M9 V70 demo (KAN-1059; ADR 0021): a human creates a team and adds a board to it
// entirely from the browser — the Teams screen (mirroring Epics) plus the board
// switcher's Team picker (mirroring how a board's key/name are set there).
test.afterAll(() => Promise.all([cleanupE2eBoards(), cleanupE2eTeams()]));

test("create a team and link a board to it from the board switcher", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();

  const teamName = uniqueTitle("team");
  await createTeam(page, teamName);

  // The creator is auto-added as owner; the card shows the role pill and (since
  // there are no other members/boards yet) the empty states.
  const item = teamItem(page, teamName);
  await expect(item.locator(".role-pill")).toHaveText("owner");
  await expect(item.getByText("No boards linked yet.")).toBeVisible();

  // Create a board and link it to the team via the picker (R2: creating a board
  // lets its creator attach it). createTeam() left the Teams view open; the
  // switcher itself lives in the persistent top bar regardless of view.
  const boardName = uniqueTitle("teamboard");
  await page.locator(".board-switcher").getByRole("button", { name: "New board" }).click();
  await page.getByLabel("Board name").fill(boardName);
  await pickSelect(page, page.locator(".board-switcher"), "Team", teamName);
  await page.locator(".board-switcher").getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.locator(".board-switcher")).toContainText(boardName);

  // The switcher stays on the Teams view (creating a board doesn't navigate),
  // and the card already lists the newly linked board — state is server-fetched
  // reactively, no reload needed.
  await expect(teamItem(page, teamName).getByText(boardName)).toBeVisible();
});

test("an owner adds a member, re-roles them, then removes them", async ({ browser }) => {
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const owner = `e2e-owner-${stamp}@example.com`;
  const teammate = `e2e-mate-${stamp}@example.com`;

  // Bootstrap the teammate's user row (test-login upserts on first use) so the
  // owner can look them up by email — mirrors board Members' own precondition.
  const bootstrapCtx = await browser.newContext();
  const bootstrapPage = await bootstrapCtx.newPage();
  await login(bootstrapPage, teammate);
  await bootstrapCtx.close();

  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await login(page, owner);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Todo", exact: true })).toBeVisible();

  const teamName = uniqueTitle("team");
  await createTeam(page, teamName);
  await teamItem(page, teamName).click();
  const modal = page.locator(".card-modal");
  await expect(modal).toBeVisible();

  // Add the teammate as an editor. The role picker is a native <select> here
  // (mirrors Members.svelte), not the Bits UI Select combobox pickSelect() drives.
  await modal.getByRole("button", { name: "Add member" }).click();
  await modal.getByLabel("Member email").fill(teammate);
  await modal.getByLabel("Role", { exact: true }).selectOption("editor");
  await modal.getByRole("button", { name: "Add", exact: true }).click();
  await expect(modal.getByText(teammate)).toBeVisible();

  // Re-role the teammate to viewer via their row's own select.
  await modal
    .getByLabel(`Role for ${teammate}`)
    .selectOption("viewer");
  await expect(modal.getByLabel(`Role for ${teammate}`)).toHaveValue("viewer");

  // Remove the teammate: the inline danger button, then confirm.
  await modal.getByRole("button", { name: `Remove ${teammate}` }).click();
  await modal.getByRole("button", { name: "Confirm" }).click();
  await expect(modal.getByText(teammate)).toHaveCount(0);

  await ctx.close();
});
