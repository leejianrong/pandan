# ADR 0019 — MCP surface right-sizing: keep the breadth, freeze its growth

- **Status:** Accepted — and **executed**. Phase 1 (measure + decide) and Phase 2 (freeze + compact +
  document) have both landed. Nothing was removed and no tool was renamed.
- **Date:** 2026-07-31
- **Context source:** Milestone 7 ("Name & Sharpen the Tools"), slice **V49** / **KAN-432**, shaped
  requirement **R3.1** (measure the schema token cost of the tool surface and of each alternative) and
  Shape A part **A8**. Builds on ADR 0005 (API-first — the CLI and MCP server are both thin adapters,
  and parity between them may not silently regress), ADR 0014/0015 (PAT auth + board scoping, which is
  what the MCP tools carry), and ADR 0018 (the `pandan` rebrand, which renamed the tool namespace to
  `mcp__pandan__*` but changed no tool). Retires nothing.

## Context

The MCP server exposes one tool per `/api/v1` capability. Every one of those schemas is serialized
into an agent's context **before it does any work**, whether or not the session ever touches the
board. Meanwhile Milestone 7 spent eight slices making the CLI cheap to drive (`--fields`, structured
errors, pre-computed aggregates, content truncation, content-first output, `--format toon`, ambient
session context). The premise of KAN-432 was that this makes the CLI strictly cheaper per task, so the
breadth of the MCP surface is now dead weight worth paying down.

Two of that premise's factual claims did **not** survive measurement, and they change the answer:

1. **The resident cost is real but it is not where the tokens are.** The whole 49-tool surface costs
   **8,775** tokens. A *single* `list_cards` call against the live Pandan Roadmap board returns
   **44,902** — 5.1× the entire schema surface, in one tool result. Right-sizing the resident surface
   optimises a ~4%-of-a-200k-window line item while a 22% one sits next to it untouched.
2. **The CLI is not at full parity with MCP.** Parity is one-directional: every `pandan` verb has an
   MCP twin, not the reverse. `pandan board` has only `list` and `create` (verified against
   `pandan board --help`), so **`update_board` and `delete_board` are unreachable from the CLI** — the
   packaged skill already documents this and hands out a `curl` workaround
   (`pandan_cli/skills/pandan/SKILL.md`, "Known gap"), directly under a bolded "full parity" claim it
   contradicts. Two more MCP tools lose a guarantee rather than a verb: `claim_card` claims a *named*
   card atomically (the CLI's `next --claim` only claims whatever is next, so a chosen card needs
   `move` + `update` — two calls, non-atomic), and `create_cards` batches N creates into one round
   trip (the CLI needs N invocations).

Claim 2 is decisive: under ADR 0005, removing a tool whose capability the CLI cannot reach is a silent
parity regression, which is the one thing this project's adapter layer is not allowed to do.

## Measurement

All figures are **`o200k_base` tokens via `tiktoken`**. That is not Claude's tokenizer, so treat the
absolute numbers as a consistent proxy rather than a billing figure; it is the encoding V47 used to
measure TOON, and matching it is the reason for the choice — the two measurements are comparable.

Re-run everything below with the committed harness:

```bash
cd mcp && uv run --with tiktoken python scripts/measure_tool_schema_tokens.py [--per-tool]
```

### Resident cost — the current surface and each option

The unit measured is the JSON object a client puts in the model's context per tool —
`{"name": "mcp__pandan__<tool>", "description": <docstring>, "input_schema": <inputSchema>}` — taken
from the server's real `tools/list` response (`FastMCP.list_tools()`, the same call the stdio transport
answers). The client's exact framing is not observable from inside the server, so the table brackets
it: **compact** separators for the headline and `indent=2` as the ceiling. **Options (a) and (b) are
built with FastMCP too, not hand-written JSON**, so they pass through the identical
Pydantic→JSON-Schema serializer and any per-tool framing overhead is counted the same on both sides.

| surface | tools | compact | `indent=2` | vs. before |
|---|---:|---:|---:|---:|
| 49 typed tools, before compaction | 49 | 8,775 | 12,825 | — |
| **49 typed tools, AS SHIPPED (Phase 2)** | **49** | **7,388** | **10,307** | **−16%** |
| **(a)** one tool per entity + `action` arg | 11 | 4,338 | 6,683 | **−51%** |
| (a) + the same compaction | 11 | 3,482 | 5,041 | −60% |
| **(b)** single exec-`pandan` tool | 1 | 387 | 459 | **−96%** |

