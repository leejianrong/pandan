import { expect, test, type Page } from "@playwright/test";
import { cleanupE2eBoards, login, openView, uniqueTitle } from "./helpers";

// M5 V16 awareness dashboard (KAN-249): the Dashboard view composes, for the
// active board, in-flight-by-assignee (+ PR links), a needs-attention list (V13),
// derived flow metrics (V17), and the deepened activity feed — all read-only.
// This spec seeds a board via the API (the SPA is read-only here), points the app
// at it, and asserts each panel renders. It also captures light + dark
// screenshots as per-test output artifacts (testInfo.outputPath — CI-safe on any
// runner) plus review copies at the worktree root when running locally.

const CI = !!process.env.CI;
const AGENT = "agent-smith";

test.afterAll(async () => {
  await cleanupE2eBoards();
});

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("kanban.theme", t);
    } catch {
      /* ignore */
    }
  }, theme);
}

// Seed a fresh board with a completed card (throughput + cycle time), an in-flight
// card with a PR work-link, and a needs-human handoff. Returns the note text so the
// test can assert it. Points the SPA at the board via localStorage before load.
async function seedDashboardBoard(page: Page): Promise<{ note: string }> {
  await login(page);
  const board = await (
    await page.request.post("/api/v1/boards", { data: { name: uniqueTitle("dash-board") } })
  ).json();
  const boardId: number = board.id;

  // A cycle spanning [2 days ago, today] so the burndown panel (V34) has a window.
  const day = 24 * 3600 * 1000;
  const startsOn = new Date(Date.now() - 2 * day).toISOString();
  const endsOn = new Date().toISOString();
  const cycle = await (
    await page.request.post(`/api/v1/boards/${boardId}/cycles`, {
      data: { name: uniqueTitle("sprint"), starts_on: startsOn, ends_on: endsOn },
    })
  ).json();

  // Completed card: todo → in_progress → done (drives throughput + cycle time).
  // Assigned to the cycle with story points, so committed/completed/velocity show.
  const done = await (
    await page.request.post("/api/v1/cards", {
      data: {
        title: uniqueTitle("shipped"),
        board_id: boardId,
        assignee: AGENT,
        cycle_id: cycle.id,
        story_points: 5,
      },
    })
  ).json();
  await page.request.post(`/api/v1/cards/${done.id}/move`, { data: { column: "in_progress" } });
  await page.request.post(`/api/v1/cards/${done.id}/move`, { data: { column: "done" } });

  // In-flight card with a PR work-link (in-flight-by-assignee panel + link chip).
  const wip = await (
    await page.request.post("/api/v1/cards", {
      data: {
        title: uniqueTitle("in-flight"),
        board_id: boardId,
        assignee: AGENT,
        column: "in_progress",
        cycle_id: cycle.id,
        story_points: 3,
      },
    })
  ).json();
  await page.request.post(`/api/v1/cards/${wip.id}/links`, {
    data: { label: "PR", url: "https://github.com/example/repo/pull/7" },
  });

  // A card that needs a human (V13 handoff) with a note.
  const note = "Need a decision on the API shape";
  const handoff = await (
    await page.request.post("/api/v1/cards", {
      data: { title: uniqueTitle("needs-me"), board_id: boardId },
    })
  ).json();
  await page.request.post(`/api/v1/cards/${handoff.id}/needs-human`, {
    data: { attention_note: note },
  });

  // Make the seeded board active before the SPA boots (board.svelte reads this key).
  await page.addInitScript((id) => {
    try {
      localStorage.setItem("kanban.activeBoardId", String(id));
    } catch {
      /* ignore */
    }
  }, boardId);

  return { note };
}

