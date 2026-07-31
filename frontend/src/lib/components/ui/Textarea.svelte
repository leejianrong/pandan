<script lang="ts">
  // Textarea — standardized <textarea>, matching TextInput's chrome.
  import type { HTMLTextareaAttributes } from "svelte/elements";

  let {
    value = $bindable(""),
    error = false,
    class: klass = "",
    ...rest
  }: {
    value?: string;
    error?: boolean;
    class?: string;
  } & Omit<HTMLTextareaAttributes, "value" | "class"> = $props();
</script>

<textarea class="ui-textarea {klass}" class:is-error={error} bind:value {...rest}></textarea>
