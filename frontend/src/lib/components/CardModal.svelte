<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { Ban, Link as LinkIcon, Plus, Trash2, X } from "lucide-svelte";
  import {
    addComment,
    deleteComment,
    listComments,
    type Column,
    type Comment,
    type Priority,
  } from "../api";
  import {
    addBlocker,
    addCardLink,
    board,
    cardById,
    COLUMNS,
    editCard,
    epicFor,
    epicStore,
    labelStore,
    moveCard,
    removeBlocker,
    removeCard,
    removeCardLink,
  } from "../board.svelte";
  import { session } from "../session.svelte";
  import { marked } from "marked";
  import DOMPurify from "dompurify";
  import Modal from "./Modal.svelte";
  import { Select } from "./ui";

  // --- Markdown description (render sanitized; edit raw) -------------------
  // We {@html} user-authored text, so sanitizing is MANDATORY (XSS). marked
  // turns the raw markdown into HTML; DOMPurify then strips anything outside a
  // deliberately narrow allow-list — no <script>, no event handlers, no raw
  // HTML passthrough — which also keeps us clean under the report-only CSP.
  marked.setOptions({ gfm: true, breaks: true });

  // Force every surviving link to open isolated in a new tab; DOMPurify already
  // blocks javascript:/data: URIs, and ALLOWED_URI_REGEXP below double-locks the
  // scheme to http(s)/mailto/in-page anchors.
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  });

  const MD_SANITIZE = {
    ALLOWED_TAGS: [
      "p", "br", "hr", "strong", "em", "del", "a",
      "ul", "ol", "li", "code", "pre", "blockquote",
      "h1", "h2", "h3", "h4", "h5", "h6",
    ],
    ALLOWED_ATTR: ["href", "title", "target", "rel"],
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|#)/i,
  };

  function renderMarkdown(src: string): string {
    const html = marked.parse(src, { async: false }) as string;
    return DOMPurify.sanitize(html, MD_SANITIZE);
  }

  // The card is read live from the store by id (not a snapshot): every mutation
  // refetches board state, and this modal must reflect the fresh card without
  // being reopened. If the card vanishes (deleted elsewhere), close.
  // `editFocus` (V36, KAN-300): when opened via the `e` keyboard shortcut, focus +
  // select the title input on mount so the card lands ready to edit (vs. `o`/Enter,
  // which open it with focus on the Close button, the Modal's default).
  let {
    cardId,
    onclose,
    editFocus = false,
  }: { cardId: number; onclose: () => void; editFocus?: boolean } = $props();

  let titleInput = $state<HTMLInputElement | undefined>();

  const card = $derived(cardById(cardId));
  $effect(() => {
    if (card == null) onclose();
  });

  const STORY_POINTS = [1, 2, 3, 5, 8, 13];
  const PRIORITIES: Priority[] = ["none", "low", "medium", "high", "urgent"];

  // A card's due_date (ISO) → the "YYYY-MM-DD" a <input type=date> wants (local).
  function toDateInput(iso: string | null | undefined): string {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  // Editable fields (title/description/story_points/assignee/epic/priority/due/
  // labels) are batched behind "Save changes" (PATCH). Snapshot the initial values
  // once so a refetch while the modal is open doesn't clobber in-progress edits;
  // the snapshot also drives change detection. Status is NOT here — it moves the
  // card immediately via the dedicated move endpoint (see onStatusChange).
  const initial = untrack(() => ({
    title: card?.title ?? "",
    desc: card?.description ?? "",
    assignee: card?.assignee ?? "",
    pts: card?.story_points != null ? String(card.story_points) : "",
    epic: card?.epic_id != null ? String(card.epic_id) : "",
    priority: (card?.priority ?? "none") as Priority,
    due: toDateInput(card?.due_date),
    labels: (card?.labels ?? []).map((l) => l.id).sort((a, b) => a - b),
  }));

  let title = $state(initial.title);
  let description = $state(initial.desc);
  let assignee = $state(initial.assignee);
  let storyPoints = $state<string>(initial.pts);
  let epicId = $state<string>(initial.epic);
  let priority = $state<Priority>(initial.priority);
  let dueDate = $state<string>(initial.due);
  let labelIds = $state<number[]>([...initial.labels]);
  let submitting = $state(false);
  let error = $state<string | null>(null);

  // Description shows rendered markdown by default when there's something to
  // read, dropping into the raw editor on demand (or immediately for a blank
  // card). The raw `description` string is what's bound + submitted; the toggle
  // only changes how it's presented.
  let descMode = $state<"edit" | "preview">(
    initial.desc.trim() ? "preview" : "edit",
  );

  const epicOptions = $derived(epicStore.epics);
  const labelOptions = $derived(labelStore.labels);

  // Option lists for the standardized Select primitives.
  const statusOptions = COLUMNS.map((c) => ({ value: c.key, label: c.label }));
  const pointOptions = [
    { value: "", label: "— unestimated" },
    ...STORY_POINTS.map((p) => ({ value: String(p), label: String(p) })),
  ];
  const priorityOptions = PRIORITIES.map((p) => ({
    value: p,
    label: p === "none" ? "— none" : p,
  }));
  const epicSelectOptions = $derived([
    { value: "", label: "— no epic" },
    ...epicOptions.map((e) => ({
      value: String(e.id),
      label: `${e.ticket_number} · ${e.name}`,
    })),
  ]);

  function toggleLabel(id: number) {
    labelIds = labelIds.includes(id)
      ? labelIds.filter((x) => x !== id)
      : [...labelIds, id];
  }
  const epic = $derived(card ? epicFor(card.epic_id) : null);
  const ticket = $derived(card?.ticket_number ?? "");
  const columnLabel = $derived(
    COLUMNS.find((c) => c.key === card?.column)?.label ?? "",
  );

  // --- Status → move (dedicated endpoint, immediate) ----------------------
  let moving = $state(false);
  async function onStatusChange(next: string) {
    if (!card || next === card.column) return;
    moving = true;
    try {
      await moveCard(card.id, { column: next as Column });
    } finally {
      moving = false;
    }
  }

  // --- Blockers (immediate) ------------------------------------------------
  const blockers = $derived(
    card ? card.blocked_by.map((id) => board.cards.find((c) => c.id === id)) : [],
  );
  const blockerCandidates = $derived(
    card
      ? board.cards.filter(
          (c) => c.id !== card.id && !card.blocked_by.includes(c.id),
        )
      : [],
  );
  const blocks = $derived(
    card ? card.blocks.map((id) => cardById(id)) : [],
  );
  const blockerOptions = $derived([
    {
      value: "",
      label: blockerCandidates.length === 0 ? "— no cards to add" : "— add a blocker",
    },
    ...blockerCandidates.map((c) => ({
      value: String(c.id),
      label: `${c.ticket_number} · ${c.title}`,
    })),
  ]);
  let depBusy = $state(false);
  let depError = $state<string | null>(null);

  async function onAddBlocker(blockerId: string) {
    if (!blockerId || !card) return;
    depBusy = true;
    depError = null;
    try {
      await addBlocker(card.id, Number(blockerId));
    } catch (e) {
      depError = e instanceof Error ? e.message : "Failed to add blocker";
    } finally {
      depBusy = false;
    }
  }
  async function onRemoveBlocker(blockerId: number) {
    if (!card) return;
    depBusy = true;
    depError = null;
    try {
      await removeBlocker(card.id, blockerId);
    } catch (e) {
      depError = e instanceof Error ? e.message : "Failed to remove blocker";
    } finally {
      depBusy = false;
    }
  }

  // --- Work-links (immediate) ---------------------------------------------
  const links = $derived(card ? card.links : []);
  let linkLabel = $state("");
  let linkUrl = $state("");
  let linkBusy = $state(false);
  let linkError = $state<string | null>(null);
  const canAddLink = $derived(
    linkLabel.trim().length > 0 && linkUrl.trim().length > 0 && !linkBusy,
  );
  async function onAddLink() {
    if (!canAddLink || !card) return;
    linkBusy = true;
    linkError = null;
    try {
      await addCardLink(card.id, linkLabel.trim(), linkUrl.trim());
      linkLabel = "";
      linkUrl = "";
    } catch (e) {
      linkError = e instanceof Error ? e.message : "Failed to add link";
    } finally {
      linkBusy = false;
    }
  }
  async function onRemoveLink(linkId: number) {
    if (!card) return;
    linkBusy = true;
    linkError = null;
    try {
      await removeCardLink(card.id, linkId);
    } catch (e) {
      linkError = e instanceof Error ? e.message : "Failed to remove link";
    } finally {
      linkBusy = false;
    }
  }

  // --- Comments / notes (immediate; fetched on open) ----------------------
  let comments = $state<Comment[]>([]);
  let commentsLoaded = $state(false);
  let newComment = $state("");
  let commentBusy = $state(false);
  let commentError = $state<string | null>(null);

  async function loadComments() {
    try {
      comments = await listComments(cardId);
    } catch (e) {
      commentError = e instanceof Error ? e.message : "Failed to load comments";
    } finally {
      commentsLoaded = true;
    }
  }
  onMount(loadComments);
  onMount(() => {
    if (editFocus) {
      titleInput?.focus();
      titleInput?.select();
    }
  });

  const canPostComment = $derived(newComment.trim().length > 0 && !commentBusy);
  async function onPostComment() {
    if (!canPostComment) return;
    commentBusy = true;
    commentError = null;
    try {
      await addComment(cardId, newComment.trim());
      newComment = "";
      await loadComments();
    } catch (e) {
      commentError = e instanceof Error ? e.message : "Failed to post comment";
    } finally {
      commentBusy = false;
    }
  }
  async function onDeleteComment(commentId: number) {
    commentBusy = true;
    commentError = null;
    try {
      await deleteComment(cardId, commentId);
      await loadComments();
    } catch (e) {
      commentError = e instanceof Error ? e.message : "Failed to delete comment";
    } finally {
      commentBusy = false;
    }
  }
  function ownComment(c: Comment): boolean {
    return session.userId != null && c.author_id === session.userId;
  }
  function formatWhen(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  }
  function initialOf(name: string | null | undefined): string {
    return name?.trim().charAt(0).toUpperCase() ?? "•";
  }

  // --- Field edits (batched behind Save) ----------------------------------
  const labelsDirty = $derived(
    JSON.stringify([...labelIds].sort((a, b) => a - b)) !==
      JSON.stringify(initial.labels),
  );
  const dirty = $derived(
    title.trim() !== initial.title ||
      description.trim() !== initial.desc ||
      assignee.trim() !== initial.assignee ||
      storyPoints !== initial.pts ||
      epicId !== initial.epic ||
      priority !== initial.priority ||
      dueDate !== initial.due ||
      labelsDirty,
  );
  const canSubmit = $derived(title.trim().length > 0 && dirty && !submitting);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!canSubmit || !card) return;
    submitting = true;
    error = null;
    try {
      await editCard(card.id, {
        title: title.trim(),
        description: description.trim() || null,
        assignee: assignee.trim() || null,
        story_points: storyPoints ? Number(storyPoints) : null,
        epic_id: epicId ? Number(epicId) : null,
        priority,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
        label_ids: labelIds,
      });
      onclose();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to save card";
    } finally {
      submitting = false;
    }
  }

  // --- Delete (confirm inline in the footer) ------------------------------
  let confirming = $state(false);
  let deleting = $state(false);
  let deleteError = $state<string | null>(null);
  async function confirmDelete() {
    if (!card) return;
    deleting = true;
    deleteError = null;
    try {
      await removeCard(card.id);
      onclose();
    } catch (e) {
      deleteError = e instanceof Error ? e.message : "Failed to delete card";
      deleting = false;
    }
  }
