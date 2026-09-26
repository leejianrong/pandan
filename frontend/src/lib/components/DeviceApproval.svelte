<script lang="ts">
  // Consent screen for two OAuth 2.1 grants (ADR 0024/0026): the CLI's device
  // flow (`?user_code=…`, KAN-1729) and, since KAN-1735, a browser-embedded
  // client's authorization_code+PKCE redirect (`?client_id=&redirect_uri=…`) —
  // "the same component... reached via a second entry path" (ADR 0026). Both
  // are reached via a deep link, never through normal in-app navigation (no
  // NavRail/palette entry on purpose: nothing else in the app should navigate
  // here).
  import {
    approveAuthorize,
    approveDeviceAuthorization,
    denyAuthorize,
    denyDeviceAuthorization,
    getAuthorizeInfo,
    getDeviceAuthorization,
    type AuthorizeInfo,
    type AuthorizeParams,
    type DeviceAuthorization,
    type TokenScope,
  } from "../api";
  import { boardStore } from "../board.svelte";
  import { workspaceStore } from "../workspaces.svelte";

  let {
    mode,
    userCode,
    authorizeParams,
    onDone,
  }: {
    mode: "device" | "authorize";
    userCode?: string;
    authorizeParams?: AuthorizeParams;
    onDone: () => void;
  } = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let deviceRequest = $state<DeviceAuthorization | null>(null);
  let authorizeInfo = $state<AuthorizeInfo | null>(null);
  let scope = $state<TokenScope>("write");
  // "All boards you own" is the default — mirrors today's Tokens-UI behaviour
  // (a PAT with no allow-list is unrestricted), so approving without touching
  // this form grants exactly what a Tokens-UI-minted PAT already would.
  let unrestricted = $state(true);
  let selectedBoardIds = $state<Set<number>>(new Set());
  let busy = $state(false);
  // Only ever reached in device mode — authorize mode navigates the browser
  // away (approve()/deny() below) rather than rendering a resolved state here.
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
      if (mode === "device") {
        deviceRequest = await getDeviceAuthorization(userCode!);
        scope = deviceRequest.requested_scope;
        if (deviceRequest.requested_board_ids && deviceRequest.requested_board_ids.length > 0) {
          unrestricted = false;
          selectedBoardIds = new Set(deviceRequest.requested_board_ids);
        }
      } else {
        authorizeInfo = await getAuthorizeInfo(authorizeParams!);
        scope = authorizeInfo.requested_scope;
      }
    } catch {
      // Always the friendly message here, never the raw ApiError detail — a
      // 404/400's detail reads like a lookup bug, not the routine "you
      // typed/opened a stale link" outcome this actually is.
      error =
        mode === "device"
          ? "This code is invalid or has expired — check it against your terminal."
          : "This request is invalid or has expired — go back and try connecting again.";
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
    if (busy) return;
    busy = true;
    error = null;
    const board_ids = unrestricted ? null : [...selectedBoardIds];
    try {
      if (mode === "device") {
        await approveDeviceAuthorization(userCode!, { scope, board_ids });
        resolution = "approved";
      } else {
        // Unlike device mode, this ends the flow by leaving Pandan's UI
        // entirely — a real top-level navigation back to the requesting app.
        const result = await approveAuthorize(authorizeParams!, { scope, board_ids });
        window.location.href = result.redirect_to;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not approve — try again.";
      busy = false;
    }
  }

  async function deny() {
    if (busy) return;
    busy = true;
    error = null;
    try {
      if (mode === "device") {
        await denyDeviceAuthorization(userCode!);
        resolution = "denied";
      } else {
        const result = await denyAuthorize(authorizeParams!);
        window.location.href = result.redirect_to;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not deny — try again.";
      busy = false;
    }
  }
</script>

<div class="device-approval page-view">
  <div class="page-head">
    <div>
      {#if mode === "device"}
        <h2>Approve CLI login</h2>
        <p class="page-sub">
          Someone (hopefully you) ran <code>pandan auth login</code>. Confirm the code
          below matches your terminal, choose what it can access, then approve or deny.
        </p>
      {:else}
        <h2>Connect an application</h2>
        <p class="page-sub">
          <strong>{authorizeInfo?.client_name ?? "An application"}</strong> wants to connect
          to your Pandan account. Choose what it can access, then approve or deny.
        </p>
      {/if}
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
  {:else if mode === "device" && deviceRequest && deviceRequest.status !== "pending"}
    <div class="banner" role="status">
      <span>This code was already {deviceRequest.status}.</span>
    </div>
    <button class="link" onclick={onDone}>Back to your boards</button>
  {:else if (mode === "device" && deviceRequest) || (mode === "authorize" && authorizeInfo)}
    {#if mode === "device" && deviceRequest}
      <p class="device-user-code">
        Code: <code>{deviceRequest.user_code}</code>
      </p>
    {/if}

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
