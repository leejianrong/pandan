<script lang="ts">
  import { untrack } from "svelte";
  import type { Epic } from "../api";
  import { addEpic, editEpic } from "../board.svelte";
  import { displayRef } from "../tickets";
  import EpicColorPicker from "./EpicColorPicker.svelte";

  // Create mode: no `epic`. Edit mode: pass `epic`. Mirrors CardForm (ADR 0009).
  let {
    epic,
    onclose,
  }: {
    epic?: Epic;
    onclose: () => void;
  } = $props();

  const { isEdit, iName, iDesc, iColor } = untrack(() => ({
    isEdit: !!epic,
    iName: epic?.name ?? "",
    iDesc: epic?.description ?? "",
    iColor: epic?.color ?? null,
  }));

  let name = $state(iName);
  let description = $state(iDesc);
  let color = $state<string | null>(iColor);
  let submitting = $state(false);
  let error = $state<string | null>(null);

  const dirty = $derived(
    name.trim() !== iName || description.trim() !== iDesc || color !== iColor,
  );
  const canSubmit = $derived(
    name.trim().length > 0 && (!isEdit || dirty) && !submitting,
  );

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    submitting = true;
    error = null;
    const fields = { name: name.trim(), description: description.trim() || null, color };
    try {
      if (isEdit) {
        await editEpic(epic!.id, fields);
      } else {
        await addEpic(fields);
      }
      onclose();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to save epic";
    } finally {
      submitting = false;
    }
  }
</script>

<form class="card-form" onsubmit={submit}>
  {#if isEdit}
    <span class="ticket" title={epic!.ticket_number}>{displayRef(epic!)}</span>
  {/if}
  <!-- svelte-ignore a11y_autofocus -->
  <input type="text" placeholder="Epic name (required)" bind:value={name} autofocus />
  <textarea placeholder="Description (optional)" rows="2" bind:value={description}
  ></textarea>
  <EpicColorPicker
    name={isEdit ? `epic-${epic!.id}-color` : "new-epic-color"}
    value={color}
    onchange={(c) => (color = c)}
  />

  {#if error}
    <p class="form-error" role="alert">{error}</p>
  {/if}

  <div class="row actions">
    <button type="submit" class="primary" disabled={!canSubmit}>
      {isEdit ? "Save" : "Create"}
    </button>
    <button type="button" onclick={onclose} disabled={submitting}>Cancel</button>
  </div>
</form>
