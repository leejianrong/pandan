<script lang="ts">
  // Sprint selector + Done-hide control above the board (PAN-235/236). Renders
  // nothing for a board that has no sprints and nothing hidden, so a board that
  // never opted into sprints looks exactly as it did before.
  import {
    activeBoard,
    hiddenDoneCount,
    setSprintSelection,
    sprintStore,
  } from "../board.svelte";
  import { activeCycle, type SprintSelection } from "../sprintScope";
  import { Select } from "./ui";
  import SprintStartModal from "./SprintStartModal.svelte";

  let starting = $state(false);
  // Creating cycles needs editor+; a viewer would only meet a 403.
  const canStart = $derived(activeBoard()?.role !== "viewer");

  const hasSprints = $derived(sprintStore.cycles.length > 0);
  const hidden = $derived(hiddenDoneCount());
  const active = $derived(activeCycle(sprintStore.cycles, Date.now()));

  const options = $derived([
    { value: "active", label: active ? `Current sprint · ${active.name}` : "Current sprint" },
    { value: "all", label: "All cards" },
    ...[...sprintStore.cycles]
      .sort((a, b) => (b.starts_on ?? "").localeCompare(a.starts_on ?? ""))
      .map((c) => ({
        value: String(c.id),
        label: c.closed_at ? `${c.name} (closed)` : c.name,
      })),
  ]);

  function onSelect(raw: string) {
    const selection: SprintSelection =
      raw === "active" || raw === "all" ? raw : Number(raw);
    setSprintSelection(selection);
  }
</script>

{#if hasSprints || hidden > 0 || sprintStore.showAllDone || canStart}
  <div class="sprint-scope">
    {#if hasSprints}
      <label class="sprint-select">
        <span>Sprint</span>
        <Select
          class="compact"
          aria-label="Sprint"
          value={String(sprintStore.selection)}
          {options}
          onValueChange={onSelect}
        />
      </label>
    {/if}
    {#if !hasSprints && canStart}
      <button type="button" class="chip-btn start-sprints" onclick={() => (starting = true)}>
        Start sprints
      </button>
    {/if}
    {#if hidden > 0 || sprintStore.showAllDone}
      <button
        type="button"
        class="chip-btn done-hide-toggle"
        onclick={() => (sprintStore.showAllDone = !sprintStore.showAllDone)}
      >
        {sprintStore.showAllDone
          ? "Hide old done cards"
          : `${hidden} older done ${hidden === 1 ? "card" : "cards"} hidden · Show all`}
      </button>
    {/if}
  </div>
{/if}

{#if starting}
  <SprintStartModal onclose={() => (starting = false)} />
{/if}

<style>
  .sprint-scope {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin: 0 0 0.75rem;
  }
  .sprint-select {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
  }
</style>
