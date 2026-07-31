import { defineConfig, devices } from "@playwright/test";

// End-to-end smoke tests. Playwright brings up the full local stack itself:
// the FastAPI backend (:8000) and the Vite dev server (:5173, which proxies
// /api → :8000). A local Postgres must already be running —
// `docker compose up -d db` from the repo root (same prereq as running the
// backend normally). Tests are self-contained: each creates cards with a unique
// title prefix and cleans them up, so they tolerate pre-existing dev data.
//
// Ports are ENV-overridable (KAN-391): FRONTEND_PORT / BACKEND_PORT default to
// 5173 / 8000, so CI and normal dev are unchanged, but a worktree run can dodge a
// foreign app on the defaults with e.g.
//   BACKEND_PORT=8010 FRONTEND_PORT=5183 npm run e2e
// The Vite webServer inherits these via process.env, so its proxy target (see
// vite.config.ts) follows BACKEND_PORT; helpers.ts derives API_ORIGIN the same way.
const CI = !!process.env.CI;
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT) || 5173;
const BACKEND_PORT = Number(process.env.BACKEND_PORT) || 8000;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // shared backend/DB — keep specs sequential for determinism
  workers: 1,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? "line" : "list",
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      // Migrate then serve the API. Uses the default DATABASE_URL (the
      // docker-compose Postgres). cwd is this config's dir (frontend/).
      command: `sh -c "cd ../backend && uv run alembic upgrade head && uv run uvicorn app.main:app --port ${BACKEND_PORT}"`,
      port: BACKEND_PORT,
      reuseExistingServer: !CI,
      timeout: 120_000,
      // M3 V8: /api/v1 is owner-gated, so e2e needs a real session. E2E_AUTH_BYPASS
      // mounts POST /auth/test-login (session-mint seam, never in prod); the cleanup
      // helpers use it to act as each owning user (V10 removed the API_TOKENS SERVICE
      // bypass). Merged over process.env, so the CI job's DATABASE_URL is preserved.
      env: {
        E2E_AUTH_BYPASS: "1",
      },
    },
    {
      // `npm run dev` reads FRONTEND_PORT / BACKEND_PORT from process.env
      // (vite.config.ts), so the Vite port + its /api proxy target both follow.
      command: "npm run dev",
      port: FRONTEND_PORT,
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
  ],
});
