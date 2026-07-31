"""Database wiring: synchronous SQLAlchemy 2.0 + psycopg (v3) driver (ADR 0008).

The engine reads ``DATABASE_URL`` from the environment. Locally this points at the
docker-compose Postgres; in prod it is a Fly secret pointing at Neon.

**DB + cold-start resilience (V30, KAN-294).** The prod DB is a free-tier Neon that
scales to zero and cold-starts (~1s on the first request after idle). To stop a slow
query on a cold-woken DB from piling up connections and wedging the 256MB box, both
app engines below carry:
- a Postgres ``statement_timeout`` (server-side per-statement cap), applied via the
  libpq ``options`` connect-arg — psycopg v3 accepts this for its sync *and* async
  connections — so a runaway query is cancelled server-side rather than hanging;
- ``pool_pre_ping`` (drop dead connections before use — important across Neon's
  scale-to-zero) plus a **bounded** pool (``pool_size`` + ``max_overflow``) and a
  ``pool_timeout`` so a burst degrades gracefully (callers get a prompt pool-timeout
  error) instead of unbounded connection growth;
- a libpq ``connect_timeout`` so establishing a connection to a stuck DB fails fast.

All five are env-configurable (defaults below). **These live on the APP engines only —
Alembic builds its own engine in ``alembic/env.py`` and is deliberately left alone, so
legitimately long-running migrations are never cut short by ``statement_timeout``.**
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Default targets the local docker-compose Postgres. The +psycopg suffix selects
# the psycopg v3 driver for SQLAlchemy.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://kanban:kanban@localhost:5432/kanban",
)


def _int_env(name: str, default: int) -> int:
    """Read a non-negative int from the environment, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Per-statement server-side cap (milliseconds). Legit app queries are fast and Neon
# cold-starts in ~1s, so 30s sits comfortably above any honest query while still
# capping a runaway/hung one long before it can exhaust the pool. 0 disables it — don't.
DB_STATEMENT_TIMEOUT_MS = _int_env("DB_STATEMENT_TIMEOUT_MS", 30_000)
# Bounded pool: the 256MB prod box can't afford unbounded connections. 5 persistent +
# 5 overflow (10 max) is ample for this low-traffic single instance.
DB_POOL_SIZE = _int_env("DB_POOL_SIZE", 5)
DB_MAX_OVERFLOW = _int_env("DB_MAX_OVERFLOW", 5)
# How long a caller waits for a free pooled connection before failing (seconds). Short,
# so a burst surfaces a prompt error rather than a hang.
DB_POOL_TIMEOUT = _int_env("DB_POOL_TIMEOUT", 10)
# libpq connect timeout (seconds) — fail fast if the DB won't accept a connection.
DB_CONNECT_TIMEOUT = _int_env("DB_CONNECT_TIMEOUT", 10)


def _connect_args(statement_timeout_ms: int = DB_STATEMENT_TIMEOUT_MS) -> dict:
    """psycopg v3 connect args carrying the statement timeout + connect timeout.

    ``options`` passes a libpq startup option; ``-c statement_timeout=<ms>`` sets the
    server-side timeout for every statement on the connection. psycopg v3 accepts both
    ``options`` and ``connect_timeout`` for its sync *and* async connections, so the
    same dict serves both engines below. The timeout is overridable so tests can build
    a low-timeout engine against the same driver path.
    """
    return {
        "options": f"-c statement_timeout={statement_timeout_ms}",
        "connect_timeout": DB_CONNECT_TIMEOUT,
    }


# Pool/reliability kwargs shared by both engines. AsyncAdaptedQueuePool (the async
# default) honours the same pool_size/max_overflow/pool_timeout knobs as QueuePool.
_POOL_KWARGS = dict(
    pool_pre_ping=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
)

engine = create_engine(DATABASE_URL, connect_args=_connect_args(), **_POOL_KWARGS)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Second, ASYNC engine — used ONLY by fastapi-users' human login/session/OAuth
# store (Milestone 3 V6, ADR 0011). fastapi-users' user DB is async-only, so it
# needs an AsyncSession. All board/epic/card CRUD (and the agent-token lookup)
# stay on the sync engine above — ADR 0008 is preserved for the whole app surface.
# Both engines point at the same DATABASE_URL database; psycopg v3 serves sync and
# async, so the +psycopg URL works unchanged for both — including the same
# statement_timeout / pool bounds (V30).
async_engine = create_async_engine(
    DATABASE_URL, connect_args=_connect_args(), **_POOL_KWARGS
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models — board domain (models.py) and auth
    (auth_models.py) share this one metadata, so one Alembic pipeline covers both."""


def get_db():
    """FastAPI dependency yielding a sync session, closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async session for the auth routes only."""
    async with AsyncSessionLocal() as session:
        yield session
