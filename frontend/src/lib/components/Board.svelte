<script lang="ts">
  import { board, cardsFor, COLUMNS, refetch, viewStore } from "../board.svelte";
  import { handleBoardKeydown } from "../keyboard.svelte";
  import Column from "./Column.svelte";
  import ViewSwitcher from "./ViewSwitcher.svelte";
  import BoardTable from "./BoardTable.svelte";

  // Below the mobile breakpoint (app.css's `@media (max-width: 768px)` on
  // `.board`), the 3-column grid becomes a horizontal scroll-snap row — one
  // column filling most of the viewport at a time, swiped between. The dot
  // row is a position indicator + jump-to-column control so a bare swipe
  // gesture isn't the only way to tell there are 3 columns or which one
  // you're on; it's `display:none` above the breakpoint (CSS-only, no need
  // to watch viewport width from script) so it costs nothing on desktop.
  let boardEl = $state<HTMLDivElement | undefined>();
  let activeCol = $state(0);

  function onBoardScroll() {
    if (!boardEl) return;
    const children = Array.from(boardEl.children) as HTMLElement[];
    const center = boardEl.scrollLeft + boardEl.clientWidth / 2;
    let closest = 0;
    let closestDist = Infinity;
    children.forEach((child, i) => {
      const dist = Math.abs(child.offsetLeft + child.offsetWidth / 2 - center);
      if (dist < closestDist) {
        closestDist = dist;
        closest = i;
      }
    });
    activeCol = closest;
  }

  function scrollToColumn(i: number) {
    (boardEl?.children[i] as HTMLElement | undefined)?.scrollIntoView({
      behavior: "smooth",
      inline: "start",
      block: "nearest",
    });
  }
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
  <div class="board-col-indicator" role="tablist" aria-label="Column">
    {#each COLUMNS as col, i (col.key)}
      <button
        type="button"
        class="board-col-dot"
        class:active={activeCol === i}
        role="tab"
        aria-selected={activeCol === i}
        aria-label={col.label}
        onclick={() => scrollToColumn(i)}
      ></button>
    {/each}
  </div>
  <div class="board" bind:this={boardEl} onscroll={onBoardScroll}>
    {#each COLUMNS as col (col.key)}
      <Column column={col.key} label={col.label} cards={cardsFor(col.key)} />
    {/each}
  </div>
{/if}
