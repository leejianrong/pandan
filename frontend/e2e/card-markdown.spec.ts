import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createCard,
  openFreshBoard,
  uniqueTitle,
} from "./helpers";

// U3 (KAN-318): the card modal's Description is edited as raw Markdown and
// DISPLAYED as sanitized rendered HTML (marked + DOMPurify). Because we
// {@html} user text, sanitizing is mandatory — a <script>/onerror injection
// must be stripped, never executed. Also asserts the Notes→Comments rename.
// Server-authoritative throughout (the description round-trips via PATCH).
test.afterAll(() => cleanupE2eBoards());

// Screenshots land in the harness scratchpad (outside the repo), so the run
// never dirties tracked baseline PNGs.
const SHOTS_DIR =
  "/tmp/claude-1000/-home-jian-tutorials-agentic-course-simple-kanban/6bdfc2b3-5103-4e1e-a1ff-6f4db122a6ca/scratchpad";

const MARKDOWN = [
  "# Heading",
  "",
  "Some **bold** and *italic* text with a [link](https://example.com).",
  "",
  "- first bullet",
  "- second bullet",
  "",
  "`inline code`",
  "",
  "<script>window.__pwned = true</script>",
  '<img src=x onerror="window.__pwned = true">',
].join("\n");

test("description edits raw markdown and renders sanitized; Notes is now Comments", async ({
  page,
}) => {
  await openFreshBoard(page);

  const title = uniqueTitle("md");
  await createCard(page, "Todo", title);
  const card = cardInColumn(page, "Todo", title);

  // Open the card modal.
  await card.getByRole("button", { name: "Edit" }).click();
  const form = page.locator(".card-form");
  await expect(form).toBeVisible();

  // A blank card opens straight into the raw editor. Type Markdown (incl. two
  // XSS attempts) into the textarea.
  const editor = form.locator(".desc-input");
  await expect(editor).toBeVisible();
  await editor.fill(MARKDOWN);

  // Flip to Preview: the rendered, sanitized HTML appears.
  await form.getByRole("button", { name: "Preview" }).click();
  const rendered = form.locator(".desc-rendered");
  await expect(rendered).toBeVisible();

  // Markdown constructs render as real elements.
  await expect(rendered.locator("strong")).toHaveText("bold");
  await expect(rendered.locator("em")).toHaveText("italic");
  await expect(rendered.locator("h1")).toHaveText("Heading");
  await expect(rendered.locator("li")).toHaveCount(2);
  await expect(rendered.locator("code")).toHaveText("inline code");

  // The link is kept, made safe (http(s) scheme, isolated new tab).
  const link = rendered.locator("a");
  await expect(link).toHaveAttribute("href", "https://example.com");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await expect(link).toHaveAttribute("target", "_blank");

  // XSS stripped: no <script>/<img> survived sanitization, and nothing ran.
  await expect(rendered.locator("script")).toHaveCount(0);
  await expect(rendered.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __pwned?: boolean }).__pwned)).toBeUndefined();

  // The renamed thread: "Comments", not "Notes & activity".
  await expect(form.getByText("Comments", { exact: true })).toBeVisible();
  await expect(form.getByPlaceholder("Add a comment…")).toBeVisible();
  await expect(form.getByText("No comments yet.")).toBeVisible();

  // Persist (PATCH) and reopen: the description survives and re-opens in the
  // rendered preview (server-authoritative — no optimistic UI).
  await form.getByRole("button", { name: "Save changes" }).click();
  await expect(form).toHaveCount(0);

  await cardInColumn(page, "Todo", title).getByRole("button", { name: "Edit" }).click();
  await expect(form).toBeVisible();
  await expect(form.locator(".desc-rendered strong")).toHaveText("bold");
  await expect(form.locator(".desc-rendered script")).toHaveCount(0);
});

// Visual card: capture the raw-edit and rendered-preview states in light + dark.
test("visual: markdown edit + preview, light and dark", async ({ page }) => {
  await openFreshBoard(page);

  const title = uniqueTitle("md-visual");
  await createCard(page, "Todo", title);
  const card = cardInColumn(page, "Todo", title);
  await card.getByRole("button", { name: "Edit" }).click();
  const form = page.locator(".card-form");
  await expect(form).toBeVisible();
  await form.locator(".desc-input").fill(MARKDOWN);

  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => localStorage.setItem("kanban.theme", t), theme);
    // Re-apply theme live without a reload (which would close the modal).
    await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);

    // Raw-edit state.
    await form.getByRole("button", { name: "Edit", exact: true }).click();
    await expect(form.locator(".desc-input")).toBeVisible();
    await page.screenshot({ path: `${SHOTS_DIR}/u3-markdown-edit-${theme}.png` });

    // Rendered-preview state.
    await form.getByRole("button", { name: "Preview" }).click();
    await expect(form.locator(".desc-rendered")).toBeVisible();
    await expect(form.getByText("Comments", { exact: true })).toBeVisible();
    await page.screenshot({ path: `${SHOTS_DIR}/u3-markdown-preview-${theme}.png` });
  }
});
