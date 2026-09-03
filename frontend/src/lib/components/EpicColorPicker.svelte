<script lang="ts">
  // The epic-colour swatch grid (M8 V63, KAN-984, issue #278) — shared by EpicForm
  // (create) and EpicModal (edit), which is what earns this its own component
  // rather than a third copy of Labels.svelte's inline snippet.
  //
  // Same seven-token palette + picker idiom as Labels.svelte (V62, KAN-983: "the
  // palette is the picker", SHAPING D11), with one real difference: an epic's
  // colour is OPTIONAL (nullable, unlike label.color), so this grid always offers
  // a leading "No colour" option, which Labels.svelte's never needs to.
  //
  // A legacy/custom value (set via the CLI or MCP, which pass a colour straight
  // through with no local validation) gets its own leading swatch too, so it is
  // visible and re-selectable rather than silently unrepresented — mirroring
  // Labels.svelte's own `optionsFor`.
  import { LABEL_PALETTE, labelColor } from "../api";

  let {
    name,
    value,
    onchange,
  }: {
    name: string;
    value: string | null;
    onchange: (color: string | null) => void;
  } = $props();

  const options = $derived.by((): (string | null)[] => {
    const tokens = LABEL_PALETTE as readonly string[];
    if (value && !tokens.includes(value)) {
      return [null, value, ...tokens];
    }
    return [null, ...tokens];
  });

  function optionLabel(color: string | null): string {
    if (color === null) return "No colour";
    return (LABEL_PALETTE as readonly string[]).includes(color) ? color : `custom (${color})`;
  }
</script>

<div class="swatch-grid" role="group" aria-label="Epic colour">
  {#each options as color (color ?? "__none__")}
    <label class="swatch-opt" title={optionLabel(color)}>
      <input
        type="radio"
        {name}
        value={color ?? ""}
        checked={value === color}
        onchange={() => onchange(color)}
      />
      {#if color === null}
        <span class="swatch swatch-pick swatch-none" aria-hidden="true"></span>
      {:else}
        <span
          class="swatch swatch-pick"
          style="background: {labelColor(color)}"
          aria-hidden="true"
        ></span>
      {/if}
      <span class="sr-only">{optionLabel(color)}</span>
    </label>
  {/each}
</div>

<style>
  /* Identical shape to Labels.svelte's own swatch-grid CSS (V62) — kept as its own
     copy rather than a shared stylesheet class, matching that file's own stated
     precedent (its sr-only rule is likewise "a local copy ... rather than a shared
     utility"). Svelte styles are component-scoped, so there is no third option
     short of a global class, which would leak into unrelated markup. */
  .swatch-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-items: center;
  }
  .swatch-opt {
    display: inline-flex;
    cursor: pointer;
    line-height: 0;
  }
  .swatch-opt input {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    border: 0;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .swatch {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 1px solid var(--border);
    flex: none;
  }
  .swatch-pick {
    width: 22px;
    height: 22px;
    transition: transform 120ms ease;
  }
  /* The "no colour" option: an empty ring rather than a filled circle, so it never
     reads as an eighth hue — deliberately the visual opposite of every other
     option here. */
  .swatch-none {
    background: transparent;
    border: 1.5px dashed var(--muted);
  }
  .swatch-opt:hover .swatch-pick {
    transform: scale(1.12);
  }
  .swatch-opt:has(input:checked) .swatch-pick {
    box-shadow: 0 0 0 2px var(--card-bg), 0 0 0 4px var(--text);
  }
  .swatch-opt:has(input:focus-visible) .swatch-pick {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
  @media (prefers-reduced-motion: reduce) {
    .swatch-pick {
      transition: none;
    }
    .swatch-opt:hover .swatch-pick {
      transform: none;
    }
  }
</style>
