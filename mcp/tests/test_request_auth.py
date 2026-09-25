"""Per-request bearer-token override for the hosted transport (KAN-1732).

The whole point of :mod:`pandan_mcp.request_auth` is isolating concurrent
hosted requests from each other — a ``contextvars.ContextVar`` rather than a
plain module global specifically because it's **task-local**, so two
concurrent asyncio tasks (two hosted requests in flight at once, on the one
always-on process ADR 0025 describes) never see each other's token. These
tests pin the basic get/set/clear contract and, more importantly, that
cross-task isolation property itself.
"""
from __future__ import annotations

import asyncio

from pandan_mcp.request_auth import clear_request_token, get_request_token, set_request_token


def test_default_is_none():
    assert get_request_token() is None


def test_set_then_get_round_trips():
    set_request_token("pandan_pat_abc")
    assert get_request_token() == "pandan_pat_abc"
    clear_request_token()


def test_clear_resets_to_none():
    set_request_token("pandan_pat_abc")
    clear_request_token()
    assert get_request_token() is None


def test_concurrent_tasks_never_see_each_others_token():
    """The property the hosted transport actually depends on: setting the
    token inside one asyncio task must not leak into a concurrently-running
    sibling task, mirroring two hosted requests in flight on the one process."""

    async def _run() -> tuple[str | None, str | None]:
        async def _as(token: str) -> str | None:
            set_request_token(token)
            # Yield control so the two tasks genuinely interleave rather than
            # one running start-to-finish before the other starts.
            await asyncio.sleep(0)
            seen = get_request_token()
            clear_request_token()
            return seen

        return await asyncio.gather(_as("pandan_pat_alice"), _as("pandan_pat_bob"))

    alice_saw, bob_saw = asyncio.run(_run())
    assert alice_saw == "pandan_pat_alice"
    assert bob_saw == "pandan_pat_bob"


def test_a_task_with_no_override_sees_none_even_while_a_sibling_has_one():
    """The stdio transport's own singleton path (no override at all) must stay
    unaffected by a hosted request happening concurrently in another task —
    this is what lets `_client_instance()` fall through to the singleton
    safely when nothing has called `set_request_token` for THIS task."""

    async def _run() -> tuple[str | None, str | None]:
        async def _with_override() -> str | None:
            set_request_token("pandan_pat_hosted")
            await asyncio.sleep(0)
            seen = get_request_token()
            clear_request_token()
            return seen

        async def _without_override() -> str | None:
            await asyncio.sleep(0)
            return get_request_token()

        return await asyncio.gather(_with_override(), _without_override())

    hosted_saw, stdio_saw = asyncio.run(_run())
    assert hosted_saw == "pandan_pat_hosted"
    assert stdio_saw is None
