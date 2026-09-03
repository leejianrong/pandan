<script lang="ts">
  // Persistent left nav rail (NR-1, KAN-1148 — docs/design-reviews/nav-rail-shaping.md).
  // Always-visible replacement for the hamburger+SideNav drawer's board-scoped
  // items. Borrows SideNav.svelte's item list/icons/aria-current pattern
  // verbatim (per the audit, "the starting point for the new rail component,
  // not a from-scratch design") but is deliberately a separate, smaller
  // component — no open/onClose/scrim/onOpenInbox, since this is always
  // visible and never shows Inbox (that stays the top-bar bell only).
  //
  // Deliberately excludes "Board" (D1, nav-rail-shaping.md): adding it here
  // while the top-bar .board-tab pill still exists would give two buttons
  // named "Board" at once, breaking epic-story.spec.ts/trash.spec.ts's
  // getByRole("button", { name: "Board", exact: true }) under Playwright's
  // strict mode. NR-2 adds it here and retires the pill atomically.
  //
  // Also excludes Tokens/Teams (account-scoped, D2) and Inbox (already has
  // the bell, D3/crease 4) — those never appear in the rail at any point.
  import {
    Activity,
    Archive,
    Layers,
    LayoutDashboard,
    Tag,
    Trash2,
    Users,
  } from "lucide-svelte";
  import type { Icon } from "lucide-svelte";

  export type RailView =
    | "dashboard"
    | "epics"
    | "labels"
    | "backlog"
    | "activity"
    | "members"
    | "trash";

  let { view, onNavigate }: { view: string; onNavigate: (view: RailView) => void } =
    $props();

  const items: { id: RailView; label: string; icon: typeof Icon }[] = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "epics", label: "Epics", icon: Layers },
    { id: "labels", label: "Labels", icon: Tag },
    { id: "backlog", label: "Backlog", icon: Archive },
    { id: "activity", label: "Activity", icon: Activity },
    { id: "members", label: "Members", icon: Users },
    { id: "trash", label: "Trash", icon: Trash2 },
  ];
</script>

<nav class="nav-rail" aria-label="Views">
  {#each items as item (item.id)}
    {@const ItemIcon = item.icon}
    <button
      class="rail-item"
      class:active={view === item.id}
      aria-current={view === item.id ? "page" : undefined}
      onclick={() => onNavigate(item.id)}
    >
      <ItemIcon size={18} />
      <span>{item.label}</span>
    </button>
  {/each}
</nav>

<style>
  /* Same visual language as SideNav.svelte's .drawer-item — this is the
     rail's whole point, so it should look like it always belonged, not
     like a bolted-on second nav. Differs only in not being a fixed overlay:
     it's a layout column (see App.svelte's .app-shell), so no position,
     transform, scrim, or z-index here. */
  .nav-rail {
    width: 200px;
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: 1rem 0.6rem;
    background: var(--card-bg);
    border-right: 1px solid var(--border);
    overflow-y: auto;
  }

  .rail-item {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    width: 100%;
    padding: 0.55rem 0.65rem;
    border: 1px solid transparent;
    border-radius: var(--shape-full);
    background: none;
    color: var(--text);
    font: inherit;
    font-size: var(--type-label-large-size);
    line-height: var(--type-label-large-line-height);
    font-weight: var(--type-label-large-weight);
    letter-spacing: var(--type-label-large-tracking);
    text-align: left;
    cursor: pointer;
  }
  .rail-item :global(svg) {
    color: var(--muted);
    flex: none;
  }
  .rail-item:hover {
    background: var(--state-hover);
  }
  .rail-item:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
    background: var(--state-focus);
  }
  .rail-item:active {
    background: var(--state-pressed);
  }
  .rail-item.active {
    background: var(--accent-soft);
    border-color: var(--border);
    color: var(--accent);
    font-weight: 600;
  }
  .rail-item.active:hover {
    background: linear-gradient(var(--state-hover), var(--state-hover)), var(--accent-soft);
  }
  .rail-item.active:focus-visible {
    background: linear-gradient(var(--state-focus), var(--state-focus)), var(--accent-soft);
  }
  .rail-item.active:active {
    background: linear-gradient(var(--state-pressed), var(--state-pressed)), var(--accent-soft);
  }
  .rail-item.active :global(svg) {
    color: var(--accent);
  }
</style>
