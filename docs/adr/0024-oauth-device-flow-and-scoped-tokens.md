# ADR 0024 — OAuth 2.1 authorization-server core, device-flow CLI login, and board/workspace-scoped PATs

- **Status:** Accepted
- **Date:** 2026-09-25
- **Context source:** Maintainer planning session on CLI/MCP/agent authentication (2026-09-25); ADR
  0011 (GitHub cookie sessions), ADR 0014 (self-serve PATs), ADR 0023 (Workspace rename). Tracked as
  [EPIC-281](https://simple-kanban-jian.fly.dev) on the Pandan Roadmap board (KAN-1726..1731).

## Context

Today, getting a `pandan`/MCP credential is manual: a human opens the SPA's Tokens UI, creates a PAT,
copies the raw secret, and pastes it into `pandan login`'s hidden prompt (or `.mcp.json`). That copy
step is the friction this ADR removes — spinning up a new agent should not require a human to
hand-carry a secret across two applications.

Separately, every PAT today inherits its owning user's **entire** board access (ADR 0014) — there is
no way to hand an agent a credential scoped to one board or a Workspace, only "everything this user can
see." As boards multiply (M8's board-local refs, and now Workspaces, ADR 0023), that all-or-nothing
grant is increasingly the wrong default for a credential handed to a non-interactive agent.

A third, forward-looking constraint: a hosted remote MCP server (ADR 0025) will need a real OAuth 2.1
*authorization server* behind it regardless — RFC 9728/7591/8707 all assume one exists. Building the
authorization-server core now, and having the CLI's device flow be its first consumer, avoids building
this twice.

## Decision

**Pandan becomes its own OAuth 2.1 authorization server**, layered on top of the existing GitHub OAuth
human-login (ADR 0011, unchanged) and PAT model (ADR 0014, extended, not replaced). Two grant types
share one core:

1. **RFC 8628 Device Authorization Grant**, for the CLI/agent case (no browser redirect target):
   - `POST /auth/device/code` → `{device_code, user_code, verification_uri_complete, expires_in,
     interval}`. Backed by a new `device_authorization` table (device_code hash, user_code, status,
     `user_id` nullable until approved, requested scope, requested board/workspace scope, expires_at,
     the PAT id once minted). Short-lived (10–15 min) and single-use.
   - The CLI (`pandan auth login`) prints the link, best-effort-opens a browser, and shows the short
     `user_code` as a fallback/confirmation — the same shape `gh auth login` uses.
   - Visiting the link goes through the existing GitHub OAuth cookie flow if not already signed in,
     then a new SPA **consent screen**: pick `read`/`write` scope, and pick which boards (or whole
     Workspaces, as a one-click bulk-select over their member boards) this token may access. Approving
     mints a real `personal_access_token` row exactly like the Tokens UI does today — **this is a new
     minting path for an existing credential type, not a new credential format.**
   - `POST /auth/device/token` is polled by the CLI at `interval` (min 5s, enforced server-side with
     `slow_down`) until `authorization_pending` → `success` (returns the raw PAT once, never again) /
     `expired_token` / `access_denied`.
   - `pandan auth login/logout/status` join `pandan login` (unchanged, kept for CI/headless use where
     no browser is reachable) and `pandan me` (wrapped by `auth status`).
2. **A redirect-based OAuth 2.1 + PKCE flow**, reserved for ADR 0025's hosted MCP clients — out of
   scope to build in this ADR's slice, but the consent screen, scope model, and token-minting path
   above are written to serve both grant types without rework.

**Board/workspace scoping is a new, additive dimension on `personal_access_token`**: a
`personal_access_token_board` allow-list join table. **No rows = unrestricted** — every PAT minted via
the existing Tokens UI, before and after this change, keeps its current "all boards I own" behaviour.
`authorize_board` (ADR 0013) gains one more check: if the resolved principal is a PAT with any allow-
list rows, the board must be in that list, in addition to the existing owner check.

## Consequences

- **Positive:** an agent can be onboarded with a browser click and no copy-pasted secret. A credential
  handed to an agent can be scoped to exactly the boards/Workspaces it needs, closing the current
  all-or-nothing gap. The authorization-server core is reusable by ADR 0025 rather than rebuilt.
- **Neutral:** `personal_access_token` gains scope dimensions (board allow-list) beyond the existing
  read/write column; every read/write call site that reasons about "what can this PAT touch" must
  consult both.
- **Negative / deferred:** device-code/user-code entropy, exact expiry (~10–15 min) and poll-interval
  values are implementation details to pin in the build, not fixed by this ADR. MCP's config loader
  currently reads only environment variables, not the CLI's config file (KAN-1731) — until that lands,
  `pandan auth login` populates the CLI's credential but does not, by itself, wire up an MCP server
  already configured via `.mcp.json` env vars.
