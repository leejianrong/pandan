<script lang="ts">
  // The backlog view (M8 V56, KAN-977) — "a place you can open" (SHAPING R2.2),
  // not a filter toggle bolted onto the board. The backlog itself is *derived*
  // (cycle_id IS NULL, SHAPING D8) — backlogStore already holds exactly that
  // slice, fetched server-side via `listCards(boardId, { backlog: true })`.
  // `parked` is the one real, stored field this slice adds: a card someone
  // deliberately parked, distinct from one simply not yet scheduled.
  import { ArrowDown, ArrowUp } from "lucide-svelte";
  import type { Card } from "../api";
  import { backlogStore, editCard, refetchBacklog } from "../board.svelte";
  import { compareTicketRefs, displayRef } from "../tickets";
  import CardModal from "./CardModal.svelte";

  const PRIORITY_RANK: Record<string, number> = {
    none: 0,
    low: 1,
    medium: 2,
    high: 3,
    urgent: 4,
  };

  type SortKey = "ticket_number" | "title" | "priority" | "assignee" | "parked";
  let sortKey = $state<SortKey>("ticket_number");
  let desc = $state(false);

  function toggle(key: SortKey) {
    if (sortKey === key) desc = !desc;
    else {
      sortKey = key;
      desc = false;
    }
  }

  function compare(av: string | number, bv: string | number): number {
    return av < bv ? -1 : av > bv ? 1 : 0;
  }

  function value(card: Card, key: SortKey): string | number {
    if (key === "priority") return PRIORITY_RANK[card.priority] ?? 0;
    if (key === "parked") return card.parked ? 1 : 0;
    const v = card[key];
    return v == null ? "" : v;
  }

  const rows = $derived(
    [...backlogStore.cards].sort((a, b) => {
      let cmp =
        sortKey === "ticket_number"
          ? compareTicketRefs(displayRef(a), displayRef(b))
          : compare(value(a, sortKey), value(b, sortKey));
      if (cmp === 0) cmp = a.id - b.id; // stable tiebreak
      return desc ? -cmp : cmp;
    }),
  );

  const COLUMNS: { key: SortKey; label: string }[] = [
    { key: "ticket_number", label: "Ticket" },
    { key: "title", label: "Title" },
    { key: "priority", label: "Priority" },
    { key: "assignee", label: "Assignee" },
    { key: "parked", label: "Parked" },
  ];

  let openCardId = $state<number | null>(null);

  // Toggling parked is a plain field edit — no need to open the full modal for it.
  // Stop propagation so the row click (which opens the modal) doesn't also fire.
  async function toggleParked(e: MouseEvent, card: Card) {
    e.stopPropagation();
    await editCard(card.id, { parked: !card.parked });
  }
</script>

<div class="backlog-view page-view">
  {#if backlogStore.error}
    <div class="banner error" role="alert">
      <span>{backlogStore.error}</span>
      <button onclick={refetchBacklog}>Retry</button>
    </div>
  {/if}

  <div class="page-head">
    <div>
      <h2>Backlog</h2>
      <p class="page-sub">Cards with no cycle assigned — schedule them or mark them parked.</p>
    </div>
  </div>

  {#if backlogStore.loading && rows.length === 0}
    <p class="hint">Loading…</p>
  {:else if rows.length === 0}
    <p class="empty">The backlog is empty — every card is scheduled into a cycle.</p>
  {:else}
    <div class="table-wrap">
      <table class="card-table">
        <thead>
          <tr>
            {#each COLUMNS as col (col.key)}
              <th>
                <button
                  class="th-btn"
                  aria-label={`Sort by ${col.label}`}
                  onclick={() => toggle(col.key)}
                >
                  {col.label}
                  {#if sortKey === col.key}
                    {#if desc}<ArrowDown size={13} />{:else}<ArrowUp size={13} />{/if}
                  {/if}
                </button>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each rows as card (card.id)}
            <tr onclick={() => (openCardId = card.id)} class:parked={card.parked}>
              <td class="mono" title={card.ticket_number}>{displayRef(card)}</td>
              <td class="title-cell">{card.title}</td>
              <td class="cap">{card.priority}</td>
              <td>{card.assignee ?? "—"}</td>
              <td>
                <label class="parked-toggle">
                  <input
                    type="checkbox"
                    checked={card.parked}
                    onclick={(e) => toggleParked(e, card)}
                    aria-label={card.parked ? "Unmark parked" : "Mark parked"}
                  />
                </label>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

{#if openCardId != null}
  <CardModal cardId={openCardId} editFocus={false} onclose={() => (openCardId = null)} />
{/if}

<style>
  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card-bg);
  }
  .card-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }
  thead th {
    position: sticky;
    top: 0;
    text-align: left;
    background: var(--surface-2);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  .th-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    width: 100%;
    padding: 0.55rem 0.7rem;
    font: inherit;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--muted);
    background: none;
    border: none;
    cursor: pointer;
  }
  .th-btn:hover {
    color: var(--text);
  }
  tbody td {
    padding: 0.5rem 0.7rem;
    border-bottom: 1px solid var(--border);
    color: var(--text);
  }
  tbody tr:last-child td {
    border-bottom: none;
  }
  tbody tr {
    cursor: pointer;
  }
  tbody tr:hover {
    background: var(--hover);
  }
  tbody tr.parked {
    opacity: 0.65;
  }
  .title-cell {
    max-width: 28rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mono {
    font-family: var(--mono);
    color: var(--muted);
    white-space: nowrap;
  }
  .cap {
    text-transform: capitalize;
  }
  .parked-toggle {
    display: inline-flex;
    cursor: pointer;
  }
</style>
