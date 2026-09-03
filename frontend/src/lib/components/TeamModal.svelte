<script lang="ts">
  import { untrack } from "svelte";
  import { Plus, Trash2, UserPlus, X } from "lucide-svelte";
  import { ApiError, type Role } from "../api";
  import { boardStore } from "../board.svelte";
  import {
    changeTeamMemberRole,
    editTeam,
    inviteTeamMember,
    kickTeamMember,
    refetchTeamMembers,
    removeTeam,
    teamMemberStore,
    teamStore,
  } from "../teams.svelte";
  import Modal from "./Modal.svelte";

  // Team detail: rename/delete + full member management (add/re-role/remove),
  // plus a read-only list of the team's boards. Mirrors EpicModal's shape (name
  // edit + rollup) crossed with Members.svelte's inline management UI, since a
  // team's membership — unlike an epic's stories — is mutable from right here.
  let { teamId, onclose }: { teamId: number; onclose: () => void } = $props();

  const team = $derived(teamStore.teams.find((t) => t.id === teamId));
  $effect(() => {
    if (team == null) onclose();
  });
  const isOwner = $derived(team?.role === "owner");

  // Members are loaded fresh every time the modal opens — the grid's preview
  // list is best-effort, this is the authoritative one the mutations act on.
  $effect(() => {
    refetchTeamMembers(teamId);
  });

  const boards = $derived(boardStore.boards.filter((b) => b.team_id === teamId));

  const ROLES: Role[] = ["viewer", "editor", "owner"];

  const initialName = untrack(() => team?.name ?? "");
  let name = $state(initialName);
  let submitting = $state(false);
  let renameError = $state<string | null>(null);
  const dirty = $derived(name.trim() !== initialName);
  const canSubmit = $derived(name.trim().length > 0 && dirty && !submitting);

  async function submitRename(e: SubmitEvent) {
    e.preventDefault();
    if (!canSubmit || !team) return;
    submitting = true;
    renameError = null;
    try {
      await editTeam(team.id, name.trim());
    } catch (e) {
      renameError = e instanceof Error ? e.message : "Failed to rename team";
    } finally {
      submitting = false;
    }
  }

  let confirmingDelete = $state(false);
  let deleting = $state(false);
  let deleteError = $state<string | null>(null);
  async function confirmDelete() {
    if (!team) return;
    deleting = true;
    deleteError = null;
    try {
      await removeTeam(team.id);
      onclose();
    } catch (e) {
      deleteError = e instanceof Error ? e.message : "Failed to delete team";
      deleting = false;
    }
  }

  let addingMember = $state(false);
  let memberEmail = $state("");
  let memberRole = $state<Role>("viewer");
  let memberBusy = $state(false);
  let memberError = $state<string | null>(null);
  let confirmingRemoveId = $state<number | null>(null);

  async function submitAddMember() {
    const trimmed = memberEmail.trim();
    if (!trimmed || memberBusy) return;
    memberBusy = true;
    memberError = null;
    try {
      await inviteTeamMember(teamId, trimmed, memberRole);
      memberEmail = "";
      memberRole = "viewer";
      addingMember = false;
    } catch (e) {
      memberError = e instanceof ApiError ? e.message : "Failed to add member";
    } finally {
      memberBusy = false;
    }
  }

  async function onMemberRoleChange(memberId: number, next: Role) {
    if (memberBusy) return;
    memberBusy = true;
    memberError = null;
    try {
      await changeTeamMemberRole(teamId, memberId, next);
    } catch (e) {
      memberError = e instanceof ApiError ? e.message : "Failed to change role";
      await refetchTeamMembers(teamId); // snap back on failure (e.g. last-owner 409)
    } finally {
      memberBusy = false;
    }
  }

  async function removeMemberRow(memberId: number) {
    if (memberBusy) return;
    memberBusy = true;
    memberError = null;
    try {
      await kickTeamMember(teamId, memberId);
      confirmingRemoveId = null;
    } catch (e) {
      memberError = e instanceof ApiError ? e.message : "Failed to remove member";
    } finally {
      memberBusy = false;
    }
  }
</script>

