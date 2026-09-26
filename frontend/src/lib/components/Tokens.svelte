<script lang="ts">
  // Agent personal-access-token management (M3 V9, ADR 0014): create a named
  // token (secret revealed once), see your tokens' metadata, and revoke them.
  import { KeyRound, Link2, Plus, Trash2 } from "lucide-svelte";
  import type { TokenScope } from "../api";
  import {
    addToken,
    dismissRevealed,
    refetchTokens,
    removeToken,
    tokenStore,
  } from "../tokens.svelte";

  let adding = $state(false);
  let name = $state("");
  let scope = $state<TokenScope>("write");
  let busy = $state(false);
  let confirmingId = $state<number | null>(null);
  let copied = $state(false);

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    busy = true;
    try {
      await addToken(trimmed, scope);
      name = "";
      scope = "write";
      adding = false;
    } finally {
      busy = false;
    }
  }

  async function copySecret(secret: string) {
    try {
      await navigator.clipboard.writeText(secret);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      /* clipboard may be unavailable; the secret is visible to copy manually */
    }
  }

  async function revoke(id: number) {
    if (busy) return;
    busy = true;
    try {
      await removeToken(id);
      confirmingId = null;
    } finally {
      busy = false;
    }
  }

  function fmt(iso: string | null): string {
    if (!iso) return "never";
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }
</script>

<div class="tokens-view page-view">
  {#if tokenStore.error}
    <div class="banner error" role="alert">
      <span>{tokenStore.error}</span>
      <button onclick={refetchTokens}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Agent tokens</h2>
      <p class="page-sub">Personal access tokens for the MCP server, CLI and CI.</p>
    </div>
    {#if !adding}
      <button class="btn-add" onclick={() => (adding = true)}>
        <Plus size={15} /> New token
      </button>
    {/if}
  </div>

  <p class="page-intro">
    A token lets an agent (e.g. the MCP server) act as you — it can reach the same
    boards you can. The secret is shown once, so store it somewhere safe.
  </p>

  {#if adding}
    <form
      class="card-form"
      onsubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <input
        placeholder="Token name (required)"
        aria-label="Token name"
        bind:value={name}
      />
      <label class="scope-field">
        <span>Scope</span>
        <select aria-label="Token scope" bind:value={scope}>
          <option value="write">Operator — read &amp; write</option>
          <option value="read">Observer — read-only</option>
        </select>
      </label>
      <p class="scope-hint">
        {scope === "read"
          ? "Observer tokens can list and read only; any write returns 403."
          : "Operator tokens have your full board access (create, edit, move, delete)."}
      </p>
      <div class="row actions">
        <button type="submit" class="primary" disabled={!name.trim() || busy}>Create</button>
        <button type="button" class="link" onclick={() => (adding = false)}>Cancel</button>
      </div>
    </form>
  {/if}

  {#if tokenStore.revealed}
    <div class="token-reveal" role="alert">
      <p class="token-reveal-title">
        Copy your new token <strong>{tokenStore.revealed.name}</strong> now — it won't be shown again.
      </p>
      <div class="token-reveal-row">
        <code class="secret">{tokenStore.revealed.token}</code>
        <button class="primary" onclick={() => copySecret(tokenStore.revealed!.token)}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <button class="link" onclick={dismissRevealed}>Done</button>
    </div>
  {/if}

  {#if tokenStore.loading && tokenStore.tokens.length === 0}
    <p class="hint">Loading…</p>
  {:else if tokenStore.tokens.length === 0}
    <p class="empty">No tokens yet. Create one to let an agent work on your boards.</p>
  {/if}

  <div class="token-list">
    {#each tokenStore.tokens as token (token.id)}
      <div class="token-row card">
        <div class="token-info">
          <div class="token-main">
            <span class="token-icon" aria-hidden="true"><KeyRound size={16} /></span>
            <span class="token-name">{token.client_name ?? token.name}</span>
            {#if token.client_name}
              <span class="token-app-badge" title="Issued to a connected app via OAuth">
                <Link2 size={11} aria-hidden="true" /> connected app
              </span>
            {/if}
            <code class="token-prefix">{token.token_prefix}…</code>
            <span class="token-scope" class:read={token.scope === "read"}>
              {token.scope === "read" ? "observer" : "operator"}
            </span>
          </div>
          <div class="token-meta">
            <span>created <b>{fmt(token.created_at)}</b></span>
            <span>last used <b>{fmt(token.last_used_at)}</b></span>
            <span>expires <b>{fmt(token.expires_at)}</b></span>
          </div>
        </div>
        {#if confirmingId === token.id}
          <div class="token-actions">
            <span class="confirm-msg">Revoke “{token.client_name ?? token.name}”?</span>
            <button class="danger" onclick={() => revoke(token.id)} disabled={busy}>Revoke</button>
            <button class="link" onclick={() => (confirmingId = null)}>Cancel</button>
          </div>
        {:else}
          <div class="token-actions">
            <button
              class="btn-inline-danger"
              aria-label="Revoke"
              onclick={() => (confirmingId = token.id)}
            >
              <Trash2 size={14} /> Revoke
            </button>
          </div>
        {/if}
      </div>
    {/each}
  </div>
</div>
