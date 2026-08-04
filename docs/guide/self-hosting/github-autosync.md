<!--
title: "GitHub auto-sync"
description: Move cards automatically when a pull request opens or merges, using a signed GitHub webhook.
-->

# GitHub auto-sync

Auto-sync connects a repository to a board. Open a pull request on a branch named after a card and the
card gets the PR attached. Merge it and the card can move to `done`.

It needs no CI job and no polling. GitHub posts to your instance, and your instance verifies the
signature.

## How a card gets matched

Everything keys off a **ticket reference** found in the event. Auto-sync looks for `KAN-<n>`,
case-insensitively, in:

- the pull request branch name
- the pull request title
- the head branch, for CI events

So `feat/KAN-42-webhook` matches card `KAN-42`, and so does a PR titled `KAN-42: webhook receiver`. A
branch called `feature/login` matches nothing and the event is silently ignored.

Once a ticket resolves to a card, auto-sync finds that card's board and proceeds only if the board has
opted in.

## What it does

| GitHub event | Effect on the card |
| --- | --- |
| `pull_request` opened or reopened | Attach the PR URL as a `PR` work link. Idempotent, so the same URL is never added twice. |
| `pull_request` closed **and merged** | Move the card to `done`, but only if the board opted into auto-advance. |
| `check_suite` | Post a comment summarising the CI result. |
| `status` | Post a comment summarising the CI result. |

Comments posted by auto-sync have no author. It is the system speaking, not a user.

## Setting it up

### 1. Set the server secret

Auto-sync does nothing until the server has a `WEBHOOK_SECRET`. Generate one and set it:

```bash
openssl rand -hex 32
fly secrets set WEBHOOK_SECRET=<that value>     # or your platform's equivalent
```

!!! info "Unset means off, not broken"

    Without `WEBHOOK_SECRET` the endpoint returns `503`, which is the honest answer: the feature is not
    configured. A request with a bad or missing signature returns `401`.

    This is separate from `AUTH_SECRET`. Do not reuse one for the other.

### 2. Create the webhook in GitHub

In the repository, go to **Settings** then **Webhooks** then **Add webhook**.

| Field | Value |
| --- | --- |
| Payload URL | `https://<your-instance>/api/v1/webhooks/github` |
| Content type | `application/json` |
| Secret | The same value you set as `WEBHOOK_SECRET` |
| Events | "Let me select individual events", then tick **Pull requests**. Add **Check suites** and **Statuses** if you want CI comments. |

Do not select "Send me everything". The endpoint ignores what it does not handle, so it costs nothing but
noise.

### 3. Opt the board in

Both switches default to off, so nothing happens until you turn them on.

```bash
pandan board update 5 --autosync-enabled
pandan board update 5 --autosync-advance-to-done      # optional, separate
```

| `autosync_enabled` | `autosync_advance_to_done` | Behaviour |
| --- | --- | --- |
| off | anything | Nothing happens. |
| on | off | PR links attach and CI comments post. Merging does not move the card. |
| on | on | All of the above, plus a merge moves the card to `done`. |

!!! tip "Start with auto-advance off"

    Link attachment is safe and reversible. Automatically moving a card to `done` on merge is a
    judgement call about your process, since a merged PR is not always finished work. Run with links only
    for a while first.

## Verifying it

Open a pull request from a branch named `test/KAN-<n>-something`, using a card that exists on your
opted-in board. Within a few seconds the card should have a `PR` work link.

Check the delivery in GitHub under the webhook's **Recent Deliveries** tab, which shows the exact request
and your instance's response.

### When nothing happens

Work through these in order:

1. Does the branch or PR title contain `KAN-<n>`?
2. Does a card with that ticket actually exist?
3. Is it on a board with `autosync_enabled` on?
4. Is `WEBHOOK_SECRET` set on the server? A `503` in Recent Deliveries means it is not.
5. Does the secret in GitHub match the server's exactly? A `401` means it does not.

A merge that does not move the card is almost always `autosync_advance_to_done` still being off, which is
the default.

## The outbound direction

Auto-sync is inbound. There is also an outbound webhook, which posts to a URL of yours whenever a
notification is created on the board. It uses the same signature scheme, so a consumer verifies it the
same way.

```bash
pandan board update 5 --outbound-webhook-url https://example.com/hook
printf %s 'your-secret' | pandan board update 5 --outbound-webhook-secret-stdin
pandan board update 5 --outbound-webhook-enabled
```

Three things to know:

**The secret is write-only.** You can set it, and no read returns it, including `board get`. Lost means
replaced.

**Delivery cannot block a write.** It fires after the transaction commits, so a slow or dead endpoint is
logged and dropped, never rolled back into the mutation that caused it.

**There is no retry queue.** One attempt by default, tunable with `OUTBOUND_WEBHOOK_RETRIES`. A missed
delivery is missed. Treat it as a notification channel, not a reliable event log; for that, read
[activity](../tutorial/collaboration.md#activity).

## Security notes

The signature is HMAC-SHA256 over the raw request body, sent as `X-Hub-Signature-256`, which is GitHub's
own scheme. Verification happens before the body is parsed.

The endpoint is rate limited in its own tier, so a flood of deliveries cannot starve the rest of the API.

Since a ticket reference in a branch name is all it takes to match a card, anyone who can open a pull
request on your repository can attach a link to a card. That is usually fine, and worth knowing if the
repository is public.

## Recap

1. Set `WEBHOOK_SECRET` on the server.
2. Add the webhook in GitHub with the same secret, ticking Pull requests.
3. `pandan board update <id> --autosync-enabled`.
4. Leave auto-advance off until you trust it.

Reference the ticket in your branch name and the rest happens on its own.
