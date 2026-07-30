<script lang="ts">
  // Shared brand lockup — the board/cards glyph + "Pandan" wordmark. Used
  // in the app top bar and the landing header so the two read identically
  // (colours come from the theme tokens, so it works in light + dark).
  let { size = "md" }: { size?: "md" | "lg" } = $props();
</script>

<span class="brand brand-{size}">
  <span class="brand-glyph" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
  <span class="brand-name">Pandan</span>
</span>