> The as-shipped row is **7,388, not the 7,346** Phase 1 projected. Phase 1's throwaway
> strip-function collapsed *every* nullable `anyOf`; the shipped rule refuses to collapse a nullable
> **enum**, because the collapsed form rejects `null` (see *Consequences*). Six optionals therefore
> keep their `anyOf`, at a cost of 42 tokens. The harness now calls the production function rather
> than a private copy, so the published number and the shipped behaviour cannot drift again.

**The tool count is 49**, confirmed two ways: `grep -c '^@mcp.tool'` over
[`mcp/pandan_mcp/server.py`](../../mcp/pandan_mcp/server.py) and the length of `list_tools()`. The
plan's prior figure of ~10,076 tokens falls inside the compact↔`indent=2` bracket above and is
consistent with a differently-framed serialization of the same 49 tools; the 48 in the original card
was simply wrong.

Where the pre-compaction 8,775 sat: **descriptions (prose) 4,030 · input schemas 3,660 · tool names
394** (the remaining ~690 is JSON framing — the object braces, the three keys, and escaping). Phase 2's
compaction took the schema share to **2,273** (−38%), leaving prose as the clear majority of what
remains. No single tool dominates: `list_cards` is the largest at 780, `create_card`
497, `update_card` 450, and the cheapest 21 tools cost ≤130 each (`get_card` is 57). There is no fat
tail to trim — the cost is spread, which is itself an argument against a surgical "delete the rarely
used ones" pass. Run with `--per-tool` for the full breakdown.

**1,387 of the 8,775 (16%) is serializer artefact, not information** — and Phase 2 removed it. FastMCP emits a Pydantic-generated
`title` on every property and on every argument model (`"title": "Board Id"`, `"title":
"list_cardsArguments"`), and renders every optional as `anyOf: [{type: T}, {type: null}]` rather than
`type: [T, null]`. Neither tells a model anything it cannot read off the property name and type. This
saving is available under **any** option and requires no surface change, no renames and no consumer
migration — it is measured as its own row above precisely to separate *hygiene* savings from *surface*
savings.

### Per-task cost — the measurement the card didn't ask for

Resident cost is the easy measurement and the misleading one: a single exec tool has near-zero resident
cost but pays per call, while 49 typed tools pay up front and less per call. So both were measured.

Method: each MCP call is `FastMCP.call_tool()` in-process, counting the tool-result text the client
shows the model plus the JSON `tool_use` block that requests it. Each CLI call is
`uv run python -m pandan_cli …` from `pandan-cli/` (source, never a `$PATH` binary), counting filtered
stdout plus an equivalent `tool_use` block. Mutating measurements ran on a throwaway board created and
deleted by the harness, with card state reset between variants; read-only measurements ran against the
live Roadmap board (id 5, 121 cards).

**Worked example — "find the next ready card, claim it, comment on it"** (7-card scratch board):

| path | calls | tokens |
|---|---:|---:|
| MCP typed tools (`next` → `claim_card` → `add_comment`) | 3 | **622** |
| CLI via exec, step-for-step (`next` → `move` → `update` → `comment add`) | 4 | **372** |
| CLI via exec, collapsed (`next --claim` → `comment add`) | 2 | **185** |

> **Corrected in Phase 2.** The first pass of this table read **345** and **158**, because its
> `comment add` invocation omitted the required `--body` flag: the CLI returned a usage **error**, and
> the measurement counted the error text as if it were a successful result. Re-run with the correct
> invocation, the two CLI totals each rise by 27 tokens. The MCP total re-measured at exactly 622,
> which is what makes the correction trustworthy rather than just different. **A subprocess-based cost
> measurement must assert the exit code** — otherwise a failing command looks like a cheap one, and
> cheap is precisely the answer you are hoping for. The conclusion is unchanged (the CLI is 1.7×–3.4×
> cheaper on this task); the flaw biased it the way flaws usually go, in favour of the hypothesis.

**Second task — "survey the board" (`list` + `metrics` + `get`)**, same 7-card board: MCP **2,041**,
CLI defaults **317**, CLI narrowed with `--fields`/`--format toon` **327** (already at the floor —
narrowing a 7-card board costs more in argument text than it saves).

