// Board state as Svelte 5 runes (SHAPING §Board state).
// After every mutation we refetch GET /api/cards; the server state is
// authoritative — no optimistic UI (BREADBOARD §7).

import {
  addDependency,
  addLink,
  createBoard,
  createCard,
  createEpic,
  createLabel,
  createView,
  deleteBoard,
  deleteCard,
  deleteEpic,
  deleteLabel,
  deleteView,
  listBoards,
  listCards,
  listEpics,
  listLabels,
  listViews,
  moveCard as apiMoveCard,
  removeDependency,
  removeLink,
  updateBoard,
  updateCard,
  updateEpic,
  type Board,
  type Card,
  type CardCreate,
  type CardMove,
  type CardQuery,
  type CardUpdate,
  type Column,
  type Epic,
  type EpicCreate,
  type EpicUpdate,
  type Label,
  type SavedView,
} from "./api";

export const COLUMNS: { key: Column; label: string }[] = [
  { key: "todo", label: "Todo" },
  { key: "in_progress", label: "In Progress" },
  { key: "done", label: "Done" },
];

// Boards (M3 V7). The active board scopes the card/epic views + creates. Its id is
// persisted per-browser so a reload keeps you on the same board.
export const boardStore = $state<{
  boards: Board[];
  activeBoardId: number | null;
  loading: boolean;
  error: string | null;
}>({ boards: [], activeBoardId: null, loading: false, error: null });

const ACTIVE_BOARD_KEY = "kanban.activeBoardId";

function persistActiveBoard(id: number | null): void {
  if (typeof localStorage === "undefined") return;
  if (id == null) localStorage.removeItem(ACTIVE_BOARD_KEY);
  else localStorage.setItem(ACTIVE_BOARD_KEY, String(id));
}

function readPersistedActiveBoard(): number | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem(ACTIVE_BOARD_KEY);
  return raw ? Number(raw) : null;
}

export function activeBoard(): Board | null {
  return boardStore.boards.find((b) => b.id === boardStore.activeBoardId) ?? null;
}

// Load the board list and resolve which one is active: keep the current selection
// if it still exists, else the persisted one, else the first board. Does NOT load
// cards/epics — callers pair this with refetch()/refetchEpics() (or setActiveBoard).
export async function refetchBoards(): Promise<void> {
  boardStore.loading = true;
  boardStore.error = null;
  try {
    const boards = await listBoards();
    boardStore.boards = boards;
    const ids = new Set(boards.map((b) => b.id));
    let active = boardStore.activeBoardId;
    if (active == null || !ids.has(active)) active = readPersistedActiveBoard();
    if (active == null || !ids.has(active)) active = boards[0]?.id ?? null;
    boardStore.activeBoardId = active;
    persistActiveBoard(active);
  } catch (e) {
    boardStore.error = e instanceof Error ? e.message : "Failed to load boards";
  } finally {
    boardStore.loading = false;
  }
}

// Switch the active board and load its cards + epics + labels + saved views.
// Saved views belong to a board, so switching clears the active view/query first
// (else the old board's filter would carry over to the new board's cards).
export async function setActiveBoard(id: number): Promise<void> {
  boardStore.activeBoardId = id;
  persistActiveBoard(id);
  clearActiveView();
  await Promise.all([refetch(), refetchEpics(), refetchLabels(), refetchViews()]);
}

export async function addBoard(name: string): Promise<void> {
  const created = await createBoard({ name });
  await refetchBoards();
  await setActiveBoard(created.id); // creating a board switches to it
}

export async function editBoard(id: number, name: string): Promise<void> {
  await updateBoard(id, { name });
  await refetchBoards();
}

export async function removeBoard(id: number): Promise<void> {
  await deleteBoard(id);
  // If the active board was deleted, drop the selection so refetchBoards picks a
  // new one (its cards/epics were cascade-deleted server-side).
  if (boardStore.activeBoardId === id) boardStore.activeBoardId = null;
  await refetchBoards();
  await Promise.all([refetch(), refetchEpics(), refetchLabels()]);
}

// A single reactive object; we mutate its properties (never reassign the export).
export const board = $state<{
  cards: Card[];
  loading: boolean;
  error: string | null;
}>({
  cards: [],
  loading: false,
  error: null,
});

export function cardsFor(column: Column): Card[] {
  return board.cards
    .filter((c) => c.column === column)
    .sort((a, b) => a.position - b.position);
}

// A card by id, for rendering dependency references (blocked_by / blocks) by
// their ticket number + title (KAN-30). Null if it isn't in the loaded board —
// callers fall back to a bare id.
export function cardById(id: number): Card | null {
  return board.cards.find((c) => c.id === id) ?? null;
}

