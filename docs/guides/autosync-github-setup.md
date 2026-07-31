# GitHub PR-board auto-sync: setup & ops

This guide turns on **auto-sync** — the feature that lets a GitHub repository drive its Simple
Kanban board automatically. When it's on for a board, opening a pull request attaches the PR as a
work-link on the matching card, CI results land as comments, and a merged PR can move the card to
**Done**. It closes the loop so a card reflects real git/CI state without anyone dragging it by hand.

Auto-sync is **off everywhere by default**. Nothing below happens until you (1) configure the
webhook secret on the server, (2) create the GitHub webhook, and (3) opt a specific board in. A board
you never opt in behaves exactly as it always has — you move cards yourself. The design is written up
in ADR [0016](../adr/0016-github-pr-board-autosync.md).

## How the loop works

The board learns about git activity through a single inbound endpoint,
`POST /api/v1/webhooks/github`, that GitHub calls on repository events. The endpoint is
authenticated by GitHub's HMAC signature (a shared secret), **not** by a user session or PAT — the
caller is GitHub, not a logged-in person. See [webhooks.py](../../backend/app/routers/webhooks.py)
and the event-mapping in [autosync.py](../../backend/app/autosync.py).

Every action keys off a **card ticket** parsed from the event. Auto-sync looks for a `KAN-<n>`
(case-insensitive) in the PR branch name or PR title (and, for CI events, the head branch). If it
finds none, the event is a silent no-op — so a branch called `feature/login` is ignored, but
`feat/KAN-42-webhook` or a PR titled `KAN-42: webhook receiver` maps to card `KAN-42`.

Given a ticket, auto-sync resolves the card, finds its board, and only proceeds if that board has
opted in. Then:

| GitHub event | Board effect |
|---|---|
| `pull_request` `opened` / `reopened` | Attach the PR URL as a `PR` work-link on the card (idempotent — the same URL is never added twice). |
| `check_suite` (any action) | Post a card comment summarising the CI result (`status` / `conclusion`). |
| `status` | Post a card comment summarising the CI result (`context` → `state`). |
| `pull_request` `closed` **and merged** | Move the card to **Done** — **only** if the board also opted into auto-advance (see below). |

Comments posted by auto-sync have no author — they're the system speaking, not a user.

## 1. Set the webhook secret on the server

Auto-sync will not run until the server has a `WEBHOOK_SECRET`. This is the shared secret GitHub
uses to sign each delivery; the endpoint recomputes the HMAC-SHA256 over the raw body and
constant-time-compares it against the `X-Hub-Signature-256` header.

Pick a strong random value and set it as a secret. On the hosted Fly.io deploy:

```bash
fly secrets set WEBHOOK_SECRET="$(openssl rand -hex 32)"
```

Keep the value — you'll paste the **same** string into GitHub in the next step.

Endpoint behaviour depending on the secret:

- **`WEBHOOK_SECRET` unset → the endpoint returns `503`.** The receiver refuses to run unconfigured
  rather than skip verification silently, so leaving the secret unset is the effective master
  off-switch for the whole feature.
- **Missing / malformed / mismatched signature → `401`.**
- **A recognised, correctly-signed event → `200`** (and the mapping runs). An unknown event type is
  acknowledged with `200` and ignored.

`WEBHOOK_SECRET` is separate from `AUTH_SECRET` (which peppers PAT hashes and signs sessions) — they
are different secrets with different jobs.

## 2. Create the GitHub webhook

In the GitHub repository whose PRs should drive the board, go to **Settings → Webhooks → Add
webhook** and fill in:

- **Payload URL:** `https://<your-host>/api/v1/webhooks/github`
  (hosted: `https://simple-kanban-jian.fly.dev/api/v1/webhooks/github`).
- **Content type:** `application/json`. (The signature is computed over the raw JSON body, so the
  form-encoded content type will not verify — use JSON.)
