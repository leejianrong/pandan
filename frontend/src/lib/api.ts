// Thin typed fetch wrapper over the versioned API (SHAPING §Frontend components).
// The UI performs no action the API can't (R4.1). Throws on non-2xx.
//
// All calls go through the canonical /api/v1 prefix (P3, milestone-2 V2). The
// backend also serves a temporary /api alias, but the SPA rides the versioned path.
const API = "/api/v1";

export type Column = "todo" | "in_progress" | "done";

// Card priority (M5 V11, KAN-244). Must stay in sync with the backend's
// VALID_PRIORITIES / ck_card_priority (models) and PriorityEnum (schemas) — the
// three-places rule. "none" is the default (an unranked card).
export type Priority = "none" | "low" | "medium" | "high" | "urgent";

export interface Card {
  id: number;
  ticket_number: string;
  board_id: number;
  title: string;
  description: string | null;
  column: Column;
  position: number;
  story_points: number | null;
  assignee: string | null;
  epic_id: number | null;
  // Card fields (M5 V11, KAN-244): priority, optional due date (ISO string or
  // null), and the board-scoped labels attached to this card.
  priority: Priority;
  due_date: string | null;
  labels: Label[];
  // Needs-human handoff (M5 V13, KAN-246): `needs_human` is true when an agent
  // flagged the card for a human; `attention_note` is the optional ask it left.
  needs_human: boolean;
  attention_note: string | null;
  // Card-to-card dependencies (KAN-28/KAN-30): ids of cards that block this one
  // (blocked_by) and ids of cards this one blocks (blocks). `blocked` is the
  // derived signal — true when >=1 blocker is not yet done (KAN-29).
  blocked_by: number[];
  blocks: number[];
  blocked: boolean;
  // Work-links (KAN-32/KAN-34): PR / branch / CI URLs, inlined on every card read.
  links: CardLink[];
  created_at: string;
  updated_at: string;
}

// A board-scoped, colored label a card can carry (M5 V11, KAN-244).
export interface Label {
  id: number;
  board_id: number;
  name: string;
  color: string;
  created_at: string;
}

// A work-link on a card (KAN-32): a label (e.g. "PR", "branch", "CI") + a url.
export interface CardLink {
  id: number;
  label: string;
  url: string;
  created_at: string;
}

// A note/comment on a card (KAN-33): a body authored by a user. Not inlined on
// card reads — fetched on demand via listComments. `author_id` is null once the
// authoring user is deleted (SET NULL).
export interface Comment {
  id: number;
  body: string;
  author_id: string | null;
  created_at: string;
}

export interface CardCreate {
  title: string;
  description?: string | null;
  column?: Column;
  story_points?: number | null;
  assignee?: string | null;
  epic_id?: number | null;
  board_id?: number;
  // M5 V11: priority (default "none"), optional due date, and the label ids to
  // attach (each must belong to the card's board).
  priority?: Priority;
  due_date?: string | null;
  label_ids?: number[];
}

// Field edits only — no column (moving is done via /move, not PATCH).
// `epic_id` re-links the story to a different epic (or null to clear).
// `label_ids` *replaces* the card's label set ([] clears it; omit to leave it).
export interface CardUpdate {
  title?: string;
  description?: string | null;
  story_points?: number | null;
  assignee?: string | null;
  epic_id?: number | null;
  priority?: Priority;
  due_date?: string | null;
  label_ids?: number[];
}

// Derived per-epic health signal (V32, KAN-296) — computed server-side from the
// epic's target_date vs. remaining child work; null when the epic has no target_date.
export type EpicHealth = "on_track" | "at_risk" | "overdue";

// Derived rollup over an epic's non-deleted child cards (V32, KAN-296).
export interface EpicProgress {
  total: number;
  done: number;
  percent: number; // 0–100
}

