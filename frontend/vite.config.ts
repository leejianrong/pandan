import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Dev server proxies to the FastAPI backend so dev mirrors the same-origin
// production setup and needs no CORS (ADR 0008). Prod is served by FastAPI itself.
// /auth and /users are the fastapi-users auth + identity routes (M3 V6); they sit
// outside /api/v1 (session plumbing, like /api/health) so they need their own
// proxy entries.
//
// Ports are ENV-overridable (KAN-391) so a worktree e2e run can dodge a foreign
// app squatting on the defaults: FRONTEND_PORT (Vite) / BACKEND_PORT (the proxy
// target) both default to today's 5173 / 8000, so CI and normal dev are unchanged.
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT) || 5173;
const BACKEND_PORT = Number(process.env.BACKEND_PORT) || 8000;
const BACKEND_ORIGIN = `http://localhost:${BACKEND_PORT}`;

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: FRONTEND_PORT,
    proxy: {
      "/api": BACKEND_ORIGIN,
      "/auth": BACKEND_ORIGIN,
      "/users": BACKEND_ORIGIN,
    },
  },
  build: {
    outDir: "dist",
  },
});
