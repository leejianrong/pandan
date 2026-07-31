<script lang="ts">
  // Select — Bits UI single-select styled with the app tokens. Replaces the ad-hoc
  // native <select>/.rail-select controls: custom caret (rotates on open), teal
  // focus ring, and a portalled listbox so it's never clipped by a modal/column.
  //
  // Declarative `options` API (mirrors DropdownMenu). The trigger carries the
  // aria-label and role=combobox; items are role=option, so in Playwright:
  //   await scope.getByLabel("Priority").click();
  //   await page.getByRole("option", { name: "High" }).click();
  import { Select } from "bits-ui";
  import { Check, ChevronDown } from "lucide-svelte";

  export type SelectOption = { value: string; label: string; disabled?: boolean };

  let {
    value = $bindable(""),
    options,
    placeholder = "",
    disabled = false,
    onValueChange,
    "aria-label": ariaLabel,
    class: klass = "",
  }: {
    value?: string;
    options: SelectOption[];
    placeholder?: string;
    disabled?: boolean;
    onValueChange?: (value: string) => void;
    "aria-label"?: string;
    class?: string;
  } = $props();

  const selected = $derived(options.find((o) => o.value === value));
</script>

<Select.Root type="single" bind:value {disabled} {onValueChange}>
  <Select.Trigger class="ui-select {klass}" aria-label={ariaLabel}>
    {#if selected}
      <span class="ui-select-value">{selected.label}</span>
    {:else}
      <span class="ui-select-value placeholder">{placeholder}</span>
    {/if}
    <ChevronDown class="ui-select-caret" size={14} aria-hidden="true" />
  </Select.Trigger>
  <Select.Portal>
    <Select.Content class="ui-popup" sideOffset={6}>
      <Select.Viewport>
        {#each options as opt (opt.value)}
          <Select.Item
            class="ui-item ui-select-item"
            value={opt.value}
            label={opt.label}
            disabled={opt.disabled}
          >
            {#snippet children({ selected })}
              <span class="ui-item-label">{opt.label}</span>
              {#if selected}<Check class="ui-item-check" size={15} aria-hidden="true" />{/if}
            {/snippet}
          </Select.Item>
        {/each}
      </Select.Viewport>
    </Select.Content>
  </Select.Portal>
</Select.Root>
