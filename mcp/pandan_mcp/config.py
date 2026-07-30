"""Runtime config for the MCP server, read from the environment.

- ``PANDAN_API_URL`` — base URL of the Pandan API (default the local dev backend).
  The ``/api/v1`` prefix is added by the client, so give just the origin.
- ``PANDAN_TOKEN`` — bearer token. Since M3 V8 (ADR 0013) the whole ``/api/v1``
  surface is auth-required, so this is **required**: use a personal access token
  (``pandan_pat_…``, created in the SPA Tokens UI, V9/ADR 0014; a pre-rebrand
  ``kanban_pat_…`` token still authenticates). Empty/unset → no Authorization
  header, which the server rejects with ``401``.
- ``PANDAN_BOARD_ID`` — optional default board (an integer id) for board-scoped
  tools when a call omits ``board_id`` (V10). Unset → the API's own fallback
  (list = all your boards; create = your earliest board).

Each of the three also has a **deprecated** pre-rebrand spelling — ``KANBAN_API_URL``
/ ``KANBAN_TOKEN`` / ``KANBAN_BOARD_ID`` — read **second**, with a one-line notice on
stderr (V40, KAN-423, ADR 0018). stderr specifically: an MCP stdio server's *stdout*
is the JSON-RPC channel, so anything printed there would corrupt the protocol. The
fallback exists so the cutover can't brick a live ``.mcp.json``; it is scheduled for
removal once nothing reads it.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

DEFAULT_API_URL = "http://localhost:8000"

# Each config key's environment-variable spellings, **in precedence order**: the
# current name first, then names retired by the rebrand (V40, KAN-423).
_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "api_url": ("PANDAN_API_URL", "KANBAN_API_URL"),
    "token": ("PANDAN_TOKEN", "KANBAN_TOKEN"),
    "board_id": ("PANDAN_BOARD_ID", "KANBAN_BOARD_ID"),
}

# Advisory notices must not repeat — load_config may be called more than once.
_warned: set[str] = set()


@dataclass(frozen=True)
class Config:
    api_url: str
    token: str | None
    board_id: int | None


def _env(key: str) -> str:
    """The value for a config key, current env name first then the retired ones.

    Empty string is treated the same as unset (a common ``.mcp.json`` placeholder).
    Resolving from a retired name emits a one-time deprecation notice on stderr.
    """
    current, *legacy = _ENV_NAMES[key]
    val = os.environ.get(current, "").strip()
    if val:
        return val
    for name in legacy:
        val = os.environ.get(name, "").strip()
        if val:
            if name not in _warned:
                _warned.add(name)
                print(
                    f"pandan-mcp: {name} is deprecated — use {current} instead.",
                    file=sys.stderr,
                )
            return val
    return ""


def load_config() -> Config:
    api_url = _env("api_url") or DEFAULT_API_URL
    token = _env("token") or None
    board_id = _parse_board_id(_env("board_id"))
    return Config(api_url=api_url, token=token, board_id=board_id)


def _parse_board_id(raw: str) -> int | None:
    """Parse the optional default board id; empty → None, non-integer → a clear error."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{_ENV_NAMES['board_id'][0]} must be an integer, got {raw!r}"
        ) from exc
