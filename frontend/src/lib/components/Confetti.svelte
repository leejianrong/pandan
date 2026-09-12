<script lang="ts">
  import { onMount } from "svelte";

  let { onend }: { onend?: () => void } = $props();

  const COLORS = ["#f43f5e", "#fbbf24", "#34d399", "#60a5fa", "#a78bfa", "#f472b6"];
  const PIECE_COUNT = 22;
  const BURST_MS = 1100;

  const pieces = Array.from({ length: PIECE_COUNT }, (_, i) => ({
    id: i,
    left: Math.random() * 100,
    delay: Math.random() * 0.15,
    duration: 0.6 + Math.random() * 0.5,
    rotate: Math.round(Math.random() * 360),
    drift: Math.round((Math.random() - 0.5) * 60),
    color: COLORS[i % COLORS.length],
  }));

  onMount(() => {
    const t = setTimeout(() => onend?.(), BURST_MS);
    return () => clearTimeout(t);
  });
</script>

<div class="confetti" aria-hidden="true">
  {#each pieces as p (p.id)}
    <span
      class="piece"
      style="left: {p.left}%; background: {p.color}; animation-delay: {p.delay}s; animation-duration: {p.duration}s; --rotate: {p.rotate}deg; --drift: {p.drift}px;"
    ></span>
  {/each}
</div>

<style>
  .confetti {
    position: absolute;
    inset: 0;
    overflow: visible;
    pointer-events: none;
    z-index: 5;
  }
  .piece {
    position: absolute;
    top: 0;
    width: 6px;
    height: 10px;
    border-radius: 1px;
    opacity: 0;
    animation-name: confetti-fall;
    animation-timing-function: ease-out;
    animation-fill-mode: forwards;
  }
  @keyframes confetti-fall {
    0% {
      opacity: 1;
      transform: translate(0, -10px) rotate(0deg);
    }
    100% {
      opacity: 0;
      transform: translate(var(--drift), 90px) rotate(var(--rotate));
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .confetti {
      display: none;
    }
  }
</style>
