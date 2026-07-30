# Pandan — `pandan` CLI

A command-line client for the Pandan REST API (`/api/v1`). Like the
[MCP server](../mcp/README.md), it is a thin adapter over the shared
[`pandan-client`](../pandan-client/) package — every subcommand maps to one API
call — so the API stays the single source of truth (API-first, ADR 0005).
Milestone 2 follow-on; card commands **KAN-22**, board + epic commands
**KAN-23**, packaging + this README + the CI job **KAN-24**.

> **New here?** The [Agent onboarding guide](../docs/guides/agent-onboarding.md)
> covers getting access, minting a token, and using this CLI in CI end to end.

It uses only the standard library's `argparse` (no `click`/`typer`) — consistent
with the repo's thin ethos.

> **`pandan` and `pdn` are the same command.** Both console scripts point at the same
> entry point, so `pdn list` ≡ `pandan list` — the short one exists so the rename off
> `kan` (V40, [ADR 0018](../docs/adr/0018-pandan-rebrand.md)) costs no keystrokes. Every
> example below uses `pandan` for clarity.

## Commands

Card verbs are top-level; boards, epics, labels, saved views and templates are
nested groups so their verbs don't collide with the card verbs (parity with the
`/api/v1` surface).

| Command | Endpoint |
|---------|----------|
| `pandan list [--board N] [--column C] [--epic ID] [--limit N] [--json]` | `GET /cards` (V3 query API) |
| `pandan get <card_id> [--json]` | `GET /cards/{id}` |
| `pandan activity [--board N] [--actor L] [--action V] [--limit N] [--cursor C] [--json]` | `GET /boards/{id}/activity` |
| `pandan create <title> [--board N] [--description D] [--column C] [--points N] [--assignee A] [--epic ID] [--json]` | `POST /cards` |
| `pandan update <card_id> [--title T] [--description D] [--points N] [--assignee A] [--epic ID] [--json]` | `PATCH /cards/{id}` |
| `pandan move <card_id> <column> [--position N] [--json]` | `POST /cards/{id}/move` |
| `pandan delete <card_id> --yes [--json]` | `DELETE /cards/{id}` |
| `pandan next [--board N] [--claim] [--assignee A] [--label ID] [--priority P] [--json]` | `GET /boards/{id}/next` (peek); with `--claim` → `POST /boards/{id}/dispatch` (atomic claim) |
| `pandan needs-human <card_id> [--note N] [--json]` | `POST /cards/{id}/needs-human` |
| `pandan resolve <card_id> [--json]` | `POST /cards/{id}/resolve` |
| `pandan batch-update <JSON \| -> [--json]` | `PATCH /cards/batch` (atomic multi-card edit) |
| `pandan metrics [--board N] [--since ISO] [--window SPAN] [--json]` | `GET /boards/{id}/metrics` |
| `pandan board list [--json]` | `GET /boards` |
| `pandan board create <name> [--json]` | `POST /boards` |
| `pandan epic list [--board N] [--json]` | `GET /epics` |
| `pandan epic create <name> [--board N] [--description D] [--json]` | `POST /epics` |
| `pandan epic update <epic_id> [--name N] [--description D] [--json]` | `PATCH /epics/{id}` |
| `pandan epic delete <epic_id> --yes [--json]` | `DELETE /epics/{id}` |
| `pandan label list [--board N] [--json]` | `GET /boards/{id}/labels` |
| `pandan label create <name> [color] [--color C] [--board N] [--json]` | `POST /boards/{id}/labels` |
| `pandan label delete <label_id> --yes [--json]` | `DELETE /labels/{id}` |
| `pandan view list [--board N] [--json]` | `GET /boards/{id}/views` |
| `pandan view create <name> [--board N] [--column C] [--epic ID] [--priority P] [--label ID] [--due-before ISO] [--overdue] [--needs-human] [--assignee A] [--sort SPEC] [--json]` | `POST /boards/{id}/views` |
| `pandan view delete <view_id> [--board N] --yes [--json]` | `DELETE /boards/{id}/views/{view_id}` |
| `pandan template list [--board N] [--json]` | `GET /boards/{id}/templates` |
| `pandan template create <name> --cards <JSON \| -> [--board N] [--json]` | `POST /boards/{id}/templates` |
| `pandan template delete <template_id> [--board N] --yes [--json]` | `DELETE /boards/{id}/templates/{template_id}` |
| `pandan template apply <template_id> [--board N] [--json]` | `POST /boards/{id}/templates/{template_id}/apply` |
| `pandan dep add <card_id> --blocked-by BLOCKER_ID [--json]` | `POST /cards/{id}/dependencies` |
| `pandan dep rm <card_id> --blocked-by BLOCKER_ID [--json]` | `DELETE /cards/{id}/dependencies/{blocker_id}` |
| `pandan dep list <card_id> [--json]` | `GET /cards/{id}` (its `blocked_by` / `blocks`) |
| `pandan link add <card_id> --url U --label L [--json]` | `POST /cards/{id}/links` |
| `pandan link rm <card_id> --link-id ID [--json]` | `DELETE /cards/{id}/links/{link_id}` |
| `pandan comment add <card_id> --body B [--json]` | `POST /cards/{id}/comments` |
| `pandan comment list <card_id> [--json]` | `GET /cards/{id}/comments` |
| `pandan warmup [--json]` | `GET /api/health` |
| `pandan --version` (or `-v`) | *(local — prints the CLI version, e.g. `pandan 0.4.0`, and exits)* |
| `pandan login [--api-url U] [--board-id N] [--token-stdin]` | *(local — saves the PAT to the config file)* |
| `pandan config set [--api-url U] [--board-id N] [--token-stdin \| --token T]` | *(local — writes the config file)* |
| `pandan config show [--json]` | *(local — prints the effective config, token redacted)* |
| `pandan config path` | *(local — prints the config file path)* |

