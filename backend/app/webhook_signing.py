"""Shared HMAC-SHA256 webhook signing (V38, KAN-302).

The single definition of the ``X-Hub-Signature-256: sha256=<hexdigest>`` scheme
used on **both** sides of the app's webhook boundary, so the two are symmetric:

- **inbound** — GitHub signs its webhook deliveries this way and
  :mod:`app.routers.webhooks` *verifies* them with :func:`verify` (shared secret
  ``WEBHOOK_SECRET``);
- **outbound** — :mod:`app.outbound` *signs* the app's own notification webhooks
  with :func:`sign` (per-board ``outbound_webhook_secret``), MIRRORING the inbound
  scheme so a downstream receiver verifies our POST exactly as we verify GitHub's.

GitHub signs the **raw** request body (HMAC-SHA256 keyed on the shared secret). We
do the same over the raw serialized JSON body we send.
"""
from __future__ import annotations

import hashlib
import hmac

# The header both inbound (GitHub → us) and outbound (us → downstream) use.
SIGNATURE_HEADER = "X-Hub-Signature-256"


def sign(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hexdigest>`` signature for ``body`` keyed on ``secret``."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time-compare a received ``sha256=<hex>`` signature header.

    ``False`` for a missing/malformed header or a mismatch; uses
    :func:`hmac.compare_digest` so the comparison is not timing-variable.
    """
    if not header or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(sign(secret, body), header)
