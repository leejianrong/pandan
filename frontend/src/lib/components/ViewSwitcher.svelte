<script lang="ts">
  // Saved-view switcher + query bar + board/table toggle (M5 V14, KAN-247).
  // Sits above the board: pick a saved view (applies its filter+sort), tweak the
  // live filters (priority / assignee / needs-human / sort), save the current
  // query as a named view, and flip between the board and a sortable table over
  // the same (filtered) cards. board.svelte.ts owns the state + server calls;
  // every change refetch()es, so the UI only shows server-confirmed cards.
  import {
    ArrowUpDown,
    Bookmark,
    Columns3,
    ListFilter,
    Save,
    Table,
    Trash2,
    X,
  } from "lucide-svelte";
  import {
    viewStore,
    setActiveView,
    setQuery,
    saveCurrentView,
    removeView,
    setViewMode,
  } from "../board.svelte";
  import { Checkbox, Select, TextInput } from "./ui";
  import type { Priority } from "../api";

  const PRIORITIES: Priority[] = ["none", "low", "medium", "high", "urgent"];
  // Sort presets over the shared grammar; "" = the server default order.
  const SORTS: { value: string; label: string }[] = [
    { value: "", label: "Default order" },
    { value: "-priority", label: "Priority (high→low)" },
    { value: "due_date", label: "Due date (soonest)" },
    { value: "-updated_at", label: "Recently updated" },
  ];

  const priorityOptions = [
    { value: "", label: "Any" },
    ...PRIORITIES.map((p) => ({ value: p, label: p })),
  ];
  const viewOptions = $derived([
    { value: "", label: "All cards" },
    ...viewStore.views.map((v) => ({ value: String(v.id), label: v.name })),
  ]);

  let saving = $state(false);
  let newName = $state("");
  let busy = $state(false);

  function onSelectView(raw: string) {
    setActiveView(raw === "" ? null : Number(raw));
  }

  function onPriority(v: string) {
    setQuery({ priority: (v || undefined) as Priority | undefined });
  }

  let assigneeInput = $state("");
  // Keep the input in step when a saved view is applied.
  $effect(() => {
    assigneeInput = viewStore.query.assignee ?? "";
  });
  function onAssignee() {
    setQuery({ assignee: assigneeInput.trim() || undefined });
  }

  function onNeedsHuman(checked: boolean) {
    setQuery({ needs_human: checked ? true : undefined });
  }

  function onSort(v: string) {
    setQuery({ sort: v || undefined });
  }

  async function save() {
    const name = newName.trim();
    if (!name || busy) return;
    busy = true;
    try {
      await saveCurrentView(name);
      newName = "";
      saving = false;
    } finally {
      busy = false;
    }
  }

  async function deleteActive() {
    if (viewStore.activeViewId == null || busy) return;
    busy = true;
    try {
      await removeView(viewStore.activeViewId);
    } finally {
      busy = false;
    }
  }
</script>

