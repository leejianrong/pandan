<script lang="ts">
  // Checkbox — Bits UI Checkbox styled with the app tokens. The Root button is the
  // whole clickable row (box + label), so a click anywhere on the row toggles it,
  // matching the native <label><input>+<span> behaviour it replaces. The bits Root
  // exposes role=checkbox + aria-checked, so `page.getByRole("checkbox", { name })`
  // and `.check()` work in Playwright.
  import { Checkbox } from "bits-ui";
  import { Check } from "lucide-svelte";

  let {
    checked = $bindable(false),
    label,
    disabled = false,
    onCheckedChange,
    "aria-label": ariaLabel,
  }: {
    checked?: boolean;
    label: string;
    disabled?: boolean;
    onCheckedChange?: (checked: boolean) => void;
    "aria-label"?: string;
  } = $props();
</script>

<Checkbox.Root
  class="ui-check-row"
  bind:checked
  {disabled}
  {onCheckedChange}
  aria-label={ariaLabel ?? label}
>
  {#snippet children({ checked })}
    <span class="ui-checkbox" class:is-checked={checked} aria-hidden="true">
      {#if checked}<Check size={12} strokeWidth={3.5} />{/if}
    </span>
    <span class="ui-check-label">{label}</span>
  {/snippet}
</Checkbox.Root>