Valid columns are `todo`, `in_progress`, `done`. `delete` requires `--yes` as a
guard against accidental destruction.

**Ids accept tickets.** Anywhere a card or epic id is taken (`get`/`update`/`move`/
`delete`, `--epic`, `dep --blocked-by`, `epic update`/`delete`, …) you can pass the
`KAN-<n>` / `EPIC-<n>` **ticket** the CLI itself prints (case-insensitive) instead of
the numeric DB id — the CLI resolves it to the id for you via a lookup. Bare integers
still work unchanged. (Label ids are numeric only — labels have no ticket number.)

`pandan warmup` pings the public health endpoint to wake a scaled-to-zero Fly + Neon
deploy (the first request after idle is slow — a documented cold start), riding it
out via the shared client's cold-start retry/timeout. Handy as a **CI pre-step**
before a batch of `pandan` calls so the wake cost is paid once. It needs **no
`PANDAN_TOKEN`** (health is unauthenticated) and exits `0` once the API is awake,
`1` while it's still waking or on error — so a CI step can loop until it succeeds:

```bash
until pandan warmup; do sleep 2; done   # block until the API is awake
```

Every command takes `--json` to print the API's raw response (for piping, e.g.
`pandan list --json | jq`); without it you get a concise tab-separated summary
(`ticket  column  title  pts=N` for cards — `pts=-` when unestimated, reading the
API's `story_points`; `ticket  name` for epics, `id  name` for boards) suitable for
`grep`/`cut`.

Run `pandan --help`, `pandan <command> --help`, `pandan board --help`, or
`pandan epic --help` for the full option list. `pandan --version` (or `-v`) prints the
CLI version (e.g. `pandan 0.4.0`) and exits.

### Exit codes (for scripting)

| Code | Meaning |
|------|---------|
| `0` | success |
| `1` | general / config / non-mapped API error |
| `2` | usage error (argparse convention) |
| `3` | `401` unauthorized (bad/missing token) |
| `4` | `403` forbidden (board isn't yours) |
| `5` | `404` not found |

## Configuration

The three settings below are each resolved **independently**, first non-empty
source wins:

1. **Environment** — `PANDAN_API_URL` / `PANDAN_TOKEN` / `PANDAN_BOARD_ID`.
2. **Config file** — `~/.config/pandan/config.toml` (`$XDG_CONFIG_HOME` aware; mode
   `0600`), a `[pandan]` table with `api_url` / `token` / `board_id`. Write it with
   `pandan login` or `pandan config set`.
3. **`.mcp.json`** — the nearest one walking up from the current directory, read
   from `.mcpServers.pandan.env.{PANDAN_API_URL,PANDAN_TOKEN,PANDAN_BOARD_ID}`.
   This is Claude Code's convention — the PAT already lives there for the MCP
   server, so the CLI reuses it with no extra setup.

| Setting | Env var | Default | Meaning |
|---------|---------|---------|---------|
| API origin | `PANDAN_API_URL` | `http://localhost:8000` | The `/api/v1` prefix is added for you |
| Token | `PANDAN_TOKEN` | *(unset)* | **Required.** A per-user **PAT** (`pandan_pat_…`, from the SPA top-bar **Tokens** tab, V9/ADR 0014). Unresolved from every source → a clean error before any request |
| Default board | `PANDAN_BOARD_ID` | *(unset)* | Optional default for board-scoped commands (`list`/`create`, `epic list`/`epic create`) when they omit `--board`. Unset → the API's fallback (list = all your boards; create = your earliest) |

> **Deprecated fallback (V40, [ADR 0018](../docs/adr/0018-pandan-rebrand.md)).** The pre-rebrand
> `KANBAN_API_URL` / `KANBAN_TOKEN` / `KANBAN_BOARD_ID` still resolve — each key is read under its
> `PANDAN_*` name **first**, falling back to the `KANBAN_*` spelling with a one-line notice on
> **stderr** (stdout stays clean so `--json | jq` never breaks). Precedence is per *value*, so a
> half-migrated environment works. A pre-rebrand `~/.config/kan/config.toml` is copied to
> `~/.config/pandan/config.toml` on first use (the old file is left in place), a legacy `[kan]` table
> is still read, and `.mcp.json`'s old `kanban` server key is still honoured. All of this is scheduled
> for removal once nothing reads it. A `kanban_pat_…` PAT also keeps authenticating indefinitely.

> **Keep the PAT off the command line.** The token is a credential — the config
> file and `.mcp.json` sources exist so it never has to be typed into a shell (where
> it lands in history, process listings, and — for an agent — the model's context).
> Prefer `pandan login` (a hidden prompt, or `--token-stdin` to pipe it) over exporting
> `PANDAN_TOKEN=…`; the file it writes is `chmod 600`. `pandan config show` prints the
> effective config with the token **redacted**. In a Claude Code repo the token is
> already in `.mcp.json`, so `pandan` just works with no configuration at all.

**Authentication — a personal access token is required.** Since M3 V8 (ADR 0013)
the whole `/api/v1` surface is auth-required, and V10 (ADR 0015) removed the old
shared-`API_TOKENS` bypass. Create a **PAT** in the SPA (top-bar **Tokens** →
*New token*), copy the `pandan_pat_…` secret shown once, and hand it to `pandan login`
(or set `PANDAN_TOKEN`). It authenticates **as your user** and is **owner-gated** —
the CLI can only touch boards you own. A `board_id` you don't own returns exit `4`
(`403`); a bad/missing token returns exit `3` (`401`).

## Install

The CLI installs two ways: **from source with `uv`**, or as a **prebuilt standalone
binary** (no Python needed). Both work today — pick whichever fits.

### From source (uv)

The CLI depends on the sibling `pandan-client` package by **path**
(`../pandan-client`, see `[tool.uv.sources]` in `pyproject.toml`), which shapes
the realistic source-install options.

**From a checkout (supported):**

```bash
git clone https://github.com/leejianrong/simple-kanban.git
cd simple-kanban
uv tool install ./pandan-cli        # installs `pandan` (and `pdn`) on your PATH
```

`uv tool install` resolves the `../pandan-client` path source relative to the
checkout, so this works cleanly. Uninstall with `uv tool uninstall pandan-cli`.

**From git directly (supported):**

```bash
uv tool install "git+https://github.com/leejianrong/simple-kanban.git#subdirectory=pandan-cli"
```

`uv` clones the repo and resolves the sibling `../pandan-client` path source from
the **same** git checkout, so this installs `pandan` without a manual clone
(verified). Uninstall the same way (`uv tool uninstall pandan-cli`).

**During development**, skip the install and run from `pandan-cli/`:

```bash
cd pandan-cli
uv sync                              # install deps (incl. the dev group)
uv run pandan --help                    # run without installing
```

### Prebuilt standalone binary (KAN-46)

Each version ships a single self-contained executable — no Python needed (built with
PyInstaller `--onefile`, which freezes the interpreter + `pandan_cli` + the bundled
`pandan-client` + `httpx` into one file). The latest release is **v0.4.0**. Grab the
asset for your OS/arch, mark it executable, and put it on your `PATH`.

The `releases/latest/download/…` URL always resolves to the newest release's asset,
so it needs no editing per version:

```bash
# Linux x86_64 — no sudo; installs to ~/.local/bin (make sure that's on your PATH)
curl -L -o pandan https://github.com/leejianrong/simple-kanban/releases/latest/download/pandan-linux-x86_64
chmod +x pandan
mv pandan ~/.local/bin/               # or: sudo mv pandan /usr/local/bin/ for system-wide
pandan --help
```

On macOS (Apple Silicon), swap the asset for `pandan-macos-arm64`. If you have the
GitHub CLI, `gh release download` pulls a pinned version instead:

```bash
gh release download v0.4.0 --pattern pandan-linux-x86_64
```

Only two binaries ship: **`pandan-linux-x86_64`** and **`pandan-macos-arm64`** — browse them on the
[latest GitHub Release](https://github.com/leejianrong/simple-kanban/releases/latest). There is
**no Intel-mac (`pandan-macos-x86_64`) binary**: PyInstaller can't cross-compile so it must build on
a native Intel runner, and GitHub's free Intel `macos-13` runners are scarce, so that leg was
dropped (KAN-225). **Intel-Mac users** have three options: run the `pandan-macos-arm64` binary under
**Rosetta 2**, install **from source with `uv`** (see above), or use the **MCP container image**.
Windows isn't built either. On macOS, Gatekeeper may quarantine an unsigned download — clear
it with `xattr -d com.apple.quarantine pandan` if it refuses to run. The binary reads the
same env vars as the source install.

**Linux glibc floor (`pandan-linux-x86_64`):** the linux binary is built in a
glibc-2.28 environment (`manylinux_2_28`), so it needs **glibc ≥ 2.28** — it runs
on **Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+** and anything newer. On an
older distro you'll see `GLIBC_2.xx not found` when it loads; install **from
source (uv)** above instead (KAN-81).

## Usage examples

```bash
# One-time: save the PAT to ~/.config/pandan/config.toml without it touching argv/history.
# (Skip this entirely in a Claude Code repo — pandan reads the token from .mcp.json.)
pandan login --api-url http://localhost:8000 --board-id 1   # prompts for the token (hidden)
#   …or pipe it:  printf '%s' "$PAT" | pandan login --token-stdin
pandan config show                       # confirm the effective config (token redacted)

pandan board list                        # discover your boards
pandan create "Wire up CI" --column todo --points 3
pandan list --column in_progress
pandan list --json | jq '.cards[].title'
pandan move 12 done
pandan epic create "Onboarding" --description "New-user flow"
pandan delete 12 --yes
```

## Develop / test

Uses [`uv`](https://docs.astral.sh/uv/) like the rest of the repo (Python 3.12+).
Run from `pandan-cli/`:

```bash
uv sync                # install deps (incl. dev group)
uv run ruff check .    # lint (matches the CI `cli` job)
uv run pytest -q       # unit tests — mocked httpx + argparse dispatch, no DB
```

The tests mock the shared `PandanClient`, so no backend or database is needed. CI
runs this as the `cli` job (see `.github/workflows/ci.yml`), mirroring the `mcp`
and `client` jobs.

### Build the standalone binary locally

PyInstaller lives in the `build` dependency group. From `pandan-cli/`:

```bash
uv sync --group build
uv run --group build pyinstaller --onefile \
  --name "pandan-$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)" \
  --collect-submodules pandan_cli --collect-submodules pandan_client \
  packaging/pyinstaller_entry.py
./dist/pandan-*                        # the frozen executable
```

PyInstaller can't cross-compile, so the release matrix builds one asset per OS on
its native runner (`.github/workflows/release-cli.yml`, tag-triggered on `v*`).
`packaging/pyinstaller_entry.py` is the freeze entry point — it imports the
console entry (`pandan_cli.__main__:main`) *absolutely*, since PyInstaller freezes
a script (not a module) and the package's own `__main__.py` uses a relative import.