// An epic is a grouping a story can belong to (ADR 0009), scoped to a board (V7).
export interface Epic {
  id: number;
  ticket_number: string;
  board_id: number;
  name: string;
  description: string | null;
  // Lightweight project fields (V31, KAN-295) — optional target/ship date + lead.
  target_date: string | null;
  lead: string | null;
  // Derived, server-authoritative (V32, KAN-296): progress rollup + health signal.
  progress: EpicProgress;
  health: EpicHealth | null;
  created_at: string;
  updated_at: string;
}

export interface EpicCreate {
  name: string;
  description?: string | null;
  board_id?: number;
}

// A board owns a set of cards + epics (M3 V7). owner_id is a user UUID or null.
export interface Board {
  id: number;
  name: string;
  owner_id: string | null;
  // The caller's effective role on this board (KAN-15): "owner" if they own it,
  // else their membership role. Drives the switcher's shared-board badge.
  role?: Role | null;
  created_at: string;
  updated_at: string;
}

export interface BoardCreate {
  name: string;
}

export interface BoardUpdate {
  name?: string;
}

export interface EpicUpdate {
  name?: string;
  description?: string | null;
}

export interface CardMove {
  column: Column;
  position?: number | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (body?.detail) return JSON.stringify(body.detail);
  } catch {
    /* fall through */
  }
  return `Request failed (${res.status})`;
}

// The structured filter+sort grammar (M5 V14, KAN-247), shared by GET /cards and
// saved views. Every field is optional and matches a GET /cards query param, so a
// saved view's stored `query` replays verbatim. `sort` is a comma-separated list
// of keys, '-' prefix = descending (e.g. "-priority,position").
export interface CardQuery {
  column?: Column;
  epic_id?: number;
  priority?: Priority;
  label?: number;
  due_before?: string;
  overdue?: boolean;
  needs_human?: boolean;
  assignee?: string;
  // Free-text full-text search over title+description (M5 V15, KAN-248). Empty is a
  // no-op server-side; `cardQueryParams` already drops empty strings.
  q?: string;
  sort?: string;
}

// Serialize a CardQuery into query params, skipping unset/empty values.
function cardQueryParams(query?: CardQuery): URLSearchParams {
  const qs = new URLSearchParams();
  if (!query) return qs;
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    qs.set(key, String(value));
  }
  return qs;
}

