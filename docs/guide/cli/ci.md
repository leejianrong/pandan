<!--
title: "In CI"
description: Run the pandan CLI from a CI job: warm the API, keep the token secret, and avoid the patterns that wedge a pipeline.
-->

# In CI

The CLI is a single binary with three settings and no interactive prompts, which is most of what a CI
job needs. This page covers the rest.

## Install it in a job

```yaml
- name: Install pandan
  run: |
    curl -fsSL -o /usr/local/bin/pandan \
      https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64
    chmod +x /usr/local/bin/pandan
```

`-f` matters. Without it, `curl` writes an error page to the output file and `chmod +x` happily makes
it executable, so the failure surfaces later as a confusing "cannot execute binary file".

!!! tip "Pin the version for reproducibility"

    `releases/latest` moves. To keep a pipeline stable, pin a tag and check the version afterwards:

    ```yaml
    - run: |
        curl -fsSL -o /usr/local/bin/pandan \
          https://github.com/leejianrong/pandan/releases/download/v0.22.0/pandan-linux-x86_64
        chmod +x /usr/local/bin/pandan
        pandan --version    # fails loudly if the asset was not what you expected
    ```

## Configuration

Use environment variables. They are the first source the CLI checks, and CI secret stores inject them
natively.

```yaml
env:
  PANDAN_API_URL: https://simple-kanban-jian.fly.dev
  PANDAN_TOKEN: ${{ secrets.PANDAN_TOKEN }}
  PANDAN_BOARD_ID: "5"
```

Mint a token specifically for CI, name it after the pipeline, and revoke it when the pipeline goes
away. A token authenticates as the user who created it, so a CI token can reach every board that user
can. Treat it as a credential for the whole account, not for one board.

!!! danger "Never echo the token"

    `pandan config show` redacts it, which is safe to run in a job. `env | grep PANDAN` is not, and
    neither is `set -x` around a `login` call.

## Warm the API first

The hosted board scales to zero, so the first request after an idle period takes about a second, and
under a cold start it can briefly refuse connections. `warmup` needs no token and exits `0` only once
the API answers, so loop on it:

```bash
until pandan warmup; do sleep 2; done
pandan list --column todo
```

Give the loop a ceiling so a genuinely broken deploy fails the job instead of hanging it:

```bash
for i in $(seq 1 30); do
  pandan warmup && break
  sleep 2
done
pandan warmup || { echo "API did not come up after 60s"; exit 1; }
```

!!! warning "A failing warmup loop can mean a misconfigured origin"

    `warmup` reports `server not ready yet (ConnectError)` both when the API is cold and when nothing
    is listening at all. If the loop never terminates, check `PANDAN_API_URL` before blaming the
    deploy. A missing origin falls back to `http://localhost:8000`, which in CI is nothing.

## A worked example

Move the card named in a branch to `in_progress` when a pull request opens, and attach the PR link:

```yaml
name: Board sync
on:
  pull_request:
    types: [opened]

jobs:
  claim:
    runs-on: ubuntu-latest
    env:
      PANDAN_API_URL: https://simple-kanban-jian.fly.dev
      PANDAN_TOKEN: ${{ secrets.PANDAN_TOKEN }}
      PANDAN_BOARD_ID: "5"
    steps:
      - name: Install pandan
        run: |
          curl -fsSL -o /usr/local/bin/pandan \
            https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64
          chmod +x /usr/local/bin/pandan

      - name: Wake the API
        run: until pandan warmup; do sleep 2; done

      - name: Update the card
        run: |
          # a branch like feat/kan-591-cursor-flag
          ticket=$(echo "${{ github.head_ref }}" | grep -oiE 'kan-[0-9]+' | tr 'a-z' 'A-Z')
          [ -n "$ticket" ] || { echo "no ticket in branch name, nothing to do"; exit 0; }

          pandan get "$ticket" >/dev/null
          case $? in
            0) ;;
            5) echo "$ticket does not exist, skipping"; exit 0 ;;
            *) echo "lookup failed"; exit 1 ;;
          esac

          pandan move "$ticket" in_progress
          pandan link add "$ticket" \
            --label "PR #${{ github.event.number }}" \
            --url "${{ github.event.pull_request.html_url }}"
```

Two things worth copying from that: a missing ticket exits `0` because it is not an error for a branch
to have no card, and a `5` from `get` is handled separately from a real failure.

!!! info "There is a webhook for this"

    If all you want is PR-to-board syncing, the server does it natively with a signed GitHub webhook,
    no CI job required. See [GitHub auto-sync](../self-hosting/github-autosync.md).

## Reporting from a job

Post the board state into a job summary:

```bash
{
  echo '## Board'
  echo '```'
  pandan overview
  echo '```'
} >> "$GITHUB_STEP_SUMMARY"
```

Or query for something a pipeline should fail on:

```bash
blocked=$(pandan list --needs-human --json | jq '.summary.count')
if [ "$blocked" -gt 0 ]; then
  echo "::warning::$blocked card(s) are waiting on a human"
fi
```

## Rate limits

The server rate limits by tier, and full-text search and `metrics` are in the expensive tier. A job
that loops over tickets calling `list --q` will hit it. Over the limit you get a `429` and a
`Retry-After` header.

Prefer one broad query you filter locally over many narrow ones:

```bash
pandan list --column todo --json > cards.json     # one request
jq -r '.cards[] | select(.priority=="high") | .ticket_number' cards.json
```

## Recap

```bash
curl -fsSL -o pandan …/pandan-linux-x86_64 && chmod +x pandan   # -f, always
until pandan warmup; do sleep 2; done                            # with a ceiling
pandan list --column todo --json | jq -r '.cards[].ticket_number'
```

Set the three values from CI secrets, warm the API before authenticated calls, branch on exit codes
rather than text, and batch your reads.
