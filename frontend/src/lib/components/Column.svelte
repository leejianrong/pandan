<script lang="ts">
  import { flip } from "svelte/animate";
  import { Plus } from "lucide-svelte";
  import { dndzone, TRIGGERS, type DndEvent } from "svelte-dnd-action";
  import type { Card as CardType, Column } from "../api";
  import { moveCard } from "../board.svelte";
  import { kbd } from "../keyboard.svelte";
  import Card from "./Card.svelte";
  import CardForm from "./CardForm.svelte";

  let {
    column,
    label,
    cards,
  }: { column: Column; label: string; cards: CardType[] } = $props();

  let adding = $state(false);

  // The `n`/`c` keyboard shortcut (V36, KAN-300) targets a column via a one-shot
  // signal on the shared keyboard store; the matching column opens its add-card
  // form and clears the signal so it fires once.
  $effect(() => {
    if (kbd.addToColumn === column) {
      adding = true;
      kbd.addToColumn = null;
    }
  });

  // svelte-dnd-action owns a mutable copy of the list. Re-sync from the
  // server-authoritative `cards` prop whenever it changes (e.g. after refetch).
  let items = $state<CardType[]>([]);
  $effect(() => {
    items = cards;
  });

  function handleConsider(e: CustomEvent<DndEvent<CardType>>) {
    items = e.detail.items;
  }

  function handleFinalize(e: CustomEvent<DndEvent<CardType>>) {
    items = e.detail.items;
    // Only the zone the card was dropped INTO issues the move; the source
    // zone's removal is handled server-side by renumber.
    if (e.detail.info.trigger === TRIGGERS.DROPPED_INTO_ZONE) {
      const id = Number(e.detail.info.id);
      const position = items.findIndex((c) => c.id === id);
      if (position >= 0) moveCard(id, { column, position });
    }
  }

  // A card being edited or confirming delete renders its form INSIDE the drag
  // item. svelte-dnd-action already ignores drags that start on interactive
  // elements (inputs/buttons), but a press on the form's non-interactive chrome
  // would still start a drag and discard the edit. The library begins a drag
  // from a mouse/touch press on the drop zone, so we swallow such presses one
  // level up (capture on the section runs first) when they originate inside a
  // form/prompt. Guards mouse + touch (pointerdown alone isn't what it listens to).
  function guardFormPress(e: Event) {
    if ((e.target as HTMLElement).closest(".card-form, .card.confirm")) {
      e.stopPropagation();
    }
  }
</script>

<section
  class="column column-{column}"
  onmousedowncapture={guardFormPress}
  ontouchstartcapture={guardFormPress}
>
  <header class="column-head">
    <span class="status-dot" aria-hidden="true"></span>
    <h2>{label}</h2>
    <span class="count">{items.length}</span>
  </header>

  <div
    class="cards"
    use:dndzone={{ items, flipDurationMs: 150, dropTargetStyle: { outline: "2px dashed var(--accent)" } }}
    onconsider={handleConsider}
    onfinalize={handleFinalize}
  >
    {#each items as card (card.id)}
      <div class="card-dnd" animate:flip={{ duration: 150 }}>
        <Card {card} />
      </div>
    {/each}
  </div>

  {#if items.length === 0}
    <p class="empty">No cards yet</p>
  {/if}

  {#if adding}
    <CardForm {column} onclose={() => (adding = false)} />
  {:else}
    <button class="add" onclick={() => (adding = true)}>
      <Plus size={15} /> Add card
    </button>
  {/if}
</section>
