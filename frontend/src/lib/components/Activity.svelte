<script lang="ts">
  // Board activity feed (KAN-18): a read-only, newest-first, paginated log of every
  // create / update / delete / move of a card, epic or board — reading the KAN-17
  // write path via GET /api/v1/boards/{id}/activity. Board-scoped: it (re)loads
  // whenever the active board changes. Modelled on the Members / Tokens views.
  import {
    AlertTriangle,
    ArrowLeftRight,
    Check,
    Flame,
    Plus,
    Pencil,
    RefreshCw,
    RotateCcw,
    Trash2,
    History,
  } from "lucide-svelte";
  import type { ActivityAction } from "../api";
  import { activeBoard, boardStore } from "../board.svelte";
  import {
    activityStore,
    loadMoreActivity,
    refetchActivity,
  } from "../activity.svelte";

  // Board-scoped: reload whenever the active board changes (also on mount, since the
  // component only mounts when the view is open). Mirrors Members.svelte.
  $effect(() => {
    boardStore.activeBoardId;
    refetchActivity();
  });

  // Per-action icon + colour token, so the feed is scannable at a glance. Covers
  // the full backend vocabulary (models.py VALID_ACTIVITY_ACTIONS) — the Record
  // type keeps this exhaustive, so a new action can't slip through as a blank chip.
  // attention/resolved reuse Dashboard.svelte's icons; purged (permanent
  // destruction) gets Flame + a filled-danger chip, reading as more final than the
  // soft-danger `deleted`.
  const ICONS: Record<ActivityAction, typeof Plus> = {
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

  // A compact relative time ("just now", "5m ago", "3h ago", "2d ago"), falling
  // back to a locale date for anything older than a week.
  function relTime(iso: string): string {
    const then = new Date(iso).getTime();
    const secs = Math.round((Date.now() - then) / 1000);
    if (secs < 45) return "just now";
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  function fullTime(iso: string): string {
    return new Date(iso).toLocaleString();
  }
</script>

<div class="activity-view page-view">
  {#if activityStore.error}
    <div class="banner error" role="alert">
      <span>{activityStore.error}</span>
      <button onclick={refetchActivity}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Activity</h2>
      <p class="page-sub">
        Recent changes on <b>{activeBoard()?.name ?? "this board"}</b>.
      </p>
    </div>
    <button class="btn-add" onclick={refetchActivity} disabled={activityStore.loading}>
      <RefreshCw size={15} /> Refresh
    </button>
  </div>

  <p class="page-intro">
    An append-only history of every create, edit, move and delete on this board — by
    you, your members and your agents. Newest first. Owner and members can see it.
  </p>

  {#if activityStore.loading && activityStore.entries.length === 0}
    <p class="hint">Loading…</p>
  {:else if activityStore.entries.length === 0}
    <p class="empty">
      No activity yet. Create, edit or move a card and it'll show up here.
    </p>
  {/if}

  {#if activityStore.entries.length > 0}
    <ol class="feed">
      {#each activityStore.entries as entry (entry.id)}
        {@const Icon = ICONS[entry.action as ActivityAction]}
        <li class="feed-row card">
          <span class="feed-icon" data-action={entry.action} aria-hidden="true">
            <Icon size={15} />
          </span>
          <div class="feed-body">
            <p class="feed-summary">{entry.summary}</p>
            <p class="feed-meta">
              <span class="feed-actor">
                <span class="actor-avatar" aria-hidden="true">
                  {actorInitial(entry.actor_label)}
                </span>
                {entry.actor_label ?? "unknown"}
              </span>
              <span class="feed-dot" aria-hidden="true">·</span>
              <time datetime={entry.ts} title={fullTime(entry.ts)}>{relTime(entry.ts)}</time>
            </p>
          </div>
        </li>
      {/each}
    </ol>

    {#if activityStore.cursor}
      <div class="feed-more">
        <button class="btn-add" onclick={loadMoreActivity} disabled={activityStore.loading}>
          {activityStore.loading ? "Loading…" : "Load more"}
        </button>
      </div>
    {:else}
      <p class="feed-end">
        <History size={13} /> That's the whole history.
      </p>
    {/if}
  {/if}
</div>

<style>
  .feed {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .feed-row.card {
    display: grid;
    grid-template-columns: auto 1fr;
    align-items: start;
    gap: 0.75rem;
    padding: 0.7rem 0.9rem;
  }
  .feed-icon {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border-radius: 8px;
    background: var(--accent-soft);
    color: var(--accent);
    flex: none;
    margin-top: 0.05rem;
  }
  /* Colour the chip by action, staying inside the Graphite / Zinc & Teal palette.
     Matches Dashboard.svelte's feed so the two surfaces read the same. */
  .feed-icon[data-action="deleted"],
  .feed-icon[data-action="attention"] {
    background: var(--danger-soft);
    color: var(--danger);
  }
  /* purged = permanent destruction: a filled-danger chip, more final than the
     soft-danger `deleted`. */
  .feed-icon[data-action="purged"] {
    background: var(--danger);
    color: #fff;
  }
  .feed-icon[data-action="resolved"] {
    background: color-mix(in srgb, var(--success) 16%, transparent);
    color: var(--success);
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
    font-size: 0.9rem;
    line-height: 1.4;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .feed-meta {
    margin: 0.25rem 0 0;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.78rem;
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
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--agent-soft);
    color: var(--agent);
    font-size: 0.62rem;
    font-weight: 700;
    flex: none;
  }
  .feed-dot {
    color: var(--border);
  }
  .feed-more {
    display: flex;
    justify-content: center;
    margin-top: 0.9rem;
  }
  .feed-end {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    margin-top: 1rem;
    font-size: 0.78rem;
    color: var(--muted);
  }
</style>
