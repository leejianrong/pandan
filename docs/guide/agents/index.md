<!--
title: "Agents and MCP"
description: Why Pandan is built for agents, and the two ways to give one access: the MCP server or the CLI.
-->

# Agents and MCP

Pandan exists because handing work to a coding agent usually means the agent cannot see the work. It
gets a prompt, not a board. It finishes, and nothing records what it did.

So the board was built API-first, and an agent gets the same surface a human does.

## What an agent can actually do

Everything. There is no capability behind the browser that an agent cannot reach:

- Read the board, filter it, search it
- Create, edit, move and delete cards and epics
- Claim a card atomically, so two agents cannot take the same one
- See what is blocking a card, and record a new blocker
- Attach the pull request it opened
- Comment on what it found
- Flag the card for a human, with a note explaining the question
- Read its own notification inbox

That last one matters more than it sounds. An agent that can say "I need a human here, and this is
why" is far more useful than one that guesses or stops.

## Two ways in

<div class="grid cards" markdown>

-   **MCP server**

    For agents that speak [MCP](https://modelcontextprotocol.io): Claude Code, Claude Desktop, and
    anything else with an MCP client. 49 tools, one per API capability.

    [Set it up](mcp-setup.md)

-   **The CLI**

    For agents that shell out, and for CI. Same API, same permissions, and cheaper per task.

    [CLI guide](../cli/index.md)

</div>

Which one? If your agent has an MCP client, use MCP, because tool calls are structured and it does not
have to parse output. If your agent shells out, or you are writing a pipeline, use the CLI.

Some setups want both, and that is fine. They read the same configuration and the same token.

!!! info "The CLI is often cheaper"

    Measured per task, the CLI has come out around 11 times cheaper in tokens than the MCP server,
    mostly because MCP carries tool schemas in every session and returns fuller payloads. The gap has
    largely closed on the reads that matter, but if token cost dominates your setup, the CLI is still
    the leaner choice. See [token budget](token-budget.md).

## Authentication

An agent authenticates with a personal access token, the same kind you use for the CLI. There is no
shared service token and no agent-specific credential type.

This is deliberate. A token resolves to the user who created it and is permission-checked exactly like
that user, so an agent can never reach further than the person who set it up. Mint a separate token per
agent, name it after the agent, and revoke it independently.

See [first steps](../first-steps.md#mint-a-personal-access-token) for how to create one.

## Ambient context

An agent that starts a session knowing nothing has to spend calls working out what is going on. The
CLI can inject the board state at session start instead:

```bash
pandan context install
```

That adds a `SessionStart` hook so the agent begins with the current board in its context. It fails
soft within a few seconds, so a cold-starting API cannot delay a session. Details in
[configuration](../cli/configure.md#ambient-context-for-agent-sessions).

## Next

<div class="grid cards" markdown>

-   **[Set up the MCP server](mcp-setup.md)**

    The container and from-source options, and how to verify the connection.

-   **[Tool reference](mcp-tools.md)**

    All 49 tools, grouped, with the arguments that shape their output.

-   **[Agent workflows](workflows.md)**

    Claim, work, link, comment, hand back. The patterns worth copying.

-   **[Token budget](token-budget.md)**

    What a read actually costs and how to cut it.

</div>
