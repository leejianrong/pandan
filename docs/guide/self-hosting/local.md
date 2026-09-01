<!--
title: "Run it locally"
description: Get a Pandan instance running on your machine, either as one Docker Compose command or as a hot-reload development loop.
-->

# Run it locally

Two ways. Pick the first if you want to see it working, the second if you want to change it.

## The one-command version

From a checkout of the repository:

```bash
make up
```

That brings up Postgres and the application image serving the built frontend, then you open
<http://localhost:8000>.

Under the hood it is `docker compose up --build`, so the only prerequisite is Docker.

```bash
make down      # stop, keep the database volume
make down-v    # stop and delete the database volume
```

!!! warning "`make down-v` destroys your data"

    It deletes the Postgres volume. Anything on your local boards goes with it. `make down` is the one
    you usually want.

## The development loop

For editing code, you want hot reload, which means running the backend and frontend natively against a
containerised database.

```bash
make dev
```

That starts Postgres in Docker, applies migrations, then runs the backend with reload and the Vite dev
server together. Open <http://localhost:5173>. Ctrl-C stops both.

Vite proxies `/api` to the backend on port 8000, so it behaves like the single-origin production setup
without the build step.

### By hand

`make dev` is a wrapper. The steps, if you would rather run them yourself:

```bash
docker compose up -d db                              # Postgres 17 on :5432

cd backend
uv sync                                              # install, including dev dependencies
uv run alembic upgrade head                          # apply migrations
uv run uvicorn app.main:app --reload                 # API on :8000, OpenAPI at /docs

cd ../frontend
npm ci
npm run dev                                          # SPA on :5173
```

The backend uses [uv](https://docs.astral.sh/uv/) and Python 3.12. Run its commands from `backend/`,
because the package is deliberately not installable and `alembic.ini` relies on the working directory to
resolve `import app`.

!!! note "The default database URL already points at Compose"

    `DATABASE_URL` defaults to `postgresql+psycopg://kanban:kanban@localhost:5432/kanban`, which is
    exactly what `docker compose up -d db` gives you. So local development needs no configuration at
    all.

    Keep the `+psycopg` suffix if you change the URL. It selects the psycopg 3 driver, which is what the
    code expects.

!!! tip "Already running something on 5432, 8000 or 5173?"

    `make dev` handles it: it prefers those ports, falls through to the next free one when a port is
    taken, and prints the three URLs it settled on. Nothing to configure.

    Running the steps by hand instead, you own the conflict — and it is worth knowing what it looks
    like, because none of the three announce themselves as a port clash. Another Postgres on `:5432`
    answers and rejects the `kanban` credentials, so migrations fail with `password authentication
    failed` as though the URL were wrong. Another app on `:8000` will happily answer the SPA's proxied
    `/api` calls with its own responses. Set `DB_PORT` before `docker compose up -d db` to publish
    Postgres elsewhere (and point `DATABASE_URL` at it), pass `--port` to uvicorn, and set
    `BACKEND_PORT` / `FRONTEND_PORT` for Vite, which reads both — the second is its own port, the
    first is the backend it proxies to.

## Enabling login

With no OAuth credentials the instance still boots, the landing page still renders, and login is simply
unavailable. That is enough to run the API with a token, but not to get a token, since minting one needs
a logged-in session.

Pandan only ever talks to a GitHub **OAuth App**, not a GitHub App — the two are different things in
GitHub's UI, and only the OAuth App flow is wired up.

1. In GitHub, go to **Settings → Developer settings → OAuth Apps → New OAuth App** (personal account) or
   your organization's equivalent page.
2. Set **Homepage URL** to `http://localhost:5173` and **Authorization callback URL** to exactly:
   ```
   http://localhost:5173/auth/github/callback
   ```
3. Register the app, then generate a **client secret** on the app's page. You now have a client ID and a
   client secret.
4. Set both:
   ```bash
   export GITHUB_OAUTH_CLIENT_ID=…
   export GITHUB_OAUTH_CLIENT_SECRET=…
   ```
5. Restart the backend. The landing page's "Sign in with GitHub" button now works.

!!! warning "A GitHub OAuth App allows only one callback URL"

    So you cannot share one app between development and production. Create two — see
    [deploy](deploy.md#registering-the-production-oauth-app) for the production one.

## Who can sign in, and who is the admin

There is no separate admin account and no signup allowlist. **Anyone who completes GitHub OAuth against
the app you registered above can log in and start creating boards.** The only access control is at the
board level, applied after login (owner, then shared members) — nothing gates who is allowed to log in
in the first place.

There is also no explicit "bootstrap the first admin" step to run. Board ownership is captured from the
session at creation time: the first person to log in and create a board simply owns it, the same as
every board after it. (A separate mechanism, `claim-on-login`, silently adopts any *pre-existing*
unclaimed board for whoever next logs in — it exists to rescue data from a migration and does nothing on
a fresh instance with zero boards, so do not rely on it as your bootstrap step.)

For a team instance this means **network reachability is your access control**: any GitHub account that
can reach your callback URL and complete the flow gets in. Pandan does not check GitHub org membership or
consult any allowlist — nothing in the code does that today. If you need to restrict who can sign in, do
it outside Pandan: put the instance behind a VPN or an internal network, so only people who already have
network access ever reach the login button at all. See [current limits](../about/limits.md#access) for
this stated plainly.

## Migrations

```bash
cd backend
uv run alembic upgrade head                              # apply
uv run alembic revision --autogenerate -m "add a thing"  # create
```

Autogenerate only sees models imported in `alembic/env.py`, so a new model needs an import there or its
table will be silently missing from the migration.

## Running the tests

```bash
cd backend
uv run pytest tests/unit          # fast, no database
uv run pytest tests/integration   # real Postgres via testcontainers, needs Docker
uv run ruff check .
```

Integration tests spin up their own throwaway Postgres, so they do not touch your development database
and do not need Compose to be running. They do need a Docker daemon.

```bash
cd frontend
npm run check                     # type and lint pass
npm run e2e                       # Playwright, needs the database up
```

## Recap

```bash
make up      # see it working, on :8000
make dev     # work on it, on :5173
make down    # stop
```

Nothing needs configuring for local use. Next: [configuration](configuration.md) for what to set before
anyone else can reach it.