- **Secret:** the exact `WEBHOOK_SECRET` value from step 1.
- **Which events:** choose **"Let me select individual events"** and tick:
  - **Pull requests** (`pull_request`) — drives link-attach and merge→done.
  - **Check suites** (`check_suite`) **and/or** **Statuses** (`status`) — either (or both) drives the
    CI-result comments. Pick whichever your CI reports through. GitHub Actions and the Checks API
    report as `check_suite`; older/third-party integrations that use the commit-status API report as
    `status`. Ticking both is harmless.

  The default "just the `push` event" won't do anything here — auto-sync only handles the three
  events above and ignores everything else.

Save. GitHub sends a `ping` (ignored with `200`), and the webhook's **Recent Deliveries** tab shows
the response code for each event — a healthy delivery is `200`, a `401` means the secret doesn't
match, and a `503` means `WEBHOOK_SECRET` isn't set on the server.

## 3. Opt a board in (default OFF)

Even with the webhook live, auto-sync touches **no** board until that board turns it on. Two
independent per-board flags gate it, both defaulting to `false`:

- **`autosync_enabled`** — the master switch for the board. While `false`, every auto-sync action
  (link attach, CI comment, merge→done) is skipped for this board. Turn it on to opt in.
- **`autosync_advance_to_done`** — a **separate** switch that gates only the "move the card to Done
  when its PR merges" action. It has effect only when `autosync_enabled` is also `true`. Leave it
  `false` (the default) to keep auto-sync attaching links and posting CI comments while **you** still
  decide when a card is actually done — the human-in-the-loop safeguard. Turn it on when you trust a
  merge to mean done.

So the four combinations:

| `autosync_enabled` | `autosync_advance_to_done` | Behaviour |
|---|---|---|
| `false` | (any) | Nothing. Hand-move cards as usual. **This is the default.** |
| `true` | `false` | Attach PR links + post CI comments. Merges do **not** move the card. |
| `true` | `true` | All of the above, **and** a merged PR moves the card to Done. |

There's no UI toggle for these yet — set them through the API with `PATCH /api/v1/boards/{id}`,
authenticating with your own PAT (see the [Agent onboarding guide](agent-onboarding.md) for minting
one). Find your board id with `GET /api/v1/boards`.

Turn auto-sync on for board `1`, keeping merge→done off:

```bash
curl -X PATCH https://simple-kanban-jian.fly.dev/api/v1/boards/1 \
  -H "Authorization: Bearer $PANDAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"autosync_enabled": true}'
```

Later, also let merges close cards out:

```bash
curl -X PATCH https://simple-kanban-jian.fly.dev/api/v1/boards/1 \
  -H "Authorization: Bearer $PANDAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"autosync_advance_to_done": true}'
```

To opt back out, `PATCH` `{"autosync_enabled": false}`. Both flags are returned on
`GET /api/v1/boards/{id}` so you can confirm the current state. The PATCH is owner-gated like every
`/api/v1` route — your PAT can only change boards you own.

## Verifying and troubleshooting

- **Nothing happens on a PR.** Check, in order: does the branch or PR title contain `KAN-<n>`? does a
  card with that ticket exist, on a board you've opted in? is `autosync_enabled` true on that board?
  The server logs each skip reason under the `app.autosync` logger (`no card for ticket=…`,
  `autosync disabled`).
- **GitHub shows `401` in Recent Deliveries.** The webhook secret and `WEBHOOK_SECRET` differ, or the
  content type isn't `application/json`. Re-set both to the same value.
- **GitHub shows `503`.** `WEBHOOK_SECRET` isn't set on the server (step 1).
- **Merges don't move the card.** `autosync_advance_to_done` is still `false` — that's the default and
  is separate from the master switch.
- **CI comments don't appear.** Your CI may report as `status` while you only subscribed to
  `check_suite`, or vice versa — subscribe to both.

## Security notes

- The webhook is authenticated **only** by the HMAC signature over the raw body; treat
  `WEBHOOK_SECRET` like any other secret and rotate it (on both server and GitHub) if it leaks.
- Auto-sync writes act as the system, with no user attribution, and are bounded entirely by the
  per-board opt-in — so the flag is the authorization. It can only ever touch cards on boards whose
  owner turned it on.
- Rotating `WEBHOOK_SECRET` immediately breaks signature verification until you update the GitHub
  webhook to match (deliveries will `401` in between); it does **not** affect PATs or sessions
  (that's `AUTH_SECRET`).
