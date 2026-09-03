<script lang="ts">
  import { Pencil, SquareKanban, Trash2, Users } from "lucide-svelte";
  import type { Team, TeamMember } from "../api";
  import { boardStore } from "../board.svelte";
  import { removeTeam } from "../teams.svelte";
  import TeamModal from "./TeamModal.svelte";

  let {
    team,
    members,
    membersLoading,
  }: { team: Team; members: TeamMember[] | null; membersLoading: boolean } = $props();

  let mode = $state<"view" | "confirmDelete">("view");
  let showModal = $state(false);
  let deleting = $state(false);
  let deleteError = $state<string | null>(null);

  // Boards linked to this team (M9 V67, KAN-1056) — already loaded in boardStore
  // (the caller's own boards), so no extra fetch, unlike the member preview.
  const boards = $derived(boardStore.boards.filter((b) => b.team_id === team.id));

  const isOwner = $derived(team.role === "owner");

  function isInteractive(t: EventTarget | null): boolean {
    return t instanceof Element && !!t.closest("button, a");
  }
  function openFromClick(e: MouseEvent) {
    if (isInteractive(e.target)) return;
    showModal = true;
  }
  function onKeydown(e: KeyboardEvent) {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      showModal = true;
    }
  }

  async function confirmDelete() {
    deleting = true;
    deleteError = null;
    try {
      await removeTeam(team.id);
    } catch (e) {
      deleteError = e instanceof Error ? e.message : "Failed to delete team";
      deleting = false;
    }
  }
</script>

{#if mode === "confirmDelete"}
  <div class="card confirm">
    <p class="confirm-msg">
      Delete <strong>{team.name}</strong>? Its {members?.length ?? 0}
      {(members?.length ?? 0) === 1 ? "member" : "members"} lose access, and its
      {boards.length} {boards.length === 1 ? "board" : "boards"} become unclaimed
      (not deleted).
    </p>
    {#if deleteError}
      <p class="form-error" role="alert">{deleteError}</p>
    {/if}
    <div class="row actions">
      <button class="danger" onclick={confirmDelete} disabled={deleting}>Delete</button>
      <button onclick={() => (mode = "view")} disabled={deleting}>Cancel</button>
    </div>
  </div>
{:else}
  <div
    class="card team-card"
    role="button"
    tabindex="0"
    aria-label="Open team {team.name}"
    onclick={openFromClick}
    onkeydown={onKeydown}
  >
    <div class="card-top">
      <span class="team-name">{team.name}</span>
      {#if team.role}
        <span class="role-pill" title="Your role: {team.role}">{team.role}</span>
      {/if}
      {#if isOwner}
        <div class="card-actions">
          <button class="icon-btn" title="Edit" aria-label="Edit" onclick={() => (showModal = true)}>
            <Pencil size={15} />
          </button>
          <button
            class="icon-btn danger"
            title="Delete"
            aria-label="Delete"
            onclick={() => (mode = "confirmDelete")}
          >
            <Trash2 size={15} />
          </button>
        </div>
      {/if}
    </div>

    <div class="team-section">
      <span class="team-section-label"><Users size={13} /> Members</span>
      {#if membersLoading && members == null}
        <p class="hint">Loading…</p>
      {:else if members == null}
        <p class="hint">Unavailable</p>
      {:else if members.length === 0}
        <p class="empty-inline">No members.</p>
      {:else}
        <ul class="team-list">
          {#each members as member (member.id)}
            <li>
              <span class="member-email">{member.email ?? member.user_id}</span>
              <span class="member-role">{member.role}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="team-section">
      <span class="team-section-label"><SquareKanban size={13} /> Boards</span>
      {#if boards.length === 0}
        <p class="empty-inline">No boards linked yet.</p>
      {:else}
        <ul class="team-list">
          {#each boards as board (board.id)}
            <li>
              <span class="board-key">{board.key}</span>
              <span class="board-name">{board.name}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </div>
{/if}

{#if showModal}
  <TeamModal teamId={team.id} onclose={() => (showModal = false)} />
{/if}

<style>
  .card.team-card {
    padding: 1rem 1.1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    cursor: pointer;
  }
  .card.team-card:hover {
    transform: none;
  }
  .team-card .card-top {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0;
  }
  .team-name {
    font-size: var(--type-title-medium-size);
    line-height: var(--type-title-medium-line-height);
    font-weight: 650;
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .role-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.1rem 0.45rem;
    border-radius: var(--shape-full);
    font-size: var(--type-label-small-size);
    line-height: var(--type-label-small-line-height);
    letter-spacing: var(--type-label-small-tracking);
    font-weight: 600;
    text-transform: capitalize;
    color: var(--agent);
    background: var(--agent-soft);
  }
  .team-card .card-actions {
    margin-left: auto;
    display: flex;
    gap: 0.25rem;
  }
  .team-section {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .team-section-label {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: var(--type-label-medium-size);
    line-height: var(--type-label-medium-line-height);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }
  .team-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .team-list li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    font-size: var(--type-body-medium-size);
    line-height: var(--type-body-medium-line-height);
    font-weight: var(--type-body-medium-weight);
    letter-spacing: var(--type-body-medium-tracking);
    padding: 0.3rem 0.5rem;
    border-radius: var(--shape-small);
    /* Static decorative row tint (a non-interactive <li>), not a hover
       state — just carried the old --hover token name. Renamed to
       --state-hover (M8 M3-5, KAN-1094); same value. */
    background: var(--state-hover);
  }
  .member-email,
  .board-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
  }
  .member-role {
    flex: none;
    font-size: var(--type-label-medium-size);
    line-height: var(--type-label-medium-line-height);
    font-weight: var(--type-label-medium-weight);
    letter-spacing: var(--type-label-medium-tracking);
    color: var(--muted);
    text-transform: capitalize;
  }
  .board-key {
    flex: none;
    font-family: var(--mono);
    font-size: var(--type-label-medium-size);
    line-height: var(--type-label-medium-line-height);
    letter-spacing: var(--type-label-medium-tracking);
    font-weight: 600;
    color: var(--accent);
  }
  .empty-inline {
    margin: 0;
    font-size: var(--type-body-medium-size);
    line-height: var(--type-body-medium-line-height);
    font-weight: var(--type-body-medium-weight);
    letter-spacing: var(--type-body-medium-tracking);
    color: var(--muted);
  }
</style>
