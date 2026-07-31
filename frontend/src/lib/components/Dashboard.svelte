<script lang="ts">
  // Awareness dashboard — "mission control" (M5 V16, KAN-249). A read-first
  // surface for a human watching their agent fleet: what agents are doing right
  // now (in-flight-by-assignee, with PR/CI links), what needs a human (V13's
  // needs_human handoffs), derived flow metrics (V17: throughput / cycle time /
  // aging / per-assignee, rendered as a compact stat strip + inline-SVG-free CSS
  // charts, theme-aware + accessible per the dataviz conventions), and the
  // deepened, filterable activity feed. Everything is read-only and refreshes on
  // demand / on board switch (poll-refresh, no websockets — ADR 0007).
  import {
    AlertTriangle,
    ArrowLeftRight,
    ArrowRight,
    Check,
    ChevronDown,
    ChevronRight,
    Clock,
    ExternalLink,
    Flame,
    Gauge,
    History,
    Pencil,
    Plus,
    RefreshCw,
    RotateCcw,
    Table as TableIcon,
    Trash2,
    TrendingUp,
    Users,
  } from "lucide-svelte";
  import type { ActivityAction } from "../api";
  import { activeBoard, boardStore } from "../board.svelte";
  import {
    dashboardStore,
    inflightByAssignee,
    loadMoreDashboardActivity,
    refetchDashboard,
    setActiveCycle,
    setActivityFilters,
    setDashboardWindow,
    WINDOW_OPTIONS,
    type DashboardWindow,
  } from "../dashboard.svelte";
  import BoardTable from "./BoardTable.svelte";

  // Optional cross-view navigation (App passes a switch-to-board callback) so a
  // dashboard row can send the human to the board where the card lives — there's
  // no client-side router (the App toggle pattern), so this is the "link to card".
  let { navigate }: { navigate?: () => void } = $props();

  // Reload on board switch (and on mount — the component only mounts when the
  // Dashboard view is opened). Mirrors Activity.svelte / Members.svelte.
  $effect(() => {
    boardStore.activeBoardId;
    refetchDashboard();
  });

  let showTable = $state(false);

  // --- activity filter options (derived from the loaded feed) ----------------
  const ACTIONS: ActivityAction[] = ["created", "updated", "moved", "deleted", "restored"];
  const actorOptions = $derived(
    [
      ...new Set([
        ...dashboardStore.activity
          .map((a) => a.actor_label)
          .filter((x): x is string => !!x),
        ...(dashboardStore.actorFilter ? [dashboardStore.actorFilter] : []),
      ]),
    ].sort(),
  );

  function onActor(e: Event) {
    setActivityFilters((e.currentTarget as HTMLSelectElement).value, dashboardStore.actionFilter);
  }
  function onAction(e: Event) {
    setActivityFilters(dashboardStore.actorFilter, (e.currentTarget as HTMLSelectElement).value);
  }

  // --- metric derivations ----------------------------------------------------
  const assigneeRows = $derived(dashboardStore.metrics?.by_assignee ?? []);
  const assigneeMax = $derived(
    Math.max(1, ...assigneeRows.flatMap((r) => [r.throughput, r.wip])),
  );
  const agingItems = $derived(
    [...(dashboardStore.metrics?.aging_wip.items ?? [])].sort(
      (a, b) => b.age_seconds - a.age_seconds,
    ),
  );
  const agingMax = $derived(Math.max(1, ...agingItems.map((i) => i.age_seconds)));
  // Stale threshold for aging WIP: > 2 days sitting in progress (status flag, shown
  // with a label — never colour alone).
  const STALE_SECONDS = 2 * 24 * 3600;

  // --- cycle burndown / velocity (V34) ---------------------------------------
  const cycleMetrics = $derived(dashboardStore.cycleMetrics);
  const cycleUnitLabel = $derived(cycleMetrics?.unit === "count" ? "cards" : "points");
  // Committed vs completed use the metric's own unit so an unestimated cycle still
  // reads (falls back to card counts). Committed is always the larger — scale to it.
  const cycleCommitted = $derived(
    cycleMetrics
      ? cycleMetrics.unit === "count"
        ? cycleMetrics.committed.count
        : cycleMetrics.committed.points
      : 0,
  );
  const cycleCompleted = $derived(
    cycleMetrics
      ? cycleMetrics.unit === "count"
        ? cycleMetrics.completed.count
        : cycleMetrics.completed.points
      : 0,
  );
  const burndown = $derived(cycleMetrics?.burndown ?? []);
  // Scale burndown bars to the committed total (day 0's ideal), so remaining reads
  // as a fraction of the whole and the series visibly burns down.
  const burndownMax = $derived(Math.max(1, ...burndown.map((p) => p.ideal), cycleCommitted));

  function shortDay(iso: string): string {
    // iso is YYYY-MM-DD (UTC calendar day) — render as e.g. "Jul 1" without a TZ shift.
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  }

  // --- formatting helpers ----------------------------------------------------
  function fmtDuration(seconds: number | null | undefined): string {
    if (seconds == null) return "—";
    const s = Math.round(seconds);
    if (s < 60) return `${s}s`;
    const m = Math.round(s / 60);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    const remM = m % 60;
    if (h < 24) return remM ? `${h}h ${remM}m` : `${h}h`;
    const d = Math.floor(h / 24);
    const remH = h % 24;
    return remH ? `${d}d ${remH}h` : `${d}d`;
  }

  function pct(value: number, max: number): number {
    return Math.max(2, Math.round((value / max) * 100));
  }

  // Keyed by string (not just ActivityAction) so V13's attention/resolved verbs
  // also get an icon; unknown actions fall back to a blank chip.
  const ICONS: Record<string, typeof Plus> = {
    created: Plus,
    updated: Pencil,
    moved: ArrowLeftRight,
    deleted: Trash2,
    restored: RotateCcw,
    attention: AlertTriangle,
    resolved: Check,
    purged: Flame,
  };

  function actorInitial(label: string | null): string {
    return (label?.trim()?.charAt(0) ?? "?").toUpperCase();
  }
  function assigneeInitial(label: string | null): string {
    return (label?.trim()?.charAt(0) ?? "·").toUpperCase();
  }
  function relTime(iso: string): string {
    const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (secs < 45) return "just now";
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  }
  function fullTime(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  function goToBoard() {
    navigate?.();
  }
</script>

<div class="dashboard page-view">
  {#if dashboardStore.error}
    <div class="banner error" role="alert">
      <span>{dashboardStore.error}</span>
      <button onclick={refetchDashboard}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Dashboard</h2>
      <p class="page-sub">
        Mission control for <b>{activeBoard()?.name ?? "this board"}</b> — what your
        fleet is doing right now.
      </p>
    </div>
    <div class="head-controls">
      <label class="window-select">
        <span class="sr-only">Reporting window</span>
        <select
          class="rail-select"
          aria-label="Reporting window"
          value={dashboardStore.window}
          onchange={(e) =>
            setDashboardWindow((e.currentTarget as HTMLSelectElement).value as DashboardWindow)}
        >
          {#each WINDOW_OPTIONS as w (w.value)}
            <option value={w.value}>{w.label}</option>
          {/each}
        </select>
      </label>
      <button class="btn-add" onclick={refetchDashboard} disabled={dashboardStore.loading}>
        <RefreshCw size={15} /> Refresh
      </button>
    </div>
  </div>

  <!-- Stat strip: the headline numbers (dataviz: a hero-number row, not a chart). -->
  <div class="stat-strip">
    <div class="stat-tile">
      <span class="stat-icon done" aria-hidden="true"><TrendingUp size={16} /></span>
      <div class="stat-body">
        <span class="stat-value">{dashboardStore.metrics?.throughput ?? "—"}</span>
        <span class="stat-label">Completed</span>
      </div>
    </div>
    <div class="stat-tile">
      <span class="stat-icon wip" aria-hidden="true"><Gauge size={16} /></span>
      <div class="stat-body">
        <span class="stat-value">{dashboardStore.metrics?.aging_wip.count ?? dashboardStore.inflight.length}</span>
        <span class="stat-label">In progress</span>
      </div>
    </div>
    <div class="stat-tile">
      <span class="stat-icon attn" aria-hidden="true"><AlertTriangle size={16} /></span>
      <div class="stat-body">
        <span class="stat-value">{dashboardStore.attention.length}</span>
        <span class="stat-label">Needs attention</span>
      </div>
    </div>
    <div class="stat-tile">
      <span class="stat-icon cycle" aria-hidden="true"><Clock size={16} /></span>
      <div class="stat-body">
        <span class="stat-value">{fmtDuration(dashboardStore.metrics?.cycle_time.median_seconds)}</span>
        <span class="stat-label">Median cycle time</span>
      </div>
    </div>
  </div>

  <div class="panel-grid">
    <!-- In flight by assignee: what each agent is working on right now. -->
    <section class="panel" aria-labelledby="dash-inflight">
      <header class="panel-head">
        <Users size={15} aria-hidden="true" />
        <h3 id="dash-inflight">In flight by assignee</h3>
        <span class="count">{dashboardStore.inflight.length}</span>
      </header>
      {#if dashboardStore.inflight.length === 0}
        <p class="empty">Nothing in progress right now.</p>
      {:else}
        <div class="assignee-groups">
          {#each inflightByAssignee() as group (group.assignee ?? "__none__")}
            <div class="assignee-group">
              <div class="assignee-head">
                <span class="avatar-sm" aria-hidden="true">{assigneeInitial(group.assignee)}</span>
                <span class="assignee-name">{group.assignee ?? "Unassigned"}</span>
                <span class="count">{group.cards.length}</span>
              </div>
              <ul class="inflight-list">
                {#each group.cards as card (card.id)}
                  <li class="inflight-row">
                    <span class="ticket">{card.ticket_number}</span>
                    <span class="inflight-title" title={card.title}>{card.title}</span>
                    <span class="inflight-badges">
                      {#if card.needs_human}
                        <span class="mini-badge attn"><AlertTriangle size={10} /> handoff</span>
                      {/if}
                      {#if card.blocked}
                        <span class="mini-badge blocked">blocked</span>
                      {/if}
                      {#each card.links as link (link.id)}
                        <a
                          class="mini-link"
                          href={link.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="{link.label} · {link.url}"
                        >
                          <ExternalLink size={10} aria-hidden="true" />{link.label}
                        </a>
                      {/each}
                    </span>
                  </li>
                {/each}
              </ul>
            </div>
          {/each}
        </div>
      {/if}
    </section>

    <!-- Needs attention: the V13 handoff queue. -->
    <section class="panel" aria-labelledby="dash-attn">
      <header class="panel-head">
        <AlertTriangle size={15} aria-hidden="true" />
        <h3 id="dash-attn">Needs attention</h3>
        <span class="count" class:hot={dashboardStore.attention.length > 0}>
          {dashboardStore.attention.length}
        </span>
      </header>
      {#if dashboardStore.attention.length === 0}
        <p class="empty">No handoffs — your fleet isn't waiting on you.</p>
      {:else}
        <ul class="attn-list">
          {#each dashboardStore.attention as card (card.id)}
            <li class="attn-row">
              <div class="attn-top">
                <span class="ticket">{card.ticket_number}</span>
                <span class="attn-title" title={card.title}>{card.title}</span>
                {#if navigate}
                  <button class="row-link" onclick={goToBoard} title="Open on the board">
                    View <ArrowRight size={12} />
                  </button>
                {/if}
              </div>
              {#if card.attention_note}
                <p class="attn-note">{card.attention_note}</p>
              {/if}
              <p class="attn-meta">
                {#if card.assignee}<span>{card.assignee}</span>{/if}
                {#each card.links as link (link.id)}
                  <a class="mini-link" href={link.url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink size={10} aria-hidden="true" />{link.label}
                  </a>
                {/each}
              </p>
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </div>

  <!-- Flow metrics: derived charts (V17). -->
  <section class="panel metrics-panel" aria-labelledby="dash-metrics">
    <header class="panel-head">
      <Gauge size={15} aria-hidden="true" />
      <h3 id="dash-metrics">Flow metrics</h3>
      <span class="panel-sub-inline">
        {dashboardStore.window ? WINDOW_OPTIONS.find((w) => w.value === dashboardStore.window)?.label : "All time"}
      </span>
    </header>

    <div class="metrics-grid">
      <!-- Throughput & WIP by assignee: 2-series grouped bars. Legend + direct
           value labels carry identity (never colour-alone). -->
      <div class="chart-block">
        <h4 class="chart-title">Throughput &amp; WIP by assignee</h4>
        <div class="legend" aria-hidden="true">
          <span class="legend-item"><i class="swatch wip"></i>In progress</span>
          <span class="legend-item"><i class="swatch done"></i>Completed</span>
        </div>
        {#if assigneeRows.length === 0}
          <p class="empty">No assignee activity in this window.</p>
        {:else}
          <ul class="bar-rows">
            {#each assigneeRows as row (row.assignee ?? "__none__")}
              <li class="bar-row">
                <span class="bar-label" title={row.assignee ?? "Unassigned"}>
                  {row.assignee ?? "Unassigned"}
                </span>
                <div class="bar-pair">
                  <div class="bar-line">
                    <div
                      class="bar wip"
                      style="width: {pct(row.wip, assigneeMax)}%"
                      role="img"
                      aria-label="{row.assignee ?? 'Unassigned'}: {row.wip} in progress"
                    ></div>
                    <span class="bar-val">{row.wip}</span>
                  </div>
                  <div class="bar-line">
                    <div
                      class="bar done"
                      style="width: {pct(row.throughput, assigneeMax)}%"
                      role="img"
                      aria-label="{row.assignee ?? 'Unassigned'}: {row.throughput} completed"
                    ></div>
                    <span class="bar-val">{row.throughput}</span>
                  </div>
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <!-- Aging WIP: single-hue bars, length = age; stale ones flagged (label). -->
      <div class="chart-block">
        <h4 class="chart-title">Aging work in progress</h4>
        {#if agingItems.length === 0}
          <p class="empty">No cards are currently in progress.</p>
        {:else}
          <ul class="bar-rows">
            {#each agingItems as item (item.card_id)}
              {@const stale = item.age_seconds >= STALE_SECONDS}
              <li class="bar-row">
                <span class="bar-label mono" title={item.assignee ?? "Unassigned"}>
                  {item.ticket_number}
                </span>
                <div class="bar-line">
                  <div
                    class="bar age"
                    class:stale
                    style="width: {pct(item.age_seconds, agingMax)}%"
                    role="img"
                    aria-label="{item.ticket_number}: in progress {fmtDuration(item.age_seconds)}"
                  ></div>
                  <span class="bar-val">{fmtDuration(item.age_seconds)}</span>
                  {#if stale}<span class="mini-badge attn">stale</span>{/if}
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <!-- Cycle time distribution: a summary-stat readout (the right form for a
           handful of aggregate durations — not a chart). -->
      <div class="chart-block">
        <h4 class="chart-title">Cycle time</h4>
        {#if (dashboardStore.metrics?.cycle_time.count ?? 0) === 0}
          <p class="empty">No cards completed with a recorded start in this window.</p>
        {:else}
          <dl class="stat-readout">
            <div><dt>Average</dt><dd>{fmtDuration(dashboardStore.metrics?.cycle_time.avg_seconds)}</dd></div>
            <div><dt>Median</dt><dd>{fmtDuration(dashboardStore.metrics?.cycle_time.median_seconds)}</dd></div>
            <div><dt>90th pct</dt><dd>{fmtDuration(dashboardStore.metrics?.cycle_time.p90_seconds)}</dd></div>
            <div><dt>Completed</dt><dd>{dashboardStore.metrics?.cycle_time.count ?? 0}</dd></div>
          </dl>
        {/if}
      </div>
    </div>
  </section>

  <!-- Cycle burndown / velocity (V34): the selected iteration's committed-vs-
       completed + a per-day burndown, matching the flow-metrics chart style. -->
  <section class="panel metrics-panel" aria-labelledby="dash-cycle">
    <header class="panel-head">
      <TrendingUp size={15} aria-hidden="true" />
      <h3 id="dash-cycle">Cycle burndown</h3>
      {#if dashboardStore.cycles.length > 0}
        <label class="cycle-select">
          <span class="sr-only">Active cycle</span>
          <select
            class="rail-select"
            aria-label="Active cycle"
            value={dashboardStore.activeCycleId}
            onchange={(e) =>
              setActiveCycle(Number((e.currentTarget as HTMLSelectElement).value))}
          >
            {#each dashboardStore.cycles as c (c.id)}
              <option value={c.id}>{c.name}</option>
            {/each}
          </select>
        </label>
      {/if}
    </header>

    {#if dashboardStore.cycles.length === 0}
      <p class="empty">No cycles on this board yet — create one to track a burndown.</p>
    {:else if !cycleMetrics}
      <p class="empty">Select a cycle to see its burndown.</p>
    {:else}
      <div class="metrics-grid">
        <!-- Committed vs completed: 2-series bars + the velocity headline. -->
        <div class="chart-block">
          <h4 class="chart-title">Committed vs completed ({cycleUnitLabel})</h4>
          <div class="legend" aria-hidden="true">
            <span class="legend-item"><i class="swatch committed"></i>Committed</span>
            <span class="legend-item"><i class="swatch completed"></i>Completed</span>
          </div>
          <ul class="bar-rows">
            <li class="bar-row">
              <span class="bar-label">Committed</span>
              <div class="bar-line">
                <div
                  class="bar committed"
                  style="width: {pct(cycleCommitted, Math.max(1, cycleCommitted))}%"
                  role="img"
                  aria-label="Committed: {cycleCommitted} {cycleUnitLabel}"
                ></div>
                <span class="bar-val">{cycleCommitted}</span>
              </div>
            </li>
            <li class="bar-row">
              <span class="bar-label">Completed</span>
              <div class="bar-line">
                <div
                  class="bar completed"
                  style="width: {pct(cycleCompleted, Math.max(1, cycleCommitted))}%"
                  role="img"
                  aria-label="Completed: {cycleCompleted} {cycleUnitLabel}"
                ></div>
                <span class="bar-val">{cycleCompleted}</span>
              </div>
            </li>
          </ul>
          <dl class="stat-readout">
            <div><dt>Velocity</dt><dd>{cycleMetrics.velocity} pts</dd></div>
            <div>
              <dt>Stories done</dt>
              <dd>{cycleMetrics.completed.count} / {cycleMetrics.committed.count}</dd>
            </div>
          </dl>
        </div>

        <!-- Burndown: per-day remaining (teal bar), with the ideal line marked as a
             tick on the track — never colour alone (the tick carries a label). -->
        <div class="chart-block">
          <h4 class="chart-title">Burndown ({cycleUnitLabel} remaining)</h4>
          {#if burndown.length === 0}
            <p class="empty">This cycle has no start/end dates — set them for a burndown.</p>
          {:else}
            <div class="legend" aria-hidden="true">
              <span class="legend-item"><i class="swatch committed"></i>Remaining</span>
              <span class="legend-item"><i class="ideal-swatch"></i>Ideal</span>
            </div>
            <ul class="bar-rows">
              {#each burndown as point (point.date)}
                <li class="bar-row">
                  <span class="bar-label mono">{shortDay(point.date)}</span>
                  <div class="bar-line">
                    <div class="bar-track">
                      <div
                        class="bar committed"
                        style="width: {pct(point.remaining, burndownMax)}%"
                        role="img"
                        aria-label="{shortDay(point.date)}: {point.remaining} {cycleUnitLabel} remaining (ideal {point.ideal})"
                      ></div>
                      <span
                        class="ideal-tick"
                        style="left: {Math.min(100, (point.ideal / burndownMax) * 100)}%"
                        aria-hidden="true"
                      ></span>
                    </div>
                    <span class="bar-val">{point.remaining}</span>
                  </div>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      </div>
    {/if}
  </section>

  <!-- Recent activity: the deepened feed, filterable by actor + action. -->
  <section class="panel" aria-labelledby="dash-activity">
    <header class="panel-head">
      <History size={15} aria-hidden="true" />
      <h3 id="dash-activity">Recent activity</h3>
      <div class="activity-filters">
        <label class="filter">
          <span class="sr-only">Filter by actor</span>
          <select class="rail-select" aria-label="Filter by actor" value={dashboardStore.actorFilter} onchange={onActor}>
            <option value="">All actors</option>
            {#each actorOptions as a (a)}
              <option value={a}>{a}</option>
            {/each}
          </select>
        </label>
        <label class="filter">
          <span class="sr-only">Filter by action</span>
          <select class="rail-select" aria-label="Filter by action" value={dashboardStore.actionFilter} onchange={onAction}>
            <option value="">All actions</option>
            {#each ACTIONS as a (a)}
              <option value={a}>{a}</option>
            {/each}
          </select>
        </label>
      </div>
    </header>

    {#if dashboardStore.activity.length === 0}
      <p class="empty">No activity{dashboardStore.actorFilter || dashboardStore.actionFilter ? " matches these filters" : " yet"}.</p>
    {:else}
      <ol class="feed">
        {#each dashboardStore.activity as entry (entry.id)}
          {@const Icon = ICONS[entry.action]}
          <li class="feed-row">
            <span class="feed-icon" data-action={entry.action} aria-hidden="true">
              {#if Icon}<Icon size={14} />{/if}
            </span>
            <div class="feed-body">
              <p class="feed-summary">{entry.summary}</p>
              <p class="feed-meta">
                <span class="feed-actor">
                  <span class="actor-avatar" aria-hidden="true">{actorInitial(entry.actor_label)}</span>
                  {entry.actor_label ?? "unknown"}
                </span>
                <span class="feed-dot" aria-hidden="true">·</span>
                <time datetime={entry.ts} title={fullTime(entry.ts)}>{relTime(entry.ts)}</time>
              </p>
            </div>
          </li>
        {/each}
      </ol>
      {#if dashboardStore.activityCursor}
        <div class="feed-more">
          <button class="btn-add" onclick={loadMoreDashboardActivity} disabled={dashboardStore.activityLoading}>
            {dashboardStore.activityLoading ? "Loading…" : "Load more"}
          </button>
        </div>
      {/if}
    {/if}
  </section>

  <!-- Board snapshot: reuse V14's sortable BoardTable (read-only), collapsed by default. -->
  <section class="panel">
    <button class="table-toggle" aria-expanded={showTable} onclick={() => (showTable = !showTable)}>
      {#if showTable}<ChevronDown size={15} />{:else}<ChevronRight size={15} />{/if}
      <TableIcon size={15} aria-hidden="true" />
      <span>Board snapshot (table)</span>
    </button>
    {#if showTable}
      <div class="table-holder">
        <BoardTable />
      </div>
    {/if}
  </section>
</div>

<style>
  .dashboard {
    max-width: 1100px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
  .head-controls {
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }

  /* --- stat strip --- */
  .stat-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.85rem;
    margin: 1.2rem 0 1.4rem;
  }
  .stat-tile {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.85rem 1rem;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow-sm);
  }
  .stat-icon {
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    border-radius: 9px;
    flex: none;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .stat-icon.done {
    background: color-mix(in srgb, var(--success) 16%, transparent);
    color: var(--success);
  }
  .stat-icon.wip {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .stat-icon.attn {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .stat-icon.cycle {
    background: var(--agent-soft);
    color: var(--agent);
  }
  .stat-body {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.02em;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .stat-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    margin-top: 0.15rem;
  }

  /* --- panels --- */
  .panel-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-bottom: 1rem;
  }
  .panel {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem 1.1rem 1.1rem;
    margin-bottom: 1rem;
  }
  .panel-head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.85rem;
    color: var(--muted);
  }
  .panel-head h3 {
    margin: 0;
    font-size: 0.9rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .panel-head .count {
    margin-left: auto;
  }
  .count {
    font-size: 0.72rem;
    color: var(--muted);
    background: var(--surface-2);
    border-radius: 10px;
    padding: 0.05rem 0.5rem;
    font-variant-numeric: tabular-nums;
  }
  .count.hot {
    background: var(--danger-soft);
    color: var(--danger);
    font-weight: 700;
  }
  .panel-sub-inline {
    margin-left: auto;
    font-size: 0.72rem;
    color: var(--muted);
  }
  .empty {
    color: var(--muted);
    font-size: 0.82rem;
    padding: 0.4rem 0;
    margin: 0;
  }

  /* --- in-flight by assignee --- */
  .assignee-groups {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }
  .assignee-head {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin-bottom: 0.4rem;
  }
  .assignee-name {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .assignee-head .count {
    margin-left: auto;
  }
  .avatar-sm {
    flex: none;
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: var(--accent);
    color: #fff;
    font-size: 0.62rem;
    font-weight: 700;
  }
  .inflight-list,
  .attn-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .inflight-row {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.4rem 0.5rem;
    background: var(--surface-2);
    border-radius: 6px;
  }
  .ticket {
    font-family: var(--mono);
    font-size: 0.68rem;
    font-weight: 600;
    color: var(--muted);
    flex: none;
  }
  .inflight-title,
  .attn-title {
    font-size: 0.82rem;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
  }
  .inflight-badges {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    flex: none;
  }
  .mini-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    border-radius: 4px;
    padding: 0.08rem 0.35rem;
  }
  .mini-badge.attn {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .mini-badge.blocked {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .mini-link {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    font-size: 0.62rem;
    font-weight: 600;
    text-decoration: none;
    background: var(--accent-soft);
    color: var(--accent);
    border-radius: 4px;
    padding: 0.08rem 0.35rem;
  }
  .mini-link:hover {
    text-decoration: underline;
  }

  /* --- needs attention --- */
  .attn-row {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.55rem 0.6rem;
    background: var(--surface-2);
    border-left: 3px solid var(--danger);
    border-radius: 6px;
  }
  .attn-top {
    display: flex;
    align-items: center;
    gap: 0.45rem;
  }
  .row-link {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    margin-left: auto;
    flex: none;
    border: none;
    background: none;
    color: var(--accent);
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.1rem 0.2rem;
  }
  .row-link:hover {
    text-decoration: underline;
  }
  .attn-note {
    margin: 0;
    font-size: 0.8rem;
    line-height: 1.4;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .attn-meta {
    margin: 0.1rem 0 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.72rem;
    color: var(--muted);
  }

  /* --- metrics charts --- */
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1.4rem;
  }
  .chart-title {
    margin: 0 0 0.6rem;
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--text);
  }
  .legend {
    display: flex;
    gap: 0.9rem;
    margin-bottom: 0.6rem;
    font-size: 0.72rem;
    color: var(--muted);
  }
  .legend-item {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    display: inline-block;
  }
  .swatch.wip,
  .bar.wip {
    background: var(--accent);
  }
  .swatch.done,
  .bar.done {
    background: var(--agent);
  }
  /* Cycle burndown series (V34): committed = accent (teal), completed = agent
     (violet) — the same CVD-safe pair as WIP/done, so the dashboard reads as one
     system. Identity is carried by the legend + direct value labels, not colour. */
  .swatch.committed,
  .bar.committed {
    background: var(--accent);
  }
  .swatch.completed,
  .bar.completed {
    background: var(--agent);
  }
  /* Burndown ideal reference: a neutral tick on a recessive track (not a colour-
     coded status), positioned at the ideal remaining for that day. */
  .bar-track {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 9px;
    background: var(--surface-2);
    border-radius: 4px;
    display: flex;
    align-items: center;
  }
  .bar-track .bar {
    border-radius: 4px;
  }
  .ideal-tick {
    position: absolute;
    top: -2px;
    bottom: -2px;
    width: 2px;
    border-radius: 1px;
    background: var(--muted);
    transform: translateX(-1px);
  }
  .ideal-swatch {
    width: 2px;
    height: 12px;
    border-radius: 1px;
    display: inline-block;
    background: var(--muted);
  }
  .cycle-select {
    margin-left: auto;
  }
  .cycle-select .rail-select {
    font-size: 0.78rem;
    padding: 0.25rem 1.6rem 0.25rem 0.5rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background-color: var(--card-bg);
    color: var(--text);
  }
  .bar-rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
  }
  .bar-row {
    display: grid;
    grid-template-columns: 5.5rem 1fr;
    align-items: center;
    gap: 0.5rem;
  }
  .bar-label {
    font-size: 0.74rem;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bar-label.mono {
    font-family: var(--mono);
  }
  .bar-pair {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .bar-line {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  .bar {
    height: 9px;
    border-radius: 0 4px 4px 0;
    min-width: 2px;
    flex: none;
  }
  .bar.age {
    background: var(--accent);
  }
  .bar.age.stale {
    background: var(--danger);
  }
  .bar-val {
    font-size: 0.72rem;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .stat-readout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.7rem 1rem;
    margin: 0;
  }
  .stat-readout div {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .stat-readout dt {
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: var(--muted);
  }
  .stat-readout dd {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  /* --- activity feed --- */
  .activity-filters {
    margin-left: auto;
    display: flex;
    gap: 0.4rem;
  }
  .activity-filters .rail-select {
    font-size: 0.78rem;
    padding: 0.25rem 1.6rem 0.25rem 0.5rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background-color: var(--card-bg);
    color: var(--text);
  }
  .feed {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .feed-row {
    display: grid;
    grid-template-columns: auto 1fr;
    align-items: start;
    gap: 0.65rem;
    padding: 0.5rem 0.55rem;
    border-radius: 6px;
  }
  .feed-row:hover {
    background: var(--surface-2);
  }
  .feed-icon {
    display: grid;
    place-items: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: var(--accent-soft);
    color: var(--accent);
    flex: none;
    margin-top: 0.05rem;
  }
  .feed-icon[data-action="deleted"],
  .feed-icon[data-action="attention"] {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .feed-icon[data-action="resolved"] {
    background: color-mix(in srgb, var(--success) 16%, transparent);
    color: var(--success);
  }
  /* purged = permanent destruction: filled danger, more final than soft `deleted`. */
  .feed-icon[data-action="purged"] {
    background: var(--danger);
    color: #fff;
  }
  .feed-icon[data-action="created"],
  .feed-icon[data-action="restored"] {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .feed-icon[data-action="moved"],
  .feed-icon[data-action="updated"] {
    background: var(--agent-soft);
    color: var(--agent);
  }
  .feed-body {
    min-width: 0;
  }
  .feed-summary {
    margin: 0;
    font-size: 0.86rem;
    line-height: 1.4;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .feed-meta {
    margin: 0.2rem 0 0;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.74rem;
    color: var(--muted);
  }
  .feed-actor {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .actor-avatar {
    display: grid;
    place-items: center;
    width: 17px;
    height: 17px;
    border-radius: 50%;
    background: var(--agent-soft);
    color: var(--agent);
    font-size: 0.6rem;
    font-weight: 700;
    flex: none;
  }
  .feed-dot {
    color: var(--border);
  }
  .feed-more {
    display: flex;
    justify-content: center;
    margin-top: 0.8rem;
  }

  /* --- board snapshot table --- */
  .table-toggle {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    border: none;
    background: none;
    color: var(--text);
    font-size: 0.9rem;
    font-weight: 700;
    padding: 0;
  }
  .table-holder {
    margin-top: 0.85rem;
  }

  @media (max-width: 820px) {
    .stat-strip {
      grid-template-columns: repeat(2, 1fr);
    }
    .panel-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
