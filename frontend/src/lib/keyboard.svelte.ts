// Keyboard navigation for the board (V36, KAN-300).
//
// A tiny controller shared across the board tree. It owns the "focused card"
// model (a card id, kept in sync with real DOM focus) plus a one-shot signal that
// lets the global key handler start a column's "add card" form (Column.svelte)
// without prop-drilling. Opening/editing a focused card is handled by the card's
// own onkeydown (an existing, accessible role=button affordance we build on).
//
// Everything here is client-only presentation state. Actual mutations (move /
// create) still go through the server-authoritative store actions in
// board.svelte.ts, which refetch() — no optimistic UI (BREADBOARD §7).

import { tick } from "svelte";
import { COLUMNS, cardsFor, moveCard, viewStore } from "./board.svelte";
import type { Column } from "./api";

export const kbd = $state<{
  // The board card the keyboard currently acts on. Set by Card's onfocus (so it
  // tracks Tab / click focus too) and by nav below. Null = nothing focused.
  focusedCardId: number | null;
  // Whether the '?' help overlay is open.
  helpOpen: boolean;
  // One-shot signal consumed (and reset to null) by the matching Column, which
  // opens its "add card" form.
  addToColumn: Column | null;
}>({
  focusedCardId: null,
  helpOpen: false,
  addToColumn: null,
});

// --- the "don't hijack typing" guard ------------------------------------
// Single-key shortcuts must fire ONLY when the user isn't typing into a field
// and no dialog/overlay is open. A regression here breaks typing in every form.
function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable ||
    el.closest("[contenteditable='true']") != null
  );
}

// Any Modal-based overlay (card/epic detail, command palette, our own help)
// portals a `.modal-backdrop` to <body> and Bits UI menus/selects render a
// `[data-bits-*]` popper. If one is present we're inside an overlay and must not
// steal its keys. (The help overlay is handled separately, before this check.)
function overlayOpen(): boolean {
  return (
    document.querySelector(
      ".modal-backdrop, [data-bits-floating-content-wrapper], [role='listbox']",
    ) != null
  );
}

// --- focus model --------------------------------------------------------
// The flat, visual order of cards: column by column, position within column.
function orderedColumns(): { key: Column; ids: number[] }[] {
  return COLUMNS.map((c) => ({ key: c.key, ids: cardsFor(c.key).map((k) => k.id) }));
}

function locate(
  id: number | null,
): { col: number; row: number } | null {
  if (id == null) return null;
  const cols = orderedColumns();
  for (let c = 0; c < cols.length; c++) {
    const r = cols[c].ids.indexOf(id);
    if (r >= 0) return { col: c, row: r };
  }
  return null;
}

// Move DOM focus (and the model) to a card by id, after the DOM settles.
async function focusCard(id: number | null): Promise<void> {
  if (id == null) return;
  kbd.focusedCardId = id;
  await tick();
  const el = document.querySelector<HTMLElement>(`.board [data-card-id="${id}"]`);
  el?.focus();
  el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// The first card in the first non-empty column (used to seed focus).
function firstCardId(): number | null {
  for (const col of orderedColumns()) if (col.ids.length > 0) return col.ids[0];
  return null;
}

// Vertical move within a column (dir -1 up / +1 down).
function moveWithinColumn(dir: number): void {
  const cols = orderedColumns();
  const here = locate(kbd.focusedCardId);
  if (!here) return void focusCard(firstCardId());
  const ids = cols[here.col].ids;
  const next = Math.min(Math.max(here.row + dir, 0), ids.length - 1);
  void focusCard(ids[next]);
}

// Horizontal move between columns (dir -1 left / +1 right), keeping the row
// index where possible; falls back to the nearest non-empty column in `dir`.
function moveAcrossColumns(dir: number): void {
  const cols = orderedColumns();
  const here = locate(kbd.focusedCardId);
  if (!here) return void focusCard(firstCardId());
  for (let c = here.col + dir; c >= 0 && c < cols.length; c += dir) {
    const ids = cols[c].ids;
    if (ids.length > 0) {
      void focusCard(ids[Math.min(here.row, ids.length - 1)]);
      return;
    }
  }
}

// Move the focused card to the adjacent column (server-authoritative). Keep it
// focused across the refetch so the user can keep driving with the keyboard.
async function moveCardToAdjacentColumn(dir: number): Promise<void> {
  const here = locate(kbd.focusedCardId);
  if (!here) return;
  const target = here.col + dir;
  if (target < 0 || target >= COLUMNS.length) return;
  const id = kbd.focusedCardId!;
  await moveCard(id, { column: COLUMNS[target].key });
  await focusCard(id);
}

// Start "add card" in the focused card's column, else the first column.
function startCreate(): void {
  const here = locate(kbd.focusedCardId);
  kbd.addToColumn = here ? COLUMNS[here.col].key : COLUMNS[0].key;
}

// The global board key handler. Wired to <svelte:window> in Board.svelte, so it
// is only live while the board view is mounted. ⌘K (App.svelte) and other
// Cmd/Ctrl chords are never ours — we bail on modifier chords immediately.
export function handleBoardKeydown(e: KeyboardEvent): void {
  if (e.metaKey || e.ctrlKey || e.altKey) return; // chords (⌘K etc.) belong elsewhere

  // Help overlay is modal: while it's open only '?'/Esc (Esc via Modal) act, and
  // nothing else on the board is touched. Toggle it closed on '?'.
  if (kbd.helpOpen) {
    if (e.key === "?") {
      e.preventDefault();
      kbd.helpOpen = false;
    }
    return;
  }

  if (isTypingTarget(e.target)) return; // never hijack typing
  if (overlayOpen()) return; // a card modal / palette / menu owns the keys

  if (e.key === "?") {
    e.preventDefault();
    kbd.helpOpen = true;
    return;
  }

  // Card navigation only makes sense in the board (not table) presentation.
  if (viewStore.mode !== "board") return;

  switch (e.key) {
    case "ArrowDown":
    case "j":
      e.preventDefault();
      moveWithinColumn(+1);
      break;
    case "ArrowUp":
    case "k":
      e.preventDefault();
      moveWithinColumn(-1);
      break;
    case "ArrowRight":
    case "l":
      e.preventDefault();
      if (e.shiftKey) void moveCardToAdjacentColumn(+1);
      else moveAcrossColumns(+1);
      break;
    case "ArrowLeft":
    case "h":
      e.preventDefault();
      if (e.shiftKey) void moveCardToAdjacentColumn(-1);
      else moveAcrossColumns(-1);
      break;
    case "n":
    case "c":
      e.preventDefault();
      startCreate();
      break;
    // Enter / Space / o / e (open + edit) are handled by the focused Card itself
    // (Card.svelte's own onkeydown) — a focused role=button opening on Enter is an
    // existing, accessible affordance we build on rather than duplicate here.
  }
}
