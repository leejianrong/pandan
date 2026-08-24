"""Pytest fixtures for the backend API suite.

The model relies on Postgres-specific features (the ``card_ticket_seq`` sequence,
the ``'KAN-' || nextval(...)`` server default, and a CHECK constraint), so tests
run against a real Postgres — not SQLite. Rather than depend on a manually-managed
database, pytest starts an ephemeral Postgres via **testcontainers** and tears it
down at the end of the session, so the suite is fully self-contained (and CI-ready).
Requires a running Docker daemon.

Flow: start container → point DATABASE_URL at it → ``alembic upgrade head`` (which
also exercises the migrations) → reset tables + sequences between tests for
deterministic ticket numbers.
"""
from __future__ import annotations

import os
import sys

import pytest
from testcontainers.postgres import PostgresContainer


def pytest_collection_finish(session: pytest.Session) -> None:
    """Guard against the import-order trap that let PR #17 pass locally but fail CI.

    App modules build the SQLAlchemy engines from ``DATABASE_URL`` **at import
    time**. If an integration test imports one at *module top level*, that import
    runs during pytest **collection** — before the session ``_database`` fixture
    repoints ``DATABASE_URL`` at the throwaway Postgres — so the engines bind to
    the default ``localhost:5432`` URL. On a dev box with a local Postgres up that
    silently "passes" (against the wrong DB); in CI, with nothing on 5432, every
    integration test errors with "connection refused".

    So: **all app imports must live inside test/fixture bodies**, never at module
    top (see DEVELOPER-WORKFLOWS.md §1a). ``app.db`` is the module that reads
    ``DATABASE_URL`` and builds the engines; every other app module pulls it in
    transitively, so checking it here catches them all. This fires at collection —
    Docker-free — so ``pytest --collect-only`` in the pre-push hook catches it
    before a push, deterministically, whether or not a local DB is running.
    """
    if "app.db" in sys.modules:
        raise pytest.UsageError(
            "app.db was imported at collection time — an integration test (or its "
            "conftest) has a top-level `import app...`. Move app imports inside the "
            "test/fixture bodies so the _database fixture's DATABASE_URL override "
            "takes effect first. See DEVELOPER-WORKFLOWS.md §1a."
        )


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Start a throwaway Postgres, point the app + Alembic at it, migrate to head."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        # app.db and Alembic both read DATABASE_URL at import/run time; set it
        # before any app module is imported (all app imports happen in fixtures).
        os.environ["DATABASE_URL"] = postgres.get_connection_url()
        # Auth config (M3 V6) is read at import time too. Dummy GitHub creds make
        # the OAuth routes register for the whole session (the network calls are
        # mocked in the auth tests); COOKIE_SECURE stays unset so cookies are
        # stored over the test client's http origin.
        os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-client-id")
        os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")
        os.environ.setdefault("AUTH_SECRET", "test-secret-key-at-least-32-bytes-long!!")

        from alembic.config import Config

        from alembic import command

        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")

        yield


@pytest.fixture(autouse=True)
def _reset_tables():
    """Empty the card + epic tables and restart sequences before each test."""
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        # Clear board + card + epic + the auth tables so each test starts clean;
        # CASCADE drops dependents (a board's cards/epics, a user's oauth/tokens).
        # "user" is quoted (reserved word). RESTART IDENTITY makes ids deterministic.
        conn.execute(
            text('TRUNCATE board, card, epic, "user", oauth_account, access_token, '
                 "personal_access_token RESTART IDENTITY CASCADE")
        )
        conn.execute(text("ALTER SEQUENCE card_ticket_seq RESTART WITH 1"))
        conn.execute(text("ALTER SEQUENCE epic_ticket_seq RESTART WITH 1"))
        # Re-seed the default board (id=1) so card/epic creation without an explicit
        # board_id resolves to it — matching the post-migration steady state and
        # keeping the pre-board tests (which send no board_id) green. ``key`` is NOT
        # NULL since V51 (KAN-972), and 'DEF' is exactly what migration 0022's
        # backfill derives from 'Default Board' — so this row stays a faithful
        # stand-in for the real post-migration board rather than an arbitrary one.
        conn.execute(
            text("INSERT INTO board (name, key) VALUES ('Default Board', 'DEF')")
        )
    yield


@pytest.fixture
def client():
    """A FastAPI TestClient bound to the migrated test database."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


# The OAuth identity the mocked GitHub hands back (shared by the auth + board tests).
FAKE_ACCOUNT_ID = "gh-12345"
FAKE_EMAIL = "octocat@example.com"


@pytest.fixture
def mock_github(monkeypatch):
    """Stub the GitHub client's two network calls so login needs no network."""
    from app import users

    async def fake_get_access_token(code, redirect_uri, code_verifier=None):
        return {"access_token": "gh-access-token", "expires_at": None}

    async def fake_get_id_email(access_token):
        return FAKE_ACCOUNT_ID, FAKE_EMAIL

    monkeypatch.setattr(users.github_oauth_client, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(users.github_oauth_client, "get_id_email", fake_get_id_email)


def _drive_github_login(client) -> None:
    """Drive authorize → callback so ``client`` ends up holding a session cookie."""
    from urllib.parse import parse_qs, urlparse

    authorize = client.get("/auth/github/authorize")
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    client.get(
        "/auth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )


@pytest.fixture
def logged_in_client(client, mock_github):
    """A TestClient carrying a valid GitHub cookie session (authorize → callback)
    as the default identity (:data:`FAKE_EMAIL`).

    Since V8 (ADR 0013) logging in also **claims all unclaimed boards** for the
    user, so this client owns the reset fixture's default board (id=1) — which is
    what lets the board-scoped tests reach the now-owner-gated ``/api/v1`` by simply
    shadowing their ``client`` fixture with this one.
    """
    _drive_github_login(client)
    return client


@pytest.fixture
def login_as(monkeypatch):
    """Factory → a fresh logged-in TestClient for an arbitrary GitHub identity.

    Each call returns an independent client (its own cookie jar), so a single test
    can hold two distinct users — the setup for the 403 / list-scoping tests where
    one user must be denied another's board. Logging in claims unclaimed boards
    (V8), so the *first* identity created in a test adopts the default board.
    """
    import contextlib

    from fastapi.testclient import TestClient

    from app import users
    from app.main import app

    stack = contextlib.ExitStack()

    def _login(email: str, account_id: str):
        async def fake_get_access_token(code, redirect_uri, code_verifier=None):
            return {"access_token": "gh-access-token", "expires_at": None}

        async def fake_get_id_email(access_token):
            return account_id, email

        monkeypatch.setattr(users.github_oauth_client, "get_access_token", fake_get_access_token)
        monkeypatch.setattr(users.github_oauth_client, "get_id_email", fake_get_id_email)
        c = stack.enter_context(TestClient(app))
        _drive_github_login(c)
        return c

    yield _login
    stack.close()
