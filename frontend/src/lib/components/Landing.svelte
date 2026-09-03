<script lang="ts">
  // Logged-out front door (M3 V6, A9 / place S1). Adapted from
  // docs/milestone-3/landing-mockup.html into a Svelte component. The mockup's
  // richer palette is kept but scoped to `.landing` (light + dark), reusing the
  // app's accent colours — so the landing is themable without retrofitting dark
  // mode onto the rest of the (light-only) app.
  import { Moon, Sun } from "lucide-svelte";
  import { startGitHubLogin } from "../api";
  import { themeStore, toggleTheme } from "../theme.svelte";
  import Brand from "./Brand.svelte";

  let signingIn = $state(false);
  let error = $state<string | null>(null);

  async function signIn() {
    signingIn = true;
    error = null;
    try {
      // Fetches the authorize URL and navigates to GitHub (see api.ts). If it
      // returns instead of navigating, something went wrong.
      await startGitHubLogin();
    } catch {
      error = "Could not start sign-in. Is GitHub login configured on the server?";
      signingIn = false;
    }
  }
</script>

<div class="landing">
  <header class="topbar">
    <Brand size="lg" />
    <div class="top-actions">
      <button
        class="theme-toggle"
        title={themeStore.theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        aria-label={themeStore.theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        onclick={toggleTheme}
      >
        {#if themeStore.theme === "dark"}
          <Sun size={16} />
        {:else}
          <Moon size={16} />
        {/if}
      </button>
      <a class="demo-link" href="https://simple-kanban-jian.fly.dev" target="_blank" rel="noopener"
        >Live demo &rarr;</a
      >
    </div>
  </header>

  <main class="hero">
    <p class="eyebrow reveal">Pandan &middot; open-source kanban</p>
    <h1 class="reveal">Task tracking humans and <span class="hl">AI agents</span> share.</h1>
    <p class="subhead reveal">
      A board your team runs by hand &mdash; and your coding agents keep up to date over MCP. One
      source of truth for the work, whoever moves the card.
    </p>
    <div class="cta-row reveal">
      <button class="btn-github" onclick={signIn} disabled={signingIn}>
        <svg width="20" height="20" viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
          ></path>
        </svg>
        {signingIn ? "Redirecting…" : "Sign in with GitHub"}
      </button>
      <a
        class="text-link"
        href="https://simple-kanban-jian.fly.dev"
        target="_blank"
        rel="noopener">See a board in action &rarr;</a
      >
    </div>
    {#if error}
      <p class="error" role="alert">{error}</p>
    {/if}
  </main>

  <section class="features" aria-label="What it does">
    <article class="tile">
      <span class="tag">Boards</span>
      <h3>Organize work your way</h3>
      <p>Group stories into epics and move them across To Do, In Progress, and Done.</p>
    </article>
    <article class="tile">
      <span class="tag">Drag &amp; drop</span>
      <h3>Reorder in a flick</h3>
      <p>Grab a card, drop it in another column &mdash; the board saves instantly, no reload.</p>
    </article>
    <article class="tile">
      <span class="tag">Agents &middot; MCP</span>
      <h3>Let AI keep it current</h3>
      <p>Connect Claude over MCP; it creates and moves cards with a token you control and revoke.</p>
    </article>
  </section>

  <footer>
    Open source &middot; built with FastAPI + Svelte &middot;
    <a href="https://github.com/leejianrong/simple-kanban" target="_blank" rel="noopener"
      >View on GitHub &rarr;</a
    >
  </footer>
</div>

<style>
  /* Palette scoped to the landing only — reuses the app's accent values, adds the
     surfaces/dark-mode the marketing page needs without touching the rest of the app. */
  .landing {
    /* M3 role palette (M3-1, KAN-1090) — matches the app (see app.css's :root
       block for the seed/generation/mapping notes; the names here are the
       landing's own long-standing local aliases: --ground/--surface/--line/
       --ink map to app.css's --bg/--card-bg/--border/--text, --accent-2(-soft)
       to --agent(-soft)). Kept as a literal value mirror rather than reading
       app.css's custom properties directly, same as before this ticket. */
    --ground: #f7faf8;
    --surface: #ffffff;
    --line: #bec9c6;
    --ink: #191c1b;
    --muted: #3f4947;
    --accent: #006a61;
    --accent-soft: #73f8e7;
    --accent-2: #46617a;
    --accent-2-soft: #cde5ff;
    --btn-ink: #191c1b;
    --btn-on: #ffffff;
    /* M3 elevation (M3-4, KAN-1093) — mirrors app.css's --elevation-1-shadow
       (level 1: this page's tiles/button are the marketing-chrome equivalent
       of a resting card). Kept literal, same mirroring convention as the
       M3-1 palette above; no surface-tint wash here since --btn-github is a
       solid-fill button, not an elevated surface. */
    --shadow: 0 1px 2px rgba(20, 25, 30, 0.05), 0 1px 3px rgba(20, 25, 30, 0.09);
    --radius: 8px;
    --maxw: 1000px;

    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background: var(--ground);
    color: var(--ink);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }

  /* Dark palette. Two triggers, mirroring app.css so the user's toggle wins over
     the OS in both directions: the OS prefers dark (unless the toggle forced
     light), or the toggle set data-theme="dark" on <html>. */
  @media (prefers-color-scheme: dark) {
    :global(html:not([data-theme="light"])) .landing {
      --ground: #101413;
      --surface: #323535;
      --line: #3f4947;
      --ink: #e0e3e1;
      --muted: #bec9c6;
      --accent: #52dbcb;
      --accent-soft: #005049;
      --accent-2: #aecae6;
      --accent-2-soft: #2e4961;
      --btn-ink: #e0e3e1;
      --btn-on: #101413;
      --shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
    }
  }
  :global(html[data-theme="dark"]) .landing {
    --ground: #101413;
    --surface: #323535;
    --line: #3f4947;
    --ink: #e0e3e1;
    --muted: #bec9c6;
    --accent: #52dbcb;
    --accent-soft: #005049;
    --accent-2: #aecae6;
    --accent-2-soft: #2e4961;
    --btn-ink: #e0e3e1;
    --btn-on: #101413;
    --shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  }

  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 1.5rem;
    max-width: var(--maxw);
    width: 100%;
    margin: 0 auto;
    box-sizing: border-box;
    background: none;
    border-bottom: none;
  }
  .top-actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .theme-toggle {
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    padding: 0;
    border: 1px solid var(--line);
    border-radius: var(--shape-full);
    background: var(--surface);
    color: var(--muted);
    cursor: pointer;
  }
  .theme-toggle:hover {
    color: var(--ink);
    border-color: var(--muted);
    /* --state-hover is defined in app.css in terms of --text, which this
       page's own --ink mirrors exactly in both themes (see the --ink
       assignments above) — safe to reuse rather than a third copy of the
       same wash under a Landing-local name. */
    background: linear-gradient(var(--state-hover), var(--state-hover)), var(--surface);
  }
  .theme-toggle:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    background: linear-gradient(var(--state-focus), var(--state-focus)), var(--surface);
  }
  .theme-toggle:active {
    background: linear-gradient(var(--state-pressed), var(--state-pressed)), var(--surface);
  }
  .demo-link {
    font-size: var(--type-label-large-size);
    line-height: var(--type-label-large-line-height);
    letter-spacing: var(--type-label-large-tracking);
    color: var(--muted);
    text-decoration: none;
    font-weight: 500;
  }
  .demo-link:hover {
    color: var(--ink);
  }
  /* No focus-visible existed at all before this slice — a real a11y gap on
     a keyboard-reachable link. Zero padding (like button.link in app.css),
     so an outline rather than a background wash. */
  .demo-link:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    color: var(--ink);
  }

  .hero {
    position: relative;
    text-align: center;
    padding: clamp(2.5rem, 8vw, 5.5rem) 1.5rem clamp(2rem, 5vw, 3.5rem);
    overflow: hidden;
  }
  .hero::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
      linear-gradient(var(--accent) 0 0) 18% 0 / 1px 100% no-repeat,
      linear-gradient(var(--accent) 0 0) 50% 0 / 1px 100% no-repeat,
      linear-gradient(var(--accent) 0 0) 82% 0 / 1px 100% no-repeat;
    opacity: 0.05;
    -webkit-mask-image: radial-gradient(120% 80% at 50% 0%, #000 30%, transparent 75%);
    mask-image: radial-gradient(120% 80% at 50% 0%, #000 30%, transparent 75%);
    pointer-events: none;
  }
  .hero > :global(*) {
    position: relative;
  }

  .eyebrow {
    font-size: var(--type-label-medium-size);
    line-height: var(--type-label-medium-line-height);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--muted);
    margin: 0 0 1rem;
  }
  h1 {
    margin: 0 auto 1rem;
    max-width: 15ch;
    /* display-large's role size (3.5625rem) is the fluid clamp's ceiling, not a
       flat value — a fixed 3.5625rem would overflow on narrow viewports. The
       clamp's min/preferred are the pre-existing hand-tuned responsive curve
       (predates this ticket; layout, not typography, per the ticket's scope). */
    font-size: clamp(2.2rem, 6vw, var(--type-display-large-size));
    line-height: 1.05;
    letter-spacing: -0.025em;
    font-weight: 800;
    text-wrap: balance;
  }
  h1 .hl {
    color: var(--accent);
  }
  .subhead {
    margin: 0 auto;
    max-width: 52ch;
    font-size: var(--type-body-large-size);
    line-height: var(--type-body-large-line-height);
    font-weight: var(--type-body-large-weight);
    letter-spacing: var(--type-body-large-tracking);
    color: var(--muted);
    text-wrap: pretty;
  }

  .cta-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.9rem;
    justify-content: center;
    align-items: center;
    margin-top: 2rem;
  }
  .btn-github {
    display: inline-flex;
    align-items: center;
    gap: 0.6rem;
    background: var(--btn-ink);
    color: var(--btn-on);
    border: 1px solid var(--btn-ink);
    border-radius: var(--shape-full);
    padding: 0.7rem 1.25rem;
    font-size: var(--type-label-large-size);
    line-height: var(--type-label-large-line-height);
    letter-spacing: var(--type-label-large-tracking);
    font-weight: 600;
    text-decoration: none;
    box-shadow: var(--shadow);
    cursor: pointer;
    transition:
      transform 0.12s ease,
      filter 0.12s ease;
  }
  .btn-github:hover {
    /* Keeps the existing lift + brighten (this page's own established
       hover language for its hero CTA) and layers the M3 hover wash on
       top, same as every other filled button in this slice. Pairs with
       --btn-on (this button's OWN content colour on its OWN --btn-ink
       fill — not the app-shell --accent/--on-accent pair). */
    transform: translateY(-1px);
    filter: brightness(1.08);
    background: linear-gradient(color-mix(in srgb, var(--btn-on) 8%, transparent), color-mix(in srgb, var(--btn-on) 8%, transparent)), var(--btn-ink);
  }
  .btn-github:disabled {
    opacity: 0.7;
    cursor: progress;
  }
  .btn-github:focus-visible {
    outline: 3px solid var(--accent);
    outline-offset: 2px;
    background: linear-gradient(color-mix(in srgb, var(--btn-on) 12%, transparent), color-mix(in srgb, var(--btn-on) 12%, transparent)), var(--btn-ink);
  }
  .btn-github:active {
    background: linear-gradient(color-mix(in srgb, var(--btn-on) 12%, transparent), color-mix(in srgb, var(--btn-on) 12%, transparent)), var(--btn-ink);
  }
  .btn-github svg {
    fill: currentColor;
  }

  .text-link {
    color: var(--accent);
    font-weight: 600;
    font-size: var(--type-label-large-size);
    line-height: var(--type-label-large-line-height);
    letter-spacing: var(--type-label-large-tracking);
    text-decoration: none;
  }
  .text-link:hover {
    text-decoration: underline;
  }
  /* No focus-visible existed at all before this slice. Zero padding, so
     an outline rather than a wash (same reasoning as .demo-link above). */
  .text-link:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .error {
    margin: 1rem auto 0;
    max-width: 42ch;
    color: #de350b;
    font-size: var(--type-body-medium-size);
    line-height: var(--type-body-medium-line-height);
    font-weight: var(--type-body-medium-weight);
    letter-spacing: var(--type-body-medium-tracking);
  }

  .features {
    max-width: var(--maxw);
    width: 100%;
    margin: 0 auto;
    padding: 1rem 1.5rem clamp(2.5rem, 6vw, 4rem);
    box-sizing: border-box;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
  }
  .tile {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--shape-medium);
    padding: 1.1rem 1.15rem 1.25rem;
    box-shadow: var(--shadow);
  }
  .tag {
    display: inline-block;
    font-size: var(--type-label-small-size);
    line-height: var(--type-label-small-line-height);
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    border-radius: var(--shape-full);
    padding: 0.12rem 0.5rem;
    margin-bottom: 0.7rem;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .tile:nth-child(3) .tag {
    background: var(--accent-2-soft);
    color: var(--accent-2);
  }
  .tile h3 {
    margin: 0 0 0.35rem;
    font-size: var(--type-title-medium-size);
    line-height: var(--type-title-medium-line-height);
    font-weight: var(--type-title-medium-weight);
    letter-spacing: -0.01em;
  }
  .tile p {
    margin: 0;
    font-size: var(--type-body-medium-size);
    line-height: var(--type-body-medium-line-height);
    font-weight: var(--type-body-medium-weight);
    letter-spacing: var(--type-body-medium-tracking);
    color: var(--muted);
  }

  footer {
    margin-top: auto;
    border-top: 1px solid var(--line);
    padding: 1.25rem 1.5rem;
    text-align: center;
    font-size: var(--type-body-small-size);
    line-height: var(--type-body-small-line-height);
    font-weight: var(--type-body-small-weight);
    letter-spacing: var(--type-body-small-tracking);
    color: var(--muted);
  }
  footer a {
    color: inherit;
    font-weight: 600;
    text-decoration: none;
  }
  footer a:hover {
    color: var(--ink);
    text-decoration: underline;
  }
  footer a:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    color: var(--ink);
  }

  @media (prefers-reduced-motion: no-preference) {
    .reveal {
      opacity: 0;
      transform: translateY(10px);
      animation: rise 0.6s ease forwards;
    }
    .reveal:nth-child(1) {
      animation-delay: 0.02s;
    }
    .reveal:nth-child(2) {
      animation-delay: 0.08s;
    }
    .reveal:nth-child(3) {
      animation-delay: 0.16s;
    }
    .reveal:nth-child(4) {
      animation-delay: 0.24s;
    }
    .tile {
      opacity: 0;
      transform: translateY(10px);
      animation: rise 0.6s ease forwards;
    }
    .tile:nth-child(1) {
      animation-delay: 0.28s;
    }
    .tile:nth-child(2) {
      animation-delay: 0.36s;
    }
    .tile:nth-child(3) {
      animation-delay: 0.44s;
    }
    @keyframes rise {
      to {
        opacity: 1;
        transform: none;
      }
    }
  }

  @media (max-width: 720px) {
    .features {
      grid-template-columns: 1fr;
    }
  }
</style>
