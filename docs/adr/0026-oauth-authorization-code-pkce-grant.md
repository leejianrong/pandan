# ADR 0026 — OAuth 2.1 Authorization Code + PKCE grant for hosted MCP clients

- **Status:** Accepted
- **Date:** 2026-09-25
- **Context source:** ADR 0024 (device flow + scoped tokens), ADR 0025 (hosted remote MCP server) —
  this ADR fills a gap ADR 0025 left open. Discovered when EPIC-282 (KAN-1732..1737) turned out to be
  unbuildable without it: every card transitively needs a grant type neither prior ADR specifies.
  Tracked against [EPIC-282](https://simple-kanban-jian.fly.dev) on the Pandan Roadmap board.

## Context

ADR 0024 built an RFC 8628 **Device Authorization Grant** for the CLI (`pandan auth login`) and
explicitly deferred the other half: *"a redirect-based OAuth 2.1 + PKCE flow, reserved for ADR 0025's
hosted MCP clients — out of scope to build in this ADR's slice."* ADR 0025 then specified only the
**resource-server** side of hosting an MCP endpoint — RFC 9728 discovery metadata, RFC 7591 Dynamic
Client Registration, RFC 8707 resource-indicator binding — and silently assumed an authorization-server
flow already existed behind it. It doesn't: device flow has no redirect target and cannot be what a
browser-embedded client like Claude.ai completes. This left every EPIC-282 card blocked with no
specified grant to implement against — correctly caught and escalated rather than improvised.

This is exactly the missing piece: the actual **OAuth 2.1 Authorization Code grant with mandatory
PKCE**, the flow the MCP Authorization spec requires for HTTP-transport clients, reusing as much of
ADR 0024's already-shipped infrastructure (the consent screen, the board/workspace scope model, the
`personal_access_token` table) as fits.

## Decision

**Add a standard OAuth 2.1 authorization_code + PKCE grant, sharing the consent screen and scope model
ADR 0024 already shipped, with token issuance keyed to the DCR-registered client rather than to a
device.**

- **`GET /auth/authorize`** — `response_type=code`, `client_id` (an RFC 7591-registered client from
  EPIC-282's DCR card), `redirect_uri`, `code_challenge` + `code_challenge_method=S256` (**mandatory**
  — OAuth 2.1 drops `plain` entirely, no fallback), `resource` (RFC 8707, the MCP endpoint's canonical
  URI), `scope`, `state`. Requires an existing GitHub-OAuth cookie session (ADR 0011); an unauthenticated
  visitor is redirected through login first, same as the device flow's approval page today.
- **`redirect_uri` is validated by exact match against the client's DCR-registered URI list** — no
  wildcard, no prefix, no partial match. This is the specific control that prevents a registered
  client's authorization code from being redirected to an attacker-controlled origin; getting it wrong
  is an open redirect, which is why this ADR pins the rule explicitly rather than leaving it to
  implementation discretion.
- **The consent screen is the same component KAN-1729 already shipped** (`DeviceApproval.svelte` and
  its backend approve/deny routes), reached via a second entry path (`?client_id=&redirect_uri=...`
  alongside the existing `?user_code=`) rather than rebuilt: same board/workspace picker, same
  read/write scope choice, same "approver can't grant a board they don't own" guard.
- **Approval mints a short-lived, single-use authorization `code`** (≤60s expiry) bound to the
  `code_challenge`, `redirect_uri`, `resource`, and the approved board/scope selection — extending the
  `device_authorization`-style row rather than inventing a parallel table, since the state it holds
  (pending → approved → consumed, expiring, single-use) is the same shape. Redirects back to
  `redirect_uri` with `?code=&state=`.
- **`POST /auth/token`** (the same endpoint ADR 0024 built for device-flow polling) gains
  `grant_type=authorization_code`: takes `code`, `redirect_uri`, `client_id`, `code_verifier`, `resource`;
  verifies the PKCE challenge (`SHA256(code_verifier) == code_challenge`), the exact `redirect_uri` and
  `resource` match what was requested at `/authorize`, then mints the token. **This is where RFC 8707
  binding actually happens** — ADR 0025 named the requirement, this is its enforcement point.
- **Tokens minted this way are distinct from a self-serve/device-flow PAT, but reuse its schema**:
  `personal_access_token` gains a nullable `oauth_client_id` FK to a new `oauth_client` table (populated
  by DCR). `NULL` = today's PAT (Tokens UI or `pandan auth login`); non-null = **one token per (user,
  connected app)**, satisfying KAN-1736 without a parallel token model. The Tokens UI lists and revokes
  both uniformly, labelling app-issued ones by the client's registered name ("Claude.ai") instead of a
  user-typed name. Board/workspace scoping (ADR 0024's allow-list) and `read`/`write` scope apply
  identically to both kinds — one authorization model, two ways to obtain a credential under it.
- **Refresh tokens.** MCP clients are public clients (PKCE, no client secret), so refresh tokens are
  **rotating and single-use**: each refresh both extends the session and invalidates the token it
  replaces, so a leaked refresh token is usable at most once before the legitimate client's next refresh
  detects the theft (the old token failing). Access tokens stay short-lived (mirroring existing PAT
  lifetime norms); this is what makes that tolerable without forcing a re-consent per hour.

## Consequences

- **Positive:** EPIC-282 is now fully specified — KAN-1732 (transport), KAN-1733 (RFC 9728), KAN-1734
  (RFC 7591 DCR), KAN-1735 (RFC 8707 binding, now with a concrete enforcement point), KAN-1736 (token
  model, now schema-backed), and KAN-1737 (docs) can each proceed without further protocol design. The
  consent screen and scope model are reused rather than duplicated a second time.
- **Neutral:** `/auth/token` now serves two grant types (`device_code` from ADR 0024,
  `authorization_code` from this ADR) behind one endpoint, differentiated by `grant_type` — standard
  OAuth practice, not a divergence from spec.
- **Negative / deferred:** this ADR does not resolve RFC 7591 vs. the newer Client ID Metadata Document
  approach for client registration itself (ADR 0025 already left that as a build-time call for
  KAN-1734) — it specifies the grant that runs *after* a client is registered, whichever mechanism
  registers it. Exact authorization-code and access-token TTLs are implementation detail, not fixed
  here, beyond "short-lived" and "single-use where noted."
