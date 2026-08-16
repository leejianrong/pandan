<!--
title: "Configuration"
description: Every Pandan environment variable, its default, and which ones a production instance must set.
-->

# Configuration

`DATABASE_URL` is the only required setting. Everything else has a default that works, which makes local
development easy and production quietly risky, so this page flags what actually matters.

## Set these in production

Four settings. An instance without them boots and appears to work.

| Variable | Default | Why it matters |
| --- | --- | --- |
| `AUTH_SECRET` | An insecure development value | Signs session and OAuth state tokens, and peppers token hashes. Anyone who knows it can forge a session. Set a long random value. |
| `COOKIE_SECURE` | off | Marks session and CSRF cookies HTTPS-only. Off because development runs over plain HTTP. Set it to `1`. |
| `RATE_LIMIT_ENABLED` | off | All rate limiting is disabled until this is truthy. Off so the test suite and development are unaffected. |
| `E2E_AUTH_BYPASS` | off | Must stay off. See the warning below. |

!!! danger "`E2E_AUTH_BYPASS` is a login bypass"

    When truthy it mounts `POST /auth/test-login`, which mints a real session for any email with no
    authentication at all. It exists because Playwright cannot fake an httpOnly cookie. Setting it on a
    reachable instance hands anyone an account of their choosing.

!!! warning "Rotating `AUTH_SECRET` logs everyone out"

    It is also the pepper for personal access token hashes, so rotating it invalidates every existing PAT
    as well as every cookie session. That is correct behaviour, and worth planning for rather than
    discovering.

## Database

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://kanban:kanban@localhost:5432/kanban` | Keep the `+psycopg` suffix; it selects the psycopg 3 driver. Used by both the app and Alembic, so migrations always target the app's database. |

### Connection and timeout tuning

These exist because a slow query on a cold-started serverless database can otherwise pile up connections
until the process wedges. All optional, with production-safe defaults, and applied to both the
synchronous board pool and the async auth pool.

| Variable | Default | What it does |
| --- | --- | --- |
| `DB_STATEMENT_TIMEOUT_MS` | `30000` | Server-side cap per statement, in milliseconds. A runaway query is cancelled rather than hanging. `0` disables. |
| `DB_POOL_SIZE` | `5` | Pooled connections. |
| `DB_MAX_OVERFLOW` | `5` | Extra connections above the pool, so 10 maximum. |
| `DB_POOL_TIMEOUT` | `10` | Seconds a caller waits for a free connection before erroring, so a burst degrades instead of hanging. |
| `DB_CONNECT_TIMEOUT` | `10` | libpq connect timeout in seconds, so an unreachable database fails fast. |

!!! info "Alembic's own engine is deliberately untouched"

    The statement timeout does not apply to migrations, so a long `ALTER TABLE` is never cut short
    halfway.

## Authentication

| Variable | Default | Notes |
| --- | --- | --- |
| `GITHUB_OAUTH_CLIENT_ID` | unset | Both unset means the login routes do not register and the app still boots with login unavailable. |
| `GITHUB_OAUTH_CLIENT_SECRET` | unset | |
| `AUTH_SECRET` | insecure dev value | See above. |
| `COOKIE_SECURE` | off | See above. |

The OAuth callback URL is `<origin>/auth/github/callback`. A GitHub OAuth App allows exactly one, so
development and production need separate apps.

!!! warning "Behind a TLS-terminating proxy, pass the forwarded headers"

    Without them the generated `redirect_uri` is `http://` and GitHub rejects the mismatch. The shipped
    Dockerfile starts uvicorn with `--proxy-headers --forwarded-allow-ips=*` for exactly this reason. If
    you write your own start command, keep those flags.

## Rate limiting

Four tiers, each a rate string like `"300/minute"`.

| Variable | Default | Covers |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | off | Master switch. Nothing is limited until this is truthy. |
| `RATE_LIMIT_AUTH` | `30/minute` | Login and the OAuth callback. |
| `RATE_LIMIT_WRITE` | `300/minute` | Every `/api/v1` mutation, including card moves and token creation. |
| `RATE_LIMIT_EXPENSIVE` | `120/minute` | Full-text search and board metrics. |
| `RATE_LIMIT_WEBHOOK` | `240/minute` | The inbound GitHub webhook. |

Over the limit returns `429` with a `Retry-After` header.

!!! note "Limits are per process and in memory"

    Counters live in the process and reset when it restarts, and two instances do not share them. That is
    an accepted trade-off for a single-machine deployment, not a distributed rate limiter.

    Keying uses a trusted proxy header rather than `X-Forwarded-For`, which is spoofable when uvicorn runs
    with `--forwarded-allow-ips=*`.

