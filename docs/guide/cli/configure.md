<!--
title: "Configuration"
description: How the CLI resolves its settings, picks a board for the session, how to save a token safely, and how to give an agent session ambient board context.
-->

# Configuration

The CLI needs two values: an API origin and a token. It has **no default board** — you name the board
you mean, once per session (see [Picking a board](#picking-a-board)).

## Where settings come from

Three sources, checked in this order, first non-empty value wins:

1. Environment variables: `PANDAN_API_URL`, `PANDAN_TOKEN`
2. The config file: `~/.config/pandan/config.toml`
3. The nearest `.mcp.json` up the directory tree, from `.mcpServers.pandan.env`

Resolution is **per value**, not per source. So you can keep a token in the config file and override
just the origin for one command:

```bash
PANDAN_API_URL=http://localhost:8000 pandan list --board 7 --column todo
```

That third source is convenient in a repository checkout: the `.mcp.json` you wrote for your agent
already carries the origin and token, so the CLI picks them up with no extra setup.

!!! tip "Most commands also take `--board`"

    You rarely need an environment variable to target another board. `pandan list --board 7` and
    `pandan create "…" --board 7` work directly.

## Saving a token

```bash
pandan login
```

It prompts, reads the token without echoing it, and writes `~/.config/pandan/config.toml` with `600`
permissions.

To script it, pipe the token in:

```bash
printf %s 'pandan_pat_…' | pandan login --token-stdin
```

`login` can save the origin and token together, which is the fastest way to set up a new machine:

```bash
printf %s 'pandan_pat_…' | pandan login --token-stdin \
  --api-url https://simple-kanban-jian.fly.dev
```

!!! danger "Do not pass a token as an argument"

    `pandan config set --token …` exists and works, but the token lands in your shell history and in
    the process list where any other user on the machine can read it. Use `login`, or
    `config set --token-stdin`.

## Inspecting and editing config

```console
$ pandan config show
api_url	https://simple-kanban-jian.fly.dev
token	set (…c_DE)
max_text_chars	500
pinned_board	5
config_file	/home/you/.config/pandan/config.toml
mcp_json	None
```

`config show` prints what actually resolved, from wherever it came, with the token reduced to its last
four characters. When a command behaves unexpectedly, start here.

## Checking that the token works

`config show` reports what this machine resolved. Only a round trip can tell you whether the server
accepts it, and whose it is:

```console
$ pandan me
2b1c7f0e-…-9a41	you@example.com
```

Two columns: your user id and your email. Nothing else — the endpoint behind it
(`GET /api/v1/me`) is deliberately minimal, and it is the one API route with no board involved.

That makes the exit code the useful half. `me` either identifies you or fails with `3`:

| Output | Exit | Meaning |
| --- | --- | --- |
| `<id>	<email>` | `0` | The token is valid, and that is who it belongs to. |
| `error	unauthorized	…` | `3` | The token is missing, mistyped, or revoked. |

There is no `4` here, because there is no board to be denied access to. That is the difference from
`board list`, the older way of testing a token: a `4` from `board list` means the token was fine and
the *board* was not, and a `0` from it never tells you which account you are on — which matters when
you keep more than one PAT around.

```bash
pandan config path                                    # just the file path
pandan config set --api-url https://board.example.com # write one value
pandan config unset api_url                           # clear one value
```

`config unset` takes one or more keys — `api_url`, `token`, `max_text_chars`, plus the retired
`board_id` and `require_board` so a leftover one can be cleaned out of the file — and tells you per key whether it removed something or the key was never set. That
distinction matters: the config file is only the middle source, so clearing a key there can simply
unmask an environment variable or `.mcp.json` entry. When that happens, `config unset` says so on
stderr rather than reporting success while nothing changed.

The file is plain TOML and you can edit it by hand:

```toml
[pandan]
api_url = "https://simple-kanban-jian.fly.dev"
token = "pandan_pat_…"
```

Prefer `config set` and `config unset` to hand-editing, though — the file holds your PAT, so every
hand-edit is a text editor open on a live credential.

## Picking a board

There is no default board. A board-scoped command (`list`, `create`, `next`, `metrics`, `activity`,
`epic list/create`, `label list/create`, `batch-create`, and the `view`, `cycle`, `pi` and `template`
verbs) with no `--board` and no pin fails, and tells you which boards it could have meant:

```console
$ pandan list
error	board_required	no board selected — there is no default board. Pass --board <id>, or pin one for this session with `pandan board use <id|KEY>`. Your boards: 5 PAN 'Pandan Roadmap'; 6 ENG 'Engine Room'.	--board
```

A default is a sharp edge once you have several boards: a stale one makes a read give a confusing
answer, and makes `create` file a card on the wrong board with nothing in the output to say so. So name
the board, either per call or once per session:

```bash
pandan list --board 5          # per call; always wins
pandan board use ENG           # pin it: a board id or key
pandan list                    # now uses the pinned board
pandan board current           # which board is pinned here?
pandan board use --clear       # forget it
```

The pin is a small state file under `$XDG_STATE_HOME/pandan/pins/` (`~/.local/state/pandan/pins/`),
kept **per working directory** — a `cd` into a subdirectory keeps it — and per server, so a pin made
against one instance is ignored against another. It **expires after 12 hours idle**; every command that
uses it pushes the expiry out. That is deliberate: it is meant to last a working session, not to become
the stale default this replaced. `pandan overview` (a bare `pandan`) with no pin shows your boards
instead of a board's cards.

Looking a card up by ticket (`pandan get KAN-12`) needs no board, since `KAN-` numbers are unique across
every board, and neither does a canonical batch read (`pandan list --refs KAN-12,KAN-45`).

!!! note "Upgrading"

    `PANDAN_BOARD_ID`, the `board_id` config key and `require_board` are retired. A leftover one is
    ignored with a one-line notice on stderr rather than breaking the command; `pandan config unset
    board_id require_board` cleans the file. `pandan config set --board-id`, `pandan login --board-id`
    and `--require-board` are gone.

## Truncation limit

Long text fields are cut at 500 characters by default so one card cannot flood an agent's context.
Change the limit, or turn it off:

```bash
export PANDAN_MAX_TEXT_CHARS=2000   # a higher cap
export PANDAN_MAX_TEXT_CHARS=0      # no truncation at all
```

It can also live in the config file as `max_text_chars`. Either way, `--full` overrides it for a
single command. See [output formats](output-formats.md#truncation).

## Ambient context for agent sessions

`pandan context` installs a Claude Code `SessionStart` hook that drops the current board state into an
agent's context before it does anything. The agent starts out knowing what is in flight rather than
having to ask.

```bash
pandan context install     # add the hook to settings.json, idempotent
pandan context status      # is it installed?
pandan context show        # print what the hook would inject
pandan context uninstall   # remove it, and the skill if unmodified
```

The hook soft-fails within a few seconds, so a cold-starting API delays a session slightly at worst
and never blocks it.

## Older environment variable names

Pandan used to be called simple-kanban, and the old variable names still work:

| Current | Deprecated fallback |
| --- | --- |
| `PANDAN_API_URL` | `KANBAN_API_URL` |
| `PANDAN_TOKEN` | `KANBAN_TOKEN` |

Each key is read under its `PANDAN_*` name first, then the `KANBAN_*` one, and using the old spelling
prints a one-line notice on stderr. Because resolution is per value, a half-migrated environment still
works.

The same applies elsewhere: a `kanban_pat_…` token still authenticates, a `kanban` server key in
`.mcp.json` is still read, and a `~/.config/kan/config.toml` gets migrated to
`~/.config/pandan/config.toml` the first time you run a command.

!!! warning "All of it is scheduled for removal"

    These fallbacks are carried deliberately, not permanently. Move to the `PANDAN_*` names when it is
    convenient.

## Recap

```bash
# one-time setup on a new machine
printf %s 'pandan_pat_…' | pandan login --token-stdin \
  --api-url https://simple-kanban-jian.fly.dev

# check it
pandan config show
```

Settings resolve per value from the environment, then the config file, then `.mcp.json`. Keep the
token in the file, and override the board with `--board` when you need to reach elsewhere. `config
unset` clears a value without opening the file by hand, and `--require-board` makes `--board`
mandatory once you have enough boards for a stale default to be a hazard.
