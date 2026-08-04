<!--
title: "Set up the MCP server"
description: Wire the Pandan MCP server into Claude Code with the prebuilt container image or from a source checkout, then verify it works.
-->

# Set up the MCP server

The MCP server is a thin adapter over the REST API. It holds no database and no state, so running it is
just running a process that can reach your board.

Claude Code discovers project-scoped servers from a `.mcp.json` at the root of your repository. Other
MCP clients use their own config file, but the server entry is the same shape.

## Pick how to run it

=== "Container"

    Nothing to install but Docker. No Python, no `uv`, no checkout.

    ```json
    {
      "mcpServers": {
        "pandan": {
          "command": "docker",
          "args": [
            "run", "-i", "--rm",
            "-e", "PANDAN_API_URL",
            "-e", "PANDAN_TOKEN",
            "-e", "PANDAN_BOARD_ID",
            "ghcr.io/leejianrong/pandan-mcp:latest"
          ],
          "env": {
            "PANDAN_API_URL": "https://simple-kanban-jian.fly.dev",
            "PANDAN_TOKEN": "pandan_pat_…",
            "PANDAN_BOARD_ID": "5"
          }
        }
      }
    }
    ```

    The image is public, so `docker pull` needs no login and no GitHub account.

    Two details worth knowing. `-i` keeps stdin open, which the stdio transport requires. And the
    `-e NAME` flags carry **no** `=value`, which forwards each value from the `env` block into the
    container instead of putting your token in the argument list where `ps` can read it.

    Tags track the release: `latest`, plus semver tags. Pin one for a stable setup:

    ```
    ghcr.io/leejianrong/pandan-mcp:0.22.0
    ```

=== "From source"

    Needs a checkout of the repository and [uv](https://docs.astral.sh/uv/). It runs straight out of
    `mcp/`, so there is nothing to build.

    ```json
    {
      "mcpServers": {
        "pandan": {
          "command": "uv",
          "args": ["run", "--directory", "./mcp", "python", "-m", "pandan_mcp"],
          "env": {
            "PANDAN_API_URL": "https://simple-kanban-jian.fly.dev",
            "PANDAN_TOKEN": "pandan_pat_…",
            "PANDAN_BOARD_ID": "5"
          }
        }
      }
    }
    ```

    `--directory ./mcp` is relative to wherever the client launches the server, which for Claude Code
    is your repository root. Use an absolute path if you launch from elsewhere.

The repository ships a [`.mcp.json.example`](https://github.com/leejianrong/pandan/blob/main/.mcp.json.example)
with both entries. Copy it, keep one, delete the other.

## The three settings

| Variable | What it does |
| --- | --- |
| `PANDAN_API_URL` | The API origin. `https://simple-kanban-jian.fly.dev` for the hosted board, or your own. The `/api/v1` prefix is added for you. |
| `PANDAN_TOKEN` | Your `pandan_pat_…` token. Required. Empty or wrong gives `401`. |
| `PANDAN_BOARD_ID` | The default board for any call that omits `board_id`. |

!!! warning "Set `PANDAN_BOARD_ID`"

    Leave it empty and `list_*` tools span **every** board you can reach, while `create_*` tools land
    on your **earliest** one. That is how an agent files a card onto the wrong board.

    Run `list_boards` once, find your id, and put it in the config. `.mcp.json.example` presets it to
    `1`, which is the seeded default board and almost certainly not yours.

## The server key names your tools

Whatever you call the server in `mcpServers` becomes the namespace for every tool. With the key
`pandan`, `list_cards` is really `mcp__pandan__list_cards`.

!!! info "It used to be `mcp__kanban__`"

    Before the rebrand the key was `kanban`. If you have a skill, a prompt, or a `settings.json`
    allowlist that names tools by their old prefix, update it. A `kanban` server key in `.mcp.json` is
    still read for configuration purposes, but the tool namespace follows whatever key you actually
    use.

## Verify it

Restart your client so it picks up `.mcp.json`, approve the server when prompted, then run two tools.

**First `warmup`.** It pings the unauthenticated health endpoint and wakes a scaled-to-zero deploy, so
the cold start is paid once, up front, rather than inside your first real call.

**Then `list_boards`.** It returns the boards you can reach, each with an `id` and a `name`. Seeing
your board proves the token resolved to your user and authorization is working.

In Claude Code, just ask:

> Use the pandan tools to warm up the API and list my boards.

### If it does not work

| Symptom | Cause |
| --- | --- |
| Tools do not appear at all | The client has not reloaded, or `.mcp.json` is invalid JSON. Check for a trailing comma. |
| `401` | Token is missing, wrong, or revoked. Note that `.mcp.json.example` ships `PANDAN_TOKEN` empty. |
| `403` on one board | That board is not one you can reach. |
| `list_boards` returns nothing | On the hosted instance, log in to the web UI once so your first login claims a board. |
| Connection refused | Wrong origin. To reach a backend on your host from inside the container, use `host.docker.internal`, not `localhost`. |

!!! tip "Check the config the same way the CLI does"

    If you have the CLI installed in the same checkout, `pandan config show` reads the same
    `.mcp.json` and prints what resolved. That is the fastest way to confirm the values the MCP server
    will see.

## Recap

1. Copy `.mcp.json.example` to `.mcp.json` and keep one server entry.
2. Set the origin, paste your token, and set `PANDAN_BOARD_ID` to a board you own.
3. Restart the client, approve the server.
4. Run `warmup`, then `list_boards`.

Next: the [tool reference](mcp-tools.md), or the [workflows](workflows.md) worth handing an agent.