<div class="view-bar">
  <div class="view-group">
    <Bookmark size={15} class="view-icon" aria-hidden="true" />
    <Select
      class="compact"
      aria-label="Saved view"
      value={viewStore.activeViewId == null ? "" : String(viewStore.activeViewId)}
      options={viewOptions}
      onValueChange={onSelectView}
    />
    {#if viewStore.activeViewId != null}
      <button
        class="icon-btn"
        title="Delete this view"
        aria-label="Delete this view"
        onclick={deleteActive}
        disabled={busy}
      >
        <Trash2 size={15} />
      </button>
    {/if}
  </div>

  <div class="view-filters">
    <div class="control-group" role="group" aria-label="Filter cards">
      <span class="group-label">
        <ListFilter size={14} aria-hidden="true" />
        Filter
      </span>
      <label class="filter">
        <span>Priority</span>
        <Select
          class="compact"
          aria-label="Filter by priority"
          value={viewStore.query.priority ?? ""}
          options={priorityOptions}
          onValueChange={onPriority}
        />
      </label>

      <label class="filter">
        <span>Assignee</span>
        <span class="input-wrap">
          <TextInput
            placeholder="anyone"
            aria-label="Filter by assignee"
            bind:value={assigneeInput}
            onchange={onAssignee}
          />
        </span>
      </label>

      <div class="filter checkbox">
        <Checkbox
          label="Needs human"
          aria-label="Only cards needing a human"
          checked={viewStore.query.needs_human === true}
          onCheckedChange={onNeedsHuman}
        />
      </div>
    </div>

    <span class="group-divider" aria-hidden="true"></span>

    <div class="control-group" role="group" aria-label="Sort cards">
      <span class="group-label">
        <ArrowUpDown size={14} aria-hidden="true" />
        Sort
      </span>
      <label class="filter">
        <span class="sr-only">Sort by</span>
        <Select
          class="compact"
          aria-label="Sort cards"
          value={viewStore.query.sort ?? ""}
          options={SORTS}
          onValueChange={onSort}
        />
      </label>
    </div>
  </div>

  <div class="view-actions">
    {#if saving}
      <form
        class="save-form"
        onsubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <span class="input-wrap">
          <TextInput placeholder="View name" aria-label="View name" bind:value={newName} />
        </span>
        <button type="submit" class="primary" disabled={!newName.trim() || busy}>Save</button>
        <button type="button" class="icon-btn" aria-label="Cancel" onclick={() => (saving = false)}>
          <X size={15} />
        </button>
      </form>
    {:else}
      <button class="chip-btn" onclick={() => (saving = true)}>
        <Save size={14} /> Save view
      </button>
    {/if}

    <div class="mode-toggle" role="group" aria-label="View mode">
      <button
        class:active={viewStore.mode === "board"}
        title="Board view"
        aria-label="Board view"
        aria-pressed={viewStore.mode === "board"}
        onclick={() => setViewMode("board")}
      >
        <Columns3 size={15} />
      </button>
      <button
        class:active={viewStore.mode === "table"}
        title="Table view"
        aria-label="Table view"
        aria-pressed={viewStore.mode === "table"}
        onclick={() => setViewMode("table")}
      >
        <Table size={15} />
      </button>
    </div>
  </div>
</div>

<style>
  .view-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem 1rem;
    padding: 0.6rem 0.85rem;
    margin-bottom: 1rem;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .view-group,
  .view-actions {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  .view-filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.75rem;
    flex: 1 1 auto;
  }
  /* Each labelled cluster: a funnel-led FILTER group and an arrows-led SORT
     group, so the row reads as filtering vs sorting at a glance (U5). */
  .control-group {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem 0.75rem;
  }
  .group-label {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--muted);
  }
  /* Slim vertical rule separating the two groups. */
  .group-divider {
    align-self: stretch;
    width: 1px;
    min-height: 1.2rem;
    background: var(--border);
  }
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
  :global(.view-icon) {
    color: var(--muted);
  }
  .filter {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.8rem;
    color: var(--muted);
  }
  .filter.checkbox {
    gap: 0.3rem;
    cursor: pointer;
  }
  /* Fixed-width wrapper for the primitive TextInput (renders width:100%). */
  .input-wrap {
    display: inline-flex;
    width: 9rem;
  }
  .save-form {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .chip-btn,
  .mode-toggle button {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.35rem 0.6rem;
    font: inherit;
    font-size: 0.82rem;
    color: var(--text);
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    cursor: pointer;
  }
  .chip-btn:hover,
  .mode-toggle button:hover {
    background: var(--hover);
  }
  .mode-toggle {
    display: inline-flex;
    gap: 0.25rem;
  }
  .mode-toggle button.active {
    color: var(--accent);
    background: var(--accent-soft);
    border-color: var(--accent);
  }
  button.primary {
    padding: 0.35rem 0.7rem;
    font: inherit;
    font-size: 0.82rem;
    color: #fff;
    background: var(--accent);
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    cursor: pointer;
  }
  button.primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
