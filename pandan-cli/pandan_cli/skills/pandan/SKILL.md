---
name: pandan
description: >-
  Read and write the Pandan board from an agent or the command line using the `pandan` CLI —
  the primary interface — with the `mcp__pandan__*` MCP tools as the fallback. Use whenever the task
  is to look at, create, update, move, or organise cards/epics/boards on Pandan (the board at
  simple-kanban-jian.fly.dev or a self-hosted instance): "add a card", "what's on the board", "move
  KAN-12 to done", "list my epics", "track this work on kanban". For orchestrating a whole backlog as
  a scrum-master, see the pandan-pm skill; this skill is the tool reference it builds on.
---

# Driving Pandan with the `pandan` CLI

Pandan is API-first: every board action is a plain `/api/v1` REST call, and there are two thin
clients over it. The **`pandan` CLI is the primary way to drive the board** — it's a single binary, easy
to shell out to, scriptable, and works in CI. The **MCP server (`mcp__pandan__*` tools) is the
fallback**, for when the CLI isn't installed or errors. Cards, boards, epics, labels, saved views,
card templates, dependencies, work-links, comments, dispatch/claim, needs-human handoff, metrics and
the activity feed are all reachable from either.

> **Parity now holds in both directions as of `pandan 0.19.0` — and it is a test, not a claim.**
> This section used to assert "full parity as of v0.3.0" while the *same file* documented a `curl`
> workaround for a missing CLI verb forty lines below. KAN-432 / ADR 0019 verified the relationship was
> **MCP ⊇ CLI** and named four gaps; **KAN-502 closed all four** — `pandan board get/update/delete`,
> `pandan claim <id> --assignee X` (an atomic claim of a *chosen* card), and `pandan batch-create`
> (N creates in one invocation), plus `pandan epic get`.
>
> What makes this different from the claim it replaces: `pandan-cli/tests/test_parity.py` enumerates the
> MCP tool surface out of `mcp/pandan_mcp/server.py` and the CLI verb surface out of the real argparse
> parser, and asserts the mapping **mechanically** in both directions — including
> `MCP_ONLY == {}`. If a future tool or verb breaks parity, that test fails; nobody has to
> notice a stale paragraph. The only CLI verbs with no MCP twin are the local ones
> (`login`, `config`, `context`, the bare `overview`), which touch your installation, not the board.
>
> Still don't repeat "full parity" as bare prose: the old shorthand was inherited into a roadmap card
> and nearly justified deleting the MCP surface. Cite the test.

Prefer `pandan`. Drop to MCP only when you have to, and say why when you do.

## Setup

`pandan` needs three config values, and resolves each one independently from the first source that
supplies it, in this precedence order:

1. **Environment** — `PANDAN_API_URL` / `PANDAN_TOKEN` / `PANDAN_BOARD_ID`.
2. **User config file** — `~/.config/pandan/config.toml` (`$XDG_CONFIG_HOME`-aware), written once by
   `pandan login` / `pandan config set` at mode `0600`. **This is how you authenticate one time and never
   pass the token again** (see below). A pre-rebrand `~/.config/kan/config.toml` is migrated across on
   first use and left in place (V40, KAN-423; `pandan_cli/config.py:100-107`).
3. **`.mcp.json`** — the nearest one walking up from the CWD, read from `.mcpServers.pandan.env.*`.

The three values:

- `PANDAN_API_URL` — the board origin, e.g. `https://simple-kanban-jian.fly.dev` (or a self-host URL).
- `PANDAN_TOKEN` — a PAT (`pandan_pat_…`). Minted at the board's **Tokens** tab after logging in.
  It acts as you and reaches boards you own **or are a member of**. `warmup` is the one command that
  needs no token.
- `PANDAN_BOARD_ID` — the default board id. Set it. Without it, `list`/`create` span all your boards
  or land on your earliest one, which is an easy way to touch the wrong board.

Because of the precedence chain, **in a Claude Code project you usually don't have to set anything**:
`pandan` finds the PAT in the repo's `.mcp.json` on its own (source 3). For a standalone machine or CI,
authenticate once with `pandan login` (source 2) — after that every `pandan` call just works.

