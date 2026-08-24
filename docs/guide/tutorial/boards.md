<!--
title: "Boards"
description: Create and switch boards, and share one with a teammate using viewer, editor and owner roles.
-->

# Boards

A board holds cards and epics. Every card belongs to exactly one board, and every board has exactly one
owner.

## Your first board

You already have one. Logging in for the first time claims a board for you, so there is nothing to
create before you can start.

## Creating another

Use the board switcher in the top bar, or the command palette (++ctrl+k++ then "Jump to board"). From
the CLI:

```bash
pandan board create "Q4 planning"
```

Each board gets a short **key** — `Q4 planning` becomes `Q4P` — derived from the name so that creating
a board never stops to ask you for one. Pick your own with `--key ENG`, or change it later with
`pandan board update <id> --key ENG`; nothing breaks when you do, because a card's own ticket number
never changes.

Keys are unique among your own boards rather than across everybody's, so you are not competing with
other people for the short ones.

Separate boards are the right tool when the work has nothing to do with each other. Two products, or a
work board and a personal one. Within one project, prefer [epics](epics.md) and
[labels](organising.md) over a second board, because cards cannot move between boards and reporting
does not span them.

## Switching

The board switcher in the top bar lists the boards you can reach. Your choice is remembered locally, so
you come back to the same board next time.

!!! tip "Tell the CLI and your agents which board too"

    The web UI remembering your board does not tell the CLI anything. Set it separately:

    ```bash
    pandan board list          # find the id
    pandan config set --board-id 5
    ```

    Without that, CLI list commands span every board you can reach and `create` lands on your earliest
    one. Same for `PANDAN_BOARD_ID` in an agent's config.

## Sharing a board

A board has one owner and any number of members. Open **Members** from the menu to manage them.

Three roles:

| Role | Can read | Can write cards | Can manage members and settings |
| --- | --- | --- | --- |
| `viewer` | Yes | No | No |
| `editor` | Yes | Yes | No |
| `owner` | Yes | Yes | Yes |

Add someone by email or user id. They need an account on the same instance, so on the hosted board they
have to have logged in with GitHub at least once.

Two rules worth knowing:

**Managing members is owner-only.** An editor can create and move cards all day but cannot add or
remove people, or change anyone's role.

**Any member can see the member list.** A viewer can see who else is on the board. Membership is not
secret.

!!! warning "A personal access token inherits your access, not a role"

    A token authenticates as the user who created it and reaches exactly what that user reaches. So if
    you are an `editor` on someone else's board, your token can write to it. If you hand an agent a
    token, the agent has your access on every board you can reach, not just the one you had in mind.

    Mint a token per agent so you can revoke one without breaking the others, and set
    `PANDAN_BOARD_ID` so it stays where you meant it to be.

## Renaming and deleting

Rename from board settings, or:

```bash
pandan board update 5 --name "Pandan Roadmap"
```

Deleting is the dangerous one.

!!! danger "Deleting a board deletes its cards and epics"

    The delete cascades. Cards do not go to the trash, and there is no undo. Move anything you want to
    keep to another board first, though note that "moving" means recreating, since a card cannot change
    boards.

```bash
pandan board delete 5
```

## Board settings

Beyond the name, a board carries integration settings, all off by default:

- **GitHub auto-sync**, which moves cards when a pull request that references them opens or merges. Two
  switches: whether to sync at all, and whether a merge advances a card to `done`. Setup is in
  [GitHub auto-sync](../self-hosting/github-autosync.md).
- **An outbound webhook**, which POSTs a signed payload to a URL of yours whenever a notification is
  created. Useful for piping board events into Slack or your own service.

The outbound webhook secret is write-only. You can set it, and no read ever returns it, including
`board get`. If you lose it, set a new one.

## Recap

- One board, one owner, plus members with `viewer`, `editor` or `owner`.
- Only owners manage members and settings. Every member can see who else is there.
- Cards cannot move between boards, so prefer epics and labels over extra boards.
- Tell the CLI and your agents which board to use; the UI's choice is local to the browser.
- Deleting a board takes its cards with it.

Next: [cards](cards.md).