**The same reads against the real 121-card board**, one call each:

| call | MCP | CLI | ratio |
|---|---:|---:|---:|
| `list --column todo` | 7,014 | 324 | 21.6× |
| `list` (all cards) | 44,605 | 2,689 | 16.6× |
| `metrics` | 2,275 | 1,021 | 2.2× |
| `activity --limit 20` | 2,678 | 895 | 3.0× |
| `epic list` | 4,796 | 476 | 10.1× |
| **total** | **61,368** | **5,405** | **11.4×** |

So the CLI is cheaper per task as well as resident — the card's conclusion holds. But **the reason is
not the tool count**, and this is the finding that drives the decision. Decomposing that 44k
`list_cards` payload (121 cards × 22 keys):

| variant | tokens |
|---|---:|
| as shipped — dict returned to FastMCP, which serializes at `indent=2` | 44,902 |
| same fields, compact JSON | 37,534 |
| narrowed to 5 useful fields, `indent=2` | 7,204 |
| narrowed, compact | 4,954 |
| TSV rows (what the CLI's default human format emits) | 3,276 |

Pretty-printing is only 16% of it; **field breadth is the cost** — 1,111 null/empty values are
serialized across that one page. The gap is therefore **not intrinsic to MCP**. It exists because the
MCP adapter never received V42 (`--fields`), V45 (truncation), V46 (content-first) or V47 (TOON): its
tools return `PandanClient`'s raw dict, and the SDK renders it at `indent=2`
(`mcp/server/fastmcp/utilities/func_metadata.py:539`). A `fields` argument on the read tools would
recover ~84% of it while changing no tool name and removing no capability.

### What the CLI path costs in context, for fairness

Option (b) is not free of resident cost either, and V48 made board state ambient, which is a real
context cost on the CLI side:

| item | tokens | when paid |
|---|---:|---|
| exec-`pandan` tool schema | 387 | every session |
| packaged skill frontmatter (`SKILL.md`) | 168 | every session the skill is installed |
| `SKILL.md` body | 5,785 | once, when the skill is invoked |
| `pandan --help` | 789 | if the agent discovers the grammar itself |
| per-verb `--help` | 59–791 | per verb discovered |
| V48 `SessionStart` ambient block (`pandan context show`) | 471 | every session, and it is board *data*, not overhead |

Even pessimistically (387 + 5,785 = 6,172) option (b) beats today's 8,775 — and unlike the 8,775 it is
paid only when board work actually happens. V48 does weaken the case for resident tools further: the
board state an agent would have spent its first two tool calls fetching is already in the prompt.

## Options considered

### (a) Consolidate to a small verb set — one tool per entity with an `action` argument

Eleven tools (`board`, `card`, `epic`, `card_relation`, `label`, `view`, `cycle`, `template`,
`report`, `notification`, `warmup`), authored in full in the harness so the −51% is measured rather
than estimated. **Rejected.**

- It saves 4,437 resident tokens and does **nothing** about the 44k payload. Wrong lever.
- It dissolves 49 precise schemas into 11 unions in which nearly every argument must be optional. The
  schema can no longer *tell* the model that `claim` needs `assignee` or that `move` needs `column`;
  that knowledge moves into prose and enforcement moves from schema-time to runtime. Cheaper context,
  more invalid calls — and the tokens saved get spent on retries.
- It renames every tool, so every `settings.json` allowlist, the skill's documented 1:1 twin table
  (`SKILL.md`, "When to fall back to MCP") and any prompt naming `mcp__pandan__create_card` break at
  once, for a 2%-of-window saving that prompt caching already amortises.

### (b) A single exec-`pandan` tool, with the CLI as the surface

Best numbers by far: −96% resident, and it inherits the CLI's payload shaping for free (the 11.4×).
**Rejected for now, on two concrete blockers rather than on principle.**

- **It would regress parity, which ADR 0005 forbids.** `update_board` and `delete_board` have no CLI
  verb at all; `claim_card` and `create_cards` lose atomicity and round-trip batching. Until the CLI
  closes those, "let the CLI be the surface" means "delete four capabilities".
- **The published image has no CLI to exec.** [`mcp/Dockerfile`](../../mcp/Dockerfile) copies only
  `pandan-client/` and `mcp/` (lines 26–28); `pandan-cli/` is absent and is not a dependency of
  `mcp/pyproject.toml`. Shipping (b) means bundling the CLI into the image, which couples every MCP
  release to the CLI's version-bump guard and ships two copies of the argument surface.
- It also converts a typed, schema-validated surface into a stringly-typed one for every consumer, to
  fix a cost that is mostly fixable inside the existing tools.

One correction to how the card frames this option, because it affects the reasoning: **an exec tool is
executed by the MCP *server*, not by the model.** A client whose model has no shell tool can still
call it. So (b) is not literally "useless to a shell-less agent" — what such a consumer actually loses
is typed argument validation and in-schema discovery, having to learn the grammar through `--help`
round-trips instead. That is a lesser cost than the card assumes, and it is *not* why (b) is rejected;
the parity and packaging blockers are.

### (c) Keep the breadth as the documented fallback and freeze its growth — **chosen**

## Decision

**Adopt (c).** Keep all 49 tools as the documented fallback for a consumer that cannot run the CLI,
**freeze the surface against growth**, and attack the cost where the measurement says it actually is.

1. **Freeze.** Pin the surface at exactly today's 49 names *and* the count, so adding a tool requires
   amending this ADR rather than merely appending a decorator. The MCP server stops being the place
   new capability lands by default; the CLI is.
2. **Take the free 16%.** Strip the generated `title` keys and collapse `anyOf[{T},{null}]` →
   `type: [T, null]`. 8,775 → 7,388 with no rename, no removal, no consumer migration, no parity
   question.
3. **Document the breadth as a fallback**, in `mcp/README.md` and in the skill — and **fix the skill's
   false "full parity" claim**, which currently asserts bidirectional parity in bold and contradicts
   itself 40 lines later. State the direction (MCP ⊇ CLI) and list the four gaps.
4. **Do not touch the tool names, the `pandan_client` core, or any capability.** `pandan-client`
   remains the shared core under both adapters, exactly as ADR 0005 intends.

### How Phase 2 executed it

- **The freeze** is [`mcp/tests/test_schema.py`](../../mcp/tests/test_schema.py): `FROZEN_TOOLS`
  (the one place the name set now lives — `test_server.py` imports it) plus `FROZEN_TOOL_COUNT`, both
  asserted, failing with a message that explains *why* the pin exists and warns that a removal needs a
  CLI-parity check first. Mutation-tested in both directions.
- **The compaction** is [`mcp/pandan_mcp/schema.py`](../../mcp/pandan_mcp/schema.py), applied once at
  import in `server.py` after every decorator has registered.
- **The documentation** is `mcp/README.md` § *Why 49 tools, and why that is frozen*, which carries the
  numbers and the rejected options so the decision is not re-litigated from the resident-cost headline.
  The skill's false parity claim was fixed separately by the maintainer (it lives outside this repo).
- **The harness** now imports the production compaction function instead of duplicating the rule, so a
  future change to the rule cannot silently invalidate the published measurement.

Deliberately **out of V49's scope**, and filed as follow-ups because they are where the tokens are:

- **A `fields` argument on the MCP read tools** (`list_cards`, `get_card`, `list_epics`, `activity`,
  `metrics`), plus V45-style truncation — measured at ~−84% on a real board read, i.e. roughly ten
  times the saving any resident-surface change offers. This is the actual V49 finding.
  > **✅ Landed 2026-07-31 as KAN-501** (PR #229), and the prediction held: **−82% across five real
  > reads** (58,413 → 10,405 `o200k_base`), with `list_cards` alone 48,291 → 7,430 (−85%). It cost
  > **+552 resident tokens** (7,388 → **7,940**, +7.5%) — repaid ~74× by a single narrowed
  > `list_cards`, which is the trade this ADR predicted would be "obviously right". Re-runnable via
  > `mcp/scripts/measure_read_payload_tokens.py`. The tool count is unchanged, so the freeze below is
  > untouched. Also measured and **declined**: returning a pre-serialized compact string (a further
  > −30%) would restring the `dict[str, Any]` output contract every consumer reads, to chase the
  > smaller half.
- **Closing the four CLI gaps** (`board get/update/delete`, an atomic claim of a named card, a batch
  create). That is the precondition that would make option (b) *available* later, and it should be
  done for the CLI's own sake regardless.

## Why not remove anything — the precedent

This project has retired surface area twice, and both times the standard was the same: **remove a
mechanism only once its replacement exists and nothing depends on it.** ADR 0015 deleted the
`API_TOKENS` SERVICE bypass outright — but only after PATs (ADR 0014) had fully replaced it and the
maintainer was already on one. ADR 0010 was marked *superseded* rather than deleted, because its
replacement was named and complete.

Neither condition holds here. The MCP surface is the only entry point for a consumer without a
Python/uv checkout, four of its capabilities have no CLI equivalent, and the published image cannot run
the CLI. Removing tools now would be retiring a mechanism *ahead* of its replacement — the inverse of
the precedent. Freezing is the honest intermediate state, and it is reversible in the direction we
want: once the CLI closes the gaps and the image carries it, (b) becomes a real option and this ADR can
be superseded by one that takes it.

## Consequences

- **Positive:** no consumer breaks, no capability disappears, no tool is renamed, ADR 0005 parity is
  intact. The surface stops growing, which is the durable part of the win — the drift this slice was
  really about. The measurement is committed and re-runnable, so the next person to ask this question
  starts from numbers. And 16% of the resident cost goes away for free.
- **Neutral:** the resident 7,388 tokens stay. At ~3.7% of a 200k window, prompt-cache-stable across a
  session's turns, that is a price worth paying for a typed fallback surface — and it is an order of
  magnitude less than what a single un-narrowed board read costs today.
  > **Update 2026-07-31:** now **7,940** (~4.0%) after KAN-501 added `fields`/`full` to the read tools.
  > The +552 is the price of the −82% per-read win recorded above.
- **Negative / deferred:** the expensive problem is *named but not fixed* by this slice. Until the
  `fields` follow-up lands, an agent that calls `mcp__pandan__list_cards` on a busy board still burns
  ~45k tokens in one result, and the mitigation is advice ("prefer the CLI") rather than a mechanism.
  The four CLI parity gaps also remain, so the skill's fallback guidance stays load-bearing rather than
  vestigial.
  > **Update 2026-07-31 — the first half is fixed, the second is not.** KAN-501 replaced the advice with
  > a mechanism: an un-narrowed `list_cards` is now the caller's choice, not the only option. **The four
  > CLI parity gaps remain open (KAN-502)**, so the skill's fallback guidance is still load-bearing, and
  > option (b) is still unavailable — that part of this consequence stands as written.
- **Falsified by measurement, recorded so it is not re-assumed:** the surface is 49 tools, not 48; the
  CLI is *not* at full parity with MCP; and the resident schema cost — the thing the card is about — is
  a small fraction of what the MCP path actually costs an agent per task.

### Two traps the compaction turned up, worth keeping in the record

Both were found while implementing the "provably cosmetic" change, which is a useful reminder that
*cosmetic* is a claim requiring proof, not a category that exempts you from it.

1. **A nullable enum must not be collapsed.** `anyOf: [{enum: [...], type: string}, {type: null}]`
   accepts a member *or* `null`; the collapsed `{enum: [...], type: [string, null]}` **rejects null**,
   because `enum` constrains the whole value and `null` is not a member. So the collapse is
   **allow-listed** to sibling keys that are provably inert for `null` (`items`,
   `additionalProperties`) and blocks on anything else, including keywords nobody has reasoned about
   yet. This costs 42 tokens and is the difference between a cosmetic change and a silent narrowing of
   the advertised contract.
2. **`title` is both a JSON Schema annotation and a real argument name.** `create_card` and
   `update_card` both take a `title`. The first implementation recursed blindly, dropping every key
   called `title` at any depth — and **deleted those arguments from both tools**: a genuine behaviour
   change wearing a cosmetic disguise. Three invariant tests (argument-name preservation,
   validator/advertised agreement, and the required-set check) caught it immediately. The traversal is
   now driven by JSON Schema keywords, and the specific case has its own named guard.

The general lesson, and the reason the safety argument is structured the way it is: FastMCP keeps the
*advertised* schema (`Tool.parameters`, built at `tools/base.py:84`) separate from the *validating*
model (`fn_metadata.arg_model`, used by `Tool.run` at `tools/base.py:101`). That separation is what
makes this change safe — but "I only touched the advertised copy" is an assertion about a third-party
library's internals, so it is pinned by a test rather than trusted.
