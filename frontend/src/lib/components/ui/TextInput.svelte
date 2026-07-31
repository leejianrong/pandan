<script lang="ts">
  // TextInput — standardized <input>. Bindable value; consistent placeholder,
  // focus ring and disabled/error styling. Extra attrs (aria-label, name, type,
  // min, disabled, onchange, …) pass straight through via ...rest.
  import type { HTMLInputAttributes } from "svelte/elements";

  let {
    value = $bindable(""),
    error = false,
    class: klass = "",
    ...rest
  }: {
    value?: string;
    error?: boolean;
    class?: string;
  } & Omit<HTMLInputAttributes, "value" | "class"> = $props();
</script>

<input class="ui-input {klass}" class:is-error={error} bind:value {...rest} />
