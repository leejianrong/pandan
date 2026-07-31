<script lang="ts">
  // Field — layout wrapper standardizing label + control + hint/error spacing.
  // Purely presentational: the control itself carries its own aria-label (we keep
  // the existing accessibility contract), so the label here is a visual <span>.
  import type { Snippet } from "svelte";

  let {
    label,
    hint,
    error,
    required = false,
    children,
  }: {
    label?: string;
    hint?: string;
    error?: string | null;
    required?: boolean;
    children: Snippet;
  } = $props();
</script>

<div class="ui-field">
  {#if label}
    <span class="ui-label">{label}{#if required}<span class="req">*</span>{/if}</span>
  {/if}
  {@render children()}
  {#if error}
    <span class="ui-error" role="alert">{error}</span>
  {:else if hint}
    <span class="ui-hint">{hint}</span>
  {/if}
</div>
