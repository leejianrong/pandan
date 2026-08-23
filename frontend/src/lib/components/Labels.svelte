<script lang="ts">
  // Board labels panel (V61, KAN-982): list the active board's labels with a swatch
  // and how many cards carry each, create one, rename/recolour in place, and delete
  // with a confirm that names the blast radius.
  //
  // This screen is the gap KAN-982 was filed for. `createLabel`/`deleteLabel` had
  // been sitting in api.ts since M5 V11 with NO component calling either one, so
  // labels could only be created from the CLI or MCP — which is why issue #278's
  // request for a colour picker had nowhere to live.
  //
  // Colour is still a free string here, the mechanism M5 V11 shipped. **V62 (KAN-983)
  // replaces the text input with a swatch grid over ~12 palette tokens** that are
  // defined for both themes, and adds server-side validation; until then the live
  // preview swatch below is what stops a typo from being invisible. Deliberately not
  // pulled forward — which twelve hues, and whether they are disjoint from the
  // semantic tokens, is V62's decision (it is: disjoint).
  //
  // Modelled on Members.svelte: a page view with a create form over a list of
  // mutable rows. Server-authoritative like every mutation — the store refetches
  // cards as well as labels, because a card's `labels` are inlined in its payload.
  import { Check, Plus, Tag, Trash2, X } from "lucide-svelte";
  import { ApiError, type Label } from "../api";
  import {
    activeBoard,
    addLabel,
    boardStore,
    editLabel,
    labelStore,
    refetchLabels,
    removeLabel,
  } from "../board.svelte";

  // The neutral the CLI falls back to (pandan_cli DEFAULT_LABEL_COLOR), so a label
  // made here and one made from the terminal start the same colour.
  const DEFAULT_COLOR = "#94a3b8";

  let adding = $state(false);
  let newName = $state("");
  let newColor = $state(DEFAULT_COLOR);
  let busy = $state(false);
  let formError = $state<string | null>(null);

  // Inline edit state: at most one row is editable at a time, which keeps "discard
  // on cancel" unambiguous and avoids a save-all button nobody looks for.
  let editingId = $state<number | null>(null);
  let editName = $state("");
  let editColor = $state("");
  let confirmingId = $state<number | null>(null);

  // Labels are board-scoped: (re)load whenever the active board changes. Runs on
  // mount too, since this component only mounts when the view is open.
  $effect(() => {
    boardStore.activeBoardId;
    refetchLabels();
  });

  async function submit() {
    const name = newName.trim();
    const color = newColor.trim();
    if (!name || !color || busy) return;
    busy = true;
    formError = null;
    try {
      await addLabel(name, color);
      newName = "";
      newColor = DEFAULT_COLOR;
      adding = false;
    } catch (e) {
      formError = e instanceof ApiError ? e.message : "Failed to create label";
    } finally {
      busy = false;
    }
  }

  function startEdit(label: Label) {
    editingId = label.id;
    editName = label.name;
    editColor = label.color;
    confirmingId = null;
    formError = null;
  }

  function cancelEdit() {
    editingId = null;
    formError = null;
  }

  async function saveEdit(label: Label) {
    const name = editName.trim();
    const color = editColor.trim();
    if (!name || !color || busy) return;
    // Send only what actually changed, so a rename never rewrites the colour (and a
    // no-op save is a no-op request rather than a pointless PATCH).
    const patch: { name?: string; color?: string } = {};
    if (name !== label.name) patch.name = name;
    if (color !== label.color) patch.color = color;
    if (Object.keys(patch).length === 0) {
      editingId = null;
      return;
    }
    busy = true;
    formError = null;
    try {
      await editLabel(label.id, patch);
      editingId = null;
    } catch (e) {
      formError = e instanceof ApiError ? e.message : "Failed to update label";
    } finally {
      busy = false;
    }
  }

  async function remove(id: number) {
    if (busy) return;
    busy = true;
    formError = null;
    try {
      await removeLabel(id);
      confirmingId = null;
    } catch (e) {
      formError = e instanceof ApiError ? e.message : "Failed to delete label";
    } finally {
      busy = false;
    }
  }

  // "on 3 cards" / "on 1 card" / "unused" — the delete confirm needs the count in
  // words, since detaching from cards is the part that isn't undoable.
  function usage(label: Label): string {
    const n = label.usage_count ?? 0;
    if (n === 0) return "unused";
    return n === 1 ? "on 1 card" : `on ${n} cards`;
  }