// Epics live in their own store (they are not board cards — ADR 0009). Loaded
// alongside cards so both the Board (story epic-tags) and the Epics view can read
// them.
export const epicStore = $state<{
  epics: Epic[];
  loading: boolean;
  error: string | null;
}>({
  epics: [],
  loading: false,
  error: null,
});

// The epic a story belongs to (for its card-face tag), or null.
export function epicFor(id: number | null): Epic | null {
  if (id == null) return null;
  return epicStore.epics.find((e) => e.id === id) ?? null;
}

// Stories that belong to a given epic (for the Epics-view rollup).
export function cardsForEpic(epicId: number): Card[] {
  return board.cards.filter((c) => c.epic_id === epicId);
}

export async function refetch(): Promise<void> {
  board.loading = true;
  board.error = null;
  try {
    // Scope to the active board; with none selected there's nothing to show. The
    // active saved-view query (M5 V14) filters + sorts server-side — an empty
    // query means "all cards" (identical to the pre-V14 behaviour).
    board.cards =
      boardStore.activeBoardId == null
        ? []
        : await listCards(boardStore.activeBoardId, viewStore.query);
  } catch (e) {
    board.error = e instanceof Error ? e.message : "Failed to load cards";
  } finally {
    board.loading = false;
  }
}

// Card create/edit/delete can all change an epic's rollup (a new/removed child, or
// a re-linked epic_id), so refetch epics alongside cards — the Epics view's
// server-authoritative progress + health (V32, KAN-296) must not go stale.
export async function addCard(payload: CardCreate): Promise<void> {
  await createCard({ ...payload, board_id: boardStore.activeBoardId ?? undefined });
  await Promise.all([refetch(), refetchEpics()]);
}

export async function editCard(id: number, payload: CardUpdate): Promise<void> {
  await updateCard(id, payload);
  await Promise.all([refetch(), refetchEpics()]);
}

export async function removeCard(id: number): Promise<void> {
  await deleteCard(id);
  await Promise.all([refetch(), refetchEpics()]);
}

// Dependency edits (KAN-30). Like every other mutation these are
// server-authoritative: the endpoint enforces the same-board / no-cycle rules
// and we refetch() to pick up the refreshed blocked_by/blocks/blocked on every
// affected card (a blocker moving in/out of a card also flips `blocked`).
export async function addBlocker(cardId: number, blockerId: number): Promise<void> {
  await addDependency(cardId, blockerId);
  await refetch();
}

export async function removeBlocker(cardId: number, blockerId: number): Promise<void> {
  await removeDependency(cardId, blockerId);
  await refetch();
}

// Work-link edits (KAN-34). Links are inlined on every card read, so like the
// other mutations these are server-authoritative: add/remove then refetch() to
// pick up the card's refreshed `links` array.
export async function addCardLink(
  cardId: number,
  label: string,
  url: string,
): Promise<void> {
  await addLink(cardId, label, url);
  await refetch();
}

export async function removeCardLink(cardId: number, linkId: number): Promise<void> {
  await removeLink(cardId, linkId);
  await refetch();
}

export async function moveCard(id: number, payload: CardMove): Promise<void> {
  // Unlike the other mutations, a drag has already changed the board visually
  // (svelte-dnd-action reorders optimistically). So on failure we must refetch
  // to snap back to the authoritative server order, then surface the error —
  // refetch() clears board.error, so set it afterwards (BREADBOARD §7).
  try {
    await apiMoveCard(id, payload);
    // A column change flips the done-count, so refresh the epic rollups too (V32).
    await Promise.all([refetch(), refetchEpics()]);
  } catch (e) {
    await refetch();
    board.error = e instanceof Error ? e.message : "Failed to move card";
  }
}

export async function refetchEpics(): Promise<void> {
  epicStore.loading = true;
  epicStore.error = null;
  try {
    epicStore.epics =
      boardStore.activeBoardId == null ? [] : await listEpics(boardStore.activeBoardId);
  } catch (e) {
    epicStore.error = e instanceof Error ? e.message : "Failed to load epics";
  } finally {
    epicStore.loading = false;
  }
}

export async function addEpic(payload: EpicCreate): Promise<void> {
  await createEpic({ ...payload, board_id: boardStore.activeBoardId ?? undefined });
  await refetchEpics();
}

export async function editEpic(id: number, payload: EpicUpdate): Promise<void> {
  await updateEpic(id, payload);
  await refetchEpics();
}

