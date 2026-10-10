"""Runtime config for the MCP server, read from the environment, then falling
back to the CLI's own config file (ADR 0024, KAN-1731).

- ``PANDAN_API_URL`` — base URL of the Pandan API (default the local dev backend).
  The ``/api/v1`` prefix is added by the client, so give just the origin.
- ``PANDAN_TOKEN`` — bearer token. Since M3 V8 (ADR 0013) the whole ``/api/v1``
  surface is auth-required, so this is **required**: use a personal access token
  (``pandan_pat_…``, created in the SPA Tokens UI, V9/ADR 0014; a pre-rebrand
  ``kanban_pat_…`` token still authenticates). Empty/unset → no Authorization
  header, which the server rejects with ``401``.
**There is no default board.** ``PANDAN_BOARD_ID`` / ``KANBAN_BOARD_ID`` is
retired: board-scoped tools require ``board_id`` per call, or one ``use_board`` call
for the (stdio) session. A leftover value is ignored with a one-line stderr notice
rather than an error, so an existing ``.mcp.json`` keeps launching.

Each of the two also has a **deprecated** pre-rebrand spelling — ``KANBAN_API_URL``
/ ``KANBAN_TOKEN`` — read **second**, with a one-line notice on
stderr (V40, KAN-423, ADR 0018). stderr specifically: an MCP stdio server's *stdout*
is the JSON-RPC channel, so anything printed there would corrupt the protocol. The
fallback exists so the cutover can't brick a live ``.mcp.json``; it is scheduled for
removal once nothing reads it.

**The config-file fallback (ADR 0024, KAN-1731).** A server launched with no
``PANDAN_TOKEN`` in its ``.mcp.json`` env now also checks
``~/.config/pandan/config.toml`` — the same file ``pandan auth login``/``pandan
login`` write. Precedence stays **environment first**: a value already set in
``.mcp.json`` is never overridden by the file. This is deliberately a **read-only,
minimal** mirror of ``pandan_cli.config``'s own file handling — no legacy
``~/.config/kan/config.toml`` migration, no ``.mcp.json``-in-a-parent-directory
walk (this process is *itself* what a ``.mcp.json`` launches, so reading its own
launcher's file would be circular) — those stay CLI-only. Its purpose is narrow:
close the one gap ADR 0024 named — "``pandan auth login`` populates the CLI's
credential but does not, by itself, wire up an MCP server already configured via
``.mcp.json`` env vars" — for the specific case of an ``.mcp.json`` that sets no
``PANDAN_TOKEN`` at all yet, not the case of one that sets a stale one (env still
wins there, on purpose: an explicit ``.mcp.json`` entry is a deliberate choice).
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_URL = "http://localhost:8000"

# Each config key's environment-variable spellings, **in precedence order**: the
# current name first, then names retired by the rebrand (V40, KAN-423).
_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "api_url": ("PANDAN_API_URL", "KANBAN_API_URL"),
    "token": ("PANDAN_TOKEN", "KANBAN_TOKEN"),
}
# Retired: the default board. Recognised only to say it is ignored.
_RETIRED_ENV_NAMES = ("PANDAN_BOARD_ID", "KANBAN_BOARD_ID")

# The config file's TOML table, current name only (see module docstring: this
# fallback is deliberately narrower than the CLI's own, which also reads a
# legacy ``[kan]`` table).
_CONFIG_TABLE_NAME = "pandan"

# Advisory notices must not repeat — load_config may be called more than once.
_warned: set[str] = set()


@dataclass(frozen=True)
class Config:
    api_url: str
    token: str | None


def _config_file_path() -> Path:
    """``$XDG_CONFIG_HOME/pandan/config.toml``, or ``~/.config/pandan/config.toml``
    when unset — the exact path ``pandan_cli.config.config_file_path()`` computes,
    duplicated rather than imported (this package must not depend on the CLI, the
    same adapter-independence rule that keeps ``pandan-client`` the only code the
    two share)."""
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "pandan" / "config.toml"


def _from_config_file() -> dict[str, str]:
    """Values from the CLI's config file, or ``{}`` if it doesn't exist, isn't
    readable, or isn't valid TOML — a missing/broken file is never fatal here,
    since the file is a convenience this fallback adds on top of, not something
    this server depends on."""
    path = _config_file_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    table = data.get(_CONFIG_TABLE_NAME, data)
    if not isinstance(table, dict):
        return {}
    return {k: str(v) for k, v in table.items() if isinstance(k, str) and v is not None}


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


def _resolve(key: str, file_values: dict[str, str]) -> str:
    """Environment (current, then deprecated spellings) first; the CLI's config
    file only when **no** environment spelling supplied anything at all."""
    val = _env(key)
    if val:
        return val
    return file_values.get(key, "").strip()


def load_config() -> Config:
    for name in _RETIRED_ENV_NAMES:
        if os.environ.get(name, "").strip() and name not in _warned:
            _warned.add(name)
            print(
                f"pandan-mcp: {name} is ignored — there is no default board any more. "
                "Pass board_id on each call, or call use_board once per session.",
                file=sys.stderr,
            )
    file_values = _from_config_file()
    api_url = _resolve("api_url", file_values) or DEFAULT_API_URL
    token = _resolve("token", file_values) or None
    return Config(api_url=api_url, token=token)
