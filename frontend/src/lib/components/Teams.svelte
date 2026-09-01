<script lang="ts">
  // Teams screen (M9 V70, KAN-1059; ADR 0021) — mirrors Epics.svelte's list +
  // create-form + grid-of-cards shape. Teams are user-scoped (not board-scoped):
  // the list is loaded once at login (board.svelte.ts's onMount) and lives in
  // teamStore, so this view just renders it plus a create form.
  //
  // Each card previews its members + boards inline (mirroring how EpicItem
  // previews its stories inline, without a click-through). Boards-by-team come
  // free from the already-loaded boardStore; members-by-team need a per-team
  // fetch (TeamRead carries no embedded member list), so this view loads them
  // itself, bounded by the caller's own (typically small) team count.
  import { Plus } from "lucide-svelte";
  import { listTeamMembers, type TeamMember } from "../api";
  import { refetchTeams, teamStore } from "../teams.svelte";
  import TeamForm from "./TeamForm.svelte";
  import TeamItem from "./TeamItem.svelte";

  let adding = $state(false);

  let membersByTeam = $state<Record<number, TeamMember[]>>({});
  let membersLoading = $state(false);

  async function loadPreviews() {
    const teams = teamStore.teams;
    if (teams.length === 0) {
      membersByTeam = {};
      return;
    }
    membersLoading = true;
    try {
      const entries = await Promise.all(
        teams.map(async (t) => [t.id, await listTeamMembers(t.id)] as const),
      );
      membersByTeam = Object.fromEntries(entries);
    } catch {
      // Best-effort preview only — TeamModal re-fetches authoritatively on open,
      // so a failed preview just leaves that team's card showing "…".
    } finally {
      membersLoading = false;
    }
  }

  $effect(() => {
    // Re-run whenever the team list changes (create/rename/delete all refetch it).
    teamStore.teams;
    loadPreviews();
  });
</script>

<div class="teams-view page-view">
  {#if teamStore.error}
    <div class="banner error" role="alert">
      <span>{teamStore.error}</span>
      <button onclick={refetchTeams}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Teams</h2>
      <p class="page-sub">The tenant tier above a user — members share default access to a team's boards.</p>
    </div>
    {#if !adding}
      <button class="btn-add" onclick={() => (adding = true)}>
        <Plus size={15} /> New team
      </button>
    {/if}
  </div>

  {#if adding}
    <TeamForm onclose={() => (adding = false)} />
  {/if}

  {#if teamStore.loading && teamStore.teams.length === 0}
    <p class="hint">Loading…</p>
  {:else if teamStore.teams.length === 0}
    <p class="empty">No teams yet. Create one to share board access with a group.</p>
  {/if}

  {#if teamStore.teams.length > 0}
    <div class="epic-grid">
      {#each teamStore.teams as team (team.id)}
        <TeamItem {team} members={membersByTeam[team.id] ?? null} {membersLoading} />
      {/each}
    </div>
  {/if}
</div>
