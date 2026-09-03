<script lang="ts">
  import { untrack } from "svelte";
  import { Trash2, X } from "lucide-svelte";
  import { labelColor } from "../api";
  import { cardsForEpic, editEpic, epicStore, removeEpic } from "../board.svelte";
  import { displayRef } from "../tickets";
  import EpicColorPicker from "./EpicColorPicker.svelte";
  import Modal from "./Modal.svelte";

  // Edit an epic's name + description in place, with its story rollup shown for
  // context. Same modal shell / a11y as the card modal. Server-authoritative:
  // save/delete go through the store's refetchEpics()/refetch() helpers.
  let { epicId, onclose }: { epicId: number; onclose: () => void } = $props();

  const epic = $derived(epicStore.epics.find((e) => e.id === epicId));
  $effect(() => {
    if (epic == null) onclose();
  });

  const stories = $derived(cardsForEpic(epicId));
  const doneCount = $derived(stories.filter((s) => s.column === "done").length);
  const pct = $derived(stories.length ? Math.round((doneCount / stories.length) * 100) : 0);
  const allDone = $derived(stories.length > 0 && doneCount === stories.length);

  const initial = untrack(() => ({
    name: epic?.name ?? "",
    desc: epic?.description ?? "",
    color: epic?.color ?? null,
  }));
  let name = $state(initial.name);
  let description = $state(initial.desc);
  let color = $state<string | null>(initial.color);
  let submitting = $state(false);
  let error = $state<string | null>(null);

  const dirty = $derived(
    name.trim() !== initial.name ||
      description.trim() !== initial.desc ||
      color !== initial.color,
  );
  const canSubmit = $derived(name.trim().length > 0 && dirty && !submitting);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!canSubmit || !epic) return;
    submitting = true;
    error = null;
    try {
      await editEpic(epic.id, {
        name: name.trim(),
        description: description.trim() || null,
        color,
      });
      onclose();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to save epic";
    } finally {
      submitting = false;
    }
  }

  let confirming = $state(false);
  let deleting = $state(false);
  let deleteError = $state<string | null>(null);
  async function confirmDelete() {
    if (!epic) return;
    deleting = true;
    deleteError = null;
    try {
      await removeEpic(epic.id);
      onclose();
    } catch (e) {
      deleteError = e instanceof Error ? e.message : "Failed to delete epic";
      deleting = false;
    }
  }
</script>

{#if epic}
  <Modal label="Epic {displayRef(epic)}: {epic.name}" {onclose}>
    <form class="card-form epic-modal" onsubmit={submit}>
      <header class="modal-head">
        {#if epic.color}
          <span
            class="epic-color-dot"
            style="background: {labelColor(epic.color)}"
            title="Epic colour"
            aria-hidden="true"
          ></span>
        {/if}
        <span class="ticket epic-ticket" title={epic.ticket_number}>{displayRef(epic)}</span>
        <span class="epic-count">
          {stories.length}
          {stories.length === 1 ? "story" : "stories"}
        </span>
        <button
          type="button"
          class="icon-btn modal-close"
          title="Close"
          aria-label="Close"
          onclick={onclose}
        >
          <X size={18} />
        </button>
      </header>

      <div class="modal-scroll">
        <div class="modal-main epic-modal-main">
          <input
            class="modal-title-input"
            type="text"
            placeholder="Epic name (required)"
            aria-label="Epic name"
            bind:value={name}
          />
          <span class="field-label">Description</span>
          <textarea
            class="desc-input"
            placeholder="Description (optional)"
            rows="3"
            bind:value={description}
          ></textarea>

          <span class="field-label">Colour</span>
          <EpicColorPicker
            name="epic-{epic.id}-color"
            value={color}
            onchange={(c) => (color = c)}
          />

          <div class="epic-rollup-block">
            <span class="field-label">Stories</span>
            <div class="progress">
              <div class="bar"><i class:full={allDone} style="width:{pct}%"></i></div>
              <span class="pct">{doneCount} / {stories.length} done</span>
            </div>
            {#if stories.length > 0}
              <ul class="epic-stories">
                {#each stories as story (story.id)}
                  <li class:is-done={story.column === "done"}>
                    <span class="sdot {story.column}" aria-hidden="true"></span>
                    <span class="ticket" title={story.ticket_number}>{displayRef(story)}</span>
                    <span class="stitle">{story.title}</span>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="comment-empty">No stories linked yet.</p>
            {/if}
          </div>
        </div>
      </div>

      <footer class="modal-foot">
        {#if confirming}
          <span class="confirm-msg">
            Delete {displayRef(epic)}? Its {stories.length}
            linked {stories.length === 1 ? "story" : "stories"} will be unlinked (not deleted).
          </span>
          <button type="button" class="danger" onclick={confirmDelete} disabled={deleting}>
            Delete
          </button>
          <button type="button" class="link" onclick={() => (confirming = false)} disabled={deleting}>
            Keep
          </button>
        {:else}
          <button type="submit" class="primary" disabled={!canSubmit}>Save changes</button>
          <button type="button" class="link" onclick={onclose}>Cancel</button>
          <button
            type="button"
            class="btn-inline-danger modal-delete"
            onclick={() => (confirming = true)}
          >
            <Trash2 size={15} /> Delete
          </button>
        {/if}
      </footer>

      {#if error}<p class="form-error" role="alert">{error}</p>{/if}
      {#if deleteError}<p class="form-error" role="alert">{deleteError}</p>{/if}
    </form>
  </Modal>
{/if}
