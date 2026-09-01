<script lang="ts">
  import { untrack } from "svelte";
  import type { Team } from "../api";
  import { addTeam, editTeam } from "../teams.svelte";

  // Create mode: no `team`. Edit mode: pass `team`. Mirrors EpicForm (ADR 0009).
  let {
    team,
    onclose,
  }: {
    team?: Team;
    onclose: () => void;
  } = $props();

  const { isEdit, iName } = untrack(() => ({
    isEdit: !!team,
    iName: team?.name ?? "",
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
        await editTeam(team!.id, name.trim());
      } else {
        await addTeam(name.trim());
      }
      onclose();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to save team";
    } finally {
      submitting = false;
    }
  }
</script>

<form class="card-form" onsubmit={submit}>
  <!-- svelte-ignore a11y_autofocus -->
  <input type="text" placeholder="Team name (required)" bind:value={name} autofocus />

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