### The token is a secret — never let it enter your context

**Treat the PAT as a credential you handle blind.** Do **not** `cat`/`grep`/`echo` the token, print
it, or paste the literal `pandan_pat_…` value into any command you write — anything you emit lands in
the model context (and the transcript). The value must only ever move *machine-to-machine*.

In a Claude Code project the token already lives in **`.mcp.json`** at the repo root, under
`.mcpServers.pandan.env.PANDAN_TOKEN` (alongside `PANDAN_API_URL` and `PANDAN_BOARD_ID`). Load it into
the shell **by reference** with command substitution, so the value is resolved by the shell at runtime
and never appears in what you write or in the output. The Bash tool starts a fresh shell each call and
does **not** persist env vars, so prefix every `pandan` call with the load:

```bash
# All three, straight from .mcp.json — the literal token never surfaces:
export PANDAN_TOKEN=$(jq -r '.mcpServers.pandan.env.PANDAN_TOKEN' .mcp.json)
export PANDAN_API_URL=$(jq -r '.mcpServers.pandan.env.PANDAN_API_URL' .mcp.json)
export PANDAN_BOARD_ID=$(jq -r '.mcpServers.pandan.env.PANDAN_BOARD_ID' .mcp.json)
pandan board list
```

Collapse it into a reusable one-liner you paste at the front of each command (find `.mcp.json` by
walking up from the CWD if it isn't in the working directory):

```bash
eval "$(jq -r '.mcpServers.pandan.env | to_entries[] | "export \(.key)=\(.value|@sh)"' .mcp.json)" && pandan board list
```

If there is no `.mcp.json` (non–Claude Code shell, CI, self-host), expect the three vars to already be
in the environment — still don't echo `PANDAN_TOKEN`. If the token genuinely isn't reachable any way,
stop and ask the user rather than requesting they paste it into the chat. (The **MCP fallback** never
has this problem: the MCP server process inherits the token from `.mcp.json` directly, so
`mcp__pandan__*` tool calls never expose it — see below.)

Install the CLI (either works; the binary needs no Python):

```bash
# Prebuilt binary from the latest release (Linux glibc >= 2.28 / macOS arm64):
curl -L -o pandan https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64
chmod +x pandan && mv pandan ~/.local/bin/        # ~/.local/bin is on PATH, no sudo
ln -sf ~/.local/bin/pandan ~/.local/bin/pdn       # optional short name — see note below

# or, if you have Python + uv:
uv tool install "git+https://github.com/leejianrong/pandan.git#subdirectory=pandan-cli"
```

> **`pandan` is the only command; any short name is a symlink you make.** A `pdn`
> `[project.scripts]` alias was declared in V40 and **withdrawn in KAN-442** (see ADR 0018's
> amendment): console scripts are generated by the *packaging* installer, so it existed for
> `uv tool install` but never for the `--onefile` release, which ships one executable. A symlink
> works on both paths, and the same trick keeps the retired name alive if you have the muscle
> memory: `ln -sf ~/.local/bin/pandan ~/.local/bin/kan` — which also guarantees the old name
> isn't a stale pre-rebrand build sitting on your `PATH`.

Confirm it works: `pandan --version`, `pandan warmup` (should print `ok`), then `pandan me` — one row
of `<user_id>	<email>` when the token is good, and exit **3** when it isn't (no board is involved, so
`4` is not reachable and a failure can only mean the credential). Then `pandan board list` for the
board ids.

`--version` prints **build provenance**, not just a number (V50, KAN-435) — `pandan 0.7.0 (bd28cf0)`
for a release build, or an explicit `pandan 0.7.0 (source checkout, not a released build)` when run
from a checkout. If you are chasing behaviour that doesn't match the docs, **check this first**: a
stale binary on `$PATH` has caused two false bug reports on this project. Audit from source with
`uv run python -m pandan_cli …` from `pandan-cli/`, never a binary on `$PATH`.

### Authenticate once (so the token never has to be entered again)

