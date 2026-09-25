<script lang="ts">
  import { untrack } from "svelte";
  import type { Workspace } from "../api";
  import { addWorkspace, editWorkspace } from "../workspaces.svelte";

  // Create mode: no `workspace`. Edit mode: pass `workspace`. Mirrors EpicForm (ADR 0009).
  let {
    workspace,
    onclose,
  }: {
    workspace?: Workspace;
    onclose: () => void;
  } = $props();

  const { isEdit, iName } = untrack(() => ({
    isEdit: !!workspace,
    iName: workspace?.name ?? "",
  }));

  let name = $state(iName);
  let submitting = $state(false);
  let error = $state<string | null>(null);

  const dirty = $derived(name.trim() !== iName);
  const canSubmit = $derived(name.trim().length > 0 && (!isEdit || dirty) && !submitting);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    submitting = true;
    error = null;
    try {
      if (isEdit) {
        await editWorkspace(workspace!.id, name.trim());
      } else {
        await addWorkspace(name.trim());
      }
      onclose();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to save workspace";
    } finally {
      submitting = false;
    }
  }
</script>

<form class="card-form" onsubmit={submit}>
  <!-- svelte-ignore a11y_autofocus -->
  <input type="text" placeholder="Workspace name (required)" bind:value={name} autofocus />

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