## Request size limits

Additive caps, so normal payloads are unaffected. String length limits are fixed in code, aligned to the
database column widths, which is why an over-long field is a clean `422` rather than a failed insert.

| Variable | Default | What it caps |
| --- | --- | --- |
| `MAX_REQUEST_BODY_BYTES` | `2000000` | Body size. Checked against `Content-Length` before the body is read, so an oversized request is rejected with `413` rather than buffered. |
| `MAX_BATCH_ITEMS` | `500` | Cards per batch patch. |
| `MAX_TEMPLATE_CARDS` | `200` | Cards per template, enforced on create and on apply. |

## Webhooks

| Variable | Default | Notes |
| --- | --- | --- |
| `WEBHOOK_SECRET` | unset | The shared secret GitHub signs deliveries with. Unset means the inbound endpoint returns `503`, so auto-sync is off. A bad signature returns `401`. |
| `OUTBOUND_WEBHOOK_TIMEOUT` | `3.0` | Seconds per outbound attempt. |
| `OUTBOUND_WEBHOOK_RETRIES` | `0` | Extra attempts after the first. |
| `OUTBOUND_WEBHOOK_MIN_INTERVAL` | `1.0` | Per-board throttle in seconds, so a burst cannot hammer your endpoint. In-process, resets on restart. |

Inbound auto-sync is opt-in per board. The outbound webhook is configured per board too, with a
write-only secret. Both are covered in [GitHub auto-sync](github-autosync.md) and
[boards](../tutorial/boards.md#board-settings).

!!! info "Outbound delivery never blocks a write"

    It fires after the transaction commits, so a slow or failing endpoint is logged and swallowed. It
    cannot roll back the mutation that triggered it. There is no retry queue.

## Observability

| Variable | Default | Notes |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Level for the structured JSON request log: method, path, status, latency, principal id. |
| `SENTRY_DSN` | unset | Unset is a true no-op; the SDK is not even imported, so development and tests never report. |
| `SENTRY_ENVIRONMENT` | `production` | |
| `SENTRY_TRACES_SAMPLE_RATE` | `0` | |

The request logger allow-lists its fields and logs only the URL path, never the query string, so tokens
and cookies cannot reach a log line. Sentry runs with PII sending disabled for the same reason.

### Health endpoints

| Path | Kind | Behaviour |
| --- | --- | --- |
| `GET /api/health` | Readiness | Cheap `SELECT 1`. Returns `503` when the database is unreachable, otherwise `200`. |
| `GET /api/health/live` | Liveness | Always `200` while the process is serving. |
| `GET /api/health/version` | Provenance | `{"revision": "<git sha>"}` — the commit the image was built from, or `"unknown"` when the build passed no `GIT_REVISION` build argument. |

Point an orchestrator's readiness probe at the first and its liveness probe at the second. Using the
readiness probe for liveness will restart a healthy process whenever the database blips.

The third is build provenance, and it is opt-in at build time:

```bash
docker build --build-arg GIT_REVISION=$(git rev-parse HEAD) -t pandan .
```

Without the argument the image still builds and reports `"unknown"`. Passing it lets anything outside
your deploy pipeline — a monitor, a support ticket, you with `curl` — read back which commit a running
instance is actually serving, instead of inferring it from what the pipeline last tried to ship. It
reports the revision the build argument named, so it will believe a wrong one; that is a smaller gap
than inference, not a closed one.

## Security headers

Set by middleware with no configuration: HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options:
DENY`, a referrer policy, and a single-origin content security policy.

!!! note "The CSP ships in report-only mode"

    It is sent as `Content-Security-Policy-Report-Only`, so browsers report violations and block nothing.
    That is deliberate, because the interactive API docs use inline scripts and a CDN bundle that a strict
    policy would break.

    To enforce it, rename the header once your console is clean, and either self-host the docs bundle or
    allow its origin.

## A production checklist

```bash
DATABASE_URL=postgresql+psycopg://…       # your database
AUTH_SECRET=<long random value>           # not the default
COOKIE_SECURE=1                           # you are on HTTPS
RATE_LIMIT_ENABLED=1                      # turn protection on
GITHUB_OAUTH_CLIENT_ID=…                  # if you want login
GITHUB_OAUTH_CLIENT_SECRET=…
# E2E_AUTH_BYPASS must NOT be set
```

Then confirm: `GET /api/health` returns `200`, and logging in works end to end.

Next: [deploy it](deploy.md).
