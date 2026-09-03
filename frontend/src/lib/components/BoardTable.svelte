<script lang="ts">
  // Sortable table over the same (filtered) cards as the board (M5 V14, KAN-247).
  // The server already applied the active view's filter+sort; this presents the
  // result as a table and adds client-side column sorting (click a header) on top,
  // so a human can re-sort without a round-trip. Read-focused — mutations stay on
  // the board columns / card modal.
  import { ArrowDown, ArrowUp } from "lucide-svelte";
  import { board, epicFor } from "../board.svelte";
  import type { Card } from "../api";
  import { compareTicketRefs, displayRef } from "../tickets";

  const PRIORITY_RANK: Record<string, number> = {
    none: 0,
    low: 1,
    medium: 2,
    high: 3,
    urgent: 4,
  };
  const COLUMN_LABEL: Record<string, string> = {
    todo: "Todo",
    in_progress: "In Progress",
    done: "Done",
  };

  type SortKey = "ticket_number" | "title" | "column" | "priority" | "assignee" | "due_date";
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
    if (key === "due_date") return card.due_date ?? "";
    const v = card[key];
    return v == null ? "" : v;
  }

  const rows = $derived(
    [...board.cards].sort((a, b) => {
      // The ticket column sorts through the shared numeric-aware comparator: a
      // plain string compare puts KAN-100 ahead of KAN-9 (KAN-986). Every other
      // key is a genuine string or rank, so the relational compare is right there.
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
    { key: "column", label: "Column" },
    { key: "priority", label: "Priority" },
    { key: "assignee", label: "Assignee" },
    { key: "due_date", label: "Due" },
  ];

  function fmtDue(iso: string | null): string {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleDateString();
  }
</script>

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
        <th>Epic</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as card (card.id)}
        <tr>
          <td class="mono" title={card.ticket_number}>{displayRef(card)}</td>
          <td class="title-cell">{card.title}</td>
          <td>{COLUMN_LABEL[card.column] ?? card.column}</td>
          <td class="cap">{card.priority}</td>
          <td>{card.assignee ?? "—"}</td>
          <td>{fmtDue(card.due_date)}</td>
          <td class="muted">{epicFor(card.epic_id)?.name ?? "—"}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if rows.length === 0}
    <p class="hint">No cards match this view.</p>
  {/if}
</div>

<style>
  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--shape-medium);
    background: var(--card-bg);
  }
  .card-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--type-body-medium-size);
    line-height: var(--type-body-medium-line-height);
    font-weight: var(--type-body-medium-weight);
    letter-spacing: var(--type-body-medium-tracking);
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
    font-size: var(--type-label-large-size);
    line-height: var(--type-label-large-line-height);
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
    background: var(--state-hover);
  }
  .th-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
    color: var(--text);
    background: var(--state-focus);
  }
  .th-btn:active {
    background: var(--state-pressed);
  }
  tbody td {
    padding: 0.5rem 0.7rem;
    border-bottom: 1px solid var(--border);
    color: var(--text);
  }
  tbody tr:last-child td {
    border-bottom: none;
  }
  /* Decorative row highlight only — <tr> carries no click handler/role
     here (this table's rows aren't independently interactive), so no
     focus/pressed state is added. Just the --hover -> --state-hover
     rename (M8 M3-5, KAN-1094); same value. */
  tbody tr:hover {
    background: var(--state-hover);
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
  .muted {
    color: var(--muted);
  }
  th:last-child {
    padding: 0.55rem 0.7rem;
    font-size: var(--type-label-large-size);
    line-height: var(--type-label-large-line-height);
    font-weight: 600;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--muted);
  }
</style>