async function openDashboard(page: Page) {
  await page.goto("/");
  await openView(page, "Dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("dashboard renders in-flight, needs-attention, activity + metrics panels", async ({
  page,
}) => {
  const { note } = await seedDashboardBoard(page);
  await openDashboard(page);

  // Stat strip headline numbers.
  const strip = page.locator(".stat-strip");
  await expect(strip).toBeVisible();
  await expect(strip).toContainText("Completed");
  await expect(strip).toContainText("Needs attention");
  await expect(strip).toContainText("Median cycle time");

  // In flight by assignee: the agent + its in-flight card + the PR link chip.
  const inflight = page.locator("section", {
    has: page.getByRole("heading", { name: "In flight by assignee" }),
  });
  await expect(inflight).toContainText(AGENT);
  await expect(inflight.getByRole("link", { name: /PR/ })).toBeVisible();

  // Needs attention: the handoff note is surfaced.
  const attn = page.locator("section", {
    has: page.getByRole("heading", { name: "Needs attention" }),
  });
  await expect(attn).toContainText(note);

  // Flow metrics panel + the per-assignee chart.
  await expect(page.getByRole("heading", { name: "Flow metrics" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Throughput .* WIP by assignee/ })).toBeVisible();

  // Recent activity feed has rows (the seeding recorded several).
  const feed = page.locator(".feed");
  await expect(feed).toBeVisible();
  expect(await feed.locator(".feed-row").count()).toBeGreaterThanOrEqual(3);
});

test("dashboard renders the cycle burndown panel (V34)", async ({ page }) => {
  await seedDashboardBoard(page);
  await openDashboard(page);

  const cyclePanel = page.locator("section", {
    has: page.getByRole("heading", { name: "Cycle burndown" }),
  });
  await expect(cyclePanel).toBeVisible();
  // The active-cycle selector is present (a cycle was seeded).
  await expect(cyclePanel.getByLabel("Active cycle")).toBeVisible();
  // Committed vs completed chart + the velocity readout (5 pts done of 8 committed).
  await expect(cyclePanel.getByRole("heading", { name: /Committed vs completed/ })).toBeVisible();
  await expect(cyclePanel).toContainText("Velocity");
  // Burndown chart renders per-day bars over the seeded 3-day window.
  await expect(cyclePanel.getByRole("heading", { name: /Burndown/ })).toBeVisible();
  expect(await cyclePanel.locator(".bar-track").count()).toBeGreaterThanOrEqual(1);
});

test("dashboard activity feed filters by action", async ({ page }) => {
  await seedDashboardBoard(page);
  await openDashboard(page);

  const feed = page.locator(".feed");
  await expect(feed).toBeVisible();

  // Filter to only "moved" rows; the seeding produced two moves and no deletes.
  await page.getByLabel("Filter by action").selectOption("moved");
  await expect(feed.locator(".feed-row").first()).toContainText(/moved|→|to /i);
  const summaries = await feed.locator(".feed-summary").allInnerTexts();
  expect(summaries.length).toBeGreaterThanOrEqual(1);
});

test("dashboard screenshots — light + dark", async ({ page }, testInfo) => {
  await setTheme(page, "light");
  await seedDashboardBoard(page);
  await openDashboard(page);
  await expect(page.locator(".stat-strip")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Flow metrics" })).toBeVisible();
  // Wait for the cycle burndown data (async, after the main panels) so the shot
  // shows the rendered chart, not the "select a cycle" placeholder.
  await expect(page.getByRole("heading", { name: /Committed vs completed/ })).toBeVisible();

  await page.screenshot({ path: testInfo.outputPath("dashboard-light.png"), fullPage: true });
  if (!CI) {
    // Review copy at the worktree root (relative to the frontend/ cwd) for the PM.
    await page.screenshot({ path: "../dashboard-light.png", fullPage: true });
  }

  // Flip to dark via the top-bar theme toggle and re-shoot.
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator(':root[data-theme="dark"]')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("dashboard-dark.png"), fullPage: true });
  if (!CI) {
    await page.screenshot({ path: "../dashboard-dark.png", fullPage: true });
  }
});
