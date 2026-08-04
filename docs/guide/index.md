<!--
title: "Pandan"
description: Pandan is an API-first kanban board built so that agents and humans can drive the same work, through the same API, with the same permissions.
-->

# Pandan

<p style="font-size: 1.15rem; color: var(--md-default-fg-color--light);">
A kanban board that agents can actually use.
</p>

---

**Documentation**: <https://leejianrong.github.io/pandan/>

**Source code**: <https://github.com/leejianrong/pandan>

**Live board**: <https://simple-kanban-jian.fly.dev>

---

Pandan is a kanban board with a REST API underneath it, a command-line client on top of that, and an
MCP server next to it. The web UI is one client among three, not the only way in. Anything you can do
by dragging a card, an agent can do with a tool call.

The point is to let a coding agent pick up real work and record what it did, without you translating
between "the board" and "what the agent can see".

## Features

**One API, three clients.** The browser UI, the `pandan` CLI, and the MCP server all talk to the same
`/api/v1` endpoints. There is no capability hiding behind the browser, and no agent-only side door.

**Agents are first-class.** An agent gets its own token, claims a card, attaches the pull request it
opened, comments on what it found, and flags the card for a human when it gets stuck. All of that is
in the API.

**Cheap to read.** Board reads are shaped for a context window. Ask for the four fields you need with
`--fields`, get a token-efficient rendering with `--format toon`, and long descriptions get truncated
by default so one card can't flood an agent's context.

**Scriptable failures.** The CLI exits `3` on unauthorized, `4` on forbidden, and `5` on not-found,
and prints errors as one machine-readable row on stdout. A CI job can branch on auth versus
not-found without parsing prose.

**Keyboard-driven.** Navigate with `j`/`k`/`h`/`l`, move a card with ++shift+arrow-right++, open the
command palette with ++ctrl+k++, and press ++question++ for the full list.

**Boards you can share.** A board has an owner plus members with a `viewer`, `editor`, or `owner`
role, so a teammate can read or write without owning the board.

## Install

Grab the binary for your platform. No Python needed.

```bash
curl -L -o pandan https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64
chmod +x pandan && mv pandan ~/.local/bin/
```

Then point it at a board and log in:

```bash
pandan config set --api-url https://simple-kanban-jian.fly.dev
pandan login
```

That's it. Read your board:

```console
$ pandan overview
https://simple-kanban-jian.fly.dev · board 5 · open cards (todo, in_progress):
KAN-591	todo	pandan overview builds a list envelope in-handler	pts=2
KAN-595	todo	Bake the git revision into the app image	pts=2
8 cards · 8 todo · 0 in_progress · 0 done · 1 needs-human
```

The [installation guide](install.md) covers the other install paths, and
[first steps](first-steps.md) walks through minting a token and finding your board id.

## Where to go next

<div class="grid cards" markdown>

-   **Just getting started**

    [Installation](install.md) then [first steps](first-steps.md). About five minutes to a board you
    can read from the terminal.

-   **Using the board in a browser**

    The [user guide](tutorial/index.md) covers boards, cards, epics, labels, cycles, and the
    [keyboard shortcuts](tutorial/keyboard-shortcuts.md).

-   **Wiring up an agent**

    [Agents and MCP](agents/index.md) sets up the MCP server and shows the workflows an agent runs:
    claim, comment, link, hand back to a human.

-   **Scripting and CI**

    The [CLI guide](cli/index.md) has the output formats, the exit codes, and a warmup pattern for
    CI jobs.

-   **Running your own**

    [Self-hosting](self-hosting/index.md) covers Docker, the environment variables, and deploying
    the single artifact.

-   **Looking something up**

    [Reference](reference/api.md) has the REST surface, the [glossary](reference/glossary.md), and
    the error codes.

</div>

## A note on the name

The product is Pandan and the command is `pandan`. Ticket numbers still read `KAN-123` and
`EPIC-4`, and the hosted board still lives at `simple-kanban-jian.fly.dev`. Those are deliberate
leftovers from an earlier name, kept because renaming them would break ticket history and log every
user out. See [design decisions](about/design-decisions.md) if you want the reasoning.
