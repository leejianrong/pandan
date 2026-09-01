<!--
title: "Deploy it"
description: Build the Pandan image and run it in production, including the Fly.io and managed-Postgres setup behind the hosted board.
-->

# Deploy it

One image, one process, one database. If you can run a container with an environment file, you can deploy
Pandan.

## What the image does

The `Dockerfile` at the repository root builds the frontend, then copies the static bundle into a Python
image alongside the backend. The result serves the API and the SPA from one origin.

```bash
docker build -t pandan .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql+psycopg://user:pass@host/db \
  -e AUTH_SECRET=… \
  -e COOKIE_SECURE=1 \
  -e RATE_LIMIT_ENABLED=1 \
  pandan
```

!!! warning "Keep the proxy header flags"

    The image starts uvicorn with `--proxy-headers --forwarded-allow-ips=*`, which is what makes the app
    generate `https://` OAuth redirect URIs behind a TLS-terminating proxy. Override the command without
    them and GitHub login breaks with a redirect URI mismatch.

## Migrations

Migrations are not run by the image on startup. Apply them yourself as a separate step:

```bash
cd backend
DATABASE_URL=… uv run alembic upgrade head
```

!!! danger "Deploy a migration on its own"

    Land and deploy a schema change by itself rather than alongside application changes. If a migration
    and the code that depends on it go out together and the migration fails, you have a running app
    against a schema it does not expect.

## Registering the production OAuth App

GitHub login needs its own **OAuth App** (not a GitHub App) per environment, because an OAuth App allows
exactly one callback URL — the one you used for local development cannot also serve production.

1. In GitHub, go to **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Set **Homepage URL** to your instance's public URL (`https://kanban.example.com`, say) and
   **Authorization callback URL** to exactly:
   ```
   https://kanban.example.com/auth/github/callback
   ```
3. Register the app, generate a client secret, and set both as secrets on your deployment:
   ```bash
   GITHUB_OAUTH_CLIENT_ID=…
   GITHUB_OAUTH_CLIENT_SECRET=…
   ```

If the callback URL is wrong or the app is missing the proxy header flags (see the warning above),
GitHub either rejects the redirect outright or the app generates an `http://` redirect URI that GitHub
refuses to match against the registered `https://` one — both look the same from the login button:
sign-in starts and immediately errors.

## Bootstrapping the first user

There is no separate install wizard and no "admin" role to seed. The first person to complete GitHub
login can immediately create a board, and owning it works exactly the way it works for every board after
it — ownership is captured from the session at creation time, not granted by being first. See
[who can sign in, and who is the admin](local.md#who-can-sign-in-and-who-is-the-admin) for what that
does and does not restrict; it applies identically in production. In short: registering the OAuth App
above **is** your access control, since anyone who can complete that flow can create boards, and nothing
in Pandan gates sign-in beyond it.

## Things worth changing before you point this at real users

**The landing page links to the hosted demo.** `frontend/src/lib/components/Landing.svelte` hardcodes
two links to `https://simple-kanban-jian.fly.dev` (the "Live demo" button and "See a board in action").
They ship in every build from source, including yours, so your own users land on a page that invites
them to someone else's board. Edit or remove both before you build the frontend for production.

**This repository's own CI/CD is not a self-hosting tool.** `fly.toml` and the GitHub Actions workflows
under `.github/workflows/` (`deploy.yml`, `keepalive.yml`) automate *this project's* hosted board on Fly
— they are not something you need, and you should not point them at your instance by leaving them
running in a fork. `keepalive.yml` in particular exists only to work around Fly/Neon's free-tier
scale-to-zero (see the warning below) and is a no-op cost if you run on infrastructure that does not
scale to zero. If you do fork the repository and keep its Actions enabled, override the
`KEEPALIVE_URL` / `PROD_VERSION_URL` repository variables — both already read from a variable with the
hosted URL only as a fallback — or disable the workflows outright.

## The hosted setup

The hosted board runs on Fly.io with a managed serverless Postgres. `fly.toml` and the root `Dockerfile`
are the whole configuration.

```bash
fly deploy
fly secrets set AUTH_SECRET=… COOKIE_SECURE=1 RATE_LIMIT_ENABLED=1
fly secrets set GITHUB_OAUTH_CLIENT_ID=… GITHUB_OAUTH_CLIENT_SECRET=…
fly secrets set DATABASE_URL=…
```

Two things about this setup are worth copying, and one is worth knowing about.

**Scale to zero is why `warmup` exists.** The database tier scales to zero when idle, so the first request
after a quiet period takes about a second. That is a documented cold start rather than a fault. Any
client that batches work should call `warmup` first, which is why the CLI and MCP server both have it.
See [in CI](../cli/ci.md#warm-the-api-first).

**The box is small, which is why the pool is bounded.** The connection and timeout settings in
[configuration](configuration.md#connection-and-timeout-tuning) exist so that a slow query against a
cold-woken database cannot pile up connections until the process is unusable. If you deploy somewhere
tight on memory, keep them.

## Continuous deployment

Deployment runs on a successful CI run on the default branch, rather than on the push itself.

That indirection is worth understanding if you copy the pattern, because it can silently skip a deploy in
three ways:

- A merge attributed to a bot using the default CI token creates **no workflow runs at all**, so nothing
  triggers and nothing deploys.
- Two merges close together can cancel each other's runs if they share a concurrency group.
- A genuinely failing run on the default branch means no deploy.

None of those turn anything red. The branch is simply ahead of what is running, and it heals on the next
merge that does deploy.

!!! tip "Watch for drift explicitly"

    Because the failure mode is silence, the repository runs a scheduled watcher that compares the
    default branch against what production is actually serving and fails loudly when they differ.

    To check by hand, compare the branch against the head commit of the newest deploy run whose **deploy
    job** succeeded. Not the newest run whose overall conclusion was success, which reads as successful
    with the deploy job skipped on every docs-only merge. That distinction is the trap.

## Deploying elsewhere

Nothing here is Fly-specific. The requirements are:

- Run the container, one process is enough
- Reach a Postgres 17 database
- Terminate TLS in front of it and forward the standard proxy headers
- Set the environment from [configuration](configuration.md)
- Point a readiness probe at `/api/health` and a liveness probe at `/api/health/live`

Because state lives entirely in Postgres, the container is disposable and horizontal scaling works, with
one caveat: rate limit counters are per process and in memory, so several instances each enforce their own
limits.

## Backups

Pandan has no backup mechanism of its own. Everything is in Postgres, so back up the database with
whatever your provider or `pg_dump` gives you.

Worth testing a restore before you need one. Ticket sequences are part of the schema, and a restore that
loses them would start reissuing numbers that already exist.

## Recap

- One image serves the API and the SPA on one origin.
- Run migrations as their own step, and deploy schema changes alone.
- Keep the proxy header flags, or OAuth breaks.
- `warmup` exists because the database scales to zero.
- A green build does not prove a deploy happened. Compare the branch against the last successful deploy
  job.

Next: [GitHub auto-sync](github-autosync.md).
