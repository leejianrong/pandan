<script lang="ts">
  // Board switcher in the top bar (M3 V7): select the active board, and
  // create / rename / delete boards. Selecting a board reloads the board view
  // for it (board.svelte.ts owns the state + server calls).
  import { Plus, MoreHorizontal, Pencil, Trash2 } from "lucide-svelte";
  import {
    addBoard,
    boardStore,
    editBoard,
    removeBoard,
    setActiveBoard,
    activeBoard,
  } from "../board.svelte";
  import { DropdownMenu, Select, TextInput } from "./ui";
  import type { MenuItem } from "./ui";

  import type { Board, Role } from "../api";

  type Mode = "idle" | "creating" | "renaming" | "confirmDelete";
  let mode = $state<Mode>("idle");
  let name = $state("");
  let busy = $state(false);

  // A board the caller doesn't own is "shared" — surface the role (KAN-15).
  // The option label carries the role in text and the active board also gets a
  // styled pill next to the select.
  const sharedRole = (b: Board): Role | null =>
    b.role && b.role !== "owner" ? b.role : null;

  const boardOptions = $derived(
    boardStore.boards.map((b) => ({
      value: String(b.id),
      label: `${b.name}${sharedRole(b) ? ` (${sharedRole(b)})` : ""}`,
    })),
  );

  // Rename/Delete live in a "⋯" DropdownMenu — Bits UI handles outside-click,
  // Escape, and focus, so no manual document listeners are needed here.
  const boardMenuItems = $derived<MenuItem[]>([
    { label: "Rename board", icon: Pencil, onSelect: startRename },
    {
      label: "Delete board",
      icon: Trash2,
      danger: true,
      onSelect: () => {
        mode = "confirmDelete";
      },
    },
  ]);

  function onSelect(value: string) {
    const id = Number(value);
    if (id && id !== boardStore.activeBoardId) setActiveBoard(id);
  }

  function startCreate() {
    name = "";
    mode = "creating";
  }
  function startRename() {
    name = activeBoard()?.name ?? "";
    mode = "renaming";
  }
  function cancel() {
    mode = "idle";
    name = "";
  }

  async function submit() {
    const trimmed = name.trim();
    if (busy) return;
    if (mode === "creating") {
      if (!trimmed) return;
      busy = true;
      try {
        await addBoard(trimmed);
        cancel();
      } finally {
        busy = false;
      }
    } else if (mode === "renaming") {
      const b = activeBoard();
      if (!b || !trimmed) return;
      busy = true;
      try {
        await editBoard(b.id, trimmed);
        cancel();
      } finally {
        busy = false;
      }
    }
  }

  async function confirmDelete() {
    const b = activeBoard();
    if (!b || busy) return;
    busy = true;
    try {
      await removeBoard(b.id);
      mode = "idle";
    } finally {
      busy = false;
    }
  }
</script>

<div class="board-switcher">
  {#if mode === "creating" || mode === "renaming"}
    <form
      onsubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <TextInput
        placeholder={mode === "creating" ? "Board name (required)" : "Rename board"}
        bind:value={name}
        aria-label="Board name"
      />
      <button type="submit" class="primary" disabled={!name.trim() || busy}>
        {mode === "creating" ? "Create" : "Save"}
      </button>
      <button type="button" class="link" onclick={cancel}>Cancel</button>
    </form>
  {:else if mode === "confirmDelete"}
    <span class="confirm-msg">Delete “{activeBoard()?.name}” and all its cards?</span>
    <button class="danger" onclick={confirmDelete} disabled={busy}>Delete</button>
    <button class="link" onclick={() => (mode = "idle")}>Cancel</button>
  {:else}
    <div class="board-select">
      <Select
        aria-label="Switch board"
        value={String(boardStore.activeBoardId ?? "")}
        options={boardOptions}
        onValueChange={onSelect}
      />
    </div>
    {#if activeBoard() && sharedRole(activeBoard()!)}
      <span
        class="role-badge"
        title="Shared board — you are a {sharedRole(activeBoard()!)}"
      >
        {sharedRole(activeBoard()!)}
      </span>
    {/if}
    <button class="icon-btn" title="New board" aria-label="New board" onclick={startCreate}>
      <Plus size={16} />
    </button>
    {#if activeBoard()}
      <DropdownMenu
        items={boardMenuItems}
        triggerClass="icon-btn"
        triggerLabel="Board actions"
      >
        {#snippet trigger()}
          <MoreHorizontal size={16} />
        {/snippet}
      </DropdownMenu>
    {/if}
  {/if}
</div>

<style>
  /* Constrain the board Select trigger (which is width:100%) in the top bar. */
  .board-select {
    width: 12rem;
    max-width: 12rem;
  }
  /* Role pill for a shared board (KAN-15): you're a member, not the owner. */
  .role-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: capitalize;
    letter-spacing: 0.01em;
    color: var(--agent);
    background: var(--agent-soft);
    white-space: nowrap;
  }
</style>
