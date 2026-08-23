import { expect, test } from "@playwright/test";
import { login, openView, uniqueTitle } from "./helpers";

// V61 (KAN-982): the label management screen. Before this slice `createLabel` and
// `deleteLabel` had sat in api.ts since M5 V11 with no component calling either, so
// labels were unreachable from the UI entirely — which is why issue #278's request
// for a colour picker had nowhere to land. These specs exercise the full round trip
// through the real API (labels are owner-gated like the rest of /api/v1), and clean
// up after themselves like the rest of the suite.
//
// Rows are addressed by `data-label-id`, NOT by their text: in edit mode the name
// moves into an <input>, so a text-filtered locator stops matching the row it just
// put into edit mode. That cost a real debugging round on this spec.

async function createLabel(page: import("@playwright/test").Page, name: string, color?: string) {
  await page.getByRole("button", { name: "New label" }).click();
  await page.getByLabel("Label name").fill(name);
  if (color) await page.getByLabel("Label color").fill(color);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const row = page.locator(".label-row", { has: page.getByText(name, { exact: true }) });
  await expect(row).toBeVisible();
  const id = await row.getAttribute("data-label-id");
  return page.locator(`.label-row[data-label-id="${id}"]`);
}

async function deleteRow(row: import("@playwright/test").Locator) {
  await row.getByRole("button", { name: /^Delete / }).click();
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(row).toHaveCount(0);
}

test("create a label, rename and recolour it, then delete it", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await openView(page, "Labels");

  const name = uniqueTitle("label");
  const row = await createLabel(page, name, "#ef4444");

  // A brand-new label is on nothing, and the screen says so — the count is what makes
  // the delete confirm honest, so it is worth asserting rather than assuming.
  await expect(row.locator(".label-usage")).toHaveText("unused");

  // Rename + recolour in one save. This is the capability that did not exist at all
  // before KAN-982: PATCH /labels/{id} was never implemented, so the only way to fix
  // a typo was to delete the label and lose its card attachments.
  const renamed = `${name}-fixed`;
  await row.getByRole("button", { name: `Edit ${name}` }).click();
  await row.getByLabel("Label name").fill(renamed);
  await row.getByLabel("Label color").fill("#0ea5e9");
  await row.getByRole("button", { name: "Save" }).click();

  await expect(row.getByText(renamed, { exact: true })).toBeVisible();
  // Asserted as computed CSS, not the style attribute: Svelte serializes the bound
  // hex to `background: rgb(14, 165, 233)`, so an attribute regex on the hex fails
  // even though the recolour worked.
  await expect(row.locator(".swatch")).toHaveCSS("background-color", "rgb(14, 165, 233)");

  await deleteRow(row);
});

test("cancelling an edit discards it rather than saving", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await openView(page, "Labels");

  const name = uniqueTitle("label");
  const row = await createLabel(page, name);

  await row.getByRole("button", { name: `Edit ${name}` }).click();
  await row.getByLabel("Label name").fill("SHOULD-NOT-PERSIST");
  await row.getByRole("button", { name: "Cancel" }).click();

  // The original name is still the one on the board. Asserted on the row's own text
  // rather than "the string is absent from the page", so a half-applied edit fails.
  await expect(row.getByText(name, { exact: true })).toBeVisible();
  await expect(page.getByText("SHOULD-NOT-PERSIST")).toHaveCount(0);

  await deleteRow(row);
});
