# Pandan — MCP server

An [MCP](https://modelcontextprotocol.io) server that exposes the Pandan
REST API (`/api/v1`) as tools an agent (e.g. Claude Code) can call. It is a thin
`httpx` wrapper — every tool maps to one endpoint — so the API stays the single
source of truth (API-first, ADR 0005). Milestone 2 slice **V5**; board-scoped in
**V10** (ADR 0015).

> **New here? Read the docs site, not this file.**
> [Set up the MCP server](https://leejianrong.github.io/pandan/agents/mcp-setup/) walks through
> getting access, minting a token, and wiring this server into Claude Code end to end, and
> [MCP tool reference](https://leejianrong.github.io/pandan/agents/mcp-tools/) documents the tools
> for users. This README is the implementation-facing companion: how the server is built, tested and
> published.
>
> Source for those pages: [`docs/guide/agents/`](../docs/guide/agents/).

> **Prefer the [`pandan` CLI](../pandan-cli/) if your agent can run one.** It is the
> primary interface; this server is the deliberate **fallback**. See
> [Why 49 tools, and why that is frozen](#why-49-tools-and-why-that-is-frozen) — it
> is a measured decision, not an accident, and the measurement says the CLI is
> ~11× cheaper per task.

## Tools

| Tool | Endpoint | Board target |
|------|----------|--------------|
| `warmup()` | `GET /api/health` (unversioned) | — (wakes a scaled-to-zero server; soft status) |
| `list_boards()` | `GET /boards` | — (lists boards you own) |
| `create_board(name)` | `POST /boards` | — (creates one you own) |
| `get_board(board_id)` | `GET /boards/{id}` | — (by id) |
| `update_board(board_id, name?)` | `PATCH /boards/{id}` | via the entity's own board |
| `delete_board(board_id)` | `DELETE /boards/{id}` | via the entity's own board |
| `list_cards(board_id?, column?, epic_id?, updated_since?, limit?, cursor?, fields?, full?)` | `GET /cards` (V3 query API) | `board_id` |
| `list_epics(board_id?, fields?, full?)` | `GET /epics` | `board_id` |
| `get_card(card_id, fields?, full?)` | `GET /cards/{id}` | — (by card id) |
| `get_epic(epic_id)` | `GET /epics/{id}` | — (by id) |
| `create_card(title, board_id?, description?, column?, story_points?, assignee?, epic_id?)` | `POST /cards` | `board_id` |
| `create_cards(cards)` | `POST /cards` × N (client-side loop) | per-card `board_id` |
| `create_epic(name, board_id?, description?)` | `POST /epics` | `board_id` |
| `update_epic(epic_id, name?, description?)` | `PATCH /epics/{id}` | via the entity's own board |
| `delete_epic(epic_id)` | `DELETE /epics/{id}` | via the entity's own board |
| `update_card(card_id, title?, description?, story_points?, assignee?, epic_id?)` | `PATCH /cards/{id}` | — (by card id) |
| `move_card(card_id, column, position?)` | `POST /cards/{id}/move` | — (by card id) |
| `claim_card(card_id, assignee)` | `POST /cards/{id}/move` + `PATCH /cards/{id}` | — (by card id) |
| `delete_card(card_id)` | `DELETE /cards/{id}` | — (by card id) |
| `add_dependency(card_id, blocker_id)` | `POST /cards/{id}/dependencies` | — (by card id) |
| `remove_dependency(card_id, blocker_id)` | `DELETE /cards/{id}/dependencies/{blocker_id}` | — (by card id) |
| `list_dependencies(card_id)` | `GET /cards/{id}` (shapes `blocked_by`/`blocks`) | — (by card id) |
| `add_link(card_id, label, url)` | `POST /cards/{id}/links` | — (by card id) |
| `remove_link(card_id, link_id)` | `DELETE /cards/{id}/links/{link_id}` | — (by card id) |
| `add_comment(card_id, body)` | `POST /cards/{id}/comments` | — (by card id) |
| `list_comments(card_id, fields?, full?)` | `GET /cards/{id}/comments` (wraps in `comments`) | — (by card id) |

> Work-links (KAN-32) are also inlined on every card read — `list_cards`/`get_card`
> already return each card's `links` array — so `add_link`/`remove_link` are just the
> write path. Comments (KAN-33) are a thread, so they live behind `list_comments`
> rather than on the card body.

**Board scoping (V10, ADR 0015).** Call `list_boards` to discover the boards you
own, then target any of them per call:

- The board-scoped tools take an optional **`board_id`**. Omit it and the server
  uses **`PANDAN_BOARD_ID`** if set, else the API's own fallback (`list_*` = all
  your boards; `create_*` = your earliest board).
- Card-id-addressed tools (`get_card`/`update_card`/`move_card`/`delete_card`) need
  no `board_id` — the server authorizes via the card's own board.
- Access is bounded to boards **you** own: a `board_id` you don't own returns `403`
  ("that board isn't yours — call `list_boards`"). A bad/expired token returns
  `401` ("set `PANDAN_TOKEN` to a valid PAT").

**Authentication — a personal access token is required.** Since M3 V8 (ADR 0013)
the whole `/api/v1` surface is auth-required, and V10 (ADR 0015) removed the old
shared-`API_TOKENS` bypass. Create a **PAT** in the SPA (top-bar **Tokens** →
*New token*), copy the `pandan_pat_…` secret shown once, and set it as
`PANDAN_TOKEN`. It authenticates **as your user** and is **owner-gated** — the
agent can only touch boards you own. A tokenless (or bad-token) server rejects the
MCP with `401`.

## Cheap reads: `fields` and `full` (KAN-501)

A board read is the most expensive thing this server does — far more expensive than
its whole tool surface (see the next section). So **every read tool narrows**:

| argument | what it does |
|---|---|
| `fields` | The keys to keep. `["ticket_number","title","column"]` on a list narrows every row; on a single object (`get_card`) or a report (`metrics`, `cycle_metrics`) it picks top-level keys/sections. `ticket`/`pts`/`points` are accepted as aliases but the returned key is always the API's own name. An unknown name errors and lists the valid ones. |
| `full` | Turns **off** the truncation of long free text, which is on by default. |

Long free text (`description`, `body`, `attention_note`, an activity row's
`summary`) is cut to **500 characters** with a hint carrying the *true* total —
`(truncated, 3431 chars total — pass full=true for the complete text)` — so you can
decide whether a second call is worth it. `PANDAN_MAX_TEXT_CHARS` changes the limit
(`0` disables it everywhere). A `next_cursor` or a work-link `url` is **never** cut,
however long: the rule is an allow-list of prose fields, not "any long string".

**Omit both and nothing changes** — you get exactly the payload the API returned,
key for key. That invariant is the first thing `tests/test_shaping.py` asserts.

What it saves, measured on a real capture of the Pandan Roadmap board (125 cards ×
22 keys), rendered with the SDK's own serializer (`o200k_base` tokens):

| read | before | default (truncated) | narrowed |
|---|---:|---:|---:|
| `list_cards` (whole board) | 48,291 | 39,635 | **7,430** |
| `list_epics` | 4,796 | 4,781 | 1,460 |
| `activity(limit=20)` | 2,633 | 2,633 | 1,373 |
| `metrics` | 2,452 | 2,452 | 65 |
| `get_card` | 241 | 241 | 77 |
| **all five** | **58,413** | **49,742** | **10,405 (−82%)** |

Adding these arguments cost **+552 resident tokens** (7,388 → 7,940), and KAN-517 a
further +222 (→ 8,162), which one narrowed `list_cards` repays about 74 times over.

> **The table above is a 2026-07-31 snapshot of a live board, not a constant.** Re-measured
> on 2026-08-01 the `list_cards` "before" figure reads **53,508** rather than 48,291 —
> the board grew from 125 to 131 cards. The **−82%** the table is about is the durable
> part; the absolute numbers move with the data. Re-run rather than quoting these.

Re-run it yourself — the harness
captures a real payload once and then measures offline, asserting every read really
was a non-empty page before counting it:

```bash
uv run --with tiktoken python scripts/measure_read_payload_tokens.py \
    --capture /tmp/roadmap.json --board 5 --credentials ~/.config/pandan/config.toml
uv run --with tiktoken python scripts/measure_read_payload_tokens.py --payload /tmp/roadmap.json
```

> Not every read is shaped, and since **KAN-517** that is measured rather than assumed.
> `list_notifications` is now shaped: the inbox takes no `limit` and returns no cursor,
> so it hands back your whole history and only grows — 127 rows cost **14,326** tokens,
> `fields=["id","kind","body"]` costs 4,658. `list_boards` takes `fields`
> (1,157 → 181; six of a board row's ten keys are autosync/webhook settings a discovery
> call never reads) and `get_epic` takes `full`, so it truncates a long description
> exactly as `list_epics` does — the listing and the targeted read now agree about the
> same epic.
>
> `next`, `dispatch`, `list_labels`, `list_views`, `list_templates`, `list_cycles`,
> `get_board` and `list_dependencies` deliberately stay raw: measured against the real
> account they return **7–474** tokens, and ~+60 resident tokens each to bound a payload
> that small is the *opposite* of the trade ADR 0019 endorsed. (`get_board` and
> `list_dependencies` were missing from KAN-501's own list of unshaped reads — the
> enumeration was never complete.) A test pins them that way; if you want to shape one,
> measure it first.

## Why 49 tools, and why that is frozen

The surface is **frozen at 49 tools** by [ADR 0019](../docs/adr/0019-mcp-surface-right-sizing.md)
(V49). It is deliberately broad, deliberately kept, and deliberately not growing.
Recorded here because the resident-cost headline invites the wrong conclusion, and
this decision should not be re-litigated from it.

**What it costs.** Every one of these schemas loads into an agent's context before
it does any work: **8,162 `o200k_base` tokens** as shipped (7,940 before KAN-517's three
extra shaped reads; 7,388 before KAN-501's `fields`/`full` arguments; 8,775 before the
schema compaction below). That counts `{name, description, input_schema}` per tool — a
`tools/list` entry also carries an **`outputSchema`**, a further **836** compact if your
client forwards it into the model's context (many will not: the Anthropic Messages API
tool definition has no field for it). ADR 0019 § *The fourth field* (KAN-518) has the
bracket, and why it is measured but deliberately **not** compacted. Re-measure any
time — the harness is committed:

```bash
uv run --with tiktoken python scripts/measure_tool_schema_tokens.py [--per-tool]
```

**The headline is a trap.** That resident number is the *small* half. When V49
measured it, a single `list_cards` against a real 121-card board returned
**~45,000 tokens** — over 5× the entire schema surface, in one tool result — because
these tools returned the raw API envelope while the CLI had field selection,
truncation and TSV/TOON output; per task the CLI came out **~11× cheaper** on real
reads. So the expensive thing about this server was its *payloads*, not its tool
count, and shrinking the count would have optimised the wrong line item. **KAN-501
has since closed most of that gap** — see [the section above](#cheap-reads-fields-and-full-kan-501),
which takes the same page from 48,291 to 7,430 tokens for +552 resident. The CLI
remains cheaper by default; the MCP reads are now within reach of it when narrowed.

**Why not the alternatives.** Both were measured on the same yardstick, built through
the same FastMCP serializer:

| option | tools | resident | verdict |
|---|---:|---:|---|
| today (frozen) | 49 | 8,162 | **chosen** |
| (a) one tool per entity + an `action` arg | 11 | 4,338 | rejected |
| (b) a single exec-`pandan` tool | 1 | 387 | rejected *for now* |

- **(a)** saves ~4.4k tokens but dissolves 49 precise schemas into 11 unions where
  nearly every argument must be optional — the schema can no longer tell a model
  that `claim` needs `assignee`, so validation slides from schema-time to runtime
  and the saving gets spent on retries. It also renames every tool, breaking
  allowlists and prompts, and does nothing about the payloads.
- **(b)** has the best numbers and inherits the CLI's payload shaping — but the CLI
  cannot yet reach `update_board` or `delete_board`, so making it the only surface
  would **delete capability** (ADR 0005 forbids a silent parity regression), and the
  published container image [ships no CLI binary](#as-a-container-ghcrio-kan-47) to
  exec. Revisit once both are fixed.

**What "frozen" means in practice.** New board capability lands in the **CLI**,
which costs a session nothing until it is used. Adding a tool here is an **ADR
amendment**, not a code change: `tests/test_schema.py` pins the name set *and* the
count and fails with an explanation. Removing one requires checking the CLI actually
covers the capability first.

**The schema compaction.** `pandan_mcp/schema.py` strips Pydantic's generated
`title` annotations and flattens nullable `anyOf` to `type: [T, null]` in the schema
clients are *shown* — −16% for no behaviour change, because FastMCP validates calls
through a separate object (`fn_metadata.arg_model`) that is never touched. Two traps
are pinned by tests: a nullable **enum** must not be collapsed (the collapsed form
rejects `null`), and `title` is both an annotation and a real argument name on
`create_card`/`update_card`.

## Configuration (env)

| Var | Default | Meaning |
|-----|---------|---------|
| `PANDAN_API_URL` | `http://localhost:8000` | API origin (the `/api/v1` prefix is added for you) |
| `PANDAN_TOKEN` | *(unset)* | **Required.** A per-user **PAT** (`pandan_pat_…`, created in the Tokens UI, V9/ADR 0014). Empty → `401` |
| `PANDAN_BOARD_ID` | *(unset)* | Optional default board id for board-scoped tools when a call omits `board_id`. Unset → the API's fallback (list = all your boards; create = earliest) |
| `PANDAN_MAX_TEXT_CHARS` | `500` | Character cap for a long free-text field on a read (KAN-501). `0` disables truncation everywhere — the deployment-wide form of `full=true`. Same name and default as the CLI's |

> **Deprecated fallback (V40, [ADR 0018](../docs/adr/0018-pandan-rebrand.md)).** The pre-rebrand
> `KANBAN_API_URL` / `KANBAN_TOKEN` / `KANBAN_BOARD_ID` still work: each key is read under its
> `PANDAN_*` name **first** and only falls back to the `KANBAN_*` spelling, emitting a one-line notice
> on **stderr** (never stdout — that's the JSON-RPC channel). Precedence is per *value*, so a
> half-migrated `.mcp.json` resolves correctly. They will be removed in a later milestone.
> A PAT minted before the rename (`kanban_pat_…`) also keeps authenticating indefinitely.

## Run it

Two ways to run the server: **from source with `uv`** (needs a checkout + uv), or a
**prebuilt container from ghcr.io** (KAN-47 — no Python/uv/checkout, just Docker).
Both speak MCP over **stdio**, so you normally don't run them by hand — a client
(Claude Code) launches them.

### From source (uv)

Uses [`uv`](https://docs.astral.sh/uv/) like the backend (Python 3.12+):

```bash
cd mcp
uv sync                                   # install deps
PANDAN_API_URL=http://localhost:8000 uv run python -m pandan_mcp   # stdio server
```

To smoke-test the tools without a client, run the test suite:

```bash
uv run pytest -q          # unit tests (mocked httpx) + a tool-list smoke test
```

### As a container (ghcr.io, KAN-47)

The image is `ghcr.io/leejianrong/pandan-mcp`, pushed on every version tag by
`.github/workflows/publish-mcp-image.yml`.

> **In transition (KAN-437).** The image path was renamed from `simple-kanban-mcp` with the rebrand,
> and a renamed path is a **new ghcr package**, so `pandan-mcp` does not exist until the **next**
> version tag is pushed — and GitHub makes a package **private on its first push**, needing a one-time
> visibility flip in the web UI (Packages → `pandan-mcp` → Settings → Change visibility → Public;
> the CI token has no `packages` scope, so this can't be automated). Until both have happened, the
> last published image is the old public `ghcr.io/leejianrong/simple-kanban-mcp:latest`, which keeps
> working but stops receiving updates. If a `pandan-mcp` pull 404s, that's which side of the
> transition you're on — not a broken tag.

Once published and made public it pulls with no `docker login` and no GitHub account:

```bash
docker pull ghcr.io/leejianrong/pandan-mcp:latest
```

Tags follow the release: `latest` on the newest, plus the semver `0.2.2`, `0.2`, and
`0`. **`:latest` is the try-it-out tag; pin a semver tag or a digest for anything
long-lived** — see [Which build am I running?](#which-build-am-i-running-kan-452)
below. Run it with `-i` (the stdio transport needs stdin open) and pass config
via `-e`:

```bash
docker run -i --rm \
  -e PANDAN_API_URL=https://simple-kanban-jian.fly.dev \
  -e PANDAN_TOKEN=pandan_pat_… \
  -e PANDAN_BOARD_ID=1 \
  ghcr.io/leejianrong/pandan-mcp:latest
```

> To reach a backend running on your **host** (not in Docker), use
> `PANDAN_API_URL=http://host.docker.internal:8000` rather than `localhost`.

**Build it yourself.** The image bundles the sibling `pandan-client` path dep, so
the build **context must be the repo root** with `-f mcp/Dockerfile` — building
from inside `mcp/` can't see `../pandan-client` and will fail:

```bash
docker build -f mcp/Dockerfile -t pandan-mcp .   # run from the REPO ROOT
```

### Which build am I running? (KAN-452)

`:latest` is a *moving* tag — it tells you nothing about which commit is inside.
The CLI answers that question with `pandan --version` printing
`pandan 0.5.0 (5da9ace)`; a container's native answer is **OCI labels + the
digest**. Every published image carries them
(`docker/metadata-action` emits them and the release workflow **fails** if the
built image doesn't name the release commit — see
[`mcp/scripts/assert-image-provenance.sh`](scripts/assert-image-provenance.sh)),
so a stale pull is always *detectable*:

```bash
# What commit / version / build time is this image?
docker inspect --format '{{json .Config.Labels}}' \
  ghcr.io/leejianrong/pandan-mcp:latest | jq .
# → "org.opencontainers.image.revision": "5da9ace…"   the exact commit
#   "org.opencontainers.image.version":  "0.2.2"      the release
#   "org.opencontainers.image.created":  "2026-…"     when it was built
```

`docker inspect` reads the **local** copy, so it answers *"which build did I
pull?"* — which is the staleness question. To see what the registry holds right
now without pulling (and to get the digest to pin), ask the registry directly:

```bash
docker buildx imagetools inspect ghcr.io/leejianrong/pandan-mcp:latest
```

**Pin by digest for a reproducible run.** A semver tag (`:0.2.2`) is immutable by
convention; a digest is immutable by construction — the same bytes forever, even
if a tag is re-pushed:

```bash
docker pull ghcr.io/leejianrong/pandan-mcp@sha256:<digest>
```

The publishing run prints the digest and a ready-to-paste `docker pull` line in
its job summary, so you never have to hunt for it. If a `docker inspect` shows a
`revision` you don't recognise, `git log -1 <revision>` tells you exactly how far
behind you are — that is the whole point of the labels.

The gate script is also the one-liner for *"is my pulled image my checkout?"* —
it needs only bash + docker:

```bash
mcp/scripts/assert-image-provenance.sh \
  ghcr.io/leejianrong/pandan-mcp:latest "$(git rev-parse HEAD)"
# exit 0 → the image was built from this commit; exit 1 → it wasn't, and it says so
```

> **Why keep `:latest` at all?** It was worth asking (KAN-452): the lesson from
> the CLI was that a build must be able to **identify itself**, not that floating
> tags are forbidden. With the labels and the release gate, `:latest` *is*
> self-identifying, and it is what makes the "no checkout, no Python, just
> `docker pull`" onboarding path work. So it stays — but as the try-it-out tag.
> Anything long-lived (a committed `.mcp.json`, a CI job) should pin a semver tag
> or a digest.

### Which toolchain is inside? (KAN-475)

**Scope statement, up front: the MCP image is _not_ byte-reproducible from its
commit alone, and that is a deliberate, documented position rather than an
oversight.** "Pin by digest for a reproducible **run**" above is a different
promise from a reproducible **build** — the first says *these exact bytes again*,
the second says *this commit yields these bytes*. Only the first is true here.

`mcp/Dockerfile`'s two build inputs float, so `docker build` from a fixed commit
can produce different images over time:

| Input | Dockerfile default | Drift |
| --- | --- | --- |
| `python:3.12-slim` | interpreter + OS base | patch releases **and the Debian base**. It resolved to Debian 12 / glibc 2.36 once and to `3.12.13-slim-trixie` — Debian 13.6 / **glibc 2.41** — when KAN-475 measured it. Calling it "pinned to a minor" is generous: the C library floor moved. |
| `ghcr.io/astral-sh/uv:latest` | the uv binary | fully unconstrained; any release at any time (0.12.0 when measured). |

So `org.opencontainers.image.revision` is true but weaker than it looks — it
says which commit, not which toolchain, and the release gate compares label
values so it cannot see a toolchain difference either.

**What the release does about it.** `publish-mcp-image.yml` resolves both tags to
immutable digests **once per release**, builds against those digests, and records
them on the image:

```bash
docker inspect --format '{{json .Config.Labels}}' \
  ghcr.io/leejianrong/pandan-mcp:latest | jq .
# → "io.github.leejianrong.pandan.build.python": "python@sha256:57cd7c3a…"
#   "io.github.leejianrong.pandan.build.uv":     "ghcr.io/astral-sh/uv@sha256:606e70c7…"
```

The gate **fails the release** if either label is missing or is not digest-pinned,
so the record cannot quietly regress. Two consequences worth stating plainly:

- **Within a release the build is pinned.** The workflow builds twice (gate, then
  push) and both builds now get the same resolved digests, so they cannot differ
  in interpreter or uv.
- **Across releases the inputs still move**, on purpose — you get current security
  patches. The image is therefore **auditable, not reproducible**: it tells you
  exactly which toolchain it got.

**Rebuilding a published image's toolchain.** Read the two labels off the image
(or the publishing run's job summary, which prints them) and pass them back:

```bash
docker build -f mcp/Dockerfile -t pandan-mcp:rebuild \
  --build-arg PYTHON_BASE=python@sha256:<from the label> \
  --build-arg UV_SOURCE=ghcr.io/astral-sh/uv@sha256:<from the label> .
```

With no `--build-arg` the defaults are the floating tags, so a plain
`docker build` still needs no arguments.

> **Why not just commit digest pins to the Dockerfile?** Because they would have
> **no watcher**, which is worse than floating: a stale pin *looks* maintained.
> `.github/dependabot.yml` has no `docker` ecosystem, and adding one would not
> help the input that matters most — Dependabot's Docker updater ignores
> `COPY --from` image references entirely
> ([dependabot/dependabot-core#5103](https://github.com/dependabot/dependabot-core/issues/5103),
> open since 2022), which is exactly how `uv` enters this image. A committed `uv`
> pin could therefore never be bumped automatically, and would rot into a
> stale-security-patch. Resolving at release time needs no watcher at all: every
> release picks up current patches *and* records precisely what it picked up.
> Committed digest pins become the right trade when the deployment threat model
> changes — revisit alongside the k8s migration (KAN-439).
>
> The gate is consequently a check on a **release artifact**, not on any local
> build: a plain `docker build` passes no labels, so it fails the gate (it already
> did, on `.revision`). Images published *before* KAN-475 have no toolchain labels
> and will fail on those two assertions specifically.

## Wire it into Claude Code

Copy [`.mcp.json.example`](../.mcp.json.example) to `.mcp.json` at the repo root
and adjust the env. It ships **two** server entries — `pandan` (runs from source
with `uv`) and `pandan-docker` (runs the prebuilt ghcr.io image, KAN-47, no
Python/uv/checkout). Both work today; keep the one you want and delete the other.
Claude Code discovers project-scoped servers there and will ask you to approve it. In
every case set `PANDAN_TOKEN` to a `pandan_pat_…` you created in the SPA Tokens tab.

> **The `mcpServers` key is what tool names are namespaced with.** Calling this server
> `pandan` makes its tools `mcp__pandan__list_cards`, `mcp__pandan__create_card`, … —
> before the V40 rebrand they were `mcp__kanban__*`. If you rename the key, anything
> that references a tool *by name* — a skill, a prompt, a `settings.json` allowlist —
> has to match. (The tool names themselves are unchanged; only the prefix moved.)

**Local dev** (backend on :8000):

```json
{
  "mcpServers": {
    "pandan": {
      "command": "uv",
      "args": ["run", "--directory", "./mcp", "python", "-m", "pandan_mcp"],
      "env": {
        "PANDAN_API_URL": "http://localhost:8000",
        "PANDAN_TOKEN": "pandan_pat_…",
        "PANDAN_BOARD_ID": "1"
      }
    }
  }
}
```

**Production:**

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

**Docker (prebuilt image, no Python/uv):**

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
        "PANDAN_BOARD_ID": "1"
      }
    }
  }
}
```

The `-e NAME` flags (no `=value`) forward the values from the `env` block into the
container, keeping the token out of the argument list. **A committed `.mcp.json`
is long-lived, so pin it** — `:0.2.2`, or `@sha256:…` for a byte-exact pull — and
keep `:latest` for trying the server out. See
[Which build am I running?](#which-build-am-i-running-kan-452) for how to check
what a given image actually contains.

`PANDAN_BOARD_ID` pins the default board for calls that omit `board_id`; the
snippets above (and [`.mcp.json.example`](../.mcp.json.example)) preset it to `1`,
the seeded default board — **change it to your own board id** (from `list_boards`)
so the agent doesn't target the wrong board, or leave it empty to fall back to the
API default (list = all your boards, create = your earliest). `--directory ./mcp`
is relative to the repo root (where Claude Code launches it); use an absolute path
if you run the client from elsewhere. Once
connected, ask the agent to *"list my boards"*, then *"create an epic and a couple
of stories under it on board N, then move one to In Progress"* and watch them
appear on the board.
