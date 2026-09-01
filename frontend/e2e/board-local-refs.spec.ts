import { expect, test } from "@playwright/test";
import {
  cardInColumn,
  cleanupE2eBoards,
  createCard,
  openFreshBoard,
  uniqueTitle,
} from "./helpers";

// Board-local references on screen (M8 V54, KAN-975).
//
// A fresh board's cards read `<KEY>-1`, `<KEY>-2`, … counting from one, instead of
// the canonical `KAN-<n>` drawn from an installation-wide sequence. The canonical
// ticket does not disappear: it becomes the `title` attribute beside the ref, so it
// stays hoverable and copyable for anyone who needs to quote a card outside its
// board.
//
// The board key itself is derived from the board's name (ADR 0020), which is what
// lets these specs assert on the *shape* of the ref rather than on a hardcoded key:
// what matters is that it is not `KAN-…` and that its number counts from one.

test.afterAll(() => cleanupE2eBoards());

test("a fresh board's cards read <KEY>-1 and <KEY>-2, not KAN-<n>", async ({ page }) => {
  await openFreshBoard(page);
  const first = uniqueTitle("first");
  const second = uniqueTitle("second");
  await createCard(page, "Todo", first);
  await createCard(page, "Todo", second);

  const firstTicket = cardInColumn(page, "Todo", first).locator(".ticket");
  const secondTicket = cardInColumn(page, "Todo", second).locator(".ticket");

  const firstText = (await firstTicket.innerText()).trim();
  const secondText = (await secondTicket.innerText()).trim();

  // Board-local: a derived key, then a number that counts from one on this board.
  expect(firstText).toMatch(/^[A-Z][A-Z0-9]{1,9}-1$/);
  expect(secondText).toMatch(/^[A-Z][A-Z0-9]{1,9}-2$/);
  // And emphatically not the canonical form, which is what this slice replaced.
  expect(firstText).not.toMatch(/^KAN-/);
});

test("the canonical ticket survives as the title attribute", async ({ page }) => {
  await openFreshBoard(page);
  const title = uniqueTitle("hoverable");
  await createCard(page, "Todo", title);

  const ticket = cardInColumn(page, "Todo", title).locator(".ticket");
  const shown = (await ticket.innerText()).trim();
  const canonical = await ticket.getAttribute("title");

  expect(canonical).toMatch(/^KAN-\d+$/);
  expect(canonical).not.toBe(shown);
});

test("the command palette finds a card by EITHER form", async ({ page }) => {
  // The palette shows the board-local ref, so it must also *match* it — otherwise
  // typing back the string on screen would find nothing. And it must keep matching
  // the canonical ticket, which is what the rest of the product accepts.
  await openFreshBoard(page);
  const title = uniqueTitle("palette");
  await createCard(page, "Todo", title);

  const ticket = cardInColumn(page, "Todo", title).locator(".ticket");
  const localRef = (await ticket.innerText()).trim();
  const canonical = (await ticket.getAttribute("title"))!;

  for (const term of [localRef, canonical]) {
    const palette = page.getByRole("dialog", { name: "Command palette" });
    await page.keyboard.press("ControlOrMeta+KeyK");
    await expect(palette).toBeVisible();

    // Step 1: pick "Move card…" — that is the step whose list searches by ticket.
    await page.keyboard.type("Move card");
    await palette.getByRole("option", { name: /Move card/ }).click();

    // Step 2: search by this form. The option's accessible name is the label, which
    // V54 changed to the board-local ref — so matching on the TITLE proves the row
    // was found by the search term rather than by whatever it happens to be called.
    await page.keyboard.type(term);
    await expect(
      palette.getByRole("option", { name: new RegExp(title) }),
      `searching for ${term}`,
    ).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();
  }
});
