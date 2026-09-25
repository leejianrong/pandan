import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Device-flow consent screen (ADR 0024, KAN-1729): a human opens the link
// `pandan auth login` prints (`?user_code=…`), already signed in to the SPA in
// this browser (the common case — see App.svelte's onMount for the deep-link
// detection), and approves or denies. The `/auth/device/code` call itself needs
// no auth (mirroring the real CLI, which has no credential yet); everything
// after that requires the real cookie session `login()` mints.

async function createDeviceCode(page: import("@playwright/test").Page) {
  const res = await page.request.post("/auth/device/code", { data: {} });
  expect(res.ok()).toBeTruthy();
  return res.json() as Promise<{ device_code: string; user_code: string }>;
}

test("approve a device-flow login from the deep link", async ({ page }) => {
  await login(page);
  const { device_code, user_code } = await createDeviceCode(page);

  await page.goto(`/?user_code=${user_code}`);
  await expect(page.getByRole("heading", { name: "Approve CLI login" })).toBeVisible();
  await expect(page.getByText(user_code)).toBeVisible();

  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText(/Approved/)).toBeVisible();

  // The CLI's poll now succeeds and mints a real token.
  const poll = await page.request.post("/auth/device/token", {
    data: { device_code },
  });
  expect(poll.ok()).toBeTruthy();
  const body = await poll.json();
  expect(body.token).toMatch(/^pandan_pat_/);

  // Returning to the board clears the deep link (no user_code lingering in the URL).
  await page.getByRole("button", { name: "Back to your boards" }).click();
  await expect(page).toHaveURL(/^[^?]*$/);
});

test("deny a device-flow login from the deep link", async ({ page }) => {
  await login(page);
  const { device_code, user_code } = await createDeviceCode(page);

  await page.goto(`/?user_code=${user_code}`);
  await page.getByRole("button", { name: "Deny", exact: true }).click();
  await expect(page.getByText(/Denied/)).toBeVisible();

  const poll = await page.request.post("/auth/device/token", {
    data: { device_code },
  });
  const body = await poll.json();
  expect(body.error).toBe("access_denied");
});

test("revisiting an already-approved link shows its resolved state", async ({ page }) => {
  await login(page);
  const { user_code } = await createDeviceCode(page);

  await page.goto(`/?user_code=${user_code}`);
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText(/Approved/)).toBeVisible();

  await page.goto(`/?user_code=${user_code}`);
  await expect(page.getByText("This code was already approved.")).toBeVisible();
});

test("an unknown or expired code shows a clean error, not a crash", async ({ page }) => {
  await login(page);
  await page.goto("/?user_code=NOPE-NOPE");
  await expect(page.getByText(/invalid or has expired/)).toBeVisible();
});