export async function listCards(boardId?: number, query?: CardQuery): Promise<Card[]> {
  const qs = cardQueryParams(query);
  if (boardId != null) qs.set("board_id", String(boardId));
  const suffix = qs.toString() ? `?${qs}` : "";
  const res = await fetch(`${API}/cards${suffix}`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function createCard(payload: CardCreate): Promise<Card> {
  const res = await fetch(`${API}/cards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function updateCard(id: number, payload: CardUpdate): Promise<Card> {
  const res = await fetch(`${API}/cards/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function moveCard(id: number, payload: CardMove): Promise<Card> {
  const res = await fetch(`${API}/cards/${id}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function deleteCard(id: number): Promise<void> {
  const res = await fetch(`${API}/cards/${id}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Trash & restore (KAN-20) ----------------------------------------------
// Soft-deleted (KAN-19) cards/epics can be listed, restored (un-tombstoned), or
// purged (permanent hard-delete). `deleted_at` is exposed only on these trash
// listings — the normal Card/Epic reads stay unchanged.

export interface TrashCard extends Card {
  deleted_at: string;
}

export interface TrashEpic extends Epic {
  deleted_at: string;
}

export async function listTrashCards(boardId?: number): Promise<TrashCard[]> {
  const qs = boardId != null ? `?board_id=${boardId}` : "";
  const res = await fetch(`${API}/cards/trash${qs}`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function restoreCard(id: number): Promise<Card> {
  const res = await fetch(`${API}/cards/${id}/restore`, { method: "POST" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function purgeCard(id: number): Promise<void> {
  const res = await fetch(`${API}/cards/${id}/purge`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

export async function listTrashEpics(boardId?: number): Promise<TrashEpic[]> {
  const qs = boardId != null ? `?board_id=${boardId}` : "";
  const res = await fetch(`${API}/epics/trash${qs}`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function restoreEpic(id: number): Promise<Epic> {
  const res = await fetch(`${API}/epics/${id}/restore`, { method: "POST" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function purgeEpic(id: number): Promise<void> {
  const res = await fetch(`${API}/epics/${id}/purge`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Card dependencies (KAN-28 API, surfaced in the UI by KAN-30) -----------
// `addDependency(cardId, blockerId)` records that `cardId` is blocked-by
// `blockerId`; `removeDependency` clears that edge. Both return the (refreshed)
// blocked card. The server enforces same-board / no-self / no-dup / no-cycle
// (422) and owner-gating — surfaced via ApiError like every other call.

export async function addDependency(cardId: number, blockerId: number): Promise<Card> {
  const res = await fetch(`${API}/cards/${cardId}/dependencies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocker_id: blockerId }),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function removeDependency(cardId: number, blockerId: number): Promise<Card> {
  const res = await fetch(`${API}/cards/${cardId}/dependencies/${blockerId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

// --- Card work-links (KAN-32 API, surfaced in the UI by KAN-34) -------------
// `addLink` attaches a label+url to a card; `removeLink` detaches one by id. Both
// return the (refreshed) card with its `links` array. Owner-gated like every call.

export async function addLink(cardId: number, label: string, url: string): Promise<Card> {
  const res = await fetch(`${API}/cards/${cardId}/links`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, url }),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function removeLink(cardId: number, linkId: number): Promise<Card> {
  const res = await fetch(`${API}/cards/${cardId}/links/${linkId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

// --- Card notes / comments (KAN-33 API, surfaced in the UI by KAN-34) --------
// Comments are a thread, so unlike links they aren't inlined on card reads —
// `listComments` fetches them on demand (oldest-first). `addComment` posts one
// (author is the session user); `deleteComment` removes your own (403 otherwise).

export async function listComments(cardId: number): Promise<Comment[]> {
  const res = await fetch(`${API}/cards/${cardId}/comments`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function addComment(cardId: number, body: string): Promise<Comment> {
  const res = await fetch(`${API}/cards/${cardId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function deleteComment(cardId: number, commentId: number): Promise<void> {
  const res = await fetch(`${API}/cards/${cardId}/comments/${commentId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Needs-human handoff (M5 V13, KAN-246) ---------------------------------
// An agent flags a card as needing a human (with an optional note); a human
// clears it. Both return the refreshed card; the resolution channel for the agent
// is the card's comments. Server-authoritative like every mutation (refetch after).

export async function needsHuman(cardId: number, attentionNote?: string | null): Promise<Card> {
  const res = await fetch(`${API}/cards/${cardId}/needs-human`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ attention_note: attentionNote ?? null }),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function resolveCard(cardId: number): Promise<Card> {
  const res = await fetch(`${API}/cards/${cardId}/resolve`, { method: "POST" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function listEpics(boardId?: number): Promise<Epic[]> {
  const qs = boardId != null ? `?board_id=${boardId}` : "";
  const res = await fetch(`${API}/epics${qs}`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function createEpic(payload: EpicCreate): Promise<Epic> {
  const res = await fetch(`${API}/epics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function updateEpic(id: number, payload: EpicUpdate): Promise<Epic> {
  const res = await fetch(`${API}/epics/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function deleteEpic(id: number): Promise<void> {
  const res = await fetch(`${API}/epics/${id}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Board labels (M5 V11, KAN-244) ----------------------------------------
// Labels are board-scoped, colored tags. List/create are addressed by board;
// delete is addressed by the label's own id. Attach to cards via `label_ids` on
// create/update. Server-authoritative like every mutation (refetch after).

export interface LabelCreate {
  name: string;
  color: string;
}

export async function listLabels(boardId: number): Promise<Label[]> {
  const res = await fetch(`${API}/boards/${boardId}/labels`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function createLabel(boardId: number, payload: LabelCreate): Promise<Label> {
  const res = await fetch(`${API}/boards/${boardId}/labels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function deleteLabel(id: number): Promise<void> {
  const res = await fetch(`${API}/labels/${id}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Saved views (M5 V14, KAN-247) -----------------------------------------
// A named, persisted card query on a board. `query` is the CardQuery grammar;
// applying it (via listCards) reproduces the view's result set. Board-scoped;
// server-authoritative like every mutation (refetch after).

export interface SavedView {
  id: number;
  board_id: number;
  name: string;
  query: CardQuery;
  created_at: string;
}

export interface SavedViewCreate {
  name: string;
  query?: CardQuery;
}

export async function listViews(boardId: number): Promise<SavedView[]> {
  const res = await fetch(`${API}/boards/${boardId}/views`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function createView(
  boardId: number,
  payload: SavedViewCreate,
): Promise<SavedView> {
  const res = await fetch(`${API}/boards/${boardId}/views`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: payload.name, query: payload.query ?? {} }),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function deleteView(boardId: number, viewId: number): Promise<void> {
  const res = await fetch(`${API}/boards/${boardId}/views/${viewId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Boards (Milestone 3 V7, ADR 0012) -------------------------------------

export async function listBoards(): Promise<Board[]> {
  const res = await fetch(`${API}/boards`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function createBoard(payload: BoardCreate): Promise<Board> {
  const res = await fetch(`${API}/boards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function updateBoard(id: number, payload: BoardUpdate): Promise<Board> {
  const res = await fetch(`${API}/boards/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function deleteBoard(id: number): Promise<void> {
  const res = await fetch(`${API}/boards/${id}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Agent tokens (Milestone 3 V9, ADR 0014) -------------------------------
// Self-serve personal access tokens: a token acts as its owning user (inherits
// board access). The secret is returned exactly once, on create.

// A token is an observer (read: GET only) or operator (write: full access) —
// M5 V18, KAN-251. Existing tokens default to write.
export type TokenScope = "read" | "write";

export interface Token {
  id: number;
  name: string;
  token_prefix: string;
  scope: TokenScope;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

// The create response — metadata plus the raw secret (shown once, never again).
export interface TokenCreated extends Token {
  token: string;
}

export interface TokenCreate {
  name: string;
  scope?: TokenScope;
  expires_at?: string | null;
}

export async function listTokens(): Promise<Token[]> {
  const res = await fetch(`${API}/tokens`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function createToken(payload: TokenCreate): Promise<TokenCreated> {
  const res = await fetch(`${API}/tokens`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function deleteToken(id: number): Promise<void> {
  const res = await fetch(`${API}/tokens/${id}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Board members (KAN-12 API, surfaced in the UI by KAN-14) --------------
// A board can have members (users other than the owner) with a role. The
// management API is owner-gated (403 for non-owners). Members are scoped to a
// board, so every call carries the board id in its path.

export type Role = "viewer" | "editor" | "owner";

export interface Member {
  id: number;
  board_id: number;
  user_id: string;
  // The member's email, populated server-side from the user table.
  email: string | null;
  role: Role;
  created_at: string;
  updated_at: string;
}

// Add a member by email (the UI path) or user_id — exactly one. `role` defaults
// to "viewer" server-side.
export interface MemberCreate {
  email?: string;
  user_id?: string;
  role?: Role;
}

export interface MemberUpdate {
  role: Role;
}

export async function listMembers(boardId: number): Promise<Member[]> {
  const res = await fetch(`${API}/boards/${boardId}/members`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function addMember(boardId: number, payload: MemberCreate): Promise<Member> {
  const res = await fetch(`${API}/boards/${boardId}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function updateMember(
  boardId: number,
  memberId: number,
  payload: MemberUpdate,
): Promise<Member> {
  const res = await fetch(`${API}/boards/${boardId}/members/${memberId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function removeMember(boardId: number, memberId: number): Promise<void> {
  const res = await fetch(`${API}/boards/${boardId}/members/${memberId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
}

// --- Activity feed (KAN-18, reading KAN-17's write path) --------------------
// One append-only audit record per board-domain mutation. The feed is
// member-scoped (owner + members can read) and newest-first, keyset-paginated
// over the X-Next-Cursor response header exactly like GET /cards.

export type ActivityEntityType = "card" | "epic" | "board";
// Mirrors backend VALID_ACTIVITY_ACTIONS (models.py): the CRUD verbs plus V13's
// attention/resolved handoff events and KAN-239's purged (permanent destruction).
export type ActivityAction =
  | "created"
  | "updated"
  | "deleted"
  | "moved"
  | "restored"
  | "attention"
  | "resolved"
  | "purged";

export interface Activity {
  id: number;
  board_id: number;
  // The acting user (UUID), or null once that user is deleted (SET NULL).
  actor_user_id: string | null;
  // Denormalised human handle for the actor (email / assignee), survives deletion.
  actor_label: string | null;
  entity_type: ActivityEntityType;
  entity_id: number;
  action: ActivityAction;
  summary: string;
  ts: string;
}

// A page of activity plus the opaque cursor for the next (older) page, or null on
// the last page — the caller echoes it back to page through the feed.
export interface ActivityPage {
  entries: Activity[];
  nextCursor: string | null;
}

const NEXT_CURSOR_HEADER = "X-Next-Cursor";

export async function listActivity(
  boardId: number,
  // M5 V16 (KAN-249): optional `actor` (exact actor_label) + `action` filters,
  // AND-ed server-side, so the dashboard can slice the feed by who did what.
  opts: { limit?: number; cursor?: string; actor?: string; action?: string } = {},
): Promise<ActivityPage> {
  const qs = new URLSearchParams();
  if (opts.limit != null) qs.set("limit", String(opts.limit));
  if (opts.cursor != null) qs.set("cursor", opts.cursor);
  if (opts.actor) qs.set("actor", opts.actor);
  if (opts.action) qs.set("action", opts.action);
  const suffix = qs.toString() ? `?${qs}` : "";
  const res = await fetch(`${API}/boards/${boardId}/activity${suffix}`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  const entries: Activity[] = await res.json();
  return { entries, nextCursor: res.headers.get(NEXT_CURSOR_HEADER) };
}

// --- Notifications (V37 API, KAN-301; surfaced in the UI by V39, KAN-303) -----
// A per-user inbox of events a human shouldn't miss. Poll/pull only (ADR 0007) —
// no websockets; the client polls `GET /notifications`. Owner-scoped: a caller
// only ever sees their own rows. `read_at` is null while unread.

// Mirrors the backend VALID_NOTIFICATION_KINDS (models.py) — the four events a
// human shouldn't miss.
export type NotificationKind = "needs_human" | "blocked" | "ci_failed" | "assigned";

export interface Notification {
  id: number;
  // The recipient (UUID) — always the current caller on the owner-scoped list.
  user_id: string;
  board_id: number;
  // The card the event is about, or null once that card is purged (SET NULL).
  card_id: number | null;
  kind: NotificationKind;
  body: string;
  // ISO timestamp once marked read; null while unread.
  read_at: string | null;
  created_at: string;
}

// List the caller's notifications, newest-first. `unread: true` → only the unread
// ones (server-side `?unread=true`); default returns all.
export async function listNotifications(
  opts: { unread?: boolean } = {},
): Promise<Notification[]> {
  const suffix = opts.unread ? "?unread=true" : "";
  const res = await fetch(`${API}/notifications${suffix}`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

// Mark one of the caller's notifications read (idempotent server-side). Returns the
// updated row so the caller could reconcile, though the store just refetches.
export async function markNotificationRead(id: number): Promise<Notification> {
  const res = await fetch(`${API}/notifications/${id}`, { method: "PATCH" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

// --- Board metrics (M5 V17 API, surfaced in the UI by V16, KAN-249/KAN-250) --
// Derived fleet-flow metrics for a board over a period — throughput, cycle time,
// aging WIP, and a per-assignee breakdown. All computed server-side from the
// activity feed + card timestamps (no stored metric). Read-only; owner/member-gated.

export interface CycleTimeMetrics {
  count: number;
  avg_seconds: number | null;
  median_seconds: number | null;
  p90_seconds: number | null;
}

export interface AgingWipItem {
  card_id: number;
  ticket_number: string;
  assignee: string | null;
  age_seconds: number;
}

export interface AgingWipMetrics {
  count: number;
  avg_seconds: number | null;
  max_seconds: number | null;
  items: AgingWipItem[];
}

export interface AssigneeMetrics {
  assignee: string | null;
  throughput: number;
  wip: number;
}

export interface BoardMetrics {
  board_id: number;
  generated_at: string;
  since: string | null;
  until: string;
  throughput: number;
  cycle_time: CycleTimeMetrics;
  aging_wip: AgingWipMetrics;
  by_assignee: AssigneeMetrics[];
}

export async function getBoardMetrics(
  boardId: number,
  opts: { since?: string; window?: string } = {},
): Promise<BoardMetrics> {
  const qs = new URLSearchParams();
  if (opts.since) qs.set("since", opts.since);
  if (opts.window) qs.set("window", opts.window);
  const suffix = qs.toString() ? `?${qs}` : "";
  const res = await fetch(`${API}/boards/${boardId}/metrics${suffix}`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

// --- Cycles / iterations (V33 API) + cycle burndown/velocity (V34, KAN-298) --
// A cycle is a board-scoped, time-boxed iteration a story can belong to. Its
// metrics (burndown / velocity) are derived server-side from the cycle's card
// state + the activity feed (no stored metric). Read-only; owner/member-gated.

export interface Cycle {
  id: number;
  board_id: number;
  name: string;
  starts_on: string | null;
  ends_on: string | null;
  created_at: string;
}

export interface WorkTotals {
  count: number;
  points: number;
}

export interface BurndownPoint {
  date: string; // ISO calendar day (YYYY-MM-DD, UTC)
  remaining: number;
  completed: number;
  ideal: number;
}

export interface CycleMetrics {
  board_id: number;
  cycle_id: number;
  generated_at: string;
  starts_on: string | null;
  ends_on: string | null;
  committed: WorkTotals;
  completed: WorkTotals;
  velocity: number;
  unit: "points" | "count";
  burndown: BurndownPoint[];
}

export async function listCycles(boardId: number): Promise<Cycle[]> {
  const res = await fetch(`${API}/boards/${boardId}/cycles`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function getCycleMetrics(
  boardId: number,
  cycleId: number,
): Promise<CycleMetrics> {
  const res = await fetch(`${API}/boards/${boardId}/cycles/${cycleId}/metrics`);
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

// --- Auth (Milestone 3 V6, ADR 0011) ---------------------------------------
// The fastapi-users auth + identity routes live at the origin root (/auth,
// /users), NOT under /api/v1 — they're session plumbing, so no API prefix.

export interface CurrentUser {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
}

// The signed-in user, or null when logged out (401). The app-shell auth check.
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const res = await fetch("/users/me");
  if (res.status === 401) return null;
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json();
}

export async function logout(): Promise<void> {
  const res = await fetch("/auth/logout", { method: "POST" });
  // 204 on success; 401 means the session was already gone — both are "logged out".
  if (!res.ok && res.status !== 401) throw new ApiError(res.status, await parseError(res));
}

// The GitHub authorize endpoint returns JSON `{ authorization_url }` rather than a
// redirect, so we fetch it and then navigate the browser there (ADR 0011). On the
// return trip the backend sets the session cookie and redirects to `/`.
export async function startGitHubLogin(): Promise<void> {
  const res = await fetch("/auth/github/authorize");
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  const { authorization_url } = await res.json();
  window.location.href = authorization_url;
}
