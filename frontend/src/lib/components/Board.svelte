<script lang="ts">
  import { board, cardsFor, COLUMNS, refetch, viewStore } from "../board.svelte";
  import { handleBoardKeydown } from "../keyboard.svelte";
  import Column from "./Column.svelte";
  import ViewSwitcher from "./ViewSwitcher.svelte";
  import BoardTable from "./BoardTable.svelte";
</script>

<!-- Board keyboard shortcuts (V36, KAN-300). Only live while the board view is
     mounted; coexists with App.svelte's global ⌘K handler (that one only reacts to
     the Cmd/Ctrl-K chord, this one only to un-chorded keys, and both guard typing). -->
<svelte:window onkeydown={handleBoardKeydown} />

{#if board.error}
  <div class="banner error" role="alert">
    <span>{board.error}</span>
    <button onclick={refetch}>Retry</button>
  </div>
{/if}

<ViewSwitcher />

{#if board.loading && board.cards.length === 0}
  <p class="hint">Loading…</p>
{/if}

{#if viewStore.mode === "table"}
  <BoardTable />
{:else}
  <div class="board">
    {#each COLUMNS as col (col.key)}
      <Column column={col.key} label={col.label} cards={cardsFor(col.key)} />
    {/each}
  </div>
{/if}
