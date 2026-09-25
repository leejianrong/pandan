<script lang="ts">
  // Device-flow consent screen (ADR 0024, KAN-1729) — reached via a deep link
  // (`?user_code=…`) the CLI's `pandan auth login` prints/opens, never through
  // normal in-app navigation (no NavRail/palette entry on purpose: nothing else
  // in the app should navigate here).
  import {
    approveDeviceAuthorization,
    denyDeviceAuthorization,
    getDeviceAuthorization,
    type DeviceAuthorization,
    type TokenScope,
  } from "../api";
  import { boardStore } from "../board.svelte";
  import { workspaceStore } from "../workspaces.svelte";

  let { userCode, onDone }: { userCode: string; onDone: () => void } = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let request = $state<DeviceAuthorization | null>(null);
  let scope = $state<TokenScope>("write");
  // "All boards you own" is the default — mirrors today's Tokens-UI behaviour
  // (a PAT with no allow-list is unrestricted), so approving without touching
  // this form grants exactly what a Tokens-UI-minted PAT already would.
  let unrestricted = $state(true);
  let selectedBoardIds = $state<Set<number>>(new Set());
  let busy = $state(false);
  let resolution = $state<"approved" | "denied" | null>(null);

  // The approve endpoint only accepts boards the approving principal OWNS
  // (narrower than "can access" — see backend/app/routers/device_auth.py's
  // `_reject_unowned_boards`), so the picker only ever offers those.
  const ownedBoards = $derived(boardStore.boards.filter((b) => b.role === "owner"));

  load();

  async function load() {
    loading = true;
    error = null;
    try {
      request = await getDeviceAuthorization(userCode);
      scope = request.requested_scope;
      if (request.requested_board_ids && request.requested_board_ids.length > 0) {
        unrestricted = false;
        selectedBoardIds = new Set(request.requested_board_ids);
      }
    } catch {
      // Always the friendly message here, never the raw ApiError detail — a
      // 404's "Code not found" reads like a lookup bug, not the routine "you
      // typed/opened a stale link" outcome this actually is.
      error = "This code is invalid or has expired — check it against your terminal.";
    } finally {
      loading = false;
    }
  }

  function toggleBoard(id: number) {
    const next = new Set(selectedBoardIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedBoardIds = next;
  }

  function selectWorkspace(workspaceId: number) {
    const ids = ownedBoards.filter((b) => b.workspace_id === workspaceId).map((b) => b.id);
    selectedBoardIds = new Set([...selectedBoardIds, ...ids]);
  }

  async function approve() {
    if (busy || !request) return;
    busy = true;
    error = null;
    try {
      await approveDeviceAuthorization(userCode, {
        scope,
        board_ids: unrestricted ? null : [...selectedBoardIds],
      });
      resolution = "approved";
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not approve — try again.";
    } finally {
      busy = false;
    }
  }

  async function deny() {
    if (busy || !request) return;
    busy = true;
    error = null;
    try {
      await denyDeviceAuthorization(userCode);
      resolution = "denied";
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not deny — try again.";
    } finally {
      busy = false;
    }
  }
</script>

<div class="device-approval page-view">
  <div class="page-head">
    <div>
      <h2>Approve CLI login</h2>
      <p class="page-sub">
        Someone (hopefully you) ran <code>pandan auth login</code>. Confirm the code
        below matches your terminal, choose what it can access, then approve or deny.
      </p>
    </div>
  </div>

  {#if loading}
    <p class="hint">Loading…</p>
  {:else if resolution === "approved"}
    <div class="banner" role="status">
      <span>Approved — go back to your terminal, it will finish logging in automatically.</span>
    </div>
    <button class="link" onclick={onDone}>Back to your boards</button>
  {:else if resolution === "denied"}
    <div class="banner" role="status">
      <span>Denied — the CLI login was not completed.</span>
    </div>
    <button class="link" onclick={onDone}>Back to your boards</button>
  {:else if error}
    <div class="banner error" role="alert">
      <span>{error}</span>
    </div>
    <button class="link" onclick={onDone}>Back to your boards</button>
  {:else if request && request.status !== "pending"}
    <div class="banner" role="status">
      <span>This code was already {request.status}.</span>
    </div>
    <button class="link" onclick={onDone}>Back to your boards</button>
  {:else if request}
    <p class="device-user-code">
      Code: <code>{request.user_code}</code>
    </p>

    <form
      class="card-form"
      onsubmit={(e) => {
        e.preventDefault();
        approve();
      }}
    >
      <label class="scope-field">
        <span>Scope</span>
        <select aria-label="Scope" bind:value={scope}>
          <option value="write">Operator — read &amp; write</option>
          <option value="read">Observer — read-only</option>
        </select>
      </label>
      <p class="scope-hint">
        {scope === "read"
          ? "Observer: this login can list and read only; any write returns 403."
          : "Operator: this login has full access to the boards below (create, edit, move, delete)."}
      </p>

      <fieldset class="board-picker">
        <legend>Boards</legend>
        <label class="board-picker-all">
          <input type="checkbox" bind:checked={unrestricted} />
          All boards you own
        </label>
        {#if !unrestricted}
          {#if workspaceStore.workspaces.length > 0}
            <div class="board-picker-workspaces">
              {#each workspaceStore.workspaces as ws (ws.id)}
                <button type="button" class="link" onclick={() => selectWorkspace(ws.id)}>
                  Select all of “{ws.name}”
                </button>
              {/each}
            </div>
          {/if}
          <div class="board-picker-list">
            {#each ownedBoards as b (b.id)}
              <label>
                <input
                  type="checkbox"
                  checked={selectedBoardIds.has(b.id)}
                  onchange={() => toggleBoard(b.id)}
                />
                {b.name}
              </label>
            {:else}
              <p class="empty">You don't own any boards yet.</p>
            {/each}
          </div>
        {/if}
      </fieldset>

      <div class="row actions">
        <button
          type="submit"
          class="primary"
          disabled={busy || (!unrestricted && selectedBoardIds.size === 0)}
        >
          Approve
        </button>
        <button type="button" class="danger" onclick={deny} disabled={busy}>Deny</button>
      </div>
    </form>
  {/if}
</div>

<style>
  .device-user-code {
    font-size: 1.1rem;
    margin: 0 0 1rem;
  }
  .device-user-code code {
    font-weight: 600;
    letter-spacing: 0.05em;
    background: var(--surface-2);
    padding: 0.15rem 0.5rem;
    border-radius: var(--shape-extra-small);
  }
  .board-picker {
    border: 1px solid var(--border);
    border-radius: var(--shape-small);
    padding: 0.75rem 1rem;
    margin: 0 0 1rem;
  }
  .board-picker legend {
    padding: 0 0.4rem;
    font-weight: 600;
  }
  .board-picker-all {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 500;
  }
  .board-picker-workspaces {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin: 0.5rem 0;
  }
  .board-picker-list {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-top: 0.5rem;
    max-height: 14rem;
    overflow-y: auto;
  }
  .board-picker-list label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
</style>