On a standalone machine or in CI (anywhere there's no `.mcp.json` to inherit from), authenticate a
single time and `pandan` persists it to `~/.config/pandan/config.toml` (mode `0600`, owner-only). Every
later `pandan` call — from any directory — then resolves the token from that file automatically. **Do
this without ever emitting the token**: `pandan login` reads the PAT from stdin (or a hidden prompt),
never from a command-line argument, so the literal `pandan_pat_…` never lands in argv, shell history,
or your context. Pipe it in from wherever it already lives, by reference:

```bash
# From a Claude Code .mcp.json (token resolved by jq at runtime, never printed):
jq -r '.mcpServers.pandan.env.PANDAN_TOKEN' .mcp.json \
  | pandan login --token-stdin \
      --api-url https://simple-kanban-jian.fly.dev \
      --board-id <your-board-id>     # persists all three to ~/.config/pandan/config.toml (0600)
```

If you're setting up by hand and the PAT is in some other secret store, pipe *that* into
`pandan login --token-stdin` the same way. `pandan config show` prints the effective config with the token
**redacted** (safe to run), showing which source each value came from. `pandan config set` /
`pandan config path` round out the config commands. (These live in the released binary from **v0.2.3**
onward.) After this, drop the per-call env exports entirely — `pandan list`, `pandan create`, etc. just work.

> Requires a login-capable binary (v0.2.3+). If `pandan login` errors with `invalid choice: 'login'`,
> the installed binary predates the feature — re-download the latest release.

## Cold start: warm up first

The hosted board runs on a free tier that scales to zero, so the first request after a few minutes
idle is slow and can even fail outright (timeout / TLS reset), which looks exactly like the server
being down. Run `pandan warmup` before a batch of calls — it pings the health endpoint, needs no token,
rides out the wake, and exits `0` once the API is up. In a script:

```bash
until pandan warmup; do sleep 2; done
```

## Command surface

Cards are the top-level verbs; `board`, `epic`, `label`, `view`, `template`, `dep`, `link`, and
`comment` are nested groups. Columns are `todo`, `in_progress`, `done`. Story points are one of
{1,2,3,5,8,13}. Priority is one of `none`/`low`/`medium`/`high`/`urgent`. Every command takes `--json`
for machine-readable output you can pipe into `jq`; the human line for a card is
`ticket  column  title  pts=N` (`pts=-` when unestimated).

**`--json` output is enveloped for list verbs, bare for single reads — don't guess the shape**
(KAN-434, verified 2026-07-31). `--json` is a verbatim passthrough of the shared client's return
value, and the *client* adds the envelope (a raw `GET /api/v1/cards` is a bare array), so the key
differs per verb:

| Verb | Top-level `--json` shape |
|---|---|
| `list` | `{"cards": [...]}` **+ `next_cursor`** when the page is full |
| `activity` | `{"activity": [...]}` + `next_cursor` |
| `board list` / `epic list` / `label list` / `view list` / `template list` / `comment list` / `cycle list` / `notify list` | `{"boards"}` / `{"epics"}` / `{"labels"}` / `{"views"}` / `{"templates"}` / `{"comments"}` / `{"cycles"}` / `{"notifications"}` |
| `next`, `next --claim` | `{"card": {...}}` — `{"card": null}` when nothing is ready |
| `batch-update` / `batch-create` / `template apply` | `{"updated": [...]}` / `{"created": [...]}` / `{"created": [...]}` |
| `dep add`/`rm`/`list` | `{"card_id", "blocked_by", "blocks"}` |
| `link add`/`rm` | `{"card_id", "links"}` |
| any `delete` | `{"deleted": <id>}` |
| `warmup` | `{"status", "health"}` |
| `get`, `create`, `update`, `move`, `claim`, `needs-human`, `resolve`, `comment add`, `notify read`, and every `<group> get/create/update` (incl. `board get`/`board update`, `epic get`) | **bare entity object** — no envelope |
| `metrics`, `cycle metrics`, `config show` | **bare object** — no envelope |

```bash
pandan list --json | jq -r '.cards[] | "\(.ticket_number)\t\(.title)"'   # NOT .[]
pandan next --json | jq -r '.card.ticket_number // "none ready"'
pandan get KAN-7 --json | jq -r .title                                   # single reads are BARE
```

The envelope is load-bearing (`next_cursor` rides there, and a `summary` field is coming) — treat it
as the contract, not an accident.

**`--fields a,b,c` widens the human row on any list verb** (V42/KAN-425) — cheaper than `--json` when
you want two or three extra columns rather than the whole record:

```bash
pandan list --column todo --fields ticket,title,priority   # tab-separated, `-` for null
```

The vocabulary is that row's own `--json` keys plus the aliases `ticket` and `pts`/`points`; an unknown
name is a clean error naming it. Omitting `--fields` leaves the default
`ticket  column  title  pts=N` row byte-identical, and `--fields` **does not** affect `--json` (that's
already the full record). Not available on single-entity verbs like `get` — there it's a usage error,
not a silent no-op. Don't confuse it with `--sort`, whose help line lists **`Sort keys:`**.

Cards:

- `pandan list [--board N] [--column C] [--epic ID] [--priority P] [--label ID] [--assignee A] [--due-before ISO] [--overdue] [--needs-human] [--q TEXT] [--sort SPEC] [--limit N] [--json]`
  — query/filter cards. `--q` is full-text search over title+description; `--sort` takes
  comma-separated keys, `-` prefix = descending (e.g. `--sort -priority,position`). Large results
  paginate; the output includes a next-cursor to continue.
- `pandan get <card_id> [--json]`
- `pandan create "<title>" [--board N] [--description D] [--column C] [--points N] [--assignee A] [--epic ID] [--priority P] [--due ISO] [--label ID ...] [--json]`
- `pandan update <card_id> [--title T] [--description D] [--points N] [--assignee A] [--epic ID] [--priority P] [--due ISO] [--label ID ...] [--json]`
  — field edits only. It does **not** change the column; use `move` for that. `--label` replaces the
  card's labels with the given ids.
- `pandan move <card_id> <column> [--position N]` — the dedicated column/position change.
- `pandan delete <card_id> --yes` — `--yes` is required as a guard.
- `pandan batch-update '<JSON array of {id, ...fields}>'` (or `-` for stdin) — atomically PATCH several
  cards in one call (all-or-nothing).
- `pandan batch-create '<JSON array of card objects>' [--board N]` (or `-` for stdin, so
  `pandan batch-create - < cards.json` files a whole plan) — create several cards in one invocation.
  **Fail-fast, NOT atomic**, unlike `batch-update`: there is no batch-create endpoint, so this loops one
  POST per card and the cards created *before* a rejection stay created. On failure re-run with the
  remainder, not the whole array. Object fields use the API's own names (`title` required, then
  `description`/`column`/`story_points`/`assignee`/`epic_id`/`cycle_id`/`priority`/`due_date`/
  `label_ids`/`board_id`); `--board` (or `PANDAN_BOARD_ID`) fills in `board_id` for objects that omit
  it, so a batch can't silently land on your earliest board.
