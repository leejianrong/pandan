<script lang="ts">
  // Popover — Bits UI popover styled with the app tokens: a free-form floating
  // panel (headings, prose, form controls) sharing the menu surface treatment.
  // Bits handles outside-click / Escape / focus / portalling.
  import type { Snippet } from "svelte";
  import { Popover } from "bits-ui";

  let {
    open = $bindable(false),
    trigger,
    children,
    triggerClass = "",
    triggerLabel,
    align = "start",
  }: {
    open?: boolean;
    trigger: Snippet;
    children: Snippet;
    triggerClass?: string;
    triggerLabel?: string;
    align?: "start" | "center" | "end";
  } = $props();
</script>

<Popover.Root bind:open>
  <Popover.Trigger class={triggerClass} aria-label={triggerLabel}>
    {@render trigger()}
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content class="ui-popover" {align} sideOffset={6}>
      {@render children()}
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>
