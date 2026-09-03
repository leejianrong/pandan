// Regenerates the M3 role-palette hex values baked into app.css / Landing.svelte
// (M3-1, KAN-1090). This is a "tokens only, hand-rolled markup" project — no
// @material/web / m3-svelte adoption (decided on the epic, EPIC-143/PAN-E30) — so
// the generated scheme is transcribed into CSS custom properties by hand rather
// than consumed at runtime. This script exists purely so those values are
// reproducible from the one seed color instead of hand-tuned guesses; it is not
// wired into the build.
//
// Usage: node --import ./scripts/_esm-shim.mjs is NOT needed if run via esbuild
// (the published package's internal imports omit `.js` extensions, which trips
// Node's strict ESM resolver — see the KAN-1090 PR description). Run it bundled:
//   npx esbuild scripts/gen-m3-tokens.mjs --bundle --platform=node --format=esm \
//     --outfile=/tmp/gen-m3-tokens.bundled.mjs && node /tmp/gen-m3-tokens.bundled.mjs [seedHex]
import { themeFromSourceColor, argbFromHex, hexFromArgb } from "@material/material-color-utilities";

const seed = process.argv[2] ?? "#0d9488";
const theme = themeFromSourceColor(argbFromHex(seed));

// Base roles: taken straight from the generated Scheme (contrast-checked pairs).
const schemeRoles = [
  "primary",
  "onPrimary",
  "primaryContainer",
  "tertiary",
  "onTertiary",
  "tertiaryContainer",
  "error",
  "onError",
  "errorContainer",
  "onSurface",
  "onSurfaceVariant",
  "outline",
  "outlineVariant",
];

// Surface-container tiers: `themeFromSourceColor`'s `Scheme` (this package's
// v0.4 API) predates the surface-container tier roles, so these are derived the
// same way the spec itself derives them — fixed tone steps on the seed's own
// neutral tonal palette (light: 100/98/96/94/92/90, dark: 4/6/10/12/17/22).
const surfaceTones = {
  light: { "surface-container-lowest": 100, surface: 98, "surface-container-low": 96, "surface-container": 94, "surface-container-high": 92, "surface-container-highest": 90 },
  dark: { "surface-container-lowest": 4, surface: 6, "surface-container-low": 10, "surface-container": 12, "surface-container-high": 17, "surface-container-highest": 22 },
};

for (const mode of ["light", "dark"]) {
  const scheme = theme.schemes[mode];
  console.log(`\n--- ${mode} (seed ${seed}) ---`);
  for (const role of schemeRoles) {
    console.log(`${role}: ${hexFromArgb(scheme[role])}`);
  }
  for (const [role, tone] of Object.entries(surfaceTones[mode])) {
    console.log(`${role}: ${hexFromArgb(theme.palettes.neutral.tone(tone))}`);
  }
}
