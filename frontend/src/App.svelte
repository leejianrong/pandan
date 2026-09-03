<script lang="ts">
  import { onMount } from "svelte";
  import { Keyboard, LogOut, Menu, Moon, Search, Settings, Sun } from "lucide-svelte";
  import Activity from "./lib/components/Activity.svelte";
  import Backlog from "./lib/components/Backlog.svelte";
  import Board from "./lib/components/Board.svelte";
  import Dashboard from "./lib/components/Dashboard.svelte";
  import Brand from "./lib/components/Brand.svelte";
  import Epics from "./lib/components/Epics.svelte";
  import Labels from "./lib/components/Labels.svelte";
  import Inbox from "./lib/components/Inbox.svelte";
  import Landing from "./lib/components/Landing.svelte";
  import BoardSwitcher from "./lib/components/BoardSwitcher.svelte";
  import CommandPalette from "./lib/components/CommandPalette.svelte";
  import SideNav from "./lib/components/SideNav.svelte";
  import type { DrawerView } from "./lib/components/SideNav.svelte";
  import NavRail from "./lib/components/NavRail.svelte";
  import type { RailView } from "./lib/components/NavRail.svelte";
  import Tokens from "./lib/components/Tokens.svelte";
  import Members from "./lib/components/Members.svelte";
  import Teams from "./lib/components/Teams.svelte";
  import Trash from "./lib/components/Trash.svelte";
  import ShortcutsHelp from "./lib/components/ShortcutsHelp.svelte";
  import { DropdownMenu } from "./lib/components/ui";
  import type { MenuItem } from "./lib/components/ui";
  import { refetch, refetchBacklog, refetchBoards, refetchEpics, refetchLabels, refetchViews, setQuery } from "./lib/board.svelte";
  import { refetchTokens } from "./lib/tokens.svelte";
  import { refetchTeams } from "./lib/teams.svelte";
  import {
    startNotificationPolling,
    stopNotificationPolling,
    unreadCount,
  } from "./lib/notifications.svelte";
  import { setSessionUser } from "./lib/session.svelte";
  import { initTheme, themeStore, toggleTheme } from "./lib/theme.svelte";
  import { kbd } from "./lib/keyboard.svelte";
  import { getCurrentUser, logout, type CurrentUser } from "./lib/api";

  // The board is the primary view (a pill in the top bar). Secondary views live in
  // a hamburger side-nav drawer (KAN-319/U4). Still no client-side router — a
  // conditional render keyed on `view`.
  let view = $state<
    | "board"
    | "dashboard"
    | "epics"
    | "labels"
    | "backlog"
    | "activity"
    | "tokens"
    | "members"
    | "teams"
    | "trash"
    | "settings"
  >("board");

  // The side-nav drawer's open state (secondary views live inside it).
  let drawerOpen = $state(false);

  // The ⌘K command palette's open state (V35, KAN-299).
  let paletteOpen = $state(false);

  // The notification inbox popover's open state (V39, KAN-303). Owned here (not in
  // Inbox.svelte) so the side-nav's Inbox entry can open the same popover.
  let inboxOpen = $state(false);

  // ⌘K / Ctrl-K toggles the command palette. This is a deliberate GLOBAL — it
  // fires even while focus is in an input/search box (that's the whole point of a
  // command palette), so we don't guard against a focused field here; we only ever
  // react to the ⌘/Ctrl + K chord, so ordinary typing is never hijacked. Escape and
  // the backdrop close it (handled by the Modal the palette mounts in).
  function onWindowKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      paletteOpen = !paletteOpen;
    }
  }

  // Tokens are user-scoped (not board-scoped), so load them lazily the first time
  // the Tokens view is opened.
  function show(next: typeof view) {
    view = next;
    if (next === "tokens") refetchTokens();
  }

  // Navigating from the drawer selects the view and closes the drawer.
  function navigateFromDrawer(next: DrawerView) {
    show(next);
    drawerOpen = false;
  }

  // Navigating from the persistent rail (NR-1, KAN-1148) — no drawer to close.
  function navigateFromRail(next: RailView) {
    show(next);
  }

  // Auth gating (M3 V6, A9): undefined = check in flight; null = logged out (show
  // the landing); a user = logged in (show the board). No client-side router — a
  // conditional render, matching the Board|Epics toggle style.
  let user = $state<CurrentUser | null | undefined>(undefined);

  // The avatar's initial. Derived (not inline) because the DropdownMenu trigger is
  // a snippet closure, where the `{:else user}` template narrowing doesn't reach.
  const avatarInitial = $derived((user?.email ?? "?").charAt(0).toUpperCase());

  onMount(async () => {
    initTheme();
    try {
      user = await getCurrentUser();
    } catch {
      // Treat an unreachable/erroring auth check as logged-out (show the landing)
      // rather than getting stuck on a blank screen.
      user = null;
    }
    // Expose the user id for delete-own affordances deep in the tree (comments).
    setSessionUser(user?.id ?? null);
    // Load boards first (picks the active board), then that board's cards + epics.
    if (user) {
      await refetchBoards();
      refetch();
      refetchEpics();
      refetchLabels();
      refetchViews();
      refetchBacklog();
      // Teams are user-scoped, not board-scoped (M9 V70) — load once here, not
      // per-board-switch, and eagerly (not lazily like Tokens) because the
      // BoardSwitcher's Team picker needs the list too.
      refetchTeams();
      // Start polling the notification inbox (V39, KAN-303) — user-scoped, so it
      // runs independent of the active board and keeps the top-bar badge fresh.
      startNotificationPolling();
    }
  });

  async function handleLogout() {
    // Stop the inbox poll before the session goes away (also clears the badge).
    stopNotificationPolling();
    await logout();
    user = null;
    setSessionUser(null);
  }

  // Avatar dropdown menu (KAN-319/U4): the signed-in email (as a heading/subtitle),
  // a Settings entry (stub view), and Log out (danger). Replaces the always-on
  // inline email + logout icon that used to crowd the top bar.
  const avatarMenuItems: MenuItem[] = [
    { label: "Settings", icon: Settings, onSelect: () => show("settings") },
    {
      label: "Keyboard shortcuts",
      icon: Keyboard,
      hint: "?",
      onSelect: () => (kbd.helpOpen = true),
    },
    {
      label: "Log out",
      icon: LogOut,
      danger: true,
      separatorBefore: true,
      onSelect: handleLogout,
    },
  ];

  // Full-text search (M5 V15, KAN-248): typing merges a `q` into the active card
  // query and refetches (server-authoritative — the board shows exactly what the
  // server returned for the query). Debounced so a keystroke burst is one request;
  // searching jumps to the board view so the ranked hits are visible.
  let searchText = $state("");
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  function onSearchInput(value: string) {
    searchText = value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      view = "board";
      setQuery({ q: value.trim() || undefined });
    }, 200);
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#if user === undefined}
  <!-- Auth check in flight: render nothing so the landing doesn't flash. -->
{:else if user === null}
  <Landing />
{:else}
  <header class="topbar">
    <button
      class="icon-btn"
      aria-label="Open menu"
      aria-expanded={drawerOpen}
      onclick={() => (drawerOpen = true)}
    >
      <Menu size={18} />
    </button>
    <Brand />
    <BoardSwitcher />
    <button
      class="board-tab"
      class:active={view === "board"}
      onclick={() => show("board")}
    >
      Board
    </button>
    <div class="topbar-search">
      <Search size={15} aria-hidden="true" />
      <input
        type="search"
        placeholder="Search cards…"
        aria-label="Search cards"
        value={searchText}
        oninput={(e) => onSearchInput(e.currentTarget.value)}
      />
    </div>
    <div class="topbar-user">
      <Inbox bind:open={inboxOpen} />
      <button
        class="icon-btn theme-toggle"
        title={themeStore.theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        aria-label={themeStore.theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        onclick={toggleTheme}
      >
        {#if themeStore.theme === "dark"}
          <Sun size={16} />
        {:else}
          <Moon size={16} />
        {/if}
      </button>
      <DropdownMenu
        items={avatarMenuItems}
        heading="Signed in as"
        subtitle={user.email}
        triggerClass="user-avatar"
        triggerLabel="Account menu"
        align="end"
      >
        {#snippet trigger()}
          {avatarInitial}
        {/snippet}
      </DropdownMenu>
    </div>
  </header>

  <SideNav
    {view}
    open={drawerOpen}
    unread={unreadCount()}
    onOpenInbox={() => {
      inboxOpen = true;
      drawerOpen = false;
    }}
    onNavigate={navigateFromDrawer}
    onClose={() => (drawerOpen = false)}
  />

  <CommandPalette bind:open={paletteOpen} navigate={(v) => show(v as typeof view)} />

  <!-- app-shell (NR-1, KAN-1148): a layout column for the persistent rail.
       Runs alongside the existing hamburger+SideNav drawer (both work; see
       nav-rail-shaping.md D3) until NR-4 removes the drawer. -->
  <div class="app-shell">
    <NavRail {view} onNavigate={navigateFromRail} />
    <main>
      {#if view === "board"}
        <Board />
      {:else if view === "dashboard"}
        <Dashboard navigate={() => show("board")} />
      {:else if view === "epics"}
        <Epics />
      {:else if view === "labels"}
        <Labels />
      {:else if view === "backlog"}
        <Backlog />
      {:else if view === "activity"}
        <Activity />
      {:else if view === "tokens"}
        <Tokens />
      {:else if view === "members"}
        <Members />
      {:else if view === "teams"}
        <Teams />
      {:else if view === "settings"}
        <section class="settings-stub">
          <h2>Settings</h2>
          <p>Account settings are coming soon.</p>
          <p>
            Looking for personal access tokens?
            <button class="link" onclick={() => show("tokens")}>Open Tokens →</button>
          </p>
        </section>
      {:else}
        <Trash />
      {/if}
    </main>
  </div>

  <!-- Keyboard-shortcuts help overlay (V36, KAN-300). Mounted here at the top level
       (not inside Board) so the avatar menu's "Keyboard shortcuts" entry (KAN-392)
       can open it from ANY view, not just the board. The board's `?` shortcut sets
       the same `kbd.helpOpen` flag, so it still opens here. -->
  {#if kbd.helpOpen}
    <ShortcutsHelp />
  {/if}
{/if}

<style>
  /* Layout column for NavRail + main (NR-1, KAN-1148). Previously header/main
     were plain top-level siblings with no shell — app.css's own `main`
     selector still governs main's padding/etc, this just gives the rail a
     place to sit beside it. */
  .app-shell {
    display: flex;
    align-items: flex-start;
    min-height: 0;
  }
  .app-shell > :global(main) {
    flex: 1;
    min-width: 0;
  }

  .settings-stub {
    max-width: 32rem;
    color: var(--muted);
  }
  .settings-stub h2 {
    color: var(--text);
    margin-top: 0;
  }
  .settings-stub .link {
    border: none;
    background: none;
    padding: 0;
    font: inherit;
    color: var(--accent);
    cursor: pointer;
  }
  .settings-stub .link:hover {
    text-decoration: underline;
  }
  /* Zero padding (same shape as app.css's button.link) — flagged there
     too: a background wash would clip tight with no room, so only a
     focus outline is added rather than a full state layer. */
  .settings-stub .link:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
</style>
