<!--
title: "Set up the MCP server"
description: Connect to Pandan's hosted remote MCP server with a URL and OAuth, or self-host it with the container image or a source checkout.
-->

# Set up the MCP server

The MCP server is a thin adapter over the REST API. It holds no database and no state of its own.

Two transports reach it. The **hosted server** is an always-on Streamable HTTP endpoint on Pandan's own
backend — any spec-compliant remote-MCP client adds it with a URL, no local process and no token to
copy by hand. The **stdio server** is a local subprocess a client like Claude Code launches from
`.mcp.json`, configured with a `PANDAN_TOKEN` env var. Prefer the hosted server; reach for stdio only if
your client can't do remote MCP, or you're self-hosting Pandan and want no dependency on
`simple-kanban-jian.fly.dev`.

## Connect the hosted server

Works with Claude.ai, Claude Desktop, Claude Code, ChatGPT, Cursor, or anything else that speaks
Streamable HTTP with OAuth. Add a remote server pointing at:

```
https://simple-kanban-jian.fly.dev/mcp
```

(or `<your-origin>/mcp` on a self-hosted instance). There is no config file and nothing to install.
Your client takes it from there:

1. It fetches the discovery document at `/.well-known/oauth-protected-resource/mcp` (RFC 9728) to learn
   which authorization server protects the endpoint — Pandan itself.
2. It self-registers a client identity (RFC 7591 Dynamic Client Registration), rather than sharing one
   pre-registered client with every other app that connects.
3. It opens your browser to Pandan's consent screen. Approve it.
4. It receives a token scoped to **this one connected app** (RFC 8707 resource binding — the token is
   bound to the `/mcp` endpoint and cannot be replayed elsewhere), distinct from any PAT you've minted
   for the CLI. It's listed and revocable at the board's Tokens tab like any other token, labelled with
   the connecting app's name.

!!! warning "No default board — and no session board on the hosted path"

    There is no default board anywhere any more. On the stdio server you can call `use_board` once and
    the session remembers it. The hosted server cannot: it is one process serving every caller, so
    there is nowhere safe to keep a per-user pick, and `use_board` refuses there. Pass an explicit
    `board_id` on every board-scoped call — a call without one fails rather than spanning every board
    or landing on your earliest. Call `list_boards` first and pass its id back on the calls that follow.

Verify with the same two calls as the stdio path below: `warmup`, then `list_boards`.

## Or self-host it: stdio

Two ways to run the stdio server yourself, neither needing a browser or an OAuth round trip — just a
`PANDAN_TOKEN` you mint once at the Tokens tab and paste into config.

Claude Code discovers project-scoped stdio servers from a `.mcp.json` at the root of your repository.
Other MCP clients use their own config file, but the server entry is the same shape.

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
            "ghcr.io/leejianrong/pandan-mcp:latest"
          ],
          "env": {
            "PANDAN_API_URL": "https://simple-kanban-jian.fly.dev",
            "PANDAN_TOKEN": "pandan_pat_…"
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
            "PANDAN_TOKEN": "pandan_pat_…"
          }
        }
      }
    }
    ```

    `--directory ./mcp` is relative to wherever the client launches the server, which for Claude Code
    is your repository root. Use an absolute path if you launch from elsewhere.

The repository ships a [`.mcp.json.example`](https://github.com/leejianrong/pandan/blob/main/.mcp.json.example)
with both entries. Copy it, keep one, delete the other.

## The two settings

| Variable | What it does |
| --- | --- |
| `PANDAN_API_URL` | The API origin. `https://simple-kanban-jian.fly.dev` for the hosted board, or your own. The `/api/v1` prefix is added for you. |
| `PANDAN_TOKEN` | Your `pandan_pat_…` token. Required. Empty or wrong gives `401`. |

!!! note "There is no default board"

    `PANDAN_BOARD_ID` is retired — a leftover one is ignored with a one-line notice on stderr. A
    default is how an agent files a card onto the wrong board, so board-scoped tools now need a
    `board_id`, or one `use_board` call per session. Run `list_boards`, pick an id, call `use_board`.

## The server key names your tools

Whatever you call the server in `mcpServers` becomes the namespace for every tool. With the key
`pandan`, `list_cards` is really `mcp__pandan__list_cards`.

!!! info "It used to be `mcp__kanban__`"

    Before the rebrand the key was `kanban`. If you have a skill, a prompt, or a `settings.json`
    allowlist that names tools by their old prefix, update it. A `kanban` server key in `.mcp.json` is
    still read for configuration purposes, but the tool namespace follows whatever key you actually
    use.

## Verify it

For the stdio setup above: restart your client so it picks up `.mcp.json`, approve the server when
prompted, then run two tools. (For the hosted server, this is the same pair, run right after you
approve the consent screen — see [above](#connect-the-hosted-server).)

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

**Hosted (do this unless you have a reason not to):**

1. Add `https://simple-kanban-jian.fly.dev/mcp` as a remote server in your client.
2. Approve the browser consent prompt.
3. Run `warmup`, then `list_boards` — pass `board_id` on every call after that (the hosted server has no `use_board`).

**Stdio (self-hosting, or a client with no remote-MCP support):**

1. Copy `.mcp.json.example` to `.mcp.json` and keep one server entry.
2. Set the origin and paste your token.
3. Restart the client, approve the server.
4. Run `warmup`, then `list_boards`, then `use_board` with the board you want.

Next: the [tool reference](mcp-tools.md), or the [workflows](workflows.md) worth handing an agent.
