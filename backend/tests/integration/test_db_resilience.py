"""DB + cold-start resilience tests (V30, KAN-294).

Proves the acceptance criterion: a deliberately slow statement is cancelled at the
configured ``statement_timeout`` — cleanly, with a driver error — rather than hanging,
and that BOTH app engines (the sync board engine and the async auth engine) honour it.

Two complementary checks:
- the *real* module engines (``app.db.engine`` / ``app.db.async_engine``) report a
  non-zero ``statement_timeout`` on their connections (the default 30s), confirming the
  timeout is actually applied to the engines the app uses; and
- a throwaway engine built via the same ``app.db._connect_args`` path with a *low*
  timeout cancels a ``SELECT pg_sleep(...)`` that overruns it — exercised on both the
  sync and async psycopg v3 connection.

Per the suite convention every ``import app.*`` lives inside a test body so the
``_database`` fixture's ``DATABASE_URL`` override binds the engines to the throwaway
Postgres first (the PR #17 trap; see conftest ``pytest_collection_finish``).
"""
from __future__ import annotations

import asyncio

import pytest


def test_real_sync_engine_applies_statement_timeout():
    """The app's sync board engine sets statement_timeout on its connections."""
    from sqlalchemy import text

    from app.db import engine

    with engine.connect() as conn:
        value = conn.execute(text("SHOW statement_timeout")).scalar()
    # 30_000 ms is normalised by Postgres to "30s"; the point is it is NOT "0" (off).
    assert value != "0"
    assert value == "30s"


def test_real_async_engine_applies_statement_timeout():
    """The app's async auth engine sets statement_timeout on its connections too."""
    from sqlalchemy import text

    from app.db import async_engine

    async def _show() -> str:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SHOW statement_timeout"))
            return result.scalar()

    value = asyncio.run(_show())
    assert value != "0"
    assert value == "30s"


def test_sync_slow_statement_is_cancelled_at_timeout():
    """A sync query past the timeout is cancelled with a clean error, not a hang."""
    from psycopg.errors import QueryCanceled
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    from app import db

    # 500ms timeout, then sleep 5s: must be cancelled server-side well under 5s.
    eng = create_engine(
        db.DATABASE_URL, connect_args=db._connect_args(statement_timeout_ms=500)
    )
    try:
        with pytest.raises(OperationalError) as excinfo:
            with eng.connect() as conn:
                conn.execute(text("SELECT pg_sleep(5)"))
        # Cleanly cancelled by the server (QueryCanceled), not a connection drop/hang.
        assert isinstance(excinfo.value.orig, QueryCanceled)
    finally:
        eng.dispose()


def test_async_slow_statement_is_cancelled_at_timeout():
    """An async query past the timeout is cancelled the same way — both engines honour it."""
    from psycopg.errors import QueryCanceled
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import db

    async def _run() -> None:
        eng = create_async_engine(
            db.DATABASE_URL, connect_args=db._connect_args(statement_timeout_ms=500)
        )
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT pg_sleep(5)"))
        finally:
            await eng.dispose()

    with pytest.raises(OperationalError) as excinfo:
        asyncio.run(_run())
    assert isinstance(excinfo.value.orig, QueryCanceled)
