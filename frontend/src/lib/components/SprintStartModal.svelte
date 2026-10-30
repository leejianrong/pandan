<script lang="ts">
  // Opt a board into sprints (PAN-238): picks a start date, sprint length and how
  // many to create, then calls the cadence endpoint (M8 V58). Sprints are optional
  // per board, so this is the only way a board gains them from the browser.
  import { X } from "lucide-svelte";
  import { ApiError } from "../api";
  import { startSprints } from "../board.svelte";
  import Modal from "./Modal.svelte";
  import { Field, TextInput } from "./ui";

  let { onclose }: { onclose: () => void } = $props();

  function today(): string {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  let start = $state(today());
  let lengthDays = $state("14");
  let count = $state("6");
  let template = $state("Sprint {n}");
  let submitting = $state(false);
  let error = $state<string | null>(null);

  const length = $derived(Number(lengthDays));
  const howMany = $derived(Number(count));
  const valid = $derived(
    /^\d{4}-\d{2}-\d{2}$/.test(start) &&
      Number.isInteger(length) &&
      length > 0 &&
      Number.isInteger(howMany) &&
      howMany > 0 &&
      howMany <= 52 &&
      template.trim().length > 0,
  );
  const endDay = $derived.by(() => {
    if (!valid) return "";
    const d = new Date(`${start}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + length * howMany);
    return d.toISOString().slice(0, 10);
  });

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!valid || submitting) return;
    submitting = true;
    error = null;
    try {
      await startSprints({
        start,
        length_days: length,
        count: howMany,
        name_template: template.trim(),
      });
      onclose();
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Failed to start sprints";
    } finally {
      submitting = false;
    }
  }
</script>

<Modal label="Start sprints" {onclose}>
  <form class="card-form card-modal" onsubmit={submit}>
    <header class="modal-head">
      <span class="ticket">Start sprints</span>
      <button type="button" class="icon-btn modal-close" aria-label="Close" onclick={onclose}>
        <X size={16} />
      </button>
    </header>
    <div class="modal-scroll">
      <div class="modal-main">
        <p class="hint">
          Creates back-to-back sprints. The board then shows the current sprint, and
          you can still open past sprints or all cards from the Sprint selector.
        </p>
        <Field label="First sprint starts">
          <TextInput type="date" aria-label="First sprint starts" bind:value={start} />
        </Field>
        <Field label="Length (days)">
          <TextInput type="number" aria-label="Sprint length in days" bind:value={lengthDays} />
        </Field>
        <Field label="How many sprints" hint="Up to 52.">
          <TextInput type="number" aria-label="How many sprints" bind:value={count} />
        </Field>
        <Field label="Name" hint="{'{n}'} becomes 1, 2, 3 …">
          <TextInput aria-label="Sprint name template" bind:value={template} />
        </Field>
        {#if valid}
          <p class="hint">{howMany} × {length} days, {start} → {endDay}</p>
        {/if}
        {#if error}<p class="error" role="alert">{error}</p>{/if}
      </div>
    </div>
    <footer class="modal-foot">
      <button type="button" onclick={onclose}>Cancel</button>
      <button type="submit" class="primary" disabled={!valid || submitting}>
        {submitting ? "Creating…" : "Start sprints"}
      </button>
    </footer>
  </form>
</Modal>
