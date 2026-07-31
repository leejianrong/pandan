import { expect, test } from "@playwright/test";
import { login, openView, uniqueTitle } from "./helpers";

// M3 V9 demo (ADR 0014): create a named agent token in the UI, see the secret
// exactly once, then revoke it. A real session is required (the Tokens API is
// owner-gated like the rest of /api/v1), so we log in for real.
test("create a token (revealed once), then revoke it", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await openView(page, "Tokens");

  const name = uniqueTitle("token");
  await page.getByRole("button", { name: "New token" }).click();
  await page.getByLabel("Token name").fill(name);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  // The secret is revealed exactly once, and it's a real PAT.
  const secret = page.locator(".secret");
  await expect(secret).toBeVisible();
  await expect(secret).toContainText("pandan_pat_");

  // It shows up in the token list.
  const row = page.locator(".token-row", { has: page.getByText(name, { exact: true }) });
  await expect(row).toBeVisible();

  // Dismiss the reveal → the secret is gone from the page (shown once).
  await page.getByRole("button", { name: "Done" }).click();
  await expect(secret).toHaveCount(0);

  // Revoke (confirm) → the row disappears.
  await row.getByRole("button", { name: "Revoke" }).click();
  await row.getByRole("button", { name: "Revoke" }).click(); // confirm
  await expect(row).toHaveCount(0);
});
