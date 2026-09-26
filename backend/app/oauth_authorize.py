"""OAuth 2.1 authorization_code + PKCE grant primitives (ADR 0026, KAN-1735).

The redirect-based half ADR 0024 explicitly deferred to this card: device flow
(``app/device_flow.py``) has no redirect target and cannot be what a
browser-embedded client (Claude.ai, ChatGPT, Cursor's remote-MCP mode) completes.
This module holds the pure, DB-free primitives; ``app/routers/oauth_authorize.py``
and the extended ``POST /auth/device/token`` in ``app/routers/device_auth.py`` are
the endpoints that use them.

**Two bearer secrets, generated the same way as everywhere else in this
codebase** (``generate_device_code``'s own reasoning applies unchanged): high
entropy, never displayed to a human beyond a single redirect/response, so
there's no length/typo tradeoff to make. Store only the hash
(:func:`app.tokens.hash_token`).

- **authorization code** — minted at consent approval, exchanged at most once
  at the token endpoint. ADR 0026: "a short-lived, single-use authorization
  code (≤60s expiry)".
- **refresh token** — minted alongside an access token from the
  ``authorization_code``/``refresh_token`` grants, rotated (never reused) on
  each refresh. See ``app.auth_models.OAuthRefreshToken`` for the rotation
  model.

**TTLs are implementation details neither ADR 0024 nor ADR 0026 fixes** ("exact
... TTLs are implementation detail, not fixed here, beyond 'short-lived' and
'single-use where noted'") — pinned here as module constants, same posture as
``device_flow.DEVICE_CODE_TTL_SECONDS``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from starlette.requests import Request

AUTHORIZATION_CODE_TTL_SECONDS = 60
ACCESS_TOKEN_TTL_SECONDS = 3600  # 1 hour — short-lived, refreshed via a refresh token
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# The only PKCE method OAuth 2.1 permits — `plain` is dropped entirely, no
# fallback (ADR 0026: "mandatory — OAuth 2.1 drops `plain` entirely").
SUPPORTED_CODE_CHALLENGE_METHOD = "S256"

# The one resource this authorization server protects today (ADR 0025's own
# "moot for Pandan today, since the endpoint is the resource server rather than
# a proxy to one, but the validation is built in regardless"). Kept as a suffix
# constant, not a fixed origin, so it composes with the per-request origin the
# same way `app/oauth_metadata.py`/`app/device_auth.py` already derive theirs.
_MCP_RESOURCE_PATH = "/mcp"


def generate_authorization_code() -> str:
    """A high-entropy bearer secret, exchanged at most once. Store only its hash
    (:func:`app.tokens.hash_token`)."""
    return secrets.token_urlsafe(32)


def generate_refresh_token() -> str:
    """A high-entropy bearer secret, rotated (never reused) on each refresh.
    Store only its hash (:func:`app.tokens.hash_token`)."""
    return secrets.token_urlsafe(32)


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """RFC 7636 §4.6: ``code_challenge == BASE64URL-ENCODE(SHA256(code_verifier))``
    (the ``S256`` method — the only one this server accepts). Constant-time
    compare since a timing side-channel here would leak the challenge one byte
    at a time, exactly the reasoning ``hash_token`` lookups already rely on
    being a fast, non-comparison-based DB index instead."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(computed, code_challenge)


def canonical_mcp_resource(request: Request) -> str:
    """This server's one RFC 8707 resource identifier: the hosted MCP endpoint's
    own canonical URI. Derived from ``request.base_url`` per request, not a
    fixed string baked in at import time — the same reason
    ``app/oauth_metadata.py``'s docstring gives (one image, more than one
    possible origin across dev/Fly-prod/self-hosted)."""
    origin = str(request.base_url).rstrip("/")
    return f"{origin}{_MCP_RESOURCE_PATH}"
