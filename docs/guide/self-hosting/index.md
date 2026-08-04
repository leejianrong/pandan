<!--
title: "Self-hosting"
description: Run your own Pandan instance, from a local Docker Compose stack to a deployed single artifact.
-->

# Self-hosting

Pandan ships as one deployable artifact: a FastAPI process that serves both the API and the built
frontend from the same origin. There is no separate web server, no CDN to configure, and no CORS to get
wrong.

You need that process and a Postgres database. That is the whole system.

## Why you might

**You want more than one owner's worth of privacy.** Boards can be shared with members, but every board
lives on whichever instance it was created on. A team that wants its own data owns its own instance.

**You want it on your network.** Nothing about Pandan requires the public internet.

**You want to change it.** It is a small codebase on purpose.

If none of those apply, the [hosted board](https://simple-kanban-jian.fly.dev) is free and already
running.

## What it is made of

| Piece | What it is |
| --- | --- |
| Application | One FastAPI process. Serves `/api/v1`, `/docs`, and the SPA with a catch-all fallback. |
| Database | Postgres 17. One database, two connection pools (a synchronous one for the board, an async one for auth). |
| Migrations | Alembic. One pipeline covers board tables and auth tables. |
| Frontend | Svelte, built to static files that the application serves. Not a separate deployment. |

The single-origin arrangement is load-bearing rather than incidental. Because the SPA and the API share
an origin, the session cookie just works, and there is no cross-origin configuration to get wrong.

## Where to go

<div class="grid cards" markdown>

-   **[Run it locally](local.md)**

    Docker Compose for the database, then the app. The quickest way to see it working.

-   **[Configuration](configuration.md)**

    Every environment variable, what it defaults to, and which ones you must set in production.

-   **[Deploy it](deploy.md)**

    Build the image and run it somewhere, including the Fly.io setup behind the hosted board.

-   **[GitHub auto-sync](github-autosync.md)**

    Move cards automatically when a pull request opens or merges.

</div>

## The one thing you must not skip

`DATABASE_URL` is the only required setting, and it has a working default for local development, so an
instance boots with almost nothing configured.

That convenience is a trap in production. Three settings have insecure development defaults or are
simply off, and a public instance needs all three:

- **`AUTH_SECRET`**, which signs sessions and peppers token hashes. It has a development default. Set a
  strong random value.
- **`COOKIE_SECURE`**, which marks cookies HTTPS-only. Off by default because development runs over
  plain HTTP.
- **`RATE_LIMIT_ENABLED`**, which is off by default so tests and development are unaffected.

Details and the rest in [configuration](configuration.md).
