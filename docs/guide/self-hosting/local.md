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

## Enabling login

With no OAuth credentials the instance still boots, the landing page still renders, and login is simply
unavailable. That is enough to run the API with a token, but not to get a token, since minting one needs
a logged-in session.

To enable GitHub login, create an OAuth App and set both values:

```bash
export GITHUB_OAUTH_CLIENT_ID=…
export GITHUB_OAUTH_CLIENT_SECRET=…
```

The callback URL for local development is:

```
http://localhost:5173/auth/github/callback
```

!!! warning "A GitHub OAuth App allows only one callback URL"

    So you cannot share one app between development and production. Create two.

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
