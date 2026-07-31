<script lang="ts">
  import { Ban, CalendarClock, Hand, Link as LinkIcon, Pencil, Trash2 } from "lucide-svelte";
  import type { Card, Priority } from "../api";
  import { cardById, epicFor, removeCard } from "../board.svelte";
  import { kbd } from "../keyboard.svelte";
  import CardModal from "./CardModal.svelte";

  let { card }: { card: Card } = $props();

  // The epic this story belongs to (if any) — rendered as a tag on the face.
  const epic = $derived(epicFor(card.epic_id));

  // Priority badge (M5 V11): a colored dot + label, hidden for "none". The colors
  // are chosen to read in both light and dark themes.
  const PRIORITY_META: Record<Priority, { label: string; color: string } | null> = {
    none: null,
    low: { label: "Low", color: "var(--muted)" },
    medium: { label: "Medium", color: "#d97706" },
    high: { label: "High", color: "#ea580c" },
    urgent: { label: "Urgent", color: "var(--danger)" },
  };
  const priorityMeta = $derived(PRIORITY_META[card.priority]);

  // Due / overdue pill (M5 V11): overdue = past its due date and not yet done.
  const dueInfo = $derived.by(() => {
    if (!card.due_date) return null;
    const d = new Date(card.due_date);
    if (Number.isNaN(d.getTime())) return null;
    const overdue = d.getTime() < Date.now() && card.column !== "done";
    return {
      text: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      title: d.toLocaleString(),
      overdue,
    };
  });

  // Dependency references, resolved to cards for their ticket + title.
  function ref(id: number): { ticket: string; title: string } {
    const c = cardById(id);
    return c
      ? { ticket: c.ticket_number, title: c.title }
      : { ticket: `#${id}`, title: `card ${id}` };
  }
  const blockedBy = $derived(card.blocked_by.map(ref));
  const blocks = $derived(card.blocks.map(ref));

  const initials = $derived(card.assignee?.trim().charAt(0).toUpperCase() ?? "");

  // view (P1 face) · confirmDelete (P4 quick-delete). Full view/edit is the modal.
  let mode = $state<"view" | "confirmDelete">("view");
  let showModal = $state(false);
  // Opened via the `e` shortcut → modal lands focused on the title for editing.
  let modalEditFocus = $state(false);
  let deleting = $state(false);
  let deleteError = $state<string | null>(null);

  // Click-vs-drag: svelte-dnd-action owns the drag. A press that barely moves and
  // doesn't land on an inner control is a real click → open the detail modal.
  let downX = 0;
  let downY = 0;
  function onPointerDown(e: PointerEvent) {
    downX = e.clientX;
    downY = e.clientY;
  }
  function isInteractive(t: EventTarget | null): boolean {
    return t instanceof Element && !!t.closest("button, a");
  }
  function openFromClick(e: MouseEvent) {
    if (isInteractive(e.target)) return; // let buttons / links handle themselves
    if (Math.hypot(e.clientX - downX, e.clientY - downY) > 6) return; // it was a drag
    showModal = true;
  }
  // Keyboard affordances on the focused card face (V36, KAN-300). A focused
  // role=button opening on Enter/Space is the existing, accessible affordance; we
  // build on it with `o` (open) and `e` (open focused for editing). These fire only
  // when the card itself is the key target (not an inner control) and never carry a
  // Cmd/Ctrl chord (⌘K et al. belong to the global handlers), so typing is safe.
  function onKeydown(e: KeyboardEvent) {
    if (e.target !== e.currentTarget) return; // ignore keys from inner controls
    if (e.metaKey || e.ctrlKey || e.altKey) return; // chords belong to global handlers
    if (e.key === "Enter" || e.key === " " || e.key === "o") {
      e.preventDefault();
      modalEditFocus = false;
      showModal = true;
    } else if (e.key === "e") {
      e.preventDefault();
      modalEditFocus = true;
      showModal = true;
    }
  }

  async function confirmDelete() {
    deleting = true;
    deleteError = null;
    try {
      await removeCard(card.id);
    } catch (e) {
      deleteError = e instanceof Error ? e.message : "Failed to delete card";
      deleting = false;
    }
  }
</script>

