import { expect, test, type Page } from "@playwright/test";
import { cleanupE2eBoards, login, uniqueTitle } from "./helpers";

// Notification inbox (V39, KAN-303) — the bell + unread badge in the top bar opens
// the anchored inbox popover; notifications render newest-first and can be marked
// read (per-item + all), which decrements the badge (server-authoritative refetch).
//
// A DEDICATED user (not the shared e2e user) gives this test an isolated inbox, so
// the exact unread-count assertions can't be perturbed by other specs' notifications
// (the inbox is user-scoped and spans every board the user owns). Its e2e-prefixed
// board is cleaned up after each test (deleting a board cascades its notifications).
const INBOX_USER = "e2e-inbox@example.com";

// Seed via the API (owner = INBOX_USER, so notifications land in their inbox). A
// truthy assignee on a card emits an `assigned` notification (backend V37) — the
// simplest deterministic way to create one. Uses the page's session cookie.
async function apiJson(
  page: Page,
  method: "POST" | "PATCH",
  path: string,
  body: unknown,
): Promise<{ id: number }> {
  const res = await page.request.fetch(`/api/v1${path}`, {
    method,
    data: body,
    headers: { "content-type": "application/json" },
  });
  if (!res.ok()) {
    throw new Error(`${method} ${path} failed (${res.status()}): ${await res.text()}`);
  }
  return res.json();
}

test.describe("notification inbox (V39, KAN-303)", () => {
  test.afterEach(async () => {
    await cleanupE2eBoards([INBOX_USER]);
  });

  test("renders notifications, marks read, and the unread badge decrements", async ({
    page,
  }) => {
    await login(page, INBOX_USER);

    // Two `assigned` notifications: a board + two cards, each assigned to an agent.
    const board = await apiJson(page, "POST", "/boards", {
      name: uniqueTitle("inbox-board"),
    });
    const c1 = await apiJson(page, "POST", "/cards", {
      board_id: board.id,
      title: uniqueTitle("card"),
      column: "todo",
    });
    const c2 = await apiJson(page, "POST", "/cards", {
      board_id: board.id,
      title: uniqueTitle("card"),
      column: "todo",
    });
    await apiJson(page, "PATCH", `/cards/${c1.id}`, { assignee: "e2e-agent-a" });
    await apiJson(page, "PATCH", `/cards/${c2.id}`, { assignee: "e2e-agent-b" });

    await page.goto("/");

    // The top-bar bell badge reflects 2 unread (poll refetches on mount).
    const bell = page.locator(".topbar-user").getByRole("button", { name: /Inbox/ });
    await expect(bell).toHaveAttribute("aria-label", "Inbox — 2 unread");
    await expect(bell.locator(".unread-badge")).toHaveText("2");

    // Open the popover — both notifications render as unread.
    await bell.click();
    const panel = page.locator(".inbox-panel");
    await expect(panel).toBeVisible();
    await expect(panel.locator(".note")).toHaveCount(2);
    await expect(panel.locator(".note.unread")).toHaveCount(2);
    await expect(panel.getByText(/assigned to e2e-agent-b/)).toBeVisible();

    // Mark the first (newest) notification read via its hover-revealed check button.
    const firstRow = panel.locator(".note").first();
    await firstRow.hover();
    await firstRow.getByRole("button", { name: "Mark read" }).click();

    // Server-authoritative refetch: the badge decrements to 1 and that row reads read.
    await expect(bell).toHaveAttribute("aria-label", "Inbox — 1 unread");
    await expect(bell.locator(".unread-badge")).toHaveText("1");
    await expect(panel.locator(".note.unread")).toHaveCount(1);
    await expect(panel.locator(".note.read")).toHaveCount(1);

    // The Unread filter shows only the one remaining unread notification.
    await panel.getByRole("tab", { name: "Unread" }).click();
    await expect(panel.locator(".note")).toHaveCount(1);
    await expect(panel.locator(".note.unread")).toHaveCount(1);

    // Mark all read → the badge clears entirely and the bell drops its unread label.
    await panel.getByRole("tab", { name: "All" }).click();
    await panel.getByRole("button", { name: "Mark all read" }).click();
    await expect(bell.locator(".unread-badge")).toHaveCount(0);
    await expect(bell).toHaveAttribute("aria-label", "Inbox");
  });
});
