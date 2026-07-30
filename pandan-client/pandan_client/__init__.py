"""Shared httpx client for the Simple Kanban REST API (`/api/v1`).

Single source of truth imported by both the MCP server and the CLI so the thin
adapters never drift (DRY; API-first, ADR 0005). Public surface:

- ``KanbanClient`` — one method per API endpoint.
- ``KanbanApiError`` — raised on any non-2xx response.
- ``DEFAULT_TIMEOUT`` — the client's default request timeout (seconds).
"""
from __future__ import annotations

from .client import DEFAULT_TIMEOUT, KanbanApiError, KanbanClient

__all__ = ["DEFAULT_TIMEOUT", "KanbanApiError", "KanbanClient"]

__version__ = "0.1.0"
