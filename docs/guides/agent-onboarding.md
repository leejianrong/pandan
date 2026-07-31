# Agent onboarding guide

This guide gets a coding agent — Claude Code, or anything that speaks MCP — driving a
Pandan board end to end: minting a token, wiring the MCP server, verifying the
connection, and running real workflows. There's also a CLI path for CI and non-MCP agents.

If you just want the short version: log in to the [hosted board](https://simple-kanban-jian.fly.dev),
create a personal access token in the **Tokens** tab, drop it into `.mcp.json` alongside
the `uv` server entry from [`.mcp.json.example`](../../.mcp.json.example), and ask your
agent to "list my boards".

## Why this board is agent-friendly

Pandan is API-first by design (ADR [0005](../adr/0005-api-first-mcp-ready.md)):
every action the web UI can take is a plain REST call under `/api/v1`, and the UI is just
the first client rather than the only way in. The MCP server and the `pandan` CLI are both
thin adapters over that same surface — one tool (or subcommand) per endpoint — so an agent
gets full CRUD parity with a human, including epics, card dependencies, work-links, and
comments. There's no hidden capability locked behind the browser.

That parity is the whole point. You can hand a card to an agent, and it can read the card,
see what's blocking it, claim it, attach a PR link, comment, and move it to Done, all
through tool calls.

## 1. Get access

You have two options.

**Use the hosted instance.** The board is live at
[simple-kanban-jian.fly.dev](https://simple-kanban-jian.fly.dev). Log in with GitHub. Your
first login claims any unclaimed boards and gives you a session; from there you own your
boards and only you can see or change them. This is the fastest way to try things.

**Self-host your own.** If you want an instance your team controls — which today you need
for more than one person, see [Single-owner boards](#single-owner-boards-and-what-that-means-today)
below — run it yourself. See [Self-hosting](#self-hosting) at the end.

Either way, the rest of this guide is the same; only `PANDAN_API_URL` changes.

## 2. Mint a personal access token (PAT)

`/api/v1` is auth-required for every request (ADR [0013](../adr/0013-board-authorization.md)),
and agents authenticate with a per-user PAT (ADR [0014](../adr/0014-agent-personal-access-tokens.md)).
There is no shared service token — the old `API_TOKENS` mechanism was removed in
[V10](../adr/0015-mcp-board-scoping-and-retiring-api-tokens.md).

1. Log in to the board (hosted or your own).
2. Open the **Tokens** tab in the top bar.
3. Click **New token**, give it a name, and create it.
4. Copy the `pandan_pat_…` secret. It is shown **once** — the server only stores a hash, so
   if you lose it you revoke it and mint a new one.

A PAT authenticates **as you**. It is owner-gated exactly like your logged-in session: it
can only touch boards you own. A board id you don't own returns `403`; a bad or empty token
returns `401`. Revoke a token any time from the same Tokens tab.

## 3. Wire the MCP server into Claude Code

Claude Code discovers project-scoped MCP servers from a `.mcp.json` at the repo root. Copy
[`.mcp.json.example`](../../.mcp.json.example) to `.mcp.json` and keep the server entry you
want. Full details are in [`mcp/README.md`](https://github.com/leejianrong/simple-kanban/blob/main/mcp/README.md); the essentials follow.

### Run from source with `uv`

This needs a checkout of the repo and [`uv`](https://docs.astral.sh/uv/) installed. It runs
the server straight from `mcp/`, so there's nothing to download or build:

```json
{
  "mcpServers": {
    "pandan": {
      "command": "uv",
      "args": ["run", "--directory", "./mcp", "python", "-m", "pandan_mcp"],
      "env": {
        "PANDAN_API_URL": "https://simple-kanban-jian.fly.dev",
        "PANDAN_TOKEN": "pandan_pat_…",
        "PANDAN_BOARD_ID": "1"
      }
    }
  }
}
```

Three env vars carry the config:

- `PANDAN_API_URL` — the API origin. Use `https://simple-kanban-jian.fly.dev` for the hosted
  board, or `http://localhost:8000` for a local backend. The `/api/v1` prefix is added for you.
- `PANDAN_TOKEN` — your `pandan_pat_…` from step 2. Required; empty or bad → `401`.
- `PANDAN_BOARD_ID` — the default board (an integer id) for calls that omit `board_id`. **Set
  this.** If you leave it empty, `list_*` tools span *all* your boards and `create_*` tools land
  on your *earliest* board, which is an easy way to write to the wrong place. The example presets
  it to `1` (the seeded default board) — run `list_boards` once and change it to your real id.

> **Migrating from the old names?** The pre-rebrand `KANBAN_API_URL` / `KANBAN_TOKEN` /
> `KANBAN_BOARD_ID` still work, per key, as a **deprecated fallback** — read after the `PANDAN_*`
> spelling, with a one-line notice on stderr — so an existing `.mcp.json` or CI job keeps working while
> you switch over. Same for a `kanban_pat_…` token, an old `kanban` server key in `.mcp.json`, and a
> `~/.config/kan/config.toml` (migrated to `~/.config/pandan/` on first use). All of it is scheduled
> for removal, so move to the `PANDAN_*` names when convenient.

> The hosted origin is still `simple-kanban-jian.fly.dev`. That is deliberate — the Fly app rename is
> deferred behind the k8s migration (ADR 0018, KAN-424), so the URL keeps the retired name while
> everything else says *pandan*.

`--directory ./mcp` is relative to where Claude Code launches the server (the repo root); use
an absolute path if you run the client from elsewhere.

### Run the prebuilt ghcr.io image

`.mcp.json.example` also ships a `pandan-docker` entry that runs a prebuilt image with no
Python, no `uv`, and no checkout:

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
        "ghcr.io/leejianrong/simple-kanban-mcp:latest"
      ],
      "env": {
        "PANDAN_API_URL": "https://simple-kanban-jian.fly.dev",
        "PANDAN_TOKEN": "pandan_pat_…",
        "PANDAN_BOARD_ID": "1"
      }
    }
  }
}
```

The image is **public**, so `docker pull ghcr.io/leejianrong/simple-kanban-mcp:latest` works
with no `docker login` and no GitHub account. Tags track the release — `latest`, plus the
semver `0.2.2`, `0.2`, and `0`; pin `:0.2.2` for a fixed version. The `-e NAME` flags with no
`=value` forward values from the `env` block into the container, keeping the token out of the
argument list.

## 4. Verify it works

Restart Claude Code so it picks up `.mcp.json`, approve the `pandan` server when prompted, then
ask the agent to run two tools:

1. **`warmup`** — pings the unauthenticated health endpoint and wakes a scaled-to-zero Fly + Neon
   deploy. The first request after idle is slow (a documented ~1s cold start), so this pays that
   cost up front. A healthy response reports the API is up.
2. **`list_boards`** — returns the boards you own, each with an `id` and `name`. Seeing your board
   here confirms the token resolved to your user and auth is working.

If `list_boards` comes back empty on the hosted instance, log in to the web UI once first so your
first login claims a board. If it returns `401`, the token is wrong or unset; `403` on a specific
board means that board isn't yours.

## 5. Example agent workflows

These use the real MCP tool names (see the full table in [`mcp/README.md`](https://github.com/leejianrong/simple-kanban/blob/main/mcp/README.md)).
Card columns are `todo`, `in_progress`, and `done`.

> Your agent sees each tool **namespaced by the `mcpServers` key** you chose above, so with the
> recommended `pandan` key `list_cards` is really `mcp__pandan__list_cards`. Before the V40 rebrand
> ([ADR 0018](../adr/0018-pandan-rebrand.md)) that prefix was `mcp__kanban__`; if you have a skill,
> prompt or `settings.json` allowlist naming the old prefix, update it.

**Pick up a card and start work.**

```
list_cards(column="todo")          # find something to do
claim_card(card_id, assignee="claude")   # assigns it and moves it to in_progress
add_comment(card_id, body="Starting on this — will open a PR shortly.")
```

**Record a blocker, then a fix.**

```
add_dependency(card_id, blocker_id)   # this card is now blocked by another
list_dependencies(card_id)            # see blocked_by / blocks
add_link(card_id, label="PR #57", url="https://github.com/leejianrong/simple-kanban/pull/57")
add_comment(card_id, body="Fix is up in PR #57, waiting on review.")
```

**Finish and close out.**

```
remove_dependency(card_id, blocker_id)   # blocker cleared
move_card(card_id, column="done")
```

**Plan a chunk of work.** Create an epic and hang stories off it:

```
create_epic(name="Onboarding flow", description="New-user first-run experience")
create_card(title="Landing page", column="todo", epic_id=<epic id>)
create_card(title="GitHub login button", column="todo", epic_id=<epic id>)
```

## 6. CLI path (for CI and non-MCP agents)

If your automation isn't an MCP client — a CI job, a shell script, an agent that shells out —
use the `pandan` CLI. It's the same thin adapter over `/api/v1`, exposed as subcommands. Full
reference: [`pandan-cli/README.md`](https://github.com/leejianrong/simple-kanban/blob/main/pandan-cli/README.md).

**Prebuilt binary (no Python needed).** Download the asset for your platform from the
[latest GitHub Release](https://github.com/leejianrong/simple-kanban/releases/latest) — the
`releases/latest/download/…` URL always resolves to the newest one:

```bash
curl -L -o pandan https://github.com/leejianrong/simple-kanban/releases/latest/download/pandan-linux-x86_64
chmod +x pandan && mv pandan ~/.local/bin/      # or: sudo mv pandan /usr/local/bin/
```

Only `pandan-linux-x86_64` and `pandan-macos-arm64` ship (no Intel-mac binary — that leg was dropped,
KAN-225); the linux binary needs glibc ≥ 2.28 (Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+).
**Intel-Mac users** run the `pandan-macos-arm64` binary under Rosetta 2, install from source with
`uv` (below), or use the MCP container image. See
[`pandan-cli/README.md`](https://github.com/leejianrong/simple-kanban/blob/main/pandan-cli/README.md) for the full asset list and the macOS
Gatekeeper note.

**Install from git (needs Python + `uv`):**

```bash
uv tool install "git+https://github.com/leejianrong/simple-kanban.git#subdirectory=pandan-cli"
```

`uv` clones the repo and resolves the sibling `pandan-client` path dependency from the same
checkout, so `pandan` lands on your `PATH` with no manual clone.

It reads the same env vars as the MCP server:

```bash
export PANDAN_API_URL=https://simple-kanban-jian.fly.dev
export PANDAN_TOKEN=pandan_pat_…
export PANDAN_BOARD_ID=1        # optional default board
```

**A CI pre-step.** `pandan warmup` pings the health endpoint and needs no token, so it's the ideal
first step to wake the deploy before a batch of authenticated calls. It exits `0` once the API is
awake and `1` while it's still waking, so loop on it:

```bash
until pandan warmup; do sleep 2; done   # block until the API is awake
pandan list --column todo               # now the real work
```

The CLI uses distinct exit codes for scripting — `3` for `401`, `4` for `403`, `5` for `404`
(including a `KAN-`/`EPIC-` ticket that matches nothing) — so a job can react to auth versus
not-found without parsing text. And when it does fail, the failure is **machine-readable on
stdout**: one `error<TAB>code<TAB>message<TAB>arg` row, or a `{"error": {…}}` object with
`--json`, so `jq -r .error.code` is enough to branch. Nothing needs stderr, and no verb ever
prompts when stdin isn't a terminal. Full code table:
[`pandan-cli/README.md`](https://github.com/leejianrong/simple-kanban/blob/main/pandan-cli/README.md).

## Self-hosting

You self-host when you want an instance your team owns. It's the same single artifact as the
hosted board, so nothing here duplicates the ops docs — this is just the map.

**Locally**, from the repo root:

```bash
docker compose up -d db     # Postgres 17
# then the backend + frontend per the root README's Quick start
```

`docker-compose.yml` also defines the full app if you want it containerised. For a deployed
instance, [`fly.toml`](../../fly.toml) and the root [`Dockerfile`](../../Dockerfile) build and
run the single artifact on Fly.io with a Neon Postgres — the same setup behind the hosted board.
The [Developer Workflows playbook](../DEVELOPER-WORKFLOWS.md) covers the CI/CD and deploy machinery
in depth.

To enable GitHub login on your own instance, set `GITHUB_OAUTH_CLIENT_ID` and
`GITHUB_OAUTH_CLIENT_SECRET` (both unset → the board still boots, but login is unavailable). See
the Configuration section of [`CLAUDE.md`](https://github.com/leejianrong/simple-kanban/blob/main/CLAUDE.md) for the full env-var list, including
`AUTH_SECRET` and `COOKIE_SECURE`.

## Single-owner boards, and what that means today

Every board has exactly one owner. `/api/v1` is auth-required and owner-gated: a session or a PAT
resolves to a user, and that user can only see and change boards they own. **There is no board
sharing yet** — you can't invite a teammate onto your board, and an agent's PAT can never reach
boards owned by someone else. That's a deliberate current limit, with real collaboration left to a
future milestone.

So for more than one person or team right now, the honest answer is: each person uses their own
boards, or each team self-hosts its own instance. Point your agents at a board you own, and set
`PANDAN_BOARD_ID` so they stay on it.
