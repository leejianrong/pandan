<script lang="ts">
  import { CircleAlert, CircleCheck, Pencil, TriangleAlert, Trash2 } from "lucide-svelte";
  import type { EpicHealth } from "../api";
  import type { Epic } from "../api";
  import { cardsForEpic, removeEpic } from "../board.svelte";
  import EpicModal from "./EpicModal.svelte";

  let { epic }: { epic: Epic } = $props();

  let mode = $state<"view" | "confirmDelete">("view");
  let showModal = $state(false);
  let deleting = $state(false);
  let deleteError = $state<string | null>(null);

  // Per-story detail rows come from the loaded board cards; the progress numbers +
  // health are server-authoritative (V32, KAN-296) — they ride the epic payload and
  // count every non-deleted child (not just the cards currently loaded/filtered).
  const stories = $derived(cardsForEpic(epic.id));
  const total = $derived(epic.progress.total);
  const doneCount = $derived(epic.progress.done);
  const pct = $derived(epic.progress.percent);
  const allDone = $derived(total > 0 && doneCount === total);

  // Health pill (V32) — icon + label + class per signal; null → no pill.
  const HEALTH: Record<EpicHealth, { label: string; icon: typeof CircleCheck }> = {
    on_track: { label: "On track", icon: CircleCheck },
    at_risk: { label: "At risk", icon: TriangleAlert },
    overdue: { label: "Overdue", icon: CircleAlert },
  };
  const health = $derived(epic.health ? HEALTH[epic.health] : null);

  function isInteractive(t: EventTarget | null): boolean {
    return t instanceof Element && !!t.closest("button, a");
  }
  function openFromClick(e: MouseEvent) {
    if (isInteractive(e.target)) return;
    showModal = true;
  }
  function onKeydown(e: KeyboardEvent) {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      showModal = true;
    }
  }

  async function confirmDelete() {
    deleting = true;
    deleteError = null;
    try {
      await removeEpic(epic.id);
    } catch (e) {
      deleteError = e instanceof Error ? e.message : "Failed to delete epic";
      deleting = false;
    }
  }
</script>

{#if mode === "confirmDelete"}
  <div class="card confirm">
    <p class="confirm-msg">
      Delete <strong>{epic.ticket_number}</strong> — “{epic.name}”? Its
      {total} linked {total === 1 ? "story" : "stories"} will be unlinked
      (not deleted).
    </p>
    {#if deleteError}
      <p class="form-error" role="alert">{deleteError}</p>
    {/if}
    <div class="row actions">
      <button class="danger" onclick={confirmDelete} disabled={deleting}>Delete</button>
      <button onclick={() => (mode = "view")} disabled={deleting}>Cancel</button>
    </div>
  </div>
{:else}
  <div
    class="card epic-card"
    class:completed={allDone}
    role="button"
    tabindex="0"
    aria-label="Open {epic.ticket_number}: {epic.name}"
    onclick={openFromClick}
    onkeydown={onKeydown}
  >
    <div class="card-top">
      <span class="ticket epic-ticket">{epic.ticket_number}</span>
      <span class="epic-count">{total} {total === 1 ? "story" : "stories"}</span>
      {#if health}
        <span class="health-pill {epic.health}" title="Health: {health.label}">
          <health.icon size={13} />
          {health.label}
        </span>
      {/if}
      <div class="card-actions">
        <button class="icon-btn" title="Edit" aria-label="Edit" onclick={() => (showModal = true)}>
          <Pencil size={15} />
        </button>
        <button
          class="icon-btn danger"
          title="Delete"
          aria-label="Delete"
          onclick={() => (mode = "confirmDelete")}
        >
          <Trash2 size={15} />
        </button>
      </div>
    </div>
    <p class="epic-name">{epic.name}</p>
    {#if epic.description}
      <p class="epic-desc">{epic.description}</p>
    {/if}
    <div class="progress">
      <div class="bar">
        <i class:full={allDone} class="fill-{epic.health ?? 'none'}" style="width:{pct}%"></i>
      </div>
      <span class="pct">{doneCount} / {total} done · {pct}%</span>
    </div>
    {#if stories.length > 0}
      <ul class="epic-stories">
        {#each stories as story (story.id)}
          <li class:is-done={story.column === "done"}>
            <span class="sdot {story.column}" aria-hidden="true"></span>
            <span class="ticket">{story.ticket_number}</span>
            <span class="stitle">{story.title}</span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

{#if showModal}
  <EpicModal epicId={epic.id} onclose={() => (showModal = false)} />
{/if}