</script>

{#if card}
  <Modal label="Card {ticket}: {card.title}" {onclose}>
    <form class="card-form card-modal" onsubmit={submit}>
      <header class="modal-head">
        <span class="ticket">{ticket}</span>
        <span class="status-pill status-{card.column}">
          <span class="dot" aria-hidden="true"></span>{columnLabel}
        </span>
        {#if card.blocked}
          <span class="blocked-badge" title="Blocked by an unfinished card">
            <Ban size={11} aria-hidden="true" /> Blocked
          </span>
        {/if}
        {#if epic}
          <span class="epic-tag" title="{epic.ticket_number} · {epic.name}">{epic.name}</span>
        {/if}
        <button
          type="button"
          class="icon-btn modal-close"
          title="Close"
          aria-label="Close"
          onclick={onclose}
        >
          <X size={18} />
        </button>
      </header>

      <div class="modal-scroll">
        <div class="modal-grid">
          <div class="modal-main">
            <input
              class="modal-title-input"
              type="text"
              placeholder="Title (required)"
              aria-label="Title"
              bind:value={title}
              bind:this={titleInput}
            />
            <div class="desc-head">
              <span class="field-label">Description</span>
              <div class="desc-toggle" role="group" aria-label="Description mode">
                <button
                  type="button"
                  class="desc-tab"
                  class:active={descMode === "edit"}
                  aria-pressed={descMode === "edit"}
                  onclick={() => (descMode = "edit")}
                >
                  Edit
                </button>
                <button
                  type="button"
                  class="desc-tab"
                  class:active={descMode === "preview"}
                  aria-pressed={descMode === "preview"}
                  onclick={() => (descMode = "preview")}
                >
                  Preview
                </button>
              </div>
            </div>
            {#if descMode === "edit"}
              <textarea
                class="desc-input"
                placeholder="Description (optional) — Markdown supported"
                rows="10"
                bind:value={description}
              ></textarea>
            {:else if description.trim()}
              <!-- Sanitized markdown: renderMarkdown() runs marked + DOMPurify. -->
              <div class="desc-rendered markdown-body">{@html renderMarkdown(description)}</div>
            {:else}
              <p class="desc-empty">No description yet.</p>
            {/if}

            <div class="notes">
              <span class="field-label">Comments</span>
              {#if commentsLoaded && comments.length > 0}
                <ul class="comment-list">
                  {#each comments as c (c.id)}
                    <li class="comment-item">
                      <span class="avatar-sm" aria-hidden="true">{initialOf(c.author_id)}</span>
                      <div class="comment-body-wrap">
                        <div class="comment-meta">
                          <time datetime={c.created_at}>{formatWhen(c.created_at)}</time>
                          {#if ownComment(c)}
                            <button
                              type="button"
                              class="icon-btn danger"
                              title="Delete comment"
                              aria-label="Delete comment"
                              disabled={commentBusy}
                              onclick={() => onDeleteComment(c.id)}
                            >
                              <X size={13} />
                            </button>
                          {/if}
                        </div>
                        <div class="comment-body">{c.body}</div>
                      </div>
                    </li>
                  {/each}
                </ul>
              {:else if commentsLoaded}
                <p class="comment-empty">No comments yet.</p>
              {/if}
              <div class="row comment-add">
                <input
                  type="text"
                  placeholder="Add a comment…"
                  bind:value={newComment}
                  disabled={commentBusy}
                />
                <button type="button" disabled={!canPostComment} onclick={onPostComment}>Post</button>
              </div>
              {#if commentError}
                <p class="form-error" role="alert">{commentError}</p>
              {/if}
            </div>
          </div>

          <aside class="modal-rail">
            <div class="rail-field">
              <span class="field-label">Status</span>
              <Select
                aria-label="Status"
                value={card.column}
                options={statusOptions}
                disabled={moving}
                onValueChange={onStatusChange}
              />
            </div>

            <div class="rail-field">
              <span class="field-label">Story points</span>
              <Select bind:value={storyPoints} options={pointOptions} aria-label="Story points" />
            </div>

            <div class="rail-field">
              <span class="field-label">Assignee</span>
              <input type="text" class="ui-input" placeholder="Assignee" bind:value={assignee} aria-label="Assignee" />
            </div>

            <div class="rail-field">
              <span class="field-label">Epic</span>
              <Select bind:value={epicId} options={epicSelectOptions} aria-label="Epic" />
            </div>

            <div class="rail-field">
              <span class="field-label">Priority</span>
              <Select
                value={priority}
                options={priorityOptions}
                onValueChange={(v) => (priority = v as Priority)}
                aria-label="Priority"
              />
            </div>

            <div class="rail-field">
              <span class="field-label">Due date</span>
              <input type="date" class="ui-input" bind:value={dueDate} aria-label="Due date" />
            </div>

            <div class="rail-field">
              <span class="field-label">Labels</span>
              {#if labelOptions.length > 0}
                <div class="label-picker" role="group" aria-label="Labels">
                  {#each labelOptions as label (label.id)}
                    <button
                      type="button"
                      class="label-toggle"
                      class:selected={labelIds.includes(label.id)}
                      onclick={() => toggleLabel(label.id)}
                    >
                      <span class="label-dot" style="background: {label.color}" aria-hidden="true"
                      ></span>
                      {label.name}
                    </button>
                  {/each}
                </div>
              {:else}
                <p class="rail-empty">No labels on this board yet.</p>
              {/if}
            </div>

            <div class="rail-field blockers-edit">
              <span class="field-label">Blocked by</span>
              {#if blockers.length > 0}
                <ul class="blocker-list">
                  {#each blockers as b}
                    {#if b}
                      <li class="blocker-item">
                        <span class="dep-ref" title={b.title}>{b.ticket_number}</span>
                        <span class="blocker-ref" title={b.title}>{b.title}</span>
                        <button
                          type="button"
                          class="icon-btn danger"
                          title="Remove blocker"
                          aria-label="Remove blocker {b.ticket_number}"
                          disabled={depBusy}
                          onclick={() => onRemoveBlocker(b.id)}
                        >
                          <X size={14} />
                        </button>
                      </li>
                    {/if}
                  {/each}
                </ul>
              {/if}
              <Select
                value=""
                options={blockerOptions}
                aria-label="Add blocker"
                disabled={depBusy || blockerCandidates.length === 0}
                onValueChange={(v) => {
                  if (v) onAddBlocker(v);
                }}
              />
              {#if depError}
                <p class="form-error" role="alert">{depError}</p>
              {/if}
            </div>

            {#if blocks.length > 0}
              <div class="rail-field">
                <span class="field-label">Blocks</span>
                <div class="chip-row">
                  {#each blocks as b}
                    {#if b}
                      <span class="dep-ref" title={b.title}>{b.ticket_number}</span>
                    {/if}
                  {/each}
                </div>
              </div>
            {/if}

            <div class="rail-field links-edit">
              <span class="field-label">Links</span>
              {#if links.length > 0}
                <ul class="link-list">
                  {#each links as l (l.id)}
                    <li class="link-item">
                      <LinkIcon size={12} aria-hidden="true" />
                      <a
                        class="link-ref"
                        href={l.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={l.url}
                      >
                        {l.label}
                      </a>
                      <button
                        type="button"
                        class="icon-btn danger"
                        title="Remove link"
                        aria-label="Remove link {l.label}"
                        disabled={linkBusy}
                        onclick={() => onRemoveLink(l.id)}
                      >
                        <X size={14} />
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
              <div class="link-add">
                <input
                  type="text"
                  class="link-label-input"
                  placeholder="Label (e.g. PR)"
                  bind:value={linkLabel}
                  disabled={linkBusy}
                />
                <div class="row">
                  <input
                    type="url"
                    placeholder="https://…"
                    bind:value={linkUrl}
                    disabled={linkBusy}
                  />
                  <button type="button" disabled={!canAddLink} onclick={onAddLink}>Add</button>
                </div>
              </div>
              {#if linkError}
                <p class="form-error" role="alert">{linkError}</p>
              {/if}
            </div>
          </aside>
        </div>
      </div>

      <footer class="modal-foot">
        {#if confirming}
          <span class="confirm-msg">Delete {ticket}? This can't be undone.</span>
          <button type="button" class="danger" onclick={confirmDelete} disabled={deleting}>
            Delete
          </button>
          <button type="button" class="link" onclick={() => (confirming = false)} disabled={deleting}>
            Keep
          </button>
        {:else}
          <button type="submit" class="primary" disabled={!canSubmit}>Save changes</button>
          <button type="button" class="link" onclick={onclose}>Cancel</button>
          <button
            type="button"
            class="btn-inline-danger modal-delete"
            onclick={() => (confirming = true)}
          >
            <Trash2 size={15} /> Delete
          </button>
        {/if}
      </footer>

      {#if error}<p class="form-error" role="alert">{error}</p>{/if}
      {#if deleteError}<p class="form-error" role="alert">{deleteError}</p>{/if}
    </form>
  </Modal>
{/if}
