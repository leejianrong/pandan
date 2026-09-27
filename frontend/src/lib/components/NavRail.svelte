<script lang="ts">
  // Left nav rail (NR-1, KAN-1148 — docs/design-reviews/nav-rail-shaping.md;
  // NR-5, KAN-<TBD> — reverted to an overlay, closed by default, per a
  // follow-up UI pass: nav-rail-shaping.md D6 explicitly deferred a
  // responsive/collapsible rail as future work rather than ruling it out.
  // Borrows SideNav.svelte's item list/icons/aria-current pattern verbatim
  // (per the audit, "the starting point for the new rail component, not a
  // from-scratch design") and, now, its scrim/fixed-position/Escape-to-close
  // mechanics too — but stays a separate, smaller component: no
  // onOpenInbox, since Inbox is still bell-only (D3/crease 4).
  //
  // "Board" is a rail item (NR-2, KAN-1149) — the top-bar .board-tab pill it
  // replaced is retired for good, so there is no risk of two buttons named
  // "Board" reappearing.
  //
  // Still excludes Tokens/Workspaces (account-scoped, D2) and Inbox (already has
  // the bell, D3/crease 4) — those never appear in the rail at any point.
  import {
    Activity,
    Archive,
    Layers,
    LayoutDashboard,
    SquareKanban,
    Tag,
    Trash2,
    Users,
  } from "lucide-svelte";
  import type { Icon } from "lucide-svelte";

  export type RailView =
    | "board"
    | "dashboard"
    | "epics"
    | "labels"
    | "backlog"
    | "activity"
    | "members"
    | "trash";

  let {
    view,
    open,
    onNavigate,
    onClose,
  }: { view: string; open: boolean; onNavigate: (view: RailView) => void; onClose: () => void } =
    $props();

  const items: { id: RailView; label: string; icon: typeof Icon }[] = [
    { id: "board", label: "Board", icon: SquareKanban },
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "epics", label: "Epics", icon: Layers },
    { id: "labels", label: "Labels", icon: Tag },
    { id: "backlog", label: "Backlog", icon: Archive },
    { id: "activity", label: "Activity", icon: Activity },
    { id: "members", label: "Members", icon: Users },
    { id: "trash", label: "Trash", icon: Trash2 },
  ];

  // Picking a destination navigates AND closes the rail — it's a transient
  // overlay, not a persistent layout column, so there's nothing to leave open.
  function pick(id: RailView) {
    onNavigate(id);
    onClose();
  }

  // Close on Escape while open (mirrors the old SideNav drawer's own handling).
  function onKeydown(e: KeyboardEvent) {
    if (open && e.key === "Escape") onClose();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="nav-scrim" class:open onclick={onClose} aria-hidden="true"></div>

<nav class="nav-rail" class:open aria-label="Views" aria-hidden={!open}>
  {#each items as item (item.id)}
    {@const ItemIcon = item.icon}
    <button
      class="rail-item"
      class:active={view === item.id}
      aria-current={view === item.id ? "page" : undefined}
      tabindex={open ? 0 : -1}
      onclick={() => pick(item.id)}
    >
      <ItemIcon size={18} />
      <span>{item.label}</span>
    </button>
  {/each}
</nav>

<style>
  /* An overlay, not a layout column (see App.svelte — .app-shell no longer
     reserves space for it): fixed position + a scrim behind it, so opening
     it never shifts main/.board/anything else. Same visual language as the
     old SideNav.svelte's .drawer-item throughout. */
  .nav-scrim {
    position: fixed;
    inset: 0;
    z-index: 90;
    background: var(--scrim);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.18s ease;
  }
  .nav-scrim.open {
    opacity: 1;
    pointer-events: auto;
  }

  .nav-rail {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 100;
    width: 200px;
    max-width: 82vw;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: 1rem 0.6rem;
    background: var(--elevation-3-surface);
    border-right: 1px solid var(--border);
    box-shadow: var(--elevation-3-shadow);
    overflow-y: auto;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
  }
  .nav-rail.open {
    transform: translateX(0);
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
