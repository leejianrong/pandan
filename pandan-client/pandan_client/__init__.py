"""Shared httpx client for the Pandan REST API (`/api/v1`).

Single source of truth imported by both the MCP server and the CLI so the thin
adapters never drift (DRY; API-first, ADR 0005). Public surface:

- ``PandanClient`` — one method per API endpoint.
- ``PandanApiError`` — raised on any non-2xx response.
- ``DEFAULT_TIMEOUT`` — the client's default request timeout (seconds).
"""
from __future__ import annotations

from .client import DEFAULT_TIMEOUT, PandanApiError, PandanClient, split_card_selectors

__all__ = [
    "DEFAULT_TIMEOUT",
    "PandanApiError",
    "PandanClient",
    "split_card_selectors",
]

__version__ = "0.1.0"