export async function removeEpic(id: number): Promise<void> {
  await deleteEpic(id);
  // Deleting an epic detaches its stories server-side (epic_id → null), so
  // refetch cards too to drop their now-stale epic tags.
  await Promise.all([refetchEpics(), refetch()]);
}

// Labels live in their own store (M5 V11, KAN-244) — board-scoped, colored tags
// the CardForm/CardModal multi-select reads and each Card renders as chips. Loaded
// alongside cards + epics so a card's inlined `labels` and the picker stay in step.
export const labelStore = $state<{
  labels: Label[];
  loading: boolean;
  error: string | null;
}>({ labels: [], loading: false, error: null });

export async function refetchLabels(): Promise<void> {
  labelStore.loading = true;
  labelStore.error = null;
  try {
    labelStore.labels =
      boardStore.activeBoardId == null ? [] : await listLabels(boardStore.activeBoardId);
  } catch (e) {
    labelStore.error = e instanceof Error ? e.message : "Failed to load labels";
  } finally {
    labelStore.loading = false;
  }
}

// Create a label on the active board, then refetch the label list (server
// authoritative). Returns the created label so a caller can attach it immediately.
export async function addLabel(name: string, color: string): Promise<Label | null> {
  if (boardStore.activeBoardId == null) return null;
  const created = await createLabel(boardStore.activeBoardId, { name, color });
  await refetchLabels();
  return created;
}

// Delete a label board-wide; it detaches from every card server-side (cascade),
// so refetch cards too to drop the now-stale chips.
export async function removeLabel(id: number): Promise<void> {
  await deleteLabel(id);
  await Promise.all([refetchLabels(), refetch()]);
}

// Saved views + the active query (M5 V14, KAN-247). `query` is the live filter+sort
// applied to the board (empty = all cards); `activeViewId` names the saved view it
// came from (null = an ad-hoc/unsaved query). `mode` toggles the board vs. a
// sortable table over the same (filtered) cards. Server-authoritative: changing the
// query refetch()es so the board only ever shows what the server returned.
export const viewStore = $state<{
  views: SavedView[];
  activeViewId: number | null;
  query: CardQuery;
  mode: "board" | "table";
  loading: boolean;
  error: string | null;
}>({ views: [], activeViewId: null, query: {}, mode: "board", loading: false, error: null });

// Reset to the unfiltered ad-hoc query (does not refetch — callers pair it with one).
function clearActiveView(): void {
  viewStore.activeViewId = null;
  viewStore.query = {};
}

export async function refetchViews(): Promise<void> {
  viewStore.loading = true;
  viewStore.error = null;
  try {
    viewStore.views =
      boardStore.activeBoardId == null ? [] : await listViews(boardStore.activeBoardId);
  } catch (e) {
    viewStore.error = e instanceof Error ? e.message : "Failed to load views";
  } finally {
    viewStore.loading = false;
  }
}

// Activate a saved view (apply its stored query), or pass null for "All cards"
// (the unfiltered ad-hoc query). Refetches so the board reflects the server.
export async function setActiveView(id: number | null): Promise<void> {
  if (id == null) {
    clearActiveView();
  } else {
    const view = viewStore.views.find((v) => v.id === id);
    if (!view) return;
    viewStore.activeViewId = id;
    viewStore.query = { ...view.query };
  }
  await refetch();
}

// Merge an ad-hoc filter/sort change into the active query. This detaches from any
// named view (it's now an unsaved query) and refetches.
export async function setQuery(patch: Partial<CardQuery>): Promise<void> {
  const next: CardQuery = { ...viewStore.query };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined || value === null || value === "") {
      delete (next as Record<string, unknown>)[key];
    } else {
      (next as Record<string, unknown>)[key] = value;
    }
  }
  viewStore.query = next;
  viewStore.activeViewId = null;
  await refetch();
}

// Save the current ad-hoc query as a new named view, then select it.
export async function saveCurrentView(name: string): Promise<void> {
  if (boardStore.activeBoardId == null) return;
  const created = await createView(boardStore.activeBoardId, {
    name,
    query: viewStore.query,
  });
  await refetchViews();
  viewStore.activeViewId = created.id;
}

// Delete a saved view; if it was active, fall back to the unfiltered query.
export async function removeView(id: number): Promise<void> {
  if (boardStore.activeBoardId == null) return;
  await deleteView(boardStore.activeBoardId, id);
  const wasActive = viewStore.activeViewId === id;
  await refetchViews();
  if (wasActive) await setActiveView(null);
}

// Toggle the board/table presentation (client-side only — same cards).
export function setViewMode(mode: "board" | "table"): void {
  viewStore.mode = mode;
}
