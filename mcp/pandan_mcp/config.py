"""Runtime config for the MCP server, read from the environment.

- ``KANBAN_API_URL`` — base URL of the Kanban API (default the local dev backend).
  The ``/api/v1`` prefix is added by the client, so give just the origin.
- ``KANBAN_TOKEN`` — bearer token. Since M3 V8 (ADR 0013) the whole ``/api/v1``
  surface is auth-required, so this is **required**: use a personal access token
  (``kanban_pat_…``, created in the SPA Tokens UI, V9/ADR 0014). Empty/unset →
  no Authorization header, which the server rejects with ``401``.
- ``KANBAN_BOARD_ID`` — optional default board (an integer id) for board-scoped
  tools when a call omits ``board_id`` (V10). Unset → the API's own fallback
  (list = all your boards; create = your earliest board).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_API_URL = "http://localhost:8000"


@dataclass(frozen=True)
class Config:
    api_url: str
    token: str | None
    board_id: int | None


def load_config() -> Config:
    api_url = os.environ.get("KANBAN_API_URL", DEFAULT_API_URL).strip() or DEFAULT_API_URL
    # Treat empty string the same as unset (a common .mcp.json placeholder).
    token = os.environ.get("KANBAN_TOKEN", "").strip() or None
    board_id = _parse_board_id(os.environ.get("KANBAN_BOARD_ID", ""))
    return Config(api_url=api_url, token=token, board_id=board_id)


def _parse_board_id(raw: str) -> int | None:
    """Parse the optional default board id; empty → None, non-integer → a clear error."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"KANBAN_BOARD_ID must be an integer, got {raw!r}") from exc
