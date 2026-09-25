<script lang="ts">
  // Workspaces screen (M9 V70, KAN-1059; ADR 0021) — mirrors Epics.svelte's list +
  // create-form + grid-of-cards shape. Workspaces are user-scoped (not board-scoped):
  // the list is loaded once at login (board.svelte.ts's onMount) and lives in
  // workspaceStore, so this view just renders it plus a create form.
  //
  // Each card previews its members + boards inline (mirroring how EpicItem
  // previews its stories inline, without a click-through). Boards-by-workspace come
  // free from the already-loaded boardStore; members-by-workspace need a per-workspace
  // fetch (WorkspaceRead carries no embedded member list), so this view loads them
  // itself, bounded by the caller's own (typically small) workspace count.
  import { Plus } from "lucide-svelte";
  import { listWorkspaceMembers, type WorkspaceMember } from "../api";
  import { refetchWorkspaces, workspaceStore } from "../workspaces.svelte";
  import WorkspaceForm from "./WorkspaceForm.svelte";
  import WorkspaceItem from "./WorkspaceItem.svelte";

  let adding = $state(false);

  let membersByWorkspace = $state<Record<number, WorkspaceMember[]>>({});
  let membersLoading = $state(false);

  async function loadPreviews() {
    const workspaces = workspaceStore.workspaces;
    if (workspaces.length === 0) {
      membersByWorkspace = {};
      return;
    }
    membersLoading = true;
    try {
      const entries = await Promise.all(
        workspaces.map(async (t) => [t.id, await listWorkspaceMembers(t.id)] as const),
      );
      membersByWorkspace = Object.fromEntries(entries);
    } catch {
      // Best-effort preview only — WorkspaceModal re-fetches authoritatively on open,
      // so a failed preview just leaves that workspace's card showing "…".
    } finally {
      membersLoading = false;
    }
  }

  $effect(() => {
    // Re-run whenever the workspace list changes (create/rename/delete all refetch it).
    workspaceStore.workspaces;
    loadPreviews();
  });
</script>

<div class="workspaces-view page-view">
  {#if workspaceStore.error}
    <div class="banner error" role="alert">
      <span>{workspaceStore.error}</span>
      <button onclick={refetchWorkspaces}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Workspaces</h2>
      <p class="page-sub">The tenant tier above a user — members share default access to a workspace's boards.</p>
    </div>
    {#if !adding}
      <button class="btn-add" onclick={() => (adding = true)}>
        <Plus size={15} /> New workspace
      </button>
    {/if}
  </div>

  {#if adding}
    <WorkspaceForm onclose={() => (adding = false)} />
  {/if}

  {#if workspaceStore.loading && workspaceStore.workspaces.length === 0}
    <p class="hint">Loading…</p>
  {:else if workspaceStore.workspaces.length === 0}
    <p class="empty">No workspaces yet. Create one to share board access with a group.</p>
  {/if}

  {#if workspaceStore.workspaces.length > 0}
    <div class="epic-grid">
      {#each workspaceStore.workspaces as workspace (workspace.id)}
        <WorkspaceItem {workspace} members={membersByWorkspace[workspace.id] ?? null} {membersLoading} />
      {/each}
    </div>
  {/if}
</div>
