<script lang="ts">
  // Notification inbox (V39, KAN-303) — a bell + unread badge in the top bar that
  // opens an anchored popover listing notifications newest-first, with per-item and
  // bulk mark-read and an All/Unread filter. Read-first: the only mutation is
  // mark-read (no deep-linking to the card this slice). Poll/pull only (ADR 0007) —
  // the store refetches every 60s; opening the popover refetches immediately.
  //
  // Built directly on bits-ui Popover (like the ui/ primitives) rather than the
  // shared Popover wrapper, which is fixed-width for small forms — the inbox needs a
  // wider, header+scroll+footer surface. Its styles live in app.css (`.inbox-*`),
  // global because Bits portals the content to <body>, out of this component's scope.
  import { Popover } from "bits-ui";
  import {
    Ban,
    Bell,
    Check,
    CheckCheck,
    Hand,
    Inbox as InboxIcon,
    OctagonX,
    UserPlus,
  } from "lucide-svelte";
  import type { Icon } from "lucide-svelte";
  import type { Notification, NotificationKind } from "../api";
  import {
    markAllRead,
    markRead,
    notificationStore,
    refetchNotifications,
    setNotificationFilter,
    unreadCount,
  } from "../notifications.svelte";

  // Parent (App.svelte) owns the open state so the side-nav's Inbox entry can open
  // this same popover; bits anchors it to the trigger regardless of who set it.
  let { open = $bindable(false) }: { open?: boolean } = $props();

  const count = $derived(unreadCount());
  const badge = $derived(count > 9 ? "9+" : String(count));

  // Per-kind icon + colour token, staying inside the Graphite / Zinc & Teal palette
  // and reusing the app's existing semantics: teal = a handoff to a person (matches
  // the card's needs-human badge), red = blocked, amber = a build/CI failure, violet
  // = an assignment (the agent hue). The Record keeps this exhaustive over the four
  // backend kinds — a new kind can't slip through as a blank chip.
  const KIND: Record<NotificationKind, { icon: typeof Icon; label: string }> = {
    needs_human: { icon: Hand, label: "Needs human" },
    blocked: { icon: Ban, label: "Blocked" },
    ci_failed: { icon: OctagonX, label: "CI failed" },
    assigned: { icon: UserPlus, label: "Assigned" },
  };

  // Refetch on open so the panel (and badge) reflect the latest without waiting for
  // the next poll tick.
  $effect(() => {
    if (open) void refetchNotifications();
  });

  // A compact relative time — mirrors Activity.svelte so the two surfaces read the
  // same ("just now", "5m ago", "3h ago", "2d ago", then a locale date).
  function relTime(iso: string): string {
    const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (secs < 45) return "just now";
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  function fullTime(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  async function onMarkOne(e: MouseEvent, n: Notification): Promise<void> {
    // The row isn't a link, but stop the click from bubbling to the popover.
    e.stopPropagation();
    await markRead(n.id);
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger
    class="icon-btn bell-btn"
    aria-label={count > 0 ? `Inbox — ${count} unread` : "Inbox"}
  >
    <Bell size={18} />
    {#if count > 0}
      <span class="unread-badge" aria-hidden="true">{badge}</span>
    {/if}
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content class="inbox-panel" align="end" sideOffset={8}>
      <div class="inbox-head">
        <h3>Inbox</h3>
        <span class="inbox-count" class:zero={count === 0}>
          {count > 0 ? `${count} unread` : "All read"}
        </span>
        <button
          class="inbox-mark-all"
          onclick={markAllRead}
          disabled={count === 0}
        >
          <CheckCheck size={14} /> Mark all read
        </button>
      </div>

      <div class="inbox-filter" role="tablist" aria-label="Filter notifications">
        <button
          role="tab"
          class="inbox-tab"
          class:active={notificationStore.filter === "all"}
          aria-selected={notificationStore.filter === "all"}
          onclick={() => setNotificationFilter("all")}
        >
          All
        </button>
        <button
          role="tab"
          class="inbox-tab"
          class:active={notificationStore.filter === "unread"}
          aria-selected={notificationStore.filter === "unread"}
          onclick={() => setNotificationFilter("unread")}
        >
          Unread
        </button>
      </div>

      {#if notificationStore.error}
        <div class="inbox-status" role="alert">
          <span>{notificationStore.error}</span>
          <button class="link" onclick={refetchNotifications}>Retry</button>
        </div>
      {:else if !notificationStore.loaded && notificationStore.loading}
        <p class="inbox-status">Loading…</p>
      {:else if notificationStore.items.length === 0}
        <div class="inbox-empty">
          <span class="inbox-empty-ring"><InboxIcon size={24} /></span>
          <h4>
            {notificationStore.filter === "unread"
              ? "No unread notifications"
              : "You're all caught up"}
          </h4>
          <p>New handoffs, blocks, CI failures and assignments will land here.</p>
        </div>
      {:else}
        <ul class="inbox-list">
          {#each notificationStore.items as n (n.id)}
            {@const meta = KIND[n.kind]}
            {@const Icon = meta.icon}
            {@const unread = n.read_at === null}
            <li class="note" class:unread class:read={!unread}>
              <span class="note-icon {n.kind}" aria-hidden="true">
                <Icon size={16} />
              </span>
              <div class="note-body">
                <span class="note-kind {n.kind}">{meta.label}</span>
                <p class="note-text">{n.body}</p>
                <time
                  class="note-time"
                  datetime={n.created_at}
                  title={fullTime(n.created_at)}
                >
                  {relTime(n.created_at)}
                </time>
              </div>
              <div class="note-side">
                {#if unread}
                  <span class="unread-dot" aria-hidden="true"></span>
                  <button
                    class="note-mark"
                    title="Mark read"
                    aria-label="Mark read"
                    onclick={(e) => onMarkOne(e, n)}
                  >
                    <Check size={14} />
                  </button>
                {/if}
              </div>
            </li>
          {/each}
        </ul>
        <div class="inbox-foot">Newest first · refreshes every 60s</div>
      {/if}
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>
