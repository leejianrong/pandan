<script lang="ts">
  // ⌘K command palette (V35, KAN-299). A fuzzy command menu over EXISTING API
  // actions — no new backend. It drives the reusable, styled ui/Command primitive
  // (U2/KAN-317) inside the shared Modal shell (focus-trap + Esc + scrim), and
  // builds the command registry wired to the board stores / navigation.
  //
  // Server-authoritative like the rest of the app (BREADBOARD §7): every command
  // calls an existing store action that hits the API and refetch()es — no
  // optimistic UI here. Commands that need a target (move a card, jump to a board /
  // epic, set a filter) use a two-step: pick the command, then the search box
  // filters the candidate list to pick the target.
  import {
    ArrowRight,
    LayoutDashboard,
    Layers,
    ListFilter,
    Moon,
    MoveRight,
    Plus,
    SquareKanban,
    Sun,
  } from "lucide-svelte";
  import { tick } from "svelte";
  import Modal from "./Modal.svelte";
  import { Command } from "./ui";
  import type { CommandGroup, CommandItem } from "./ui";
  import { COLUMNS, boardStore, board, epicStore, setActiveBoard, addCard, moveCard, setQuery, setActiveView } from "../board.svelte";
  import { themeStore, toggleTheme } from "../theme.svelte";
  import type { Column } from "../api";

  // App owns navigation (`show()` has side-effects like refetchTokens), so it's
  // injected. `open` is bindable so the ⌘K global (App.svelte) and Esc can toggle.
  let {
    open = $bindable(false),
    navigate,
  }: {
    open?: boolean;
    navigate: (view: string) => void;
  } = $props();

  // Which step of a (possibly multi-step) command we're on. "root" is the menu.
  type Mode =
    | "root"
    | "create"
    | "move-pick"
    | "move-target"
    | "board"
    | "epic"
    | "view"
    | "filter";
  let mode = $state<Mode>("root");
  let search = $state("");
  // The card chosen in "move-pick", carried into "move-target".
  let moveCardId = $state<number | null>(null);
  let moveCardLabel = $state("");

  // Navigable views (mirrors App.svelte's `view` union / SideNav's drawer items).
  const VIEWS: { id: string; label: string }[] = [
    { id: "board", label: "Board" },
    { id: "dashboard", label: "Dashboard" },
    { id: "epics", label: "Epics" },
    { id: "activity", label: "Activity" },
    { id: "tokens", label: "Tokens" },
    { id: "members", label: "Members" },
    { id: "trash", label: "Trash" },
    { id: "settings", label: "Settings" },
  ];

  // Reset to the root menu whenever the palette (re)opens, so a stale sub-step
  // never lingers between invocations.
  $effect(() => {
    if (open) resetToRoot();
  });

  function resetToRoot() {
    mode = "root";
    search = "";
    moveCardId = null;
    moveCardLabel = "";
  }

  function close() {
    open = false;
  }

  // Enter a sub-step: switch mode and clear the search so the target list isn't
  // pre-filtered by the command's own name. Selecting a command by MOUSE moves
  // focus to the Command root, so pull it back to the search input — otherwise the
  // user (and, in "create", the title they type) has nowhere to type. Keyboard
  // selection never lost input focus, so this is a harmless no-op there.
  async function enter(next: Mode) {
    mode = next;
    search = "";
    await tick();
    document
      .querySelector<HTMLInputElement>(".ui-command .ui-command-search input")
      ?.focus();
  }

  // Terminal action: run the API-backed store call, then close. Errors surface via
  // the board store's own error handling (each action refetch()es).
  function run(action: () => void | Promise<void>) {
    close();
    void action();
  }

  // ---- Registry, rebuilt reactively per mode ----
  const groups = $derived.by<CommandGroup[]>(() => {
    switch (mode) {
      case "create":
        return createGroups();
      case "move-pick":
        return cardPickGroups();
      case "move-target":
        return moveTargetGroups();
      case "board":
        return boardGroups();
      case "epic":
        return epicGroups();
      case "view":
        return viewGroups();
      case "filter":
        return filterGroups();
      default:
        return rootGroups();
    }
  });

  // Free-text create mode disables Bits UI filtering — the search box is the card
  // title, not a filter over a fixed list.
  const shouldFilter = $derived(mode !== "create");

  const placeholder = $derived(
    mode === "create"
      ? "New card title, then Enter…"
      : mode === "move-pick"
        ? "Search a card to move…"
        : "Type a command or search…",
  );

  const emptyMessage = $derived(
    mode === "create" ? "Type a title, then Enter to create." : "No results.",
  );

  function rootGroups(): CommandGroup[] {
    return [
      {
        heading: "Create",
        items: [
          { value: "create-card", label: "Create card", icon: Plus, keywords: ["new", "add", "story"], onSelect: () => enter("create") },
        ],
      },
      {
        heading: "Card actions",
        items: [
          { value: "move-card", label: "Move card…", icon: MoveRight, keywords: ["column", "todo", "progress", "done", "kan"], onSelect: () => enter("move-pick") },
        ],
      },
      {
        heading: "Navigate",
        items: [
          { value: "open-dashboard", label: "Open dashboard", icon: LayoutDashboard, keywords: ["metrics", "stats"], onSelect: () => run(() => navigate("dashboard")) },
          { value: "jump-view", label: "Jump to view…", icon: ArrowRight, keywords: ["go", "page", "screen"], onSelect: () => enter("view") },
          { value: "jump-board", label: "Jump to board…", icon: SquareKanban, keywords: ["switch", "project"], onSelect: () => enter("board") },
          { value: "jump-epic", label: "Jump to epic…", icon: Layers, keywords: ["filter", "group"], onSelect: () => enter("epic") },
        ],
      },
      {
        heading: "Filter & preferences",
        items: [
          { value: "set-filter", label: "Set filter…", icon: ListFilter, keywords: ["query", "column", "search"], onSelect: () => enter("filter") },
          {
            value: "toggle-theme",
            label: themeStore.theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
            icon: themeStore.theme === "dark" ? Sun : Moon,
            keywords: ["dark", "light", "appearance"],
            onSelect: () => run(toggleTheme),
          },
        ],
      },
    ];
  }

  function createGroups(): CommandGroup[] {
    const title = search.trim();
    if (!title) return [];
    return [
      {
        heading: "Create card",
        items: [
          {
            value: "do-create",
            label: `Create card "${title}"`,
            icon: Plus,
            onSelect: () => run(() => addCard({ title, column: "todo" })),
          },
        ],
      },
    ];
  }

  // The card list for "move-pick" (search by ticket + title). Empty board → nothing.
  function cardPickGroups(): CommandGroup[] {
    const items: CommandItem[] = board.cards.map((c) => ({
      value: `${c.ticket_number} ${c.title}`,
      label: `${c.ticket_number} · ${c.title}`,
      keywords: [c.ticket_number, c.title],
      onSelect: () => {
        moveCardId = c.id;
        moveCardLabel = c.ticket_number;
        enter("move-target");
      },
    }));
    return [{ heading: "Move which card?", items }];
  }

  function moveTargetGroups(): CommandGroup[] {
    const items: CommandItem[] = COLUMNS.map((col) => ({
      value: col.key,
      label: `Move ${moveCardLabel} to ${col.label}`,
      icon: MoveRight,
      keywords: [col.label],
      onSelect: () => {
        const id = moveCardId;
        if (id == null) return close();
        run(() => moveCard(id, { column: col.key as Column }));
      },
    }));
    return [{ heading: "Move to column", items }];
  }

  function boardGroups(): CommandGroup[] {
    const items: CommandItem[] = boardStore.boards.map((b) => ({
      value: `${b.id} ${b.name}`,
      label: b.name,
      icon: SquareKanban,
      keywords: [b.name],
      onSelect: () => run(async () => {
        await setActiveBoard(b.id);
        navigate("board");
      }),
    }));
    return [{ heading: "Switch board", items }];
  }

  // "Jump to epic" filters the board to that epic's stories (server-authoritative
  // via the existing query API) and shows the board.
  function epicGroups(): CommandGroup[] {
    const items: CommandItem[] = epicStore.epics.map((e) => ({
      value: `${e.ticket_number} ${e.name}`,
      label: `${e.ticket_number} · ${e.name}`,
      icon: Layers,
      keywords: [e.ticket_number, e.name],
      onSelect: () => run(async () => {
        navigate("board");
        await setQuery({ epic_id: e.id });
      }),
    }));
    return [{ heading: "Show stories in epic", items }];
  }

  function viewGroups(): CommandGroup[] {
    const items: CommandItem[] = VIEWS.map((v) => ({
      value: v.id,
      label: v.label,
      icon: ArrowRight,
      keywords: [v.label],
      onSelect: () => run(() => navigate(v.id)),
    }));
    return [{ heading: "Go to view", items }];
  }

  // Filters map to the existing card query grammar (setQuery / setActiveView).
  function filterGroups(): CommandGroup[] {
    const columnItems: CommandItem[] = COLUMNS.map((col) => ({
      value: `filter-${col.key}`,
      label: `Filter: ${col.label}`,
      icon: ListFilter,
      keywords: [col.label, "column"],
      onSelect: () => run(async () => {
        navigate("board");
        await setQuery({ column: col.key as Column });
      }),
    }));
    return [
      { heading: "Filter by column", items: columnItems },
      {
        heading: "Other filters",
        items: [
          {
            value: "filter-needs-human",
            label: "Filter: Needs human",
            icon: ListFilter,
            keywords: ["attention", "handoff"],
            onSelect: () => run(async () => {
              navigate("board");
              await setQuery({ needs_human: true });
            }),
          },
          {
            value: "filter-overdue",
            label: "Filter: Overdue",
            icon: ListFilter,
            keywords: ["late", "due"],
            onSelect: () => run(async () => {
              navigate("board");
              await setQuery({ overdue: true });
            }),
          },
          {
            value: "filter-clear",
            label: "Clear all filters",
            icon: ListFilter,
            keywords: ["reset", "all cards"],
            onSelect: () => run(() => setActiveView(null)),
          },
        ],
      },
    ];
  }
</script>

{#if open}
  <Modal label="Command palette" onclose={close}>
    <div class="command-palette">
      <Command bind:value={search} {groups} {placeholder} {emptyMessage} {shouldFilter} />
    </div>
  </Modal>
{/if}

<style>
  /* `.ui-command` is already a full panel (bg + border + radius + shadow), so
     flatten the wrapping Modal chrome for the palette to avoid a doubled box, and
     let the wrapper shrink to the palette's width so the backdrop keeps it centered
     (spotlight style, near the top — Modal's place-items:start center). */
  .command-palette {
    width: min(92vw, 540px);
  }
  :global(.modal:has(.command-palette)) {
    width: auto;
    background: transparent;
    border: none;
    box-shadow: none;
    overflow: visible;
  }
</style>
