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

// V62 (KAN-983) replaced the free-text colour field with a swatch grid, so a colour
// is now CHOSEN, not typed.
//
// Click the LABEL, not the radio. The <input type="radio"> is clipped to a 1px box
// (deliberately — `display: none` would drop it out of the tab order and take the
// native arrow-key group with it), so `.check()` on the input fails its hit-target
// check: the visible <label> is what receives the pointer, which is also what a real
// user clicks. Then assert the radio ended up checked, so the a11y semantics are
// still pinned rather than traded away for a working click.
async function pickColour(
  scope: import("@playwright/test").Page | import("@playwright/test").Locator,
  token: string,
) {
  await scope.locator(`label.swatch-opt[title="${token}"]`).click();
  await expect(scope.getByRole("radio", { name: token, exact: true })).toBeChecked();
}

async function createLabel(page: import("@playwright/test").Page, name: string, token?: string) {
  await page.getByRole("button", { name: "New label" }).click();
  await page.getByLabel("Label name").fill(name);
  if (token) await pickColour(page, token);
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
  const row = await createLabel(page, name, "mulberry");

  // A brand-new label is on nothing, and the screen says so — the count is what makes
  // the delete confirm honest, so it is worth asserting rather than assuming.
  await expect(row.locator(".label-usage")).toHaveText("unused");

  // Rename + recolour in one save. This is the capability that did not exist at all
  // before KAN-982: PATCH /labels/{id} was never implemented, so the only way to fix
  // a typo was to delete the label and lose its card attachments.
  const renamed = `${name}-fixed`;
  await row.getByRole("button", { name: `Edit ${name}` }).click();
  await row.getByLabel("Label name").fill(renamed);
  await pickColour(row, "sky");
  await row.getByRole("button", { name: "Save" }).click();

  await expect(row.getByText(renamed, { exact: true })).toBeVisible();
  // Asserted as computed CSS, not the style attribute: the attribute now reads
  // `background: var(--label-sky)`, and what actually matters is the colour that var
  // RESOLVES to — which is the whole mechanism V62 added. #0284c7 is --label-sky's
  // light value.
  await expect(row.locator(".label-info .swatch")).toHaveCSS(
    "background-color",
    "rgb(2, 132, 199)",
  );

  await deleteRow(row);
});

test("a palette token resolves to a different colour in each theme", async ({ page }) => {
  // The reason the palette exists (SHAPING D11). app.css defines every token twice,
  // once per theme; a raw user-picked hex has ONE value and is unreadable in one theme
  // about half the time. This spec is the only place that failure mode is observable —
  // a unit test can compare the two hexes in the stylesheet, but only a browser proves
  // the var actually resolves per theme on a rendered label.
  //
  // The scheme must be emulated BEFORE each navigation, not just before the
  // assertion. theme.svelte.ts resolves stored-or-OS ONCE at startup and stamps
  // `data-theme` on <html>, and app.css's dark block is guarded
  // `:root:not([data-theme="light"])` — so flipping the media query on a loaded page
  // changes nothing, because the stamped attribute already won. Reloading is what
  // re-runs that resolution, which is also the real path a user's OS setting takes.
  await page.emulateMedia({ colorScheme: "light" });
  await login(page);
  await page.goto("/");
  await openView(page, "Labels");

  const name = uniqueTitle("label");
  const row = await createLabel(page, name, "sky");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(row.locator(".label-info .swatch")).toHaveCSS(
    "background-color",
    "rgb(2, 132, 199)", // --label-sky, light
  );

  await page.emulateMedia({ colorScheme: "dark" });
  await page.reload();
  await openView(page, "Labels");
  const darkRow = page.locator(".label-row", { has: page.getByText(name, { exact: true }) });

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(darkRow.locator(".label-info .swatch")).toHaveCSS(
    "background-color",
    "rgb(56, 189, 248)", // --label-sky, dark — a DIFFERENT colour, which is the point
  );

  await deleteRow(darkRow);
});

test("a colour the picker cannot produce is refused by the server", async ({ page }) => {
  // The grid can only emit palette tokens, so this goes straight at the API with the
  // session cookie the browser already holds. The point is that validation lives on
  // the SERVER: the CLI and MCP write labels too, and before V62 "banana" was a valid
  // colour that rendered as a blank dot (issue #278).
  await login(page);
  await page.goto("/");

  const status = await page.evaluate(async () => {
    const boards = await fetch("/api/v1/boards").then((r) => r.json());
    const res = await fetch(`/api/v1/boards/${boards[0].id}/labels`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "e2e-banana", color: "banana" }),
    });
    return res.status;
  });

  expect(status).toBe(422);
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
