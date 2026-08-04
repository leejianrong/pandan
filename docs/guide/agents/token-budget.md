<!--
title: "Token budget"
description: What a Pandan read actually costs an agent in tokens, where the cost really is, and how to cut it.
-->

# Token budget

If you are paying per token, a board is a surprisingly expensive thing to read. This page is the
measured version of that problem, and what to do about it.

All figures are `o200k_base` tokens and come from two scripts in the repository, so you can re-run them
rather than trust the numbers here:

```bash
uv run --project mcp mcp/scripts/measure_tool_schema_tokens.py
uv run --project mcp mcp/scripts/measure_read_payload_tokens.py
```

## Where the cost actually is

The intuition is that 49 tools must be expensive, because their schemas sit in context for the whole
session. That turns out to be the smaller half of the problem.

| Cost | Tokens | When you pay it |
| --- | --- | --- |
| Resident tool schemas | **8,162** | Once per session |
| `outputSchema`, if your client forwards it | +836 | Once per session |
| One unnarrowed `list_cards` on a real board | **~45,000** | Every time you call it |
| One `list_notifications` over 127 rows | **14,326** | Every time you call it |

A single careless read costs more than five times the entire tool surface. So the answer was not to cut
tools. It was to make reads shapeable and then actually shape them.

## What shaping buys

Adding `fields` and `full` to the reads where the tokens were cost **552** resident tokens and saved
about **82%** across five representative reads. A later pass extended three more tools for another
**222** resident tokens, which is where the 8,162 figure comes from.

Nine other reads were left deliberately unshaped, because they return between 7 and 474 tokens each.
Adding arguments to shape a payload that small costs more schema than it could ever save, and a test
pins them that way so nobody "improves" them later.

## Cutting a read down

Start with the filter, then the fields.

```json
{ "name": "list_cards", "arguments": { "column": "todo" } }
```

```json
{
  "name": "list_cards",
  "arguments": {
    "column": "todo",
    "fields": ["ticket_number", "title", "priority", "assignee"]
  }
}
```

The second one is the version to write. `fields` drops every field you did not ask for, including the
long `description` that dominates a card payload.

For the CLI the equivalent is `--fields`:

```bash
pandan list --column todo --fields ticket,title,priority,assignee
```

### Truncation is on by default

Free text is cut at 500 characters with a hint saying how much was dropped:

```
(truncated, 3127 chars total — use --full to see complete body)
```

This is deliberately the default rather than an option, because one card with a long write-up can
otherwise fill a context window on a single `get`. Pass `full` only when you genuinely need the whole
body, and read the hint first to see what you are asking for.

### Pick the cheapest format

For the CLI, output format matters as much as field selection:

| Payload | Cheapest | Why |
| --- | --- | --- |
| Flat list of cards | `human` | Tab-separated, no keys at all |
| One card in detail | `toon` | Structured, field names printed once |
| `metrics`, `activity` | `toon` | Nested but uniform |
| Anything parsed by a program | `json` | The only format with a stable schema |

`toon` prints a uniform array's field names once in a header instead of repeating them per row, which
is where JSON spends most of its budget on list payloads.

### Let the summary do the counting

Every list read ends with a pre-computed aggregate:

```
42 cards · 12 todo · 5 in_progress · 25 done · 3 needs-human
```

Never fetch rows just to count them. The counts ride along with whatever you already asked for, and
under `--format json` they arrive as a `summary` object.

## MCP or the CLI

Measured per task, the CLI came out roughly **11 times cheaper** than the MCP server. Two reasons: MCP
carries tool schemas in every session whether or not you use them, and its payloads were fuller.

Shaping closed most of the payload half of that gap. The resident schema half does not go away, because
that is what an MCP session is.

So: if your agent has an MCP client and token cost is not your binding constraint, use MCP, because
structured tool calls are more reliable than parsing output. If token cost dominates, or the agent can
shell out anyway, the CLI is leaner.

!!! info "There is no single-tool option yet"

    Collapsing the whole surface into one tool that just runs `pandan` was considered and would cut
    resident schema to almost nothing. It needs the published container image to carry the `pandan`
    binary, which it does not, so the idea stays open rather than adopted.

## A cheap session opener

Three calls that establish what matters, for well under a thousand tokens:

```
warmup()
list_cards(column="in_progress", fields=["ticket_number", "title", "assignee"])
list_cards(needs_human=true, fields=["ticket_number", "title", "attention_note"])
```

Compare that with one unnarrowed `list_cards` at around 45,000 tokens, which tells you less.

## Recap

- Resident schema is 8,162 tokens. One careless read is 45,000. Optimise the read.
- Always filter server-side, then pass `fields`.
- Leave truncation on. Pass `full` only when you need the body.
- `human` for flat lists, `toon` for nested reads, `json` only for programs.
- Use the summary line instead of counting rows.

The full reasoning, including the options that were rejected, is in
[design decisions](../about/design-decisions.md).
