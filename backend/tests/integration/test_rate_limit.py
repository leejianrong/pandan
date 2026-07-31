"""Application rate-limiting tests (V27, KAN-291).

Covers the contract from the ticket:
- Off by default (existing suite fires many requests and must be unaffected).
- Exceed a configured limit → **429 + Retry-After**; under the limit → untouched.
- The key is the **trusted Fly client IP**, not the spoofable ``X-Forwarded-For``.
- The generic ``/api/v1`` write tier trips on writes while reads stay unlimited.

Per the suite convention, all ``app`` imports live inside test/fixture bodies so
the ``_database`` fixture's ``DATABASE_URL`` override lands first (the PR #17 trap).

The rate-limit engine is a module global the middleware consults live, so a fixture
swaps in a low-limit engine (with a fresh in-memory store) at runtime and restores
the default afterwards — no app rebuild, no effect on other tests.
"""
from __future__ import annotations

import pytest

LOGIN = "/auth/login"
CARDS = "/api/v1/cards"


@pytest.fixture
def rate_limited():
    """Factory: enable rate limiting with the given per-tier limit strings for the
    duration of a test, then restore the default (disabled) engine."""
    from app import ratelimit

    saved = ratelimit.current_engine()

    def _configure(**limits_map: str):
        engine = ratelimit.build_engine(enabled=True, limits_map=limits_map)
        ratelimit.set_engine(engine)
        return engine

    yield _configure
    ratelimit.set_engine(saved)


def _bad_login(client):
    """Fire a (deliberately failing) login. The status is never 429 unless the
    limiter trips — rate limiting happens in middleware before the route runs."""
    return client.post(LOGIN, data={"username": "nobody@example.com", "password": "x"})


def test_disabled_by_default(client):
    """With no RATE_LIMIT_ENABLED, hammering an endpoint never yields a 429."""
    for _ in range(15):
        resp = _bad_login(client)
        assert resp.status_code != 429


def test_auth_tier_429_and_retry_after(client, rate_limited):
    """Exceeding the auth tier returns 429 with a numeric Retry-After; the
    requests under the limit are unaffected (normal non-429 status)."""
    rate_limited(auth="3/minute")

    for _ in range(3):
        assert _bad_login(client).status_code != 429

    blocked = _bad_login(client)
    assert blocked.status_code == 429
    retry_after = blocked.headers.get("Retry-After")
    assert retry_after is not None and retry_after.isdigit() and int(retry_after) >= 1


def test_keys_on_fly_client_ip_not_spoofed_xff(client, rate_limited):
    """The bucket keys on Fly-Client-IP, ignoring X-Forwarded-For.

    Varying only the (spoofable) XFF while holding Fly-Client-IP constant shares
    one bucket → it still trips. A different Fly-Client-IP is a separate bucket →
    unaffected. If XFF were the key, varying it would dodge the limit."""
    rate_limited(auth="2/minute")

    ip_a = {"Fly-Client-IP": "203.0.113.7"}
    # Same real IP, different spoofed XFF each time — must still count together.
    assert client.post(LOGIN, headers={**ip_a, "X-Forwarded-For": "1.1.1.1"},
                       data={"username": "a@b.c", "password": "x"}).status_code != 429
    assert client.post(LOGIN, headers={**ip_a, "X-Forwarded-For": "2.2.2.2"},
                       data={"username": "a@b.c", "password": "x"}).status_code != 429
    third = client.post(LOGIN, headers={**ip_a, "X-Forwarded-For": "3.3.3.3"},
                        data={"username": "a@b.c", "password": "x"})
    assert third.status_code == 429

    # A genuinely different Fly client IP is a fresh bucket — not limited.
    ip_b = {"Fly-Client-IP": "198.51.100.42"}
    assert client.post(LOGIN, headers=ip_b,
                       data={"username": "a@b.c", "password": "x"}).status_code != 429


def test_write_tier_trips_but_reads_are_unlimited(logged_in_client, rate_limited):
    """The generic /api/v1 write tier trips on POSTs (covering all writes +
    dispatch + POST /tokens), while GET reads are never rate-limited."""
    rate_limited(write="3/minute")

    for i in range(3):
        resp = logged_in_client.post(CARDS, json={"title": f"rl-{i}"})
        assert resp.status_code == 201

    blocked = logged_in_client.post(CARDS, json={"title": "rl-over"})
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After") is not None

    # Reads are not classified into any tier, so they stay unaffected.
    for _ in range(10):
        assert logged_in_client.get(CARDS).status_code == 200
