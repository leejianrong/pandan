<script lang="ts">
  // Board members panel (KAN-14): list the active board's members, add one by
  // email with a role, change a member's role, and remove them. Wires to the
  // KAN-12 members API (owner-gated — a 403 surfaces gracefully). Modelled on the
  // Tokens view: a top-bar view with a create form + a list of mutable rows.
  import { Plus, Trash2, UserPlus, Users } from "lucide-svelte";
  import { ApiError, type Role } from "../api";
  import { boardStore, activeBoard } from "../board.svelte";
  import {
    changeMemberRole,
    inviteMember,
    kickMember,
    memberStore,
    refetchMembers,
  } from "../members.svelte";

  const ROLES: Role[] = ["viewer", "editor", "owner"];

  let adding = $state(false);
  let email = $state("");
  let role = $state<Role>("viewer");
  let busy = $state(false);
  let formError = $state<string | null>(null);
  let confirmingId = $state<number | null>(null);

  // Members are board-scoped: (re)load whenever the active board changes (this
  // runs on mount too, since the component only mounts when the view is open).
  $effect(() => {
    boardStore.activeBoardId;
    refetchMembers();
  });

  async function submit() {
    const trimmed = email.trim();
    if (!trimmed || busy) return;
    busy = true;
    formError = null;
    try {
      await inviteMember(trimmed, role);
      email = "";
      role = "viewer";
      adding = false;
    } catch (e) {
      formError = e instanceof ApiError ? e.message : "Failed to add member";
    } finally {
      busy = false;
    }
  }

  async function onRoleChange(memberId: number, next: Role) {
    if (busy) return;
    busy = true;
    formError = null;
    try {
      await changeMemberRole(memberId, next);
    } catch (e) {
      formError = e instanceof ApiError ? e.message : "Failed to change role";
      await refetchMembers(); // snap back to the authoritative role on failure
    } finally {
      busy = false;
    }
  }

  async function remove(memberId: number) {
    if (busy) return;
    busy = true;
    formError = null;
    try {
      await kickMember(memberId);
      confirmingId = null;
    } catch (e) {
      formError = e instanceof ApiError ? e.message : "Failed to remove member";
    } finally {
      busy = false;
    }
  }
</script>

<div class="members-view page-view">
  {#if memberStore.error}
    <div class="banner error" role="alert">
      <span>{memberStore.error}</span>
      <button onclick={refetchMembers}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Members</h2>
      <p class="page-sub">
        People with access to <b>{activeBoard()?.name ?? "this board"}</b>.
      </p>
    </div>
    {#if !adding}
      <button class="btn-add" onclick={() => { adding = true; formError = null; }}>
        <Plus size={15} /> Add member
      </button>
    {/if}
  </div>

  <p class="page-intro">
    Add a member by their email (they must already have signed in at least once),
    then set whether they can view or edit. Only the board owner can manage members.
  </p>

  {#if formError}
    <div class="banner error" role="alert">
      <span>{formError}</span>
    </div>
  {/if}

  {#if adding}
    <form
      class="card-form"
      onsubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <input
        type="email"
        placeholder="Member email (required)"
        aria-label="Member email"
        bind:value={email}
      />
      <div class="row">
        <select aria-label="Role" bind:value={role}>
          {#each ROLES as r}
            <option value={r}>{r}</option>
          {/each}
        </select>
      </div>
      <div class="row actions">
        <button type="submit" class="primary" disabled={!email.trim() || busy}>
          <UserPlus size={14} /> Add
        </button>
        <button type="button" class="link" onclick={() => { adding = false; formError = null; }}>
          Cancel
        </button>
      </div>
    </form>
  {/if}

  {#if memberStore.loading && memberStore.members.length === 0}
    <p class="hint">Loading…</p>
  {:else if memberStore.members.length === 0}
    <p class="empty">No members yet. Add one to share this board.</p>
  {/if}

  <div class="token-list">
    {#each memberStore.members as member (member.id)}
      <div class="member-row card">
        <div class="member-info">
          <span class="member-icon" aria-hidden="true"><Users size={16} /></span>
          <span class="member-email">{member.email ?? member.user_id}</span>
        </div>
        <div class="member-actions">
          <label class="role-select">
            <span class="sr-only">Role for {member.email ?? member.user_id}</span>
            <select
              value={member.role}
              disabled={busy}
              onchange={(e) => onRoleChange(member.id, e.currentTarget.value as Role)}
            >
              {#each ROLES as r}
                <option value={r}>{r}</option>
              {/each}
            </select>
          </label>
          {#if confirmingId === member.id}
            <span class="confirm-msg">Remove?</span>
            <button class="danger" onclick={() => remove(member.id)} disabled={busy}>Remove</button>
            <button class="link" onclick={() => (confirmingId = null)}>Cancel</button>
          {:else}
            <button
              class="btn-inline-danger"
              aria-label="Remove member"
              onclick={() => (confirmingId = member.id)}
            >
              <Trash2 size={14} /> Remove
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
</div>

<style>
  .member-row.card {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: 0.75rem 1rem;
    padding: 0.9rem 1.1rem;
  }
  .member-info {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-width: 0;
  }
  .member-icon {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border-radius: var(--shape-small);
    background: var(--agent-soft);
    color: var(--agent);
    flex: none;
  }
  .member-email {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .member-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .role-select select {
    text-transform: capitalize;
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
</style>
