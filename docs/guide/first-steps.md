<!--
title: "First steps"
description: Point the CLI at a board, mint a personal access token, pick a default board, and read your first card.
-->

# First steps

You have the CLI installed. Now you need three things: an origin to talk to, a token to talk with, and
a board to talk about.

By the end of this page `pandan overview` will print your board.

## Get access to a board

You have two options.

**Use the hosted board.** It runs at [simple-kanban-jian.fly.dev](https://simple-kanban-jian.fly.dev).
Log in with GitHub. Your first login gives you a session and claims any unclaimed board, so you own a
board straight away. This is the fastest way to try things.

**Run your own.** See [self-hosting](self-hosting/index.md). Everything on this page is identical
apart from the origin you point at.

## Point the CLI at the board

Do this first, before anything else.

```bash
pandan config set --api-url https://simple-kanban-jian.fly.dev
```

!!! warning "The CLI defaults to localhost"

    With no configuration the CLI targets `http://localhost:8000`, because that is where a
    development backend runs. If you skip this step, every command fails against a server that
    isn't there, and `warmup` says so:

    ```console
    $ pandan warmup
    unreachable	http://localhost:8000	nothing is listening at http://localhost:8000
    (ConnectError: [Errno 111] Connection refused). This is not a cold start — check the
    origin. Nothing set PANDAN_API_URL, so that is only the built-in local-dev default: on
    a fresh install this is the bug. Point it at your board with `pandan config set
    --api-url https://<your-host>`.
    $ echo $?
    7
    ```

    `unreachable` is not `waking`. Waiting will not fix it, and exit `7` says exactly that — see
    [errors and exit codes](cli/errors-and-exit-codes.md).

Now wake the API:

```console
$ pandan warmup
ok	https://simple-kanban-jian.fly.dev	API is awake
```

The hosted board runs on infrastructure that scales to zero, so the first request after an idle
period takes about a second. `warmup` pays that cost up front and needs no token, which makes it a
good first step in a CI job.

## Mint a personal access token

Every `/api/v1` request needs authentication. The CLI and the MCP server both use a personal access
token, and you create one in the web UI.

1. Log in to the board.
2. Open the **Tokens** tab in the top bar.
3. Click **New token**, name it after the machine or agent that will use it (`laptop-wsl`,
   `ci-runner`, `claude-code`), and create it.
4. Copy the `pandan_pat_…` secret.

!!! danger "The secret is shown once"

    The server stores only an HMAC hash of the token, so it cannot show it to you again. Lose it and
    you revoke it and mint another. Revoking is instant, from the same Tokens tab.

A token authenticates **as you**. It reaches exactly the boards you can reach and nothing else. A
board you have no access to returns `403`, and a bad or missing token returns `401`.

## Save the token

Pipe it in. Never type it as an argument.

```bash
printf %s 'pandan_pat_…' | pandan login --token-stdin
```

Or let `pandan login` prompt you, which keeps it out of your shell history too:

```console
$ pandan login
Token: 
saved to /home/you/.config/pandan/config.toml
```

The config file is written with `600` permissions, so only your user can read it.

!!! tip "One command for the whole setup"

    `login` also takes the other two settings, so a fresh machine needs a single command:

    ```bash
    printf %s 'pandan_pat_…' | pandan login --token-stdin \
      --api-url https://simple-kanban-jian.fly.dev \
      --board-id 5
    ```

### Where configuration comes from

Three sources, checked in order, first non-empty value wins. This is resolved **per value**, so you
can keep the token in a file and override the board id with an environment variable.

| Order | Source | Notes |
| --- | --- | --- |
| 1 | `PANDAN_API_URL`, `PANDAN_TOKEN`, `PANDAN_BOARD_ID` | Environment. Good for CI. |
| 2 | `~/.config/pandan/config.toml` | Written by `pandan login` and `pandan config set`. |
| 3 | `.mcp.json` | Nearest one up the directory tree, read from `.mcpServers.pandan.env`. Lets a repository checkout share one setting with your agent. |

Check what actually resolved, with the token redacted:

```console
$ pandan config show
api_url	https://simple-kanban-jian.fly.dev
token	set (…c_DE)
board_id	5
max_text_chars	500
config_file	/home/you/.config/pandan/config.toml
mcp_json	None
```

## Check the token

One call, no board needed:

```console
$ pandan me
2b1c7f0e-…-9a41	you@example.com
```

Your user id and your email. If the token is missing, mistyped, or revoked you get an error row and
exit `3` instead. Nothing else can go wrong here — there is no board involved, so a `4` (forbidden)
is not reachable, which is what makes `me` the clean answer to "did my token work?".

## Pick a default board

Now list what you can reach.

```console
$ pandan board list
5	Pandan Roadmap
6	Engine Room
7	sibei-flow
4 boards
```

The first column is the board id. Save the one you work in:

```bash
pandan config set --board-id 5
```

!!! warning "Set a default board"

    Without `board_id`, list commands span **every** board you can reach and `create` lands on the
    earliest one. That is an easy way to file a card onto the wrong board without noticing.

If `board list` prints nothing on the hosted instance, log in to the web UI once so your first login
claims a board. If it fails, the exit code tells you what went wrong:

| Output | Exit | Cause |
| --- | --- | --- |
| `error	unauthorized	…` | `3` | Token missing, wrong, or revoked. |
| `error	forbidden	…` | `4` | Valid token, but no access to that board. |
| `waking	server not ready yet` | `1` | Origin unset or unreachable. Check `pandan config show`. |

## Read the board

```console
$ pandan overview
https://simple-kanban-jian.fly.dev · board 5 · open cards (todo, in_progress):
KAN-591	todo	pandan overview builds a list envelope in-handler	pts=2
KAN-595	todo	Bake the git revision into the app image	pts=2
KAN-596	todo	ci.yml declares an 'app' paths-filter output that nothing consumes	pts=1
help: pandan list --column todo
help: pandan next --claim
8 cards · 8 todo · 0 in_progress · 0 done · 1 needs-human
```

That is the whole setup. Two useful things to notice in the output.

The `help:` lines are suggestions for what to run next. Every command emits them, which means an
agent can find its way around without being handed a manual.

The last line is a pre-computed summary, so counting cards never costs a second request. It always
describes the rows that were **returned**, so under a filter or a `--limit` it counts those, not the
whole board.

## Write something

Create a card, then move it:

```console
$ pandan create "Try out the CLI" --column todo
KAN-601	todo	Try out the CLI	pts=-

$ pandan move KAN-601 in_progress
KAN-601	in_progress	Try out the CLI	pts=-
```

Commands take a ticket number (`KAN-601`) or a numeric id. A ticket number that matches nothing exits
`5`.

Clean up:

```bash
pandan delete KAN-601
```

## Recap

```bash
# 1. point at a board (do this first, the default is localhost)
pandan config set --api-url https://simple-kanban-jian.fly.dev

# 2. wake it
pandan warmup

# 3. save the PAT you minted in the Tokens tab
printf %s 'pandan_pat_…' | pandan login --token-stdin

# 4. find your board and make it the default
pandan board list
pandan config set --board-id 5

# 5. read it
pandan overview
```

From here:

- [Using the CLI](cli/index.md) for querying, writing, output formats, and CI.
- [Agents and MCP](agents/index.md) to give an agent the same access.
- [The user guide](tutorial/index.md) for the browser.
