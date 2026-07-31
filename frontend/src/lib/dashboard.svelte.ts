// Awareness dashboard state as Svelte 5 runes (M5 V16, KAN-249) — "mission
// control" for a human watching their agent fleet. Read-first: it composes the
// board's in-flight work, the needs-human handoffs, derived flow metrics, and the
// deepened activity feed, reloading on demand / on board switch (poll-refresh, no
// websockets — ADR 0007). Server state is authoritative: this store only reads
// (via the existing /api/v1 endpoints) and never mutates.

import {
  getBoardMetrics,
  getCycleMetrics,
  listActivity,
  listCards,
  listCycles,
  type Activity,
  type BoardMetrics,
  type Card,
  type Cycle,
  type CycleMetrics,
} from "./api";
import { boardStore } from "./board.svelte";

// Reporting windows the strip/charts scope to. `""` = all time (omit the param).
export type DashboardWindow = "24h" | "7d" | "30d" | "";
export const WINDOW_OPTIONS: { value: DashboardWindow; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "", label: "All time" },
];

const ACTIVITY_PAGE = 20;

export const dashboardStore = $state<{
  // "What are my agents doing right now" — cards currently in_progress.
  inflight: Card[];
  // Cards an agent flagged needs_human (V13), with their attention_note.
  attention: Card[];
  // Derived flow metrics (throughput / cycle time / aging / per-assignee, V17).
  metrics: BoardMetrics | null;
  // The board's cycles (iterations) + the selected one's burndown/velocity (V34).
  cycles: Cycle[];
  activeCycleId: number | null;
  cycleMetrics: CycleMetrics | null;
  // The deepened activity feed (filterable by actor/action), keyset-paginated.
  activity: Activity[];
  activityCursor: string | null;
  // Active activity filters (empty = unfiltered). Applied server-side.
  actorFilter: string;
  actionFilter: string;
  // Reporting window for the metrics strip + charts.
  window: DashboardWindow;
  loading: boolean;
  activityLoading: boolean;
  error: string | null;
}>({
  inflight: [],
  attention: [],
  metrics: null,
  cycles: [],
  activeCycleId: null,
  cycleMetrics: null,
  activity: [],
  activityCursor: null,
  actorFilter: "",
  actionFilter: "",
  window: "7d",
  loading: false,
  activityLoading: false,
  error: null,
});

// (Re)load every panel for the active board in parallel. Called on mount, on board
// switch, on window change, and by the Refresh affordance.
export async function refetchDashboard(): Promise<void> {
  const boardId = boardStore.activeBoardId;
  dashboardStore.error = null;
  if (boardId == null) {
    dashboardStore.inflight = [];
    dashboardStore.attention = [];
    dashboardStore.metrics = null;
    dashboardStore.cycles = [];
    dashboardStore.activeCycleId = null;
    dashboardStore.cycleMetrics = null;
    dashboardStore.activity = [];
    dashboardStore.activityCursor = null;
    return;
  }
  dashboardStore.loading = true;
  try {
    const [inflight, attention, metrics, cycles, activityPage] = await Promise.all([
      listCards(boardId, { column: "in_progress" }),
      listCards(boardId, { needs_human: true }),
      getBoardMetrics(boardId, dashboardStore.window ? { window: dashboardStore.window } : {}),
      listCycles(boardId),
      listActivity(boardId, {
        limit: ACTIVITY_PAGE,
        actor: dashboardStore.actorFilter || undefined,
        action: dashboardStore.actionFilter || undefined,
      }),
    ]);
    dashboardStore.inflight = inflight;
    dashboardStore.attention = attention;
    dashboardStore.metrics = metrics;
    dashboardStore.cycles = cycles;
    dashboardStore.activity = activityPage.entries;
    dashboardStore.activityCursor = activityPage.nextCursor;

    // Keep the current selection if it still exists; else pick the "active"
    // cycle (its window contains now) or the most recent one.
    const stillValid = cycles.some((c) => c.id === dashboardStore.activeCycleId);
    dashboardStore.activeCycleId = stillValid
      ? dashboardStore.activeCycleId
      : pickActiveCycle(cycles);
    await refetchCycleMetrics();
  } catch (e) {
    dashboardStore.error = e instanceof Error ? e.message : "Failed to load dashboard";
  } finally {
    dashboardStore.loading = false;
  }
}