{#if team}
  <Modal label="Team: {team.name}" {onclose}>
    <form class="card-form card-modal" onsubmit={submitRename}>
      <header class="modal-head">
        <span class="ticket">Team</span>
        <span class="epic-count">
          {boards.length} {boards.length === 1 ? "board" : "boards"}
        </span>
        <button
          type="button"
          class="icon-btn modal-close"
          title="Close"
          aria-label="Close"
          onclick={onclose}
        >
          <X size={18} />
        </button>
      </header>

      <div class="modal-scroll">
        <div class="modal-main epic-modal-main">
          <input
            class="modal-title-input"
            type="text"
            placeholder="Team name (required)"
            aria-label="Team name"
            bind:value={name}
            disabled={!isOwner}
          />
          {#if renameError}<p class="form-error" role="alert">{renameError}</p>{/if}
          {#if !isOwner}
            <p class="page-intro">Only an owner-role member can rename or delete this team.</p>
          {/if}

          <div class="epic-rollup-block">
            <span class="field-label">Members</span>
            {#if memberError}<p class="form-error" role="alert">{memberError}</p>{/if}

            {#if isOwner}
              {#if addingMember}
                <div class="member-add-row">
                  <input
                    type="email"
                    placeholder="Member email"
                    aria-label="Member email"
                    bind:value={memberEmail}
                  />
                  <select aria-label="Role" bind:value={memberRole}>
                    {#each ROLES as r}
                      <option value={r}>{r}</option>
                    {/each}
                  </select>
                  <button
                    type="button"
                    class="primary"
                    onclick={submitAddMember}
                    disabled={!memberEmail.trim() || memberBusy}
                  >
                    <UserPlus size={14} /> Add
                  </button>
                  <button
                    type="button"
                    class="link"
                    onclick={() => {
                      addingMember = false;
                      memberError = null;
                    }}
                  >
                    Cancel
                  </button>
                </div>
              {:else}
                <button
                  type="button"
                  class="link"
                  onclick={() => {
                    addingMember = true;
                    memberError = null;
                  }}
                >
                  <Plus size={14} /> Add member
                </button>
              {/if}
            {/if}

            {#if teamMemberStore.loading && teamMemberStore.members.length === 0}
              <p class="hint">Loading…</p>
            {:else if teamMemberStore.members.length === 0}
              <p class="comment-empty">No members yet.</p>
            {:else}
              <ul class="epic-stories">
                {#each teamMemberStore.members as member (member.id)}
                  <li class="member-row-modal">
                    <span class="stitle">{member.email ?? member.user_id}</span>
                    {#if isOwner}
                      <select
                        aria-label="Role for {member.email ?? member.user_id}"
                        value={member.role}
                        disabled={memberBusy}
                        onchange={(e) =>
                          onMemberRoleChange(member.id, e.currentTarget.value as Role)}
                      >
                        {#each ROLES as r}
                          <option value={r}>{r}</option>
                        {/each}
                      </select>
                      {#if confirmingRemoveId === member.id}
                        <button
                          type="button"
                          class="danger"
                          onclick={() => removeMemberRow(member.id)}
                          disabled={memberBusy}
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          class="link"
                          onclick={() => (confirmingRemoveId = null)}
                        >
                          Cancel
                        </button>
                      {:else}
                        <button
                          type="button"
                          class="btn-inline-danger"
                          aria-label="Remove {member.email ?? member.user_id}"
                          onclick={() => (confirmingRemoveId = member.id)}
                        >
                          <Trash2 size={13} />
                        </button>
                      {/if}
                    {:else}
                      <span class="member-role">{member.role}</span>
                    {/if}
                  </li>
                {/each}
              </ul>
            {/if}
          </div>

          <div class="epic-rollup-block">
            <span class="field-label">Boards</span>
            {#if boards.length === 0}
              <p class="comment-empty">No boards linked yet. Link one from the board switcher's Team picker.</p>
            {:else}
              <ul class="epic-stories">
                {#each boards as board (board.id)}
                  <li>
                    <span class="ticket">{board.key}</span>
                    <span class="stitle">{board.name}</span>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        </div>
      </div>

      {#if isOwner}
        <footer class="modal-foot">
          {#if confirmingDelete}
            <span class="confirm-msg">
              Delete "{team.name}"? Its members lose access, and its
              {boards.length} {boards.length === 1 ? "board" : "boards"} become unclaimed
              (not deleted).
            </span>
            <button type="button" class="danger" onclick={confirmDelete} disabled={deleting}>
              Delete
            </button>
            <button
              type="button"
              class="link"
              onclick={() => (confirmingDelete = false)}
              disabled={deleting}
            >
              Keep
            </button>
          {:else}
            <button type="submit" class="primary" disabled={!canSubmit}>Save changes</button>
            <button type="button" class="link" onclick={onclose}>Cancel</button>
            <button
              type="button"
              class="btn-inline-danger modal-delete"
              onclick={() => (confirmingDelete = true)}
            >
              <Trash2 size={15} /> Delete
            </button>
          {/if}
        </footer>
        {#if deleteError}<p class="form-error" role="alert">{deleteError}</p>{/if}
      {/if}
    </form>
  </Modal>
{/if}

<style>
  .member-add-row {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
  }
  .member-row-modal {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .member-role {
    font-size: var(--type-label-medium-size);
    line-height: var(--type-label-medium-line-height);
    font-weight: var(--type-label-medium-weight);
    letter-spacing: var(--type-label-medium-tracking);
    color: var(--muted);
    text-transform: capitalize;
  }
</style>
