import { createHash, randomBytes } from "node:crypto";
import { expect, test } from "@playwright/test";
import { API_ORIGIN, login } from "./helpers";

// OAuth 2.1 authorization_code+PKCE consent screen (ADR 0026, KAN-1735): the
// second entry path a browser-embedded OAuth client (Claude.ai et al.) drives
// (device-flow.spec.ts covers the CLI's `user_code` entry path).
//
// Like device-flow.spec.ts, this drives the SPA directly with the query params
// GET /auth/authorize's own redirect would forward, rather than navigating
// through that redirect itself: in this dev harness Vite's proxy rewrites the
// Host header to the *backend's* own origin (not the frontend's) before the
// backend ever sees the request, so `request.base_url` — and hence the
// redirect target / the canonical `resource` — resolves to `API_ORIGIN`, which
// serves no SPA in dev (no built `frontend/dist`). That redirect mechanics is
// covered thoroughly at the integration level
// (`backend/tests/integration/test_oauth_authorize.py`, using a `TestClient`
// where `base_url` is unambiguous); this suite's job is the UI it hands off to.

const REDIRECT_URI = "http://127.0.0.1:9999/callback";
const RESOURCE = `${API_ORIGIN}/mcp`;

function pkcePair() {
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

async function registerClient(page: import("@playwright/test").Page) {
  const res = await page.request.post("/auth/register", {
    data: { redirect_uris: [REDIRECT_URI], client_name: "E2E Test Client" },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).client_id as string;
}

function consentScreenUrl(clientId: string, challenge: string, state = "e2e-state") {
  const q = new URLSearchParams({
    client_id: clientId,
    redirect_uri: REDIRECT_URI,
    code_challenge: challenge,
    code_challenge_method: "S256",
    resource: RESOURCE,
    scope: "write",
    state,
  });
  return `/?${q.toString()}`;
}

test("approve an authorization_code request from an OAuth client redirect", async ({ page }) => {
  await login(page);
  const clientId = await registerClient(page);
  const { verifier, challenge } = pkcePair();

  await page.goto(consentScreenUrl(clientId, challenge));
  await expect(page.getByRole("heading", { name: "Connect an application" })).toBeVisible();
  await expect(page.getByText("E2E Test Client")).toBeVisible();

  // Approving is a real top-level navigation away from the SPA, back to the
  // (fake) requesting app's redirect_uri — nothing actually listens there, so
  // stub it rather than let the browser's real connection attempt fail; we
  // only care what URL it tried to land on.
  await page.route(`${REDIRECT_URI}**`, (route) => route.fulfill({ status: 200, body: "ok" }));
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.waitForURL((url) => url.origin === "http://127.0.0.1:9999");
  const landed = new URL(page.url());
  expect(landed.searchParams.get("state")).toBe("e2e-state");
  const code = landed.searchParams.get("code");
  expect(code).toBeTruthy();

  // Exchanging that code actually mints a working token.
  const token = await page.request.post("/auth/device/token", {
    data: {
      grant_type: "authorization_code",
      code,
      redirect_uri: REDIRECT_URI,
      client_id: clientId,
      code_verifier: verifier,
      resource: RESOURCE,
    },
  });
  expect(token.ok()).toBeTruthy();
  const body = await token.json();
  expect(body.access_token).toMatch(/^pandan_pat_/);
  expect(body.refresh_token).toBeTruthy();
});

test("deny an authorization_code request redirects with access_denied", async ({ page }) => {
  await login(page);
  const clientId = await registerClient(page);
  const { challenge } = pkcePair();

  await page.goto(consentScreenUrl(clientId, challenge));
  await page.route(`${REDIRECT_URI}**`, (route) => route.fulfill({ status: 200, body: "ok" }));
  await page.getByRole("button", { name: "Deny", exact: true }).click();
  await page.waitForURL((url) => url.origin === "http://127.0.0.1:9999");
  const landed = new URL(page.url());
  expect(landed.searchParams.get("error")).toBe("access_denied");
  expect(landed.searchParams.get("state")).toBe("e2e-state");
});

test("an unknown client_id shows a clean error, not a crash", async ({ page }) => {
  await login(page);
  const { challenge } = pkcePair();
  await page.goto(consentScreenUrl("not-a-real-client", challenge));
  await expect(page.getByText(/invalid or has expired/)).toBeVisible();
});
