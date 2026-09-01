# ADR 0019 — MCP surface right-sizing: keep the breadth, freeze its growth

- **Status:** Accepted — and **executed**. Phase 1 (measure + decide) and Phase 2 (freeze + compact +
  document) have both landed. Nothing was removed and no tool was renamed.
- **Date:** 2026-07-31 · **amended 2026-08-01 (KAN-518)** — the resident measurement omitted
  `outputSchema` silently; it is now measured as its own bracketed row, deliberately kept out of the
  headline, and deliberately **not** compacted. See [*The fourth field*](#the-fourth-field-outputschema-kan-518).
  Superseded figures below are annotated, not deleted. · **amended 2026-09-01 (M9 V69, KAN-1058)** —
  the freeze's first actual growth: **+5 tools** (49 → 54), a `team` CRUD group mirroring the `board`
  one 1:1. See [*Amendment: the M9 team tools*](#amendment-the-m9-team-tools-2026-09-01-kan-1058) for
  the measured delta and why team *membership* management stayed CLI-only.
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

1. **The resident cost is real but it is not where the tokens are.** The whole 49-tool surface cost
   **8,775** tokens *as measured at V49* (**8,162** at `6c87260` — see the amendment note under
   *Measurement*). A *single* `list_cards` call against the live Pandan Roadmap board returns
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

> **Amended 2026-08-01 (KAN-585): every figure here is also INTERPRETER-sensitive, which nothing said.**
> Python **3.13+ dedents docstrings at compile time**, worth ~215 tokens across the 49 tool
> descriptions. The published option (a)/(b) figures (4,338 / 387) reproduce on **3.13+ only**; on 3.12
> they read slightly higher. The SDK version, by contrast, moves nothing — 1.28.1 and 2.0.0 print
> byte-identical tables on both 3.12 and 3.14. So when a number here fails to reproduce, check your
> interpreter before suspecting the surface.
>
> **Amended 2026-08-01 (KAN-518): this unit counts three of a `tools/list` entry's four fields, not
> all of them.** A tool definition also carries an **`outputSchema`**, which every figure in this
> section excludes. That is a defensible choice and it is now an explicit one — see
> [*The fourth field*](#the-fourth-field-outputschema-kan-518) below for the measurement, the bracket,
> and why it stays out of the headline. Before KAN-518 a reader had no way to know the field existed.

> **Amended 2026-08-01 (KAN-518): the two rows below are a V49-era snapshot, and re-running the
> harness today will not reproduce them.** The harness derives both rows live, and the surface has
> since gained *arguments* (not tools): KAN-501 added `fields`/`full` to five read tools, KAN-517 to
> three more. At `6c87260` the same script prints **9,678 → 8,162** where V49 printed 8,775 → 7,388.
> The **−16%** compaction saving is what this table is actually about, and it has held exactly.

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

### The fourth field: `outputSchema` (KAN-518)

*Added 2026-08-01. Measured at `6c87260`, the tip of `main` after KAN-517.*

Raised by the KAN-501 agent as an observation it deliberately declined to put a number to, which was
the right call: guessing would have manufactured a figure in the one document whose value is that its
figures are measured. Here is the number, and the decision that follows it.

Every one of the 49 tools carries an `outputSchema`, generated by FastMCP from the `-> dict[str, Any]`
return annotation. All 49 are the identical three-key object:

```json
{"additionalProperties": true, "title": "list_cardsDictOutput", "type": "object"}
```

**The measurement, as its own bracketed row — deliberately not folded into the headline:**

| surface | tools | `outputSchema` alone, compact | alone, `indent=2` | all four fields, compact | all four, `indent=2` |
|---|---:|---:|---:|---:|---:|
| **49 typed tools, as shipped** | **49** | **836** | **1,277** | **9,145** | **12,919** |
| (a) one tool per entity + `action` | 11 | 179 | 278 | 4,550 | 7,027 |
| (b) single exec-`pandan` tool | 1 | 17 | 26 | 407 | 491 |

Re-runnable: `cd mcp && uv run --with tiktoken python scripts/measure_tool_schema_tokens.py` now
prints this as a second table under the headline one.

Two things the row settles. **It is driven by tool count, not argument count** — 836 / 179 / 17 across
49 / 11 / 1 tools is a flat ~17 compact tokens each, because the object's size does not depend on the
signature. So the argument-adding slices that moved the headline (KAN-501, KAN-517, and anything like
them) cannot move this figure at all; only the freeze can. And **the headline understates a
forwarding client by ~12%**: 8,162 → 9,145 compact (the +983 rather than +836 is the extra `"output_schema"`
key and its separators), 11,348 → 12,919 at `indent=2`.

**Decision 1 — the published resident figure stays `input_schema`-only, and the ADR now says so.**
The headline's unit is "what a client puts in the **model's** context", and whether `outputSchema`
gets there is genuinely client-dependent and not observable from inside the server. The concrete
evidence, rather than a shrug: the **Anthropic Messages API tool definition has no `output_schema`
field**, so a client bridging MCP to that API has nowhere to put it and the model-context cost is
zero; an MCP-native client that forwards the whole tool definition pays the full 836. A single
headline number cannot be true for both, which is the same reason this section brackets compact
against `indent=2` instead of claiming one figure. So: the bracket above is the honest form, and the
real defect KAN-518 fixed is not the missing number — it is that **the omission was silent**. It no
longer is.

**Decision 2 — do not compact it.** The 49 generated `…DictOutput` titles are the same class of
Pydantic artefact Phase 2 stripped from `inputSchema`, and stripping them here would take 836 → **490**
compact (−346, −41%). It is declined anyway, because **V49's safety argument does not transfer**, and
the difference is structural rather than a matter of care:

- For `inputSchema` the advertised and validating schemas are *separate objects* — `Tool.parameters`
  vs. `fn_metadata.arg_model` — **and** FastMCP registers its handler with `validate_input=False`
  (`mcp/server/fastmcp/server.py:308`), so the lowlevel `jsonschema.validate` against the advertised
  copy (`mcp/server/lowlevel/server.py:534-538`) never fires. Rewriting it provably cannot reach the
  call path.
- For `outputSchema` **neither half holds**. `Tool.output_schema` is a `cached_property` returning
  `self.fn_metadata.output_schema` — the *same dict object*, not a copy
  (`mcp/server/fastmcp/tools/base.py:41-43`) — and the lowlevel server runs
  `jsonschema.validate(instance=maybe_structured_content, schema=tool.outputSchema)` on **every** tool
  result, unconditionally, with no `validate_output` flag to disable it
  (`mcp/server/lowlevel/server.py:566-573`). The advertised copy *is* the live one.

> **Amended 2026-08-01 (KAN-585): the second bullet's line numbers and its *mechanism* are SDK-1.x-only,
> and the decision survives for a different reason.** The port to SDK **2.0.0** (which renamed
> `mcp.server.fastmcp` → `mcp.server.mcpserver` and `FastMCP` → `MCPServer`, wire keys unchanged) moved
> the validation:
>
> - **Server-side, the advertised dict is no longer used at all.** 2.0.0 validates a tool result with the
>   Pydantic `output_model` (`mcp/server/mcpserver/utilities/func_metadata.py:127-143`); the
>   `jsonschema.validate(schema=tool.outputSchema)` call at `lowlevel/server.py:566-573` **is gone**.
> - **The identity still holds** — `Tool.output_schema` is still a `cached_property` returning
>   `fn_metadata.output_schema` (`mcp/server/mcpserver/tools/base.py:53-55`).
> - **The advertised dict is now compiled and enforced by the CLIENT** instead
>   (`mcp/client/session.py`, `_tool_output_validators`).
>
> So "do not compact" **stands, and is firmer**: the blast radius of mutating that object moved from one
> server to every client. But note what happened to the guard. The pinned test asserts the *identity*,
> and its docstring says "if this goes red, the SDK has separated them — re-read the decision rather
> than relaxing the test". **The identity never broke, so the test stayed green while the entire reason
> it mattered was replaced underneath it.** *Generalisable: a test can outlive its rationale without
> ever going red. Pin the fact you can check, but write down the claim it stands for, or a future reader
> inherits a green tick attached to an obsolete argument.*

`title` is a pure JSON Schema annotation and jsonschema ignores it, so the strip would in fact still be
inert — but that is now a claim about a third-party validator's keyword handling plus an in-place
mutation of an object on the request path, where V49's claim was "we never touch the thing that runs".
Paying that for ≤346 tokens of a field that may cost the model nothing is the wrong trade, and V49's
own two traps are the precedent for treating "provably cosmetic" as a claim requiring proof rather
than a category. Pinned by `test_compaction_leaves_output_schemas_untouched` and
`test_the_advertised_output_schema_is_the_object_the_server_validates_against` in
[`mcp/tests/test_schema.py`](../../mcp/tests/test_schema.py) — the second goes red if a future SDK
*does* separate them, which is the signal to re-read this decision rather than relax the test.

**One card claim that did not survive contact,** recorded because the detail is a trap for whoever
does reopen this: the titles are **not** derived from the registered tool name. Pydantic names the
generated model after the *function* (`DictModel.__name__ = f"{func_name}DictOutput"`,
`mcp/server/fastmcp/utilities/func_metadata.py:501`), so the tool registered as `next` — whose function
is `next_ready` (`mcp/pandan_mcp/server.py:577-578`) — advertises `next_readyDictOutput`. A guard
asserting `f"{tool.name}DictOutput"` would be wrong for exactly one of 49 tools.

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

Even pessimistically (387 + 5,785 = 6,172) option (b) beats the V49-era 8,775 (and the current 8,162,
and the 9,145 a client that forwards `outputSchema` pays) — and unlike the resident figure it is
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
  > **✅ Landed 2026-07-31 as KAN-502** (PR #239, `v0.19.0`). All four are reachable: `pandan board
  > get/update/delete` (rename *and* the V38 outbound-webhook trio, secret write-only and readable from
  > stdin), `pandan claim <id> --assignee`, `pandan batch-create`, plus `pandan epic get`. `pandan-client`
  > needed no change — every endpoint was already wrapped and HTTP-tested.
  >
  > **Parity is now pinned in both directions by a test, not a claim:**
  > `pandan-cli/tests/test_parity.py` parses the tool names out of `mcp/pandan_mcp/server.py` *as text*
  > (importing `pandan_mcp` would invert this ADR's own adapter independence), walks the real parser,
  > and asserts MCP ⊆ CLI, CLI ⊆ MCP and `MCP_ONLY == {}`. Its regex is cross-checked against a raw
  > `@mcp.tool` decorator count, so it cannot pass vacuously on an empty set.
  >
  > **Two corrections this landed.** (1) `claim_card` is atomic in the sense of *one invocation*, not
  > *one transaction* — `client.py:420-429` composes `move` then `update` and says so; the transactional
  > claim is `dispatch`, already behind `next --claim`. This ADR's Context above says "claims a *named*
  > card atomically", which overstates it. (2) `update_board` reaches 4 of `BoardUpdate`'s 6 fields:
  > `autosync_enabled` / `autosync_advance_to_done` are reachable from **neither** adapter — an
  > API-coverage gap, not a parity gap, and carded separately.

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
  >
  > **Update 2026-08-01 (measured under KAN-518 at `6c87260`): now 8,162** (~4.1%). KAN-517 extended
  > the same `fields`/`full` shaping to `list_notifications`, `list_boards` and `get_epic`, at +222 on
  > top of KAN-501's +552. Adding *arguments* is not an ADR amendment; adding a *tool* is, and the
  > count is still 49. Anything quoting 7,388, 7,940 or the V49-era 8,775 as the current figure is
  > stale — re-run `mcp/scripts/measure_tool_schema_tokens.py` rather than copying a number forward.
  >
  > **And this figure is `input_schema`-only** — a client that also forwards `outputSchema` pays
  > **9,145** compact. See [*The fourth field*](#the-fourth-field-outputschema-kan-518).
- **Negative / deferred:** the expensive problem is *named but not fixed* by this slice. Until the
  `fields` follow-up lands, an agent that calls `mcp__pandan__list_cards` on a busy board still burns
  ~45k tokens in one result, and the mitigation is advice ("prefer the CLI") rather than a mechanism.
  The four CLI parity gaps also remain, so the skill's fallback guidance stays load-bearing rather than
  vestigial.
  > **Update 2026-07-31 — both halves are now fixed, and option (b) is still unavailable anyway.**
  > KAN-501 replaced the advice with a mechanism: an un-narrowed `list_cards` is the caller's choice, not
  > the only option. KAN-502 then closed the four parity gaps and pinned parity **both ways** with a
  > test, so this bullet's "the four CLI parity gaps also remain" no longer holds.
  >
  > **But option (b) needs *two* preconditions and only one is cleared.** The published ghcr image
  > copies `pandan-client/` and `mcp/` only (`mcp/Dockerfile`), so it contains **no `pandan` binary to
  > exec** — a single exec-`pandan` tool would be unusable in exactly the deployment that most wants it.
  > So (b) remains closed, and this ADR stands rather than being superseded. Reopening it means shipping
  > the CLI inside the image *and* re-measuring, at which point the −96% figure would need re-deriving
  > against an image that carries a second package.
  >
  > The skill's fallback guidance is now *narrower* rather than vestigial: it stops being "MCP can do
  > things the CLI cannot" and becomes "MCP is for consumers that cannot run the CLI at all".
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

## Amendment: the M9 team tools (2026-09-01, KAN-1058)

**The freeze's first actual growth.** Every prior slice that touched the surface (KAN-501, KAN-517,
V51's `key` argument) added *arguments* to existing tools — the freeze's own text says that "is not"
an amendment. Milestone 9 ("Teams", [ADR 0021](0021-organization-team-tier.md)) is the first to ask for
new *tools*, because a team is a new addressable entity (`/api/v1/teams`), not a new field on one that
already has a tool.

**Decision: add exactly 5 tools — `list_teams`, `create_team`, `get_team`, `update_team`,
`delete_team` — mirroring the `board` CRUD group above 1:1, and decline a sixth capability
(team-member management) from this surface entirely.**

- **Why 5, not fewer.** A team is addressable the same way a board is (discover → create → read →
  rename → delete), and ADR 0021's own design gives it the same five REST verbs
  (`/api/v1/teams` `GET`/`POST`, `/api/v1/teams/{id}` `GET`/`PATCH`/`DELETE`). Collapsing to fewer tools
  (e.g. folding `get`/`update`/`delete` behind a shared `team_id` an agent must already have) would
  re-litigate option (a) from this ADR's own *Options considered* — rejected there for dissolving typed
  schemas into unions — at team scale rather than the whole-surface scale it was rejected at.
- **Why not team *membership* (`POST`/`PATCH`/`DELETE /teams/{id}/members`).** This is the part that is
  actually new reasoning, not a restatement of the freeze. **`board_member` — the closest existing
  analogue, with a complete, tested `/api/v1/boards/{id}/members` REST surface and a CLI (`pandan team
  member …` has no board equivalent because none was ever added) — has *zero* MCP tools today**, and
  nobody has asked for one across ten milestones. That is not an oversight; it is the shape of what an
  agent's normal workflow needs: reading and writing *board content* (cards, epics, comments), never
  *who else can see the board*. Team membership is the same kind of call — administrative, human-facing,
  infrequent — so it stays where "new capability goes in the CLI" (this ADR's own §Decision, item 1)
  already says new capability defaults to. `pandan team member add/rm/list/update-role` exist in the
  CLI (M9 V69, KAN-1058) with **no MCP twin**, and `pandan-cli/tests/test_parity.py`'s `CLI_ONLY` dict
  records the decision by name (the same "reason 2" pattern KAN-614's `me` and KAN-982's `label update`
  already established) rather than leaving it as a silent gap `MCP_ONLY` would otherwise have to explain.
- **The board tools grow two arguments, not two tools.** `create_board`/`update_board` gain `team_id`
  (M9 V67, KAN-1056's board↔team link) — an *argument* addition, explicitly not an amendment under this
  ADR's own rule, the same way V51's `key` wasn't.

**Measurement**, via the same harness (`mcp/scripts/measure_tool_schema_tokens.py`), comparing
immediately before and after this change on the same commit/interpreter (methodologically tighter than
comparing against an old headline number, which the *Measurement* section above has already shown
drifts on its own from unrelated argument additions):

| surface | tools | compact | `indent=2` | `outputSchema` alone (compact) |
|---|---:|---:|---:|---:|
| before (main, pre-V69) | 49 | 8,951 | 12,211 | 836 |
| **after (+5 team tools)** | **54** | **9,505** | **12,982** | **922** |
| **delta** | **+5** | **+554 (+6.2%)** | **+771** | **+86** |

+554 compact tokens for five tools is ~111 tokens/tool — close to the ~150-per-tool average V49 found
for the original 49 (8,775 ÷ 49), which is expected: these are typed CRUD tools of the same shape as
`board`'s, not a leaner or richer design. The resident figure most recently recorded in `CLAUDE.md`
(8,641, itself already flagged as drifted) is now **9,505** — re-run the script rather than quoting
either number forward, per that file's own standing advice.

**Both freeze pins were updated in the same PR, per this ADR's own requirement**: `FROZEN_TOOLS` (+5
names) and `FROZEN_TOOL_COUNT` (49 → 54) in [`mcp/tests/test_schema.py`](../../mcp/tests/test_schema.py),
and `pandan-cli/tests/test_parity.py`'s `MCP_TO_CLI` (+5 mappings to `team list/get/create/update/
delete`) and `CLI_ONLY` (+4 entries for the declined `team member` verbs). `mcp/README.md`'s tool table
and *"why the surface is frozen"* section were updated to match.

**Consequence for the freeze's own framing.** "Freeze against growth" always meant *silent* growth —
the pin test's own failure message has said "that is an ADR amendment, not a test edit" since V49. This
amendment is that mechanism doing exactly what it was built for: a deliberate, measured, documented
exception, not evidence the freeze doesn't hold. The next tool addition still needs its own amendment
here, not a precedent-by-example from this one.
