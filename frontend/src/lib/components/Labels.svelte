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
  // Colour is a PALETTE PICK, not a free string (V62, KAN-983 — "the palette is the
  // picker", SHAPING D11). The swatch grid below offers the seven `--label-*` tokens
  // from app.css, each defined for both themes; the server independently validates
  // "palette token or well-formed hex" so the CLI and MCP cannot store a colour the
  // UI would render as a blank dot.
  //
  // Seven, not the shape's "~12": the palette is disjoint from the semantic tokens AND
  // from Card.svelte's priority dots, measured in CIE Lab ΔE rather than eyeballed — a
  // first hand-picked set of nine had three members that were status colours wearing
  // different names. See backend/app/palette.py for the numbers.
  //
  // A label created before V62 may carry any old string. Such a value keeps rendering
  // (there is no value migration) and appears in the grid as a leading "custom"
  // swatch, so editing its NAME never silently recolours it.
  //
  // Modelled on Members.svelte: a page view with a create form over a list of
  // mutable rows. Server-authoritative like every mutation — the store refetches
  // cards as well as labels, because a card's `labels` are inlined in its payload.
  import { Check, Plus, Tag, Trash2, X } from "lucide-svelte";
  import {
    ApiError,
    DEFAULT_LABEL_COLOR,
    LABEL_PALETTE,
    labelColor,
    type Label,
  } from "../api";
  import {
    activeBoard,
    addLabel,
    boardStore,
    editLabel,
    labelStore,
    refetchLabels,
    removeLabel,
  } from "../board.svelte";

  // The palette token the CLI's `label create` also falls back to, so a label made
  // here and one made from the terminal start the same colour. Both now name the same
  // constant instead of each hardcoding a hex and claiming it matched the other's.
  const DEFAULT_COLOR: string = DEFAULT_LABEL_COLOR;

  // The grid for a given current value: the seven palette tokens, plus the current
  // value itself when it is NOT one of them. That extra leading swatch is what makes
  // a pre-V62 colour visible and selectable rather than silently unrepresented — with
  // no such option, no radio would be checked and the row would look unset.
  function optionsFor(current: string): string[] {
    const tokens = LABEL_PALETTE as readonly string[];
    return tokens.includes(current) || !current
      ? [...tokens]
      : [current, ...tokens];
  }

  // A swatch's accessible name. Tokens are their own name; a legacy value is
  // announced as custom so it is not mistaken for a tenth hue.
  function swatchLabel(color: string): string {
    return (LABEL_PALETTE as readonly string[]).includes(color)
      ? color
      : `custom (${color})`;
  }

  let adding = $state(false);
  let newName = $state("");
  let newColor = $state(DEFAULT_COLOR);
  // A second, independent visual dimension (M8 V64, KAN-985) — free text, since
  // unlike colour there is no fixed palette; any single grapheme is valid and the
  // server is the source of truth for that. Optional, so "" means "no emoji".
  let newEmoji = $state("");
  let busy = $state(false);
  let formError = $state<string | null>(null);

  // Inline edit state: at most one row is editable at a time, which keeps "discard
  // on cancel" unambiguous and avoids a save-all button nobody looks for.
  let editingId = $state<number | null>(null);
  let editName = $state("");
  let editColor = $state("");
  let editEmoji = $state("");
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
      await addLabel(name, color, newEmoji.trim() || null);
      newName = "";
      newColor = DEFAULT_COLOR;
      newEmoji = "";
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
    editEmoji = label.emoji ?? "";
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
    const emoji = editEmoji.trim();
    if (!name || !color || busy) return;
    // Send only what actually changed, so a rename never rewrites the colour (and a
    // no-op save is a no-op request rather than a pointless PATCH).
    const patch: { name?: string; color?: string; emoji?: string | null } = {};
    if (name !== label.name) patch.name = name;
    if (color !== label.color) patch.color = color;
    if (emoji !== (label.emoji ?? "")) patch.emoji = emoji || null;
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

<!-- The picker (V62, KAN-983). Real <input type="radio"> elements rather than a
     div-with-role: a native radiogroup gives arrow-key navigation, roving focus and
     screen-reader semantics for free, and "pick one of seven" is exactly what a radio
     group is. The visible swatch is the <label>; the input itself is clipped rather
     than `display: none`, which would take it out of the tab order. -->
