"""Personal-access-token generation + hashing (M3 V9, ADR 0014).

A PAT is a high-entropy random secret shown to the user **once**; the DB stores
only its hash (R7.1). We use **HMAC-SHA256 keyed with ``AUTH_SECRET``** (a pepper):

- *Deterministic + indexable* — auth is a single ``WHERE token_hash = :h`` lookup,
  not an O(n) scan. (Password hashes like bcrypt salt per row and can't be looked
  up; they exist to slow brute force on low-entropy passwords — a 256-bit random
  token doesn't need that.)
- *Peppered* — a stolen database alone can't be used to verify guessed tokens
  offline without also stealing ``AUTH_SECRET``.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from .users import AUTH_SECRET

# Human-readable, greppable marker so a leaked token is recognisable (and so
# secret-scanners can flag it). The random part is url-safe base64 of 32 bytes.
#
# Renamed ``kanban_pat_`` → ``pandan_pat_`` by the rebrand (V40, KAN-423, ADR 0018).
# **Tokens minted under the old prefix keep authenticating indefinitely** — see
# ``LEGACY_TOKEN_PREFIXES`` below and the guard in ``app/authz.py`` (_resolve_pat).
# Nothing forces a rotation; only rotating ``AUTH_SECRET`` (the HMAC pepper) would.
#
# The ``KAN-`` / ``EPIC-`` **ticket** prefixes are a different thing entirely and are
# deliberately NOT renamed — they come from immutable per-table Postgres SEQUENCEs
# (ADR 0006 / 0009), so a prefix change would split the board's own history. See the
# note at the ``server_default``s in ``app/models.py``. Please don't "finish" it.
TOKEN_PREFIX = "pandan_pat_"
# Prefixes retired by a rebrand but still honoured on **incoming** tokens, so an
# already-issued PAT is never invalidated by a renaming. Mint uses TOKEN_PREFIX only.
LEGACY_TOKEN_PREFIXES = ("kanban_pat_",)
# Every prefix a bearer may legitimately start with. Used by the resolver's cheap
# fast-path reject (no DB round-trip for a stray bearer); verification itself is
# always a hash lookup over the *whole* raw token.
ACCEPTED_TOKEN_PREFIXES = (TOKEN_PREFIX, *LEGACY_TOKEN_PREFIXES)
# How much of the raw token to keep as a non-secret display hint (e.g. the UI list
# shows "pandan_pat_ab12…" so a user can tell tokens apart).
PREFIX_DISPLAY_LEN = len(TOKEN_PREFIX) + 4


def hash_token(raw: str) -> str:
    """HMAC-SHA256(AUTH_SECRET, raw) as a 64-char hex digest."""
    return hmac.new(AUTH_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """Mint a new PAT → ``(raw, token_prefix, token_hash)``.

    ``raw`` is returned to the caller **once** (never stored); persist only
    ``token_prefix`` (display hint) and ``token_hash``.
    """
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:PREFIX_DISPLAY_LEN], hash_token(raw)
