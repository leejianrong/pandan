<script lang="ts">
  // Shared brand lockup — the sprout mark + "Pandan" wordmark (brand
  // exploration MARK-01, "Sprout": three blades fanning from one base,
  // echoing pandan's own rosette of leaves). Used in the app top bar and
  // the landing header so the two read identically (colours come from the
  // theme tokens, so it works in light + dark).
  let { size = "md" }: { size?: "md" | "lg" } = $props();
</script>

<span class="brand brand-{size}">
  <svg class="brand-glyph" viewBox="0 0 32 32" aria-hidden="true">
    <path
      class="blade blade-c"
      d="M16,29 C13.4,22 12.6,14.6 15.3,6.4 C15.7,5.2 16.3,5.2 16.7,6.4 C19.4,14.6 18.6,22 16,29 Z"
    />
    <path
      class="blade blade-l"
      d="M16,29 C10.8,24.4 8.2,18.6 8.5,10.6 C8.55,9.3 9.15,9.1 9.8,10.2 C14,17.2 16,22.8 16,29 Z"
      transform="rotate(-6 16 29)"
    />
    <path
      class="blade blade-r"
      d="M16,29 C21.2,24.4 23.8,18.6 23.5,10.6 C23.45,9.3 22.85,9.1 22.2,10.2 C18,17.2 16,22.8 16,29 Z"
      transform="rotate(6 16 29)"
    />
  </svg>
  <span class="brand-name">Pandan</span>
</span>
