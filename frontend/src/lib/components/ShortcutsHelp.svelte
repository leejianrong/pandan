<script lang="ts">
  // Keyboard-shortcuts help overlay (V36, KAN-300). Opened with '?' from the
  // board; lists every keyboard affordance, including the ⌘K command palette
  // (V35). Uses the shared Modal shell for the focus-trap + Esc-to-close +
  // scrim contract, matching the command palette's styling.
  import Modal from "./Modal.svelte";
  import { kbd } from "../keyboard.svelte";

  function close() {
    kbd.helpOpen = false;
  }

  // ⌘ on macOS, Ctrl elsewhere — label the palette chord for the reader's OS.
  const isMac =
    typeof navigator !== "undefined" && /mac/i.test(navigator.platform ?? "");
  const mod = isMac ? "⌘" : "Ctrl";

  type Row = { keys: string[]; label: string };
  type Section = { heading: string; rows: Row[] };

  const sections: Section[] = [
    {
      heading: "Navigate",
      rows: [
        { keys: ["j", "↓"], label: "Next card in column" },
        { keys: ["k", "↑"], label: "Previous card in column" },
        { keys: ["l", "→"], label: "Next column" },
        { keys: ["h", "←"], label: "Previous column" },
      ],
    },
    {
      heading: "Act on the focused card",
      rows: [
        { keys: ["Enter", "o"], label: "Open card" },
        { keys: ["e"], label: "Edit card" },
        { keys: ["Shift", "→"], label: "Move card to next column" },
        { keys: ["Shift", "←"], label: "Move card to previous column" },
      ],
    },
    {
      heading: "Create & search",
      rows: [
        { keys: ["n", "c"], label: "New card in column" },
        { keys: [mod, "K"], label: "Open command palette" },
      ],
    },
    {
      heading: "General",
      rows: [
        { keys: ["?"], label: "Show / hide this help" },
        { keys: ["Esc"], label: "Close dialog or help" },
      ],
    },
  ];
</script>

<Modal label="Keyboard shortcuts" onclose={close}>
  <div class="shortcuts">
    <header class="shortcuts-head">
      <h2>Keyboard shortcuts</h2>
      <p class="hint">Board navigation without the mouse.</p>
    </header>
    <div class="shortcuts-grid">
      {#each sections as section (section.heading)}
        <section class="shortcuts-section">
          <h3>{section.heading}</h3>
          <dl>
            {#each section.rows as row (row.label)}
              <div class="shortcut-row">
                <dt>
                  {#each row.keys as key, i (key)}
                    {#if i > 0}<span class="sep">/</span>{/if}
                    <kbd>{key}</kbd>
                  {/each}
                </dt>
                <dd>{row.label}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {/each}
    </div>
  </div>
</Modal>

<style>
  /* The plain Modal shell has no inner padding (its usual children bring their
     own), and defaults to 760px wide; shrink it to our content and pad it. */
  :global(.modal:has(.shortcuts)) {
    width: auto;
  }
  .shortcuts {
    width: min(92vw, 560px);
    padding: 1.25rem 1.4rem 1.4rem;
  }
  .shortcuts-head h2 {
    margin: 0;
    font-size: 1.05rem;
    color: var(--text);
  }
  .shortcuts-head .hint {
    margin: 0.15rem 0 0.9rem;
    color: var(--muted);
    font-size: 0.85rem;
  }
  .shortcuts-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.75rem 1.5rem;
  }
  @media (max-width: 480px) {
    .shortcuts-grid {
      grid-template-columns: 1fr;
    }
  }
  .shortcuts-section h3 {
    margin: 0 0 0.4rem;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }
  dl {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .shortcut-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }
  dt {
    display: flex;
    align-items: center;
    gap: 0.2rem;
    flex-shrink: 0;
  }
  dd {
    margin: 0;
    color: var(--text);
    font-size: 0.85rem;
    text-align: right;
  }
  .sep {
    color: var(--muted);
    font-size: 0.75rem;
    margin: 0 0.05rem;
  }
  kbd {
    font-family: var(--mono);
    font-size: 0.72rem;
    line-height: 1;
    min-width: 1.4rem;
    text-align: center;
    padding: 0.28rem 0.4rem;
    background: var(--accent-soft);
    color: var(--accent);
    border: 1px solid var(--border);
    border-radius: 6px;
    box-shadow: 0 1px 0 var(--border);
  }
</style>
