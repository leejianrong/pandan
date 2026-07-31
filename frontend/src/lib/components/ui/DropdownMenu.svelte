<script lang="ts">
  // DropdownMenu — Bits UI menu styled with the app tokens. Replaces hand-rolled
  // popups (e.g. BoardSwitcher's .board-menu): Bits handles outside-click, Escape,
  // focus management and portalling, so no manual document listeners are needed.
  //
  // Declarative `items` API + a `trigger` snippet for the trigger content. Items
  // support an icon, a danger variant, disabled, and a leading separator.
  import type { Snippet } from "svelte";
  import { DropdownMenu } from "bits-ui";
  import type { Icon } from "lucide-svelte";

  export type MenuItem = {
    label: string;
    icon?: typeof Icon;
    danger?: boolean;
    disabled?: boolean;
    separatorBefore?: boolean;
    /**
     * Optional trailing hint, right-aligned — e.g. the `?` shortcut on the
     * "Keyboard shortcuts" entry (KAN-392). Rendered in a <kbd>-style chip.
     */
    hint?: string;
    onSelect: () => void;
  };

  let {
    items,
    heading,
    subtitle,
    trigger,
    triggerClass = "",
    triggerLabel,
    align = "start",
  }: {
    items: MenuItem[];
    heading?: string;
    /**
     * Optional secondary line under the heading — e.g. the signed-in email in the
     * avatar menu (KAN-319/U4). Backward-compatible: callers that omit it (e.g.
     * BoardSwitcher's board-actions menu) render exactly as before.
     */
    subtitle?: string;
    trigger: Snippet;
    triggerClass?: string;
    triggerLabel?: string;
    align?: "start" | "center" | "end";
  } = $props();
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger class={triggerClass} aria-label={triggerLabel}>
    {@render trigger()}
  </DropdownMenu.Trigger>
  <DropdownMenu.Portal>
    <DropdownMenu.Content class="ui-popup detached" {align} sideOffset={6}>
      {#if heading}<div class="ui-menu-label">{heading}</div>{/if}
      {#if subtitle}<div class="ui-menu-subtitle">{subtitle}</div>{/if}
      {#each items as item (item.label)}
        {#if item.separatorBefore}<DropdownMenu.Separator class="ui-sep" />{/if}
        <DropdownMenu.Item
          class={item.danger ? "ui-item danger" : "ui-item"}
          disabled={item.disabled}
          onSelect={item.onSelect}
        >
          {#if item.icon}
            {@const Icon = item.icon}
            <Icon size={15} />
          {/if}
          <span class="ui-item-label">{item.label}</span>
          {#if item.hint}<kbd class="ui-item-hint">{item.hint}</kbd>{/if}
        </DropdownMenu.Item>
      {/each}
    </DropdownMenu.Content>
  </DropdownMenu.Portal>
</DropdownMenu.Root>