<!-- No separate preview swatch beside the grid: the selected swatch's ring IS the
     preview, and a duplicate of it sitting alongside read as an extra, eighth
     option. (V61 needed one because the colour was free text with nothing showing
     what a typo produced.) -->
{#snippet swatches(group: string, current: string, pick: (color: string) => void)}
  <div class="swatch-grid" role="group" aria-label="Label colour">
    {#each optionsFor(current) as color (color)}
      <label class="swatch-opt" title={swatchLabel(color)}>
        <input
          type="radio"
          name={group}
          value={color}
          checked={current === color}
          onchange={() => pick(color)}
        />
        <span
          class="swatch swatch-pick"
          style="background: {labelColor(color)}"
          aria-hidden="true"
        ></span>
        <span class="sr-only">{swatchLabel(color)}</span>
      </label>
    {/each}
  </div>
{/snippet}

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
      <div class="row colour-row">
        {@render swatches("new-label-color", newColor, (c) => (newColor = c))}
        <input
          class="emoji-input"
          placeholder="Emoji (optional)"
          aria-label="Label emoji"
          maxlength="8"
          bind:value={newEmoji}
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
            <input aria-label="Label name" bind:value={editName} />
            {@render swatches(`label-${label.id}-color`, editColor, (c) => (editColor = c))}
            <input
              class="emoji-input"
              placeholder="Emoji (optional)"
              aria-label="Label emoji"
              maxlength="8"
              bind:value={editEmoji}
            />
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
            {#if label.emoji}
              <span class="label-emoji" aria-hidden="true">{label.emoji}</span>
            {/if}
            <span
              class="swatch"
              style="background: {labelColor(label.color)}"
              aria-hidden="true"
            ></span>
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
  /* The emoji field (M8 V64, KAN-985) is a single grapheme, not a sentence — a
     narrow fixed width reads as "this field is different" without needing a
     label, and stops it competing with the name input for flex space.
     `.label-edit .emoji-input` beats the plain-element `.label-edit input`
     rule above on specificity, no `!important` needed. */
  .emoji-input {
    flex: 0 0 5.5rem;
    text-align: center;
  }
  .label-edit .emoji-input {
    flex: 0 0 5.5rem;
  }
  .label-emoji {
    font-size: 1rem;
    line-height: 1;
    flex: none;
  }
  /* The swatch grid (V62). Wraps, because the edit row shares one flex line with the
     name input and the save/cancel buttons — and a legacy colour adds a tenth
     option, so the count is not fixed. */
  .swatch-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-items: center;
  }
  .swatch-opt {
    display: inline-flex;
    cursor: pointer;
    line-height: 0;
  }
  /* Clipped, not hidden: `display: none` would drop the radio out of the tab order
     and take the native arrow-key group with it, which is the whole reason these are
     real inputs. Focus is shown on the sibling swatch via :has() below. */
  .swatch-opt input {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    border: 0;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .swatch-pick {
    width: 22px;
    height: 22px;
    transition: transform 120ms ease;
  }
  .swatch-opt:hover .swatch-pick {
    transform: scale(1.12);
  }
  /* Selection is a ring in the text colour rather than a tick glyph: at 22px a tick
     would sit on top of the very hue being judged, and the ring reads on all seven
     swatches in both themes. */
  .swatch-opt:has(input:checked) .swatch-pick {
    box-shadow: 0 0 0 2px var(--card-bg), 0 0 0 4px var(--text);
  }
  .swatch-opt:has(input:focus-visible) .swatch-pick {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
  }
  .colour-row {
    gap: 0.6rem;
    flex-wrap: wrap;
  }
  /* Each swatch's accessible name. Svelte styles are component-scoped, so this is a
     local copy of ViewSwitcher's rule rather than a shared utility — the same trade
     that file already made. It is what a radio's accessible name comes from, so it
     must stay in the a11y tree: clipped, never `display: none`. */
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
  @media (prefers-reduced-motion: reduce) {
    .swatch-pick {
      transition: none;
    }
    .swatch-opt:hover .swatch-pick {
      transform: none;
    }
  }
</style>