// The "active" cycle: one whose [starts_on, ends_on] window contains now; else
// the most recently created cycle; else none. Bounds may be null (open-ended).
function pickActiveCycle(cycles: Cycle[]): number | null {
  if (cycles.length === 0) return null;
  const now = Date.now();
  const current = cycles.find((c) => {
    const startsOk = !c.starts_on || new Date(c.starts_on).getTime() <= now;
    const endsOk = !c.ends_on || new Date(c.ends_on).getTime() >= now;
    return (c.starts_on || c.ends_on) && startsOk && endsOk;
  });
  if (current) return current.id;
  return [...cycles].sort((a, b) => b.id - a.id)[0].id;
}

// Load the selected cycle's burndown/velocity (or clear it when none selected).
export async function refetchCycleMetrics(): Promise<void> {
  const boardId = boardStore.activeBoardId;
  const cycleId = dashboardStore.activeCycleId;
  if (boardId == null || cycleId == null) {
    dashboardStore.cycleMetrics = null;
    return;
  }
  dashboardStore.cycleMetrics = await getCycleMetrics(boardId, cycleId);
}

// Change the selected cycle and reload just its metrics.
export async function setActiveCycle(cycleId: number | null): Promise<void> {
  dashboardStore.activeCycleId = cycleId;
  try {
    await refetchCycleMetrics();
  } catch (e) {
    dashboardStore.error = e instanceof Error ? e.message : "Failed to load cycle metrics";
  }
}

// Reload only the activity feed (used when the actor/action filter changes, so the
// heavier metrics/inflight queries don't re-run needlessly).
export async function refetchDashboardActivity(): Promise<void> {
  const boardId = boardStore.activeBoardId;
  if (boardId == null) return;
  dashboardStore.activityLoading = true;
  dashboardStore.error = null;
  try {
    const page = await listActivity(boardId, {
      limit: ACTIVITY_PAGE,
      actor: dashboardStore.actorFilter || undefined,
      action: dashboardStore.actionFilter || undefined,
    });
    dashboardStore.activity = page.entries;
    dashboardStore.activityCursor = page.nextCursor;
  } catch (e) {
    dashboardStore.error = e instanceof Error ? e.message : "Failed to load activity";
  } finally {
    dashboardStore.activityLoading = false;
  }
}

// Append the next (older) page of activity, following the keyset cursor.
export async function loadMoreDashboardActivity(): Promise<void> {
  const boardId = boardStore.activeBoardId;
  if (boardId == null || dashboardStore.activityCursor == null || dashboardStore.activityLoading)
    return;
  dashboardStore.activityLoading = true;
  try {
    const page = await listActivity(boardId, {
      limit: ACTIVITY_PAGE,
      cursor: dashboardStore.activityCursor,
      actor: dashboardStore.actorFilter || undefined,
      action: dashboardStore.actionFilter || undefined,
    });
    dashboardStore.activity = [...dashboardStore.activity, ...page.entries];
    dashboardStore.activityCursor = page.nextCursor;
  } catch (e) {
    dashboardStore.error = e instanceof Error ? e.message : "Failed to load activity";
  } finally {
    dashboardStore.activityLoading = false;
  }
}

export async function setDashboardWindow(window: DashboardWindow): Promise<void> {
  dashboardStore.window = window;
  await refetchDashboard();
}

export async function setActivityFilters(actor: string, action: string): Promise<void> {
  dashboardStore.actorFilter = actor;
  dashboardStore.actionFilter = action;
  await refetchDashboardActivity();
}

// In-flight cards grouped by assignee (unassigned bucketed under null), each bucket
// sorted by ticket for a stable render. The "what is each agent doing now" view.
export function inflightByAssignee(): { assignee: string | null; cards: Card[] }[] {
  const groups = new Map<string | null, Card[]>();
  for (const card of dashboardStore.inflight) {
    const key = card.assignee ?? null;
    const bucket = groups.get(key);
    if (bucket) bucket.push(card);
    else groups.set(key, [card]);
  }
  return [...groups.entries()]
    .map(([assignee, cards]) => ({
      assignee,
      cards: [...cards].sort((a, b) => a.ticket_number.localeCompare(b.ticket_number)),
    }))
    .sort((a, b) => {
      // Named assignees first (alphabetical), unassigned last.
      if (a.assignee == null) return 1;
      if (b.assignee == null) return -1;
      return a.assignee.localeCompare(b.assignee);
    });
}
