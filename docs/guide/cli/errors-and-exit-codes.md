<!--
title: "Errors and exit codes"
description: The CLI's exit code table, its machine-readable error row, and how to branch on failure in a script.
-->

# Errors and exit codes

When the CLI fails it tells you two things: an exit code you can branch on, and a structured row you
can parse. Neither requires reading prose, and neither goes to stderr.

## Exit codes

| Code | Meaning | Typical cause |
| --- | --- | --- |
| `0` | Success | |
| `1` | Generic error | Network failure, unreachable origin, a server `5xx` |
| `2` | Usage error | Unknown verb, missing required flag, bad enum value |
| `3` | Unauthorized (`401`) | Token missing, malformed, or revoked |
| `4` | Forbidden (`403`) | Valid token, but no access to that board |
| `5` | Not found (`404`) | No such card, epic or board, including a ticket that matches nothing |
| `6` | Conflict (`409`) | The stored state contradicts the request — e.g. that user is already a member of the board |

The split between `3`, `4`, `5` and `6` is the point. A CI job can tell "my credentials are wrong"
from "that board is not mine" from "that ticket does not exist" from "the board already looks like
that", and react differently, without matching on message text.

The numbers are stable. Rows get **added**, never renumbered, so a script written against `3`/`4`/`5`
keeps working.

!!! note "Why `6` exists, and what it does and does not promise here"

    `6` is shared with [kaya](https://github.com/leejianrong/kaya), pandan's notes sibling. kaya
    adopted this exit table from pandan verbatim, on the ground that an operator scripting both tools
    should never have to remember which is which. In kaya a `409` is a designed, **retryable**
    outcome: `kaya note edit <ref> --if-updated-at <stale>` is refused with a body carrying the
    attempted and the stored note, precisely so the caller can diff them and retry. Exit `1` there
    means "kaya failed", which sends a script either to retry a stale precondition forever or to
    abandon a conflict it could have merged. So kaya added `6`, and pandan added it too rather than
    let the same HTTP status exit `6` from one tool and `1` from the other.

    Be honest about the pandan side of that trade: pandan's own `409`s are **terminal, not
    retryable**. A duplicate board member does not become addable on a re-read, and a card write with
    no board to default to needs you to create a board, not to try again. pandan gains the sameness
    more than it gains retry semantics — which is still worth having, because telling "already a
    member" from "the API is unreachable" without parsing stdout is a real improvement on its own.

    It is deliberately not `2`. `2` means *your input was rejected*; a `409` is well-formed input
    meeting an inconvenient world.

## The error row

Errors print on **stdout**, as one tab-separated row:

```console
$ pandan get KAN-99999
error	not_found	no card found with ticket KAN-99999	KAN-99999
$ echo $?
5
```

Four fields: the literal `error`, a stable machine code, a human message, and the offending argument
(`-` when there isn't one).

```console
$ PANDAN_TOKEN=pandan_pat_bogus pandan list
error	unauthorized	401: bad or expired token — set PANDAN_TOKEN to a valid PAT	-
$ echo $?
3
```

!!! tip "Nothing important goes to stderr"

    You never have to merge streams with `2>&1` to catch an error. Deprecation notices are the only
    thing written to stderr, so stdout stays parseable.

## Structured errors

Under `--format json` the same failure comes back as an object:

```console
$ pandan get KAN-99999 --json
{
  "error": {
    "code": "not_found",
    "message": "no card found with ticket KAN-99999",
    "arg": "KAN-99999",
    "status": null,
    "exit_code": 5
  }
}
```

So branching is a one-liner:

```bash
code=$(pandan get "$TICKET" --json | jq -r '.error.code // "ok"')
```

The `code` values are stable: `not_found`, `unauthorized`, `forbidden`, `conflict`, `usage`, `error`.

## Handling failure in a script

Branch on the exit code:

```bash
#!/usr/bin/env bash
set -uo pipefail        # note: not -e, we want to inspect the code

pandan get "$TICKET" >/tmp/card.txt
case $? in
  0) echo "found it" ;;
  3) echo "token is bad, refresh it"; exit 1 ;;
  4) echo "that board is not ours, skipping"; exit 0 ;;
  5) echo "no such ticket, nothing to do"; exit 0 ;;
  6) echo "already in that state, nothing to do"; exit 0 ;;
  *) echo "unexpected failure"; cat /tmp/card.txt; exit 1 ;;
esac
```

!!! warning "`set -e` and exit codes do not mix well here"

    With `set -e`, a `3` from `pandan` kills the script before you can distinguish it from a `5`. Drop
    `-e` around the calls you want to inspect, or guard them with `|| true` and read `$?`.

Distinguish "no results" from "failed". An empty result is a success:

```console
$ pandan list --column done --assignee nobody
0 cards · 0 todo · 0 in_progress · 0 done
$ echo $?
0
```

A query that matches nothing exits `0` with a zero summary. Only a genuine failure is non-zero, so
`if pandan list …` does not silently treat an empty board as broken.

## Prompts and non-interactive use

No verb prompts when stdin is not a terminal. `pandan login` with no piped token fails rather than
hanging, which means a CI job cannot deadlock waiting on input nobody will type.

```bash
printf %s "$PANDAN_TOKEN" | pandan login --token-stdin   # correct in CI
```

## Recap

- Exit `3`, `4`, `5`, `6` for unauthorized, forbidden, not-found, conflict. `2` for usage, `1` for
  everything else.
- Errors are one tab-separated row on stdout, or `{"error": {…}}` under `--json`.
- An empty result is exit `0`, not a failure.
- Nothing prompts when stdin is not a terminal.

Next: [in CI](ci.md), which puts these together.
