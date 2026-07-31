<script lang="ts">
  import type { Column, Priority } from "../api";
  import { addCard, epicStore, labelStore } from "../board.svelte";
  import { Select, TextInput, Textarea } from "./ui";

  // Create-only: the add-card affordance inside a column. Editing an existing
  // card now happens in CardModal (opened from the card face), so this form no
  // longer carries the edit-only fields (blockers / links / notes / status).
  let { column, onclose }: { column: Column; onclose: () => void } = $props();

  const STORY_POINTS = [1, 2, 3, 5, 8, 13];
  const PRIORITIES: Priority[] = ["none", "low", "medium", "high", "urgent"];

  const pointOptions = $derived([
    { value: "", label: "— pts" },
    ...STORY_POINTS.map((p) => ({ value: String(p), label: String(p) })),
  ]);
  const priorityOptions = PRIORITIES.map((p) => ({
    value: p,
    label: p === "none" ? "— priority" : p,
  }));

  let title = $state("");
  let description = $state("");
  let assignee = $state("");
  let storyPoints = $state<string>(""); // "" = unestimated
  let epicId = $state<string>(""); // "" = no epic
  let priority = $state<Priority>("none");
  let dueDate = $state<string>(""); // "" = no due date (a <input type=date> value)
  let labelIds = $state<number[]>([]); // attached label ids
  let submitting = $state(false);
  let error = $state<string | null>(null);

  const epicOptions = $derived(epicStore.epics);
  const epicSelectOptions = $derived([
    { value: "", label: "— no epic" },
    ...epicOptions.map((e) => ({
      value: String(e.id),
      label: `${e.ticket_number} · ${e.name}`,
    })),
  ]);
  const labelOptions = $derived(labelStore.labels);
  const canSubmit = $derived(title.trim().length > 0 && !submitting);

  function toggleLabel(id: number) {
    labelIds = labelIds.includes(id)
      ? labelIds.filter((x) => x !== id)
      : [...labelIds, id];
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    submitting = true;
    error = null;
    try {
      await addCard({
        title: title.trim(),
        description: description.trim() || null,
        assignee: assignee.trim() || null,
        story_points: storyPoints ? Number(storyPoints) : null,
        epic_id: epicId ? Number(epicId) : null,
        priority,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
        label_ids: labelIds,
        column,
      });
      onclose();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to save card";
    } finally {
      submitting = false;
    }
  }
</script>

<form class="card-form" onsubmit={submit}>
  <!-- svelte-ignore a11y_autofocus -->
  <input type="text" class="ui-input" placeholder="Title (required)" bind:value={title} autofocus />
  <Textarea placeholder="Description (optional)" rows={2} bind:value={description} />
  <div class="row">
    <div class="grow">
      <TextInput placeholder="Assignee" bind:value={assignee} aria-label="Assignee" />
    </div>
    <div class="pts">
      <Select bind:value={storyPoints} options={pointOptions} aria-label="Story points" />
    </div>
  </div>

  <Select bind:value={epicId} options={epicSelectOptions} aria-label="Epic" />

  <div class="row">
    <div class="grow">
      <Select
        value={priority}
        options={priorityOptions}
        onValueChange={(v) => (priority = v as Priority)}
        aria-label="Priority"
      />
    </div>
    <div class="grow">
      <input type="date" class="ui-input" bind:value={dueDate} aria-label="Due date" />
    </div>
  </div>

  {#if labelOptions.length > 0}
    <div class="label-picker" role="group" aria-label="Labels">
      {#each labelOptions as label (label.id)}
        <button
          type="button"
          class="label-toggle"
          class:selected={labelIds.includes(label.id)}
          onclick={() => toggleLabel(label.id)}
        >
          <span class="label-dot" style="background: {label.color}" aria-hidden="true"></span>
          {label.name}
        </button>
      {/each}
    </div>
  {/if}

  {#if error}
    <p class="form-error" role="alert">{error}</p>
  {/if}

  <div class="row actions">
    <button type="submit" class="primary" disabled={!canSubmit}>Create</button>
    <button type="button" onclick={onclose} disabled={submitting}>Cancel</button>
  </div>
</form>

<style>
  /* Row layout for the primitive controls (they render width:100%). */
  .grow {
    flex: 1;
    min-width: 0;
  }
  .pts {
    flex: none;
    width: 5.5rem;
  }
</style>
