# ADR 0025 — A hosted, OAuth-protected remote MCP server

- **Status:** Accepted
- **Date:** 2026-09-25
- **Context source:** Maintainer planning session on CLI/MCP/agent authentication (2026-09-25);
  research into the MCP Authorization spec (`modelcontextprotocol.io/specification/2025-06-18/basic/
  authorization`) and how Notion/Atlassian/Linear implement it; ADR 0019 (MCP surface right-sizing),
  ADR 0024 (OAuth core). Tracked as
  [EPIC-282](https://simple-kanban-jian.fly.dev) on the Pandan Roadmap board (KAN-1732..1737).

## Context

Pandan's MCP server today is **stdio-transport**: a local subprocess Claude Code launches from
`.mcp.json`, configured with a `PANDAN_TOKEN` env var. The MCP Authorization spec is explicit that
this is **out of its scope by design** — "*Implementations using an STDIO transport SHOULD NOT follow
this specification, and instead retrieve credentials from the environment*" — so there is no
in-protocol auth upgrade available to a stdio server; that gap is exactly what ADR 0024's device flow
closes for it.

But stdio also means Pandan's MCP surface only works from a client willing to spawn and manage a local
subprocess (chiefly Claude Code). Products built for the same job — Notion (`mcp.notion.com`),
Atlassian (`mcp.atlassian.com`, Jira/Confluence), Linear (`mcp.linear.app`) — instead run a **hosted,
HTTP-transport MCP server** that any compliant client (Claude.ai, ChatGPT, Cursor) can add with a URL
and a browser consent click, no local install at all. That is a materially larger reachable audience
than "people running Claude Code locally," and it is the direction the ecosystem has converged on.

## Decision

**Stand up a hosted, always-on MCP endpoint on Pandan's existing backend**, over Streamable HTTP,
acting as a spec-compliant **OAuth 2.1 resource server** against the authorization-server core built in
ADR 0024:

- **RFC 9728 Protected Resource Metadata** at `/.well-known/oauth-protected-resource`, so a cold client
  can discover which authorization server protects this endpoint without out-of-band configuration.
- **RFC 7591 Dynamic Client Registration** (evaluating the newer Client ID Metadata Document approach
  as an alternative/successor at build time — the spec itself is mid-migration from one to the other),
  so each connecting app (Claude.ai, Cursor, ChatGPT) self-registers a distinct client identity rather
  than sharing one pre-registered client, or requiring Pandan to hand-register every possible client
  ahead of time.
- **RFC 8707 Resource Indicators**, binding every minted token to this specific MCP endpoint via the
  `resource` parameter on both the authorization and token requests, and validating that audience on
  every call. This closes the "confused deputy" / token-passthrough failure class the spec calls out
  by name — a token issued for Pandan's MCP endpoint must not be honoured elsewhere, and Pandan's MCP
  endpoint must never forward a caller's token to a third-party API unmodified (moot for Pandan today,
  since the endpoint *is* the resource server rather than a proxy to one, but the validation is built
  in regardless).
- **Per-(user, connected app) tokens**, not one PAT per human: connecting Claude.ai and connecting
  Cursor to the same Pandan account produces two independently listable/revocable tokens, on the same
  board/workspace-scope and read/write-scope model ADR 0024 introduced.
- **The existing stdio MCP package is kept**, explicitly repositioned in docs as the self-hosting /
  offline fallback. The hosted endpoint and the `pandan` CLI become the top-billed options; stdio is
  documented third, for operators running their own instance who want no dependency on Pandan's hosted
  infrastructure.

## Consequences

- **Positive:** Pandan's MCP surface becomes usable from any spec-compliant remote-MCP client, not only
  Claude Code, with no local install and no manually-managed secret — matching Notion/Atlassian/Linear's
  UX. The authorization-server investment from ADR 0024 is reused rather than duplicated.
- **Neutral:** Pandan takes on hosting responsibility for an always-on endpoint's availability, where a
  stdio subprocess's uptime was previously the user's own local concern. The MCP server needs new
  bookkeeping — one token per connected app, not per human.
- **Negative / deferred:** RFC 7591 vs. Client ID Metadata Documents is left as a build-time call, since
  the spec ecosystem is actively migrating between them (2026-07-28 formally deprecates DCR in favour
  of CIMD with a ~12-month compatibility window) and either can satisfy this ADR's intent. This ADR
  does not commit to a timeline for retiring stdio support — that stays a documented fallback
  indefinitely unless a future ADR revisits it.
