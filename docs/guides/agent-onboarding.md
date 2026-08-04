<!--
title: "Agent onboarding (moved)"
description: This guide moved to the published documentation site; this file is a pointer kept so existing links still resolve.
-->

# Agent onboarding — moved to the docs site

This guide has moved. It is now several pages on the published documentation site, which is the
single source of truth for how to use Pandan:

**<https://leejianrong.github.io/pandan/>**

| What you wanted | Where it is now |
| --- | --- |
| Install the CLI | [Installation](https://leejianrong.github.io/pandan/install/) |
| Mint a token, point a client at a board, read it | [First steps](https://leejianrong.github.io/pandan/first-steps/) |
| Why the board is agent-friendly | [Agents and MCP](https://leejianrong.github.io/pandan/agents/) |
| Wire the MCP server into Claude Code, and verify it | [Set up the MCP server](https://leejianrong.github.io/pandan/agents/mcp-setup/) |
| The 49 MCP tools | [MCP tool reference](https://leejianrong.github.io/pandan/agents/mcp-tools/) |
| Claim, comment, link, hand back to a human | [Agent workflows](https://leejianrong.github.io/pandan/agents/workflows/) |
| What a read costs, and how to cut it | [Token budget](https://leejianrong.github.io/pandan/agents/token-budget/) |
| CLI in a CI job | [In CI](https://leejianrong.github.io/pandan/cli/ci/) |
| Self-hosting | [Self-hosting](https://leejianrong.github.io/pandan/self-hosting/) |
| What Pandan does not do yet | [Current limits](https://leejianrong.github.io/pandan/about/limits/) |

The site is built from [`docs/guide/`](../guide/index.md) in this repository, so edit the pages there
rather than this file.

## Why this file still exists

Roughly two dozen links across the repo, the skills, and the READMEs pointed at
`docs/guides/agent-onboarding.md`. Keeping the path as a pointer means none of them break.

## Two corrections worth calling out

The version of this guide that lived here had gone stale in two ways, both fixed on the site:

**Boards can be shared.** The old text said "there is no board sharing yet" and that each person
needs their own boards or their own instance. That has not been true since KAN-12/13: a board has an
owner plus members with a `viewer`, `editor` or `owner` role
(`backend/app/routers/members.py`, `VALID_ROLES` in `backend/app/models.py`). See
[Boards](https://leejianrong.github.io/pandan/tutorial/boards/#sharing-a-board).

**The published MCP image is `pandan-mcp`.** The old text pointed at
`ghcr.io/leejianrong/simple-kanban-mcp` and described the rename as pending. Both paths are public
and pullable today, but new releases go to `ghcr.io/leejianrong/pandan-mcp` (KAN-437 is done bar the
cosmetic OAuth App display name).
