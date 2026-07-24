// Notification-inbox state as Svelte 5 runes (V39, KAN-303; wiring the V37 read
// API). Notifications are user-scoped (not board-scoped), so they live in their own
// store — like tokens.svelte.ts. Poll/pull only (ADR 0007): a 60s interval refetches
// the list so the top-bar badge stays fresh with no websockets. Server state is
// authoritative — every mark-read refetches rather than mutating the row in place,
// matching the board's no-optimistic-UI convention.

import {
  listNotifications,
  markNotificationRead as apiMarkNotificationRead,
  type Notification,
} from "./api";

// How often the badge/list poll the server while a user is logged in.
const POLL_INTERVAL_MS = 60_000;

export type NotificationFilter = "all" | "unread";

export const notificationStore = $state<{
  items: Notification[];
  loading: boolean;
  error: string | null;
  // Which slice the popover shows. Drives the `?unread=true` server-side filter, so
  // switching refetches (API-first — the network reflects the filter).
  filter: NotificationFilter;
  // True once the first fetch has resolved, so the panel can tell "empty inbox" from
  // "not loaded yet".
  loaded: boolean;
}>({ items: [], loading: false, error: null, filter: "all", loaded: false });

// The unread count for the top-bar badge. Derived from the loaded list rather than a
// second request: with no pagination the list holds every row for the active filter,
// so counting nulls is exact in both the "all" and "unread" views.
export function unreadCount(): number {
  return notificationStore.items.filter((n) => n.read_at === null).length;
}

// (Re)load the list for the current filter, replacing what's shown. Safe to call on
// every poll tick, on open, and after a mutation.
export async function refetchNotifications(): Promise<void> {
  notificationStore.loading = true;
  notificationStore.error = null;
  try {
    notificationStore.items = await listNotifications({
      unread: notificationStore.filter === "unread",
    });
    notificationStore.loaded = true;
  } catch (e) {
    notificationStore.error =
      e instanceof Error ? e.message : "Failed to load notifications";
  } finally {
    notificationStore.loading = false;
  }
}

// Switch the All/Unread filter and refetch (no-op if unchanged).
export async function setNotificationFilter(filter: NotificationFilter): Promise<void> {
  if (notificationStore.filter === filter) return;
  notificationStore.filter = filter;
  await refetchNotifications();
}

// Mark one notification read, then refetch (server-authoritative). In the "unread"
// view the row drops out; in "all" it dims — both fall out of the refetch.
export async function markRead(id: number): Promise<void> {
  await apiMarkNotificationRead(id);
  await refetchNotifications();
}

// Mark every currently-loaded unread notification read, then refetch. With no
// pagination the loaded list is the whole inbox, so this clears all unread.
export async function markAllRead(): Promise<void> {
  const unread = notificationStore.items.filter((n) => n.read_at === null);
  if (unread.length === 0) return;
  await Promise.all(unread.map((n) => apiMarkNotificationRead(n.id)));
  await refetchNotifications();
}

// --- Polling lifecycle -------------------------------------------------------
// A single shared interval, started when a user logs in (App.svelte) and stopped on
// logout/unmount so it never leaks or double-fires.
let pollTimer: ReturnType<typeof setInterval> | undefined;

export function startNotificationPolling(intervalMs: number = POLL_INTERVAL_MS): void {
  stopNotificationPolling();
  void refetchNotifications();
  pollTimer = setInterval(() => void refetchNotifications(), intervalMs);
}

export function stopNotificationPolling(): void {
  if (pollTimer !== undefined) {
    clearInterval(pollTimer);
    pollTimer = undefined;
  }
  // Reset so a fresh login doesn't briefly show a stale badge from the last session.
  notificationStore.items = [];
  notificationStore.loaded = false;
  notificationStore.filter = "all";
}