- `pandan claim <card_id> --assignee A [--json]` — claim a **chosen** card in one call: move it to
  `in_progress` **and** set its assignee. Use this when you already know which card you want;
  `next --claim` is the one that picks the card for you. `--assignee` is required (this path has no
  server-side "the caller" default — only `next --claim`'s dispatch endpoint has one).

Agent operating verbs (the write side of the human↔agent surface):

- `pandan next [--board N] [--claim] [--assignee A] [--label ID] [--priority P] [--json]` — show the next
  ready card (highest priority, unblocked, in `todo`); `--claim` atomically dispatches it (sets
  assignee + moves to `in_progress`), which is fleet-safe across concurrent agents.
- `pandan needs-human <card_id> [--note N]` — flag a card for a human decision. `pandan resolve <card_id>`
  — clear the flag. (Filter with `pandan list --needs-human`.)

Dependencies, work-links, comments (nested groups):

- `pandan dep add <card_id> --blocked-by <other_id>` · `pandan dep rm <card_id> --blocked-by <other_id>` ·
  `pandan dep list <card_id>`
- `pandan link add <card_id> --url <url> --label <label>` · `pandan link rm <card_id> --link-id <id>`
- `pandan comment add <card_id> --body "…"` · `pandan comment list <card_id>`

Boards, epics, labels, saved views, templates:

- `pandan board list [--json]` · `pandan board get <board_id> [--json]` · `pandan board create "<name>" [--json]`
- `pandan board update <board_id> [--name N] [--outbound-webhook-url URL]
  [--outbound-webhook-secret S | --outbound-webhook-secret-stdin]
  [--outbound-webhook-enabled | --outbound-webhook-disabled] [--json]` — **this is how you rename a
  board** (it used to need a raw `curl`), and how you configure the V38 signed outbound webhook. Only
  the flags you pass are sent. The secret is **write-only**: the API accepts it and never returns it, so
  no read can show you what is set. Pass it over `--outbound-webhook-secret-stdin`
  (`printf '%s' "$SECRET" | pandan board update 5 --outbound-webhook-secret-stdin`) — an argv value is
  visible in `ps` and lands in your shell history. `--outbound-webhook-enabled`/`-disabled` is a
  tri-state: omit both to leave the setting alone.
- `pandan board delete <board_id> --yes [--json]` — its cards and epics cascade away. `--yes` required.
- `pandan epic list [--board N] [--json]` · `pandan epic get <epic_id> [--json]` · `pandan epic create "<name>" [--board N] [--description D] [--json]`
- `pandan epic update <epic_id> [--name N] [--description D] [--json]` · `pandan epic delete <epic_id> --yes [--json]`
- `pandan label list [--board N] [--json]` · `pandan label create "<name>" [--color C] [--board N] [--json]` · `pandan label delete <label_id> --yes [--json]`
- `pandan view list|create|delete …` — saved named filter/sort views.
- `pandan template list|create|delete|apply …` — card templates; `apply` seeds a template's cards onto a board in one call.

Reporting (read-only, derived):

- `pandan metrics [--board N] [--since ISO] [--window SPAN] [--json]` — throughput / cycle time / aging WIP / per-assignee.
- `pandan activity [--board N] [--actor LABEL] [--action VERB] [--limit N] [--cursor C] [--json]` — the board's activity feed, newest-first.

Ops:

- `pandan warmup [--json]` — wake the server; no token needed.
- `pandan --version` / `pandan -v` — print the version **and build provenance**, then exit. A released
  binary reports `pandan 0.7.0 (bd28cf0)` (the commit it was built from); a source run says
  `(source checkout, not a released build)`. **If a `pandan` behaves unexpectedly, check this first** —
  a stale binary that predates a fix used to be indistinguishable from current source, which caused
  two false bug reports (KAN-435).
- `pandan login` / `pandan config set|show|path` — one-time auth + config file (see Setup).

### Errors and exit codes (the machine contract, V43/KAN-426)

Exit codes: `0` success, `1` generic/runtime error, `2` usage (argparse rejected argv), `3`
unauthorised (401), `4` forbidden (403), `5` not found (404), `6` conflict (409). So a script tells
"bad token" from "not your board" from "gone" from "already like that" without parsing text. The rule
behind 1-vs-2: **argparse rejected argv → 2; the CLI rejected a runtime value → 1.** Rows are ADDED,
never renumbered — `6` arrived in KAN-831 to match kaya's identical table, where a 409 is a
*retryable* stale-precondition refusal. pandan's own 409s are terminal, so pandan gains the sameness
rather than retry semantics.

**Errors go to stdout, structured** — not stderr as prose:

```
$ pandan get KAN-999999
error	not_found	no card found with ticket KAN-999999	KAN-999999      # exit 5
```

Tab-separated `error <code> <message> <arg>`, or under `--json` an
`{"error": {code, message, arg, status, exit_code}}` object with all five keys always present. Branch
on the stable `code` (`not_found`, `unauthorized`, `forbidden`, `conflict`, `config`, `unknown_field`,
`confirmation_required`, `invalid_ref`, `transport`, …), never on message text. Human `usage:` text
still goes to stderr.

**A card that doesn't exist reports the same code however you addressed it** — `pandan get 999999` and
`pandan get KAN-999999` both exit `5`. Before v0.7.0 the ticket-ref form exited `1`, so the code
depended on the identifier form rather than the failure.

## Example workflows

Orient, then pick up a card and start on it:

```bash
pandan warmup
pandan list --column todo                 # what's available
pandan get 42                             # read the card fully
pandan move 42 in_progress                # start it
pandan update 42 --assignee "agent:me"    # note who's on it
```

Add a chunk of work under an epic:

```bash
EPIC=$(pandan epic create "Onboarding flow" --json | jq -r .id)
pandan create "Landing page" --epic "$EPIC" --points 3
pandan create "GitHub login button" --epic "$EPIC" --points 2
```

Finish and close out:

```bash
pandan move 42 done
```

## When to fall back to MCP

Use the `mcp__pandan__*` tools instead of `pandan` when the CLI isn't installed / not on PATH, or a
`pandan` command errors for an environment reason (not a 4xx from the API). **Every one of the 49 MCP
tools has a CLI verb and every board-touching CLI verb has an MCP tool** — asserted by
`pandan-cli/tests/test_parity.py`, not by this sentence (see the note at the top of this file, and
ADR 0019 for why the surface is frozen at 49 rather than trimmed):

- **Cards:** `list_cards`, `get_card`, `create_card`, `create_cards` / `update_cards` (batch),
  `update_card`, `move_card`, `claim_card`, `delete_card`.
- **Dispatch & handoff:** `dispatch`, `next`, `needs_human`, `resolve`.
- **Dependencies / links / comments:** `add_dependency` / `remove_dependency` / `list_dependencies`,
  `add_link` / `remove_link`, `add_comment` / `list_comments`. (Card reads include
  `blocked_by`/`blocks`/`blocked` and `links` either way.)
- **Boards / epics / labels / views / templates:** `list_boards` / `create_board` / `get_board` /
  `update_board` / `delete_board`, and the parallel `*_epic`, `*_label`, `*_view`, and `*_template`
  (incl. `apply_template`) families.
- **Reporting & ops:** `metrics`, `activity`, `warmup`.

The MCP server loads at session start, so a newly added MCP *tool* isn't callable until Claude Code is
restarted; a new API *field*, though, shows up immediately since the tools pass JSON straight through.

## Access model (so errors make sense)

`/api/v1` is auth-required and access-gated by **ownership or membership**: a PAT resolves to its
owning user, and that user can see and change boards they **own** plus boards **shared with them** as
a member. Boards can be shared with other users at one of three roles — **viewer** (read-only),
**editor** (read + write cards/epics), or **owner** (full control incl. board settings + membership);
the board's creator always has full access. A PAT inherits its user's memberships, so an agent reaches
exactly the boards its user does. Errors that follow: a `401` means the token is bad or unset; a `403`
means you have no access to that board (or your role is too low for the write you attempted — e.g. a
viewer trying to create a card); a `404` means it doesn't exist. More detail is in the repo's
onboarding guide:
<https://github.com/leejianrong/pandan/blob/main/docs/guides/agent-onboarding.md>.

## Reporting bugs / opening issues

Pandan is developed at **<https://github.com/leejianrong/pandan>**. If you hit a bug, a
missing command, or a CLI↔MCP parity gap while driving the board, open an issue there with
`gh issue create --repo leejianrong/pandan` (the `gh` CLI is authenticated as the repo owner).
Keep it short and reproducible: include `pandan --version`, the exact command and its error, and the
workaround you used if any. Mention you were using the `pandan` skill.

**No known parity gaps.** The four this file used to list — including a raw-`curl` workaround for
renaming a board — closed in `pandan 0.19.0` (KAN-502). If your `pandan` is older than that, check
`pandan --version` before concluding a verb doesn't exist:

```bash
pandan board update <id> --name "New name"   # was: curl -X PATCH …/api/v1/boards/<id>
```
