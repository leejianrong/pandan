<script lang="ts">
  // Hamburger-triggered side-nav drawer (KAN-319 / U4). Being phased out by
  // NavRail.svelte (NR-1..NR-4, KAN-1148..KAN-1151) — this is what's left
  // after NR-2 moved Board to the rail and NR-3 (KAN-1150) moved the
  // account-scoped Tokens/Teams into the avatar menu. NR-4 deletes this
  // component outright once the rail covers everything it used to.
  //
  // Stateless w.r.t. navigation: App.svelte owns `view` + the `show()` side-effects.
  // This component only reports which item was picked via `onNavigate`, and
  // open/close via `open` + `onClose`.
  import {
    Activity,
    Archive,
    Inbox,
    Layers,
    LayoutDashboard,
    Tag,
    Trash2,
    Users,
    X,
  } from "lucide-svelte";
  import type { Icon } from "lucide-svelte";

  // Mirrors App.svelte's view union (minus "board"/"settings"/"tokens"/"teams",
  // none of which are in the drawer any more).
  export type DrawerView =
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
    unread = 0,
    onOpenInbox,
    onNavigate,
    onClose,
  }: {
    view: string;
    open: boolean;
    // Unread notification count for the Inbox entry's badge (V39, KAN-303).
    unread?: number;
    // Open the notification inbox popover (owned by App.svelte, anchored to the
    // top-bar bell). The Inbox entry is a second way in — it doesn't switch `view`,
    // so it's handled apart from `onNavigate`.
    onOpenInbox?: () => void;
    onNavigate: (view: DrawerView) => void;
    onClose: () => void;
  } = $props();

  const items: { id: DrawerView; label: string; icon: typeof Icon }[] = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "epics", label: "Epics", icon: Layers },
    { id: "labels", label: "Labels", icon: Tag },
    { id: "backlog", label: "Backlog", icon: Archive },
    { id: "activity", label: "Activity", icon: Activity },
    { id: "members", label: "Members", icon: Users },
    { id: "trash", label: "Trash", icon: Trash2 },
  ];

  // Close on Escape while open (Bits UI handles this for menus, but the drawer is
  // hand-rolled, so wire it here for parity with the rest of the app).
  function onKeydown(e: KeyboardEvent) {
    if (open && e.key === "Escape") onClose();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div
  class="drawer-scrim"
  class:open
  onclick={onClose}
  aria-hidden="true"
></div>

<aside class="drawer" class:open aria-label="Views" aria-hidden={!open}>
  <div class="drawer-head">
    <span class="drawer-title">Views</span>
    <button class="icon-btn" onclick={onClose} aria-label="Close menu">
      <X size={16} />
    </button>
  </div>
  <nav class="drawer-nav">
    <!-- Inbox (V39, KAN-303): opens the top-bar bell popover rather than switching a
         view, and carries the same unread count as its badge. -->
    <button
      class="drawer-item"
      onclick={() => onOpenInbox?.()}
      tabindex={open ? 0 : -1}
    >
      <Inbox size={18} />
      <span>Inbox</span>
      {#if unread > 0}
        <span class="drawer-badge">{unread > 9 ? "9+" : unread}</span>
      {/if}
    </button>
    {#each items as item (item.id)}
      {@const ItemIcon = item.icon}
      <button
        class="drawer-item"
        class:active={view === item.id}
        aria-current={view === item.id ? "page" : undefined}
        onclick={() => onNavigate(item.id)}
        tabindex={open ? 0 : -1}
      >
        <ItemIcon size={18} />
        <span>{item.label}</span>
      </button>
    {/each}
  </nav>
</aside>

<style>
  .drawer-scrim {
    position: fixed;
    inset: 0;
    z-index: 90;
    background: var(--scrim);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.18s ease;
  }
  .drawer-scrim.open {
    opacity: 1;
    pointer-events: auto;
  }

  .drawer {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 100;
    width: 264px;
    max-width: 82vw;
    background: var(--elevation-3-surface);
    border-right: 1px solid var(--border);
    box-shadow: var(--elevation-3-shadow);
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    display: flex;
    flex-direction: column;
  }
  .drawer.open {
    transform: translateX(0);
  }

  .drawer-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.85rem 1rem 0.7rem;
    border-bottom: 1px solid var(--border);
  }
  .drawer-title {
    font-size: var(--type-label-medium-size);
    line-height: var(--type-label-medium-line-height);
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .drawer-nav {
    padding: 0.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    overflow-y: auto;
  }
  .drawer-item {
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
  .drawer-item :global(svg) {
    color: var(--muted);
    flex: none;
  }
  .drawer-item:hover {
    background: var(--state-hover);
  }
  .drawer-item:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
    background: var(--state-focus);
  }
  .drawer-item:active {
    background: var(--state-pressed);
  }
  .drawer-item.active {
    background: var(--accent-soft);
    border-color: var(--border);
    color: var(--accent);
    font-weight: 600;
  }
  .drawer-item.active:hover {
    background: linear-gradient(var(--state-hover), var(--state-hover)), var(--accent-soft);
  }
  .drawer-item.active:focus-visible {
    background: linear-gradient(var(--state-focus), var(--state-focus)), var(--accent-soft);
  }
  .drawer-item.active:active {
    background: linear-gradient(var(--state-pressed), var(--state-pressed)), var(--accent-soft);
  }
  .drawer-item.active :global(svg) {
    color: var(--accent);
  }
  /* Unread count on the Inbox entry (V39, KAN-303) — the drawer twin of the top-bar
     bell badge, same teal treatment. */
  .drawer-badge {
    margin-left: auto;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    display: grid;
    place-items: center;
    font-size: var(--type-label-small-size);
    line-height: var(--type-label-small-line-height);
    letter-spacing: var(--type-label-small-tracking);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    background: var(--accent);
    color: #fff;
    border-radius: var(--shape-full);
    flex: none;
  }

  /* Matches app.css .icon-btn so the close button reads identically. */
  .icon-btn {
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 1px solid transparent;
    background: none;
    color: var(--muted);
    border-radius: var(--shape-full);
    cursor: pointer;
  }
  .icon-btn:hover {
    background: var(--state-hover);
    color: var(--text);
  }
  .icon-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
    background: var(--state-focus);
    color: var(--text);
  }
  .icon-btn:active {
    background: var(--state-pressed);
    color: var(--text);
  }
</style>