</script>

<div class="labels-view page-view">
  {#if labelStore.error}
    <div class="banner error" role="alert">
      <span>{labelStore.error}</span>
      <button onclick={refetchLabels}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Labels</h2>
      <p class="page-sub">
        Coloured tags on <b>{activeBoard()?.name ?? "this board"}</b>.
      </p>
    </div>
    {#if !adding}
      <button class="btn-add" onclick={() => { adding = true; formError = null; }}>
        <Plus size={15} /> New label
      </button>
    {/if}
  </div>

  <p class="page-intro">
    Labels are board-scoped. Attach them to cards from the card form; rename or
    recolour one here and every card carrying it updates. Deleting a label removes it
    from every card that had it.
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
      <input placeholder="Label name (required)" aria-label="Label name" bind:value={newName} />
      <div class="row">
        <span
          class="swatch"
          style="background: {newColor}"
          aria-hidden="true"
          data-testid="new-label-preview"
        ></span>
        <input
          class="color-input"
          placeholder="#0ea5e9"
          aria-label="Label color"
          bind:value={newColor}
        />
      </div>
      <div class="row actions">
        <button type="submit" class="primary" disabled={!newName.trim() || !newColor.trim() || busy}>
          <Tag size={14} /> Create
        </button>
        <button type="button" class="link" onclick={() => { adding = false; formError = null; }}>
          Cancel
        </button>
      </div>
    </form>
  {/if}

  {#if labelStore.loading && labelStore.labels.length === 0}
    <p class="hint">Loading…</p>
  {:else if labelStore.labels.length === 0}
    <p class="empty">No labels yet. Create one to start tagging cards.</p>
  {/if}

  <div class="token-list">
    {#each labelStore.labels as label (label.id)}
      <div class="label-row card" data-label-id={label.id}>
        {#if editingId === label.id}
          <form
            class="label-edit"
            onsubmit={(e) => {
              e.preventDefault();
              saveEdit(label);
            }}
          >
            <span class="swatch" style="background: {editColor}" aria-hidden="true"></span>
            <input aria-label="Label name" bind:value={editName} />
            <input class="color-input" aria-label="Label color" bind:value={editColor} />
            <button
              type="submit"
              class="primary"
              disabled={!editName.trim() || !editColor.trim() || busy}
            >
              <Check size={14} /> Save
            </button>
            <button type="button" class="link" onclick={cancelEdit}>
              <X size={14} /> Cancel
            </button>
          </form>
        {:else}
          <div class="label-info">
            <span class="swatch" style="background: {label.color}" aria-hidden="true"></span>
            <span class="label-name">{label.name}</span>
            <span class="label-usage">{usage(label)}</span>
          </div>
          <div class="label-actions">
            {#if confirmingId === label.id}
              <span class="confirm-msg">
                Delete “{label.name}”? It detaches from every card ({usage(label)}).
              </span>
              <button class="danger" onclick={() => remove(label.id)} disabled={busy}>
                Delete
              </button>
              <button class="link" onclick={() => (confirmingId = null)}>Cancel</button>
            {:else}
              <button
                class="btn-inline"
                aria-label="Edit {label.name}"
                onclick={() => startEdit(label)}
              >
                Edit
              </button>
              <button
                class="btn-inline-danger"
                aria-label="Delete {label.name}"
                onclick={() => { confirmingId = label.id; editingId = null; }}
              >
                <Trash2 size={14} /> Delete
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>
</div>

<style>
  .label-row.card {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: 0.75rem 1rem;
    padding: 0.9rem 1.1rem;
  }
  .label-info {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-width: 0;
  }
  .label-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .label-usage {
    color: var(--muted);
    font-size: 0.8rem;
    flex: none;
  }
  .label-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  /* The swatch is the only preview of a free-form colour string, so it must be
     visible against both themes' card background — hence the hairline border
     rather than relying on the fill alone (a near-background colour would
     otherwise render as nothing at all). V62 makes this moot for new picks. */
  .swatch {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 1px solid var(--border);
    flex: none;
  }
  .label-edit {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .label-edit input {
    min-width: 0;
    flex: 1 1 8rem;
  }
  .color-input {
    font-family: var(--mono);
    flex: 0 1 9rem;
  }
</style>
