<script lang="ts">
  // Trash view (KAN-20): the active board's soft-deleted (KAN-19) cards + epics,
  // each with a Restore and a Delete-permanently (purge) action. Board-scoped: it
  // (re)loads whenever the active board changes. Server state is authoritative — every
  // restore/purge is followed by a refetch (no optimistic UI). Modelled on Activity.svelte.
  import { Layers, RefreshCw, RotateCcw, SquareKanban, Trash2 } from "lucide-svelte";
  import { activeBoard, boardStore } from "../board.svelte";
  import {
    purgeCardItem,
    purgeEpicItem,
    refetchTrash,
    restoreCardItem,
    restoreEpicItem,
    trashStore,
  } from "../trash.svelte";
  import { displayRef } from "../tickets";

  // Board-scoped: reload whenever the active board changes (also on mount, since the
  // component only mounts when the view is open). Mirrors Activity / Members.
  $effect(() => {
    boardStore.activeBoardId;
    refetchTrash();
  });

  type Entry = {
    kind: "card" | "epic";
    id: number;
    ticket: string;
    // The canonical ticket, kept beside the displayed ref as the hover/copy value
    // (V54, KAN-975) — a trashed card is exactly the one you may need to quote.
    canonical: string;
    title: string;
    deleted_at: string;
  };

  // Merge cards + epics into one newest-deleted-first list (both arrive pre-sorted
  // desc; the merge re-sorts across the two).
  const entries = $derived<Entry[]>(
    [
      ...trashStore.cards.map((c) => ({
        kind: "card" as const,
        id: c.id,
        ticket: displayRef(c),
        canonical: c.ticket_number,
        title: c.title,
        deleted_at: c.deleted_at,
      })),
      ...trashStore.epics.map((e) => ({
        kind: "epic" as const,
        id: e.id,
        ticket: displayRef(e),
        canonical: e.ticket_number,
        title: e.name,
        deleted_at: e.deleted_at,
      })),
    ].sort(
      (a, b) => new Date(b.deleted_at).getTime() - new Date(a.deleted_at).getTime(),
    ),
  );

  // Per-row UI state, keyed by kind+id (the list has both cards and epics).
  let confirming = $state<string | null>(null);
  let busy = $state<string | null>(null);
  let actionError = $state<string | null>(null);

  const key = (e: Entry) => `${e.kind}-${e.id}`;

  async function restore(e: Entry) {
    busy = key(e);
    actionError = null;
    try {
      if (e.kind === "card") await restoreCardItem(e.id);
      else await restoreEpicItem(e.id);
    } catch (err) {
      actionError = err instanceof Error ? err.message : "Failed to restore";
    } finally {
      busy = null;
    }
  }

  async function confirmPurge(e: Entry) {
    busy = key(e);
    actionError = null;
    try {
      if (e.kind === "card") await purgeCardItem(e.id);
      else await purgeEpicItem(e.id);
      confirming = null;
    } catch (err) {
      actionError = err instanceof Error ? err.message : "Failed to delete permanently";
    } finally {
      busy = null;
    }
  }

  // A compact relative time, matching Activity.svelte.
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

<div class="trash-view page-view">
  {#if trashStore.error}
    <div class="banner error" role="alert">
      <span>{trashStore.error}</span>
      <button onclick={refetchTrash}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Trash</h2>
      <p class="page-sub">
        Deleted cards and epics on <b>{activeBoard()?.name ?? "this board"}</b>.
      </p>
    </div>
    <button class="btn-add" onclick={refetchTrash} disabled={trashStore.loading}>
      <RefreshCw size={15} /> Refresh
    </button>
  </div>

  <p class="page-intro">
    Deleting a card or epic moves it here instead of destroying it. Restore it to put
    it back, or delete it permanently to remove it for good. Newest first.
  </p>

  {#if actionError}
    <p class="form-error" role="alert">{actionError}</p>
  {/if}

  {#if trashStore.loading && entries.length === 0}
    <p class="hint">Loading…</p>
  {:else if entries.length === 0}
    <p class="empty">Trash is empty. Deleted cards and epics show up here.</p>
  {/if}

  {#if entries.length > 0}
    <ol class="trash-list">
      {#each entries as e (key(e))}
        <li class="trash-row card">
          <span class="trash-icon" data-kind={e.kind} aria-hidden="true">
            {#if e.kind === "card"}
              <SquareKanban size={15} />
            {:else}
              <Layers size={15} />
            {/if}
          </span>
          <div class="trash-body">
            <p class="trash-title">
              <span class="ticket" title={e.canonical}>{e.ticket}</span>
              <span class="ttitle">{e.title}</span>
            </p>
            <p class="trash-meta">
              <span class="kind-tag">{e.kind}</span>
              <span class="feed-dot" aria-hidden="true">·</span>
              <span>deleted <time datetime={e.deleted_at} title={fullTime(e.deleted_at)}>{relTime(e.deleted_at)}</time></span>
            </p>
          </div>

          {#if confirming === key(e)}
            <div class="row actions confirm-actions">
              <span class="confirm-msg">Delete forever?</span>
              <button
                class="danger"
                onclick={() => confirmPurge(e)}
                disabled={busy === key(e)}
              >
                Delete
              </button>
              <button onclick={() => (confirming = null)} disabled={busy === key(e)}>
                Cancel
              </button>
            </div>
          {:else}
            <div class="trash-actions">
              <button
                class="restore-btn"
                onclick={() => restore(e)}
                disabled={busy === key(e)}
                title="Restore"
              >
                <RotateCcw size={14} /> Restore
              </button>
              <button
                class="icon-btn danger"
                title="Delete permanently"
                aria-label="Delete permanently"
                onclick={() => (confirming = key(e))}
                disabled={busy === key(e)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</div>

<style>
  .trash-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .trash-row.card {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.75rem;
    padding: 0.7rem 0.9rem;
  }
  .trash-icon {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border-radius: 8px;
    background: var(--accent-soft);
    color: var(--accent);
    flex: none;
  }
  .trash-icon[data-kind="epic"] {
    background: var(--agent-soft);
    color: var(--agent);
  }
  .trash-body {
    min-width: 0;
  }
  .trash-title {
    margin: 0;
    display: flex;
    align-items: baseline;
    gap: 0.45rem;
    font-size: 0.9rem;
    line-height: 1.4;
    color: var(--text);
    min-width: 0;
  }
  .trash-title .ticket {
    font-size: 0.72rem;
    font-weight: 700;
    color: var(--muted);
    flex: none;
  }
  .trash-title .ttitle {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .trash-meta {
    margin: 0.25rem 0 0;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.78rem;
    color: var(--muted);
  }
  .kind-tag {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.66rem;
    font-weight: 700;
    color: var(--muted);
  }
  .feed-dot {
    color: var(--border);
  }
  .trash-actions {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex: none;
  }
  .restore-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.8rem;
  }
  .confirm-actions {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex: none;
  }
  .confirm-actions .confirm-msg {
    font-size: 0.8rem;
    color: var(--muted);
  }
</style>