{#if mode === "confirmDelete"}
  <div class="card confirm">
    <p class="confirm-msg">
      Delete <strong>{card.ticket_number}</strong> — “{card.title}”? This can't be
      undone.
    </p>
    {#if deleteError}
      <p class="form-error" role="alert">{deleteError}</p>
    {/if}
    <div class="row actions">
      <button class="danger" onclick={confirmDelete} disabled={deleting}>Delete</button>
      <button onclick={() => (mode = "view")} disabled={deleting}>Cancel</button>
    </div>
  </div>
{:else}
  <div
    class="card"
    class:is-blocked={card.blocked}
    class:kbd-focused={kbd.focusedCardId === card.id}
    role="button"
    tabindex="0"
    data-card-id={card.id}
    aria-label="Open {card.ticket_number}: {card.title}"
    onpointerdown={onPointerDown}
    onfocus={() => (kbd.focusedCardId = card.id)}
    onclick={openFromClick}
    onkeydown={onKeydown}
  >
    <div class="card-top">
      <span class="ticket">{card.ticket_number}</span>
      {#if priorityMeta}
        <span class="priority-badge" title="Priority: {priorityMeta.label}">
          <span class="priority-dot" style="background: {priorityMeta.color}" aria-hidden="true"
          ></span>
          {priorityMeta.label}
        </span>
      {/if}
      {#if card.blocked}
        <span class="blocked-badge" title="Blocked by an unfinished card">
          <Ban size={11} aria-hidden="true" />
          Blocked
        </span>
      {/if}
      {#if card.needs_human}
        <span class="needs-human-badge" title={card.attention_note ?? "Flagged for a human"}>
          <Hand size={11} aria-hidden="true" />
          Needs human
        </span>
      {/if}
      {#if epic}
        <span class="epic-tag" title="{epic.ticket_number} · {epic.name}">{epic.name}</span>
      {/if}
      {#if card.story_points != null}
        <span class="points" title="Story points">{card.story_points}</span>
      {/if}
    </div>
    <p class="card-title">{card.title}</p>
    {#if card.labels.length > 0 || dueInfo}
      <div class="card-meta">
        {#each card.labels as label (label.id)}
          <span class="label-chip" title={label.name}>
            <span class="label-dot" style="background: {label.color}" aria-hidden="true"></span>
            <span class="label-name">{label.name}</span>
          </span>
        {/each}
        {#if dueInfo}
          <span class="due-pill" class:overdue={dueInfo.overdue} title="Due {dueInfo.title}">
            <CalendarClock size={11} aria-hidden="true" />
            {dueInfo.text}
          </span>
        {/if}
      </div>
    {/if}
    {#if blockedBy.length > 0 || blocks.length > 0}
      <div class="deps">
        {#if blockedBy.length > 0}
          <p class="dep-line">
            <span class="dep-label">Blocked by</span>
            {#each blockedBy as b (b.ticket)}
              <span class="dep-ref" title={b.title}>{b.ticket}</span>
            {/each}
          </p>
        {/if}
        {#if blocks.length > 0}
          <p class="dep-line">
            <span class="dep-label">Blocks</span>
            {#each blocks as b (b.ticket)}
              <span class="dep-ref" title={b.title}>{b.ticket}</span>
            {/each}
          </p>
        {/if}
      </div>
    {/if}
    {#if card.links.length > 0}
      <div class="links">
        {#each card.links as link (link.id)}
          <a
            class="link-chip"
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            title="{link.label} · {link.url}"
          >
            <LinkIcon size={11} aria-hidden="true" />
            <span class="link-label">{link.label}</span>
          </a>
        {/each}
      </div>
    {/if}
    <div class="card-foot">
      {#if card.assignee}
        <span class="who">
          <span class="avatar-sm" aria-hidden="true">{initials}</span>
          <span class="who-name">{card.assignee}</span>
        </span>
      {/if}
      <div class="card-actions">
        <button class="icon-btn" title="Edit" aria-label="Edit" onclick={() => (showModal = true)}>
          <Pencil size={15} />
        </button>
        <button
          class="icon-btn danger"
          title="Delete"
          aria-label="Delete"
          onclick={() => (mode = "confirmDelete")}
        >
          <Trash2 size={15} />
        </button>
      </div>
    </div>
  </div>
{/if}

{#if showModal}
  <CardModal
    cardId={card.id}
    editFocus={modalEditFocus}
    onclose={() => (showModal = false)}
  />
{/if}
