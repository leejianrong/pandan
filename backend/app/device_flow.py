"""RFC 8628 Device Authorization Grant — the primitives (ADR 0024, KAN-1727).

Two secrets, generated differently because they play different roles:

- **``device_code``** — a high-entropy bearer secret the CLI polls with. Stored
  **hashed** (HMAC-SHA256 keyed with ``AUTH_SECRET``, the same
  :func:`app.tokens.hash_token` a PAT uses) — it is never displayed to a human, so
  there is no length/typo tradeoff to make; long and random is strictly better.
- **``user_code``** — a short code a human reads off the CLI and either types at
  ``verification_uri`` or confirms via ``verification_uri_complete`` (a `gh auth
  login`-style fallback). Generated from a **shape-restricted alphabet**
  (uppercase letters + digits, excluding ``0``/``O``/``1``/``I``/``L`` — the
  classic ambiguous-glyph set) and grouped ``XXXX-XXXX`` for the same reason phone
  numbers group digits: easier to read aloud, easier to type correctly, easier to
  notice a typo in. It is stored **as-is**, not hashed — the consent screen itself
  requires an authenticated human session to act on a code, so a `user_code`'s
  entire job is being findable, not being secret.

**Expiry and poll interval are implementation details ADR 0024 explicitly leaves
to the build** ("device-code/user-code entropy, exact expiry (~10-15 min) and
poll-interval values are implementation details to pin in the build, not fixed by
this ADR"). Pinned here, at the RFC's own suggested defaults:

- ``DEVICE_CODE_TTL_SECONDS = 900`` (15 minutes) — long enough that a human
  switching to a browser, signing in via GitHub if not already, and reviewing the
  consent screen is never rushed, short enough that a stale, un-actioned code
  can't be resurrected days later.
- ``DEVICE_POLL_INTERVAL_SECONDS = 5`` — RFC 8628's own suggested floor. A poll
  faster than this gets ``slow_down`` (:func:`too_soon_to_poll`).

**Poll-interval enforcement is in-process memory, not a DB column** — the same
accepted MVP tradeoff ``app/ratelimit.py`` (V27, KAN-291) already documents for
this exact reason ("single machine, resets on cold-start"): a device_authorization
row lives at most 15 minutes, so losing its poll-cadence state to a restart is
inconsequential, and it avoids a schema column, and a write, on every single poll.
"""
from __future__ import annotations

import secrets
import time

DEVICE_CODE_TTL_SECONDS = 900
DEVICE_POLL_INTERVAL_SECONDS = 5

# Crockford-ish: uppercase letters + digits, minus 0/O/1/I/L (visually ambiguous
# in most fonts, and the exact set `gh auth login`'s own user codes avoid).
_USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_USER_CODE_GROUP_LEN = 4
_USER_CODE_GROUPS = 2


def generate_device_code() -> str:
    """A high-entropy bearer secret, never shown to a human. Store only its hash
    (:func:`app.tokens.hash_token`)."""
    return secrets.token_urlsafe(32)


def generate_user_code() -> str:
    """A short, human-typeable code: two groups of four from the restricted
    alphabet, joined with a hyphen (e.g. ``"WDJB-MJHT"``). ~26 bits of entropy —
    plenty for a secret whose real job is uniqueness among the handful of codes
    live at any moment, not brute-force resistance (the consent screen it points
    at requires an authenticated human session regardless)."""
    groups = [
        "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(_USER_CODE_GROUP_LEN))
        for _ in range(_USER_CODE_GROUPS)
    ]
    return "-".join(groups)


# device_code_hash -> monotonic timestamp of its last poll. See the module
# docstring for why this is in-process memory rather than a DB column. Keyed on
# the hash (a random secret, never reused) rather than device_authorization.id
# (a recyclable surrogate key — an auto-increment id restarts under this repo's
# own test-suite convention of TRUNCATE ... RESTART IDENTITY between tests, which
# a plain id would collide across if used here, and even outside tests a hash is
# the more honest key: it's what the caller actually presents on every poll).
_last_polled_at: dict[str, float] = {}


def too_soon_to_poll(device_code_hash: str) -> bool:
    """``True`` if this device code was polled less than
    :data:`DEVICE_POLL_INTERVAL_SECONDS` ago — the caller should respond
    ``slow_down`` rather than evaluating status. Always records this poll's
    timestamp as a side effect, whether or not it was too soon, so a client that
    ignores ``slow_down`` and keeps polling at the same (too-fast) cadence keeps
    getting `slow_down` rather than sneaking in on alternating requests."""
    now = time.monotonic()
    last = _last_polled_at.get(device_code_hash)
    _last_polled_at[device_code_hash] = now
    return last is not None and (now - last) < DEVICE_POLL_INTERVAL_SECONDS


def forget_poll_state(device_code_hash: str) -> None:
    """Drop the poll-cadence entry once a code resolves (approved/denied/expired/
    redeemed) — it will never be polled meaningfully again, and an unbounded dict
    across a long process lifetime is the failure mode worth a one-line guard
    against."""
    _last_polled_at.pop(device_code_hash, None)
