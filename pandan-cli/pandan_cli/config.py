"""Runtime config for the ``kan`` CLI.

Each value (``api_url`` / ``token`` / ``board_id``) is resolved independently
through a precedence chain — the first source that supplies a non-empty value
wins:

1. **Environment** — ``KANBAN_API_URL`` / ``KANBAN_TOKEN`` / ``KANBAN_BOARD_ID``.
2. **User config file** — ``~/.config/kan/config.toml`` (``$XDG_CONFIG_HOME``
   aware), a ``[kan]`` table with ``api_url`` / ``token`` / ``board_id``. Written
   by ``kan config set`` / ``kan login`` at mode ``0600``.
3. **``.mcp.json``** — found by walking up from the CWD, reading
   ``.mcpServers.kanban.env.{KANBAN_API_URL,KANBAN_TOKEN,KANBAN_BOARD_ID}``. This
   matches Claude Code's convention: the PAT already lives there for the MCP
   server, so the CLI can reuse it.

The point of sources 2 and 3 is that a **PAT never has to be put on a command
line or echoed into the environment by hand** — it stays machine-side, so it
can't leak into a shell transcript / model context. Vars:

- ``KANBAN_API_URL`` — base URL of the Kanban API (default the local dev backend).
  The ``/api/v1`` prefix is added by the client, so give just the origin.
- ``KANBAN_TOKEN`` — bearer token. Since M3 V8 (ADR 0013) the whole ``/api/v1``
  surface is auth-required, so this is **required**: a personal access token
  (``kanban_pat_…``, created in the SPA Tokens UI, V9/ADR 0014). Empty/unset from
  every source is a clean CLI error before any request is made.
- ``KANBAN_BOARD_ID`` — optional default board (an integer id) for board-scoped
  commands (``list``/``create``) when they omit ``--board``. Unset → the API's own
  fallback (list = all your boards; create = your earliest board).
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_URL = "http://localhost:8000"

# The three config keys, in their environment-variable spelling.
_ENV_API_URL = "KANBAN_API_URL"
_ENV_TOKEN = "KANBAN_TOKEN"
_ENV_BOARD_ID = "KANBAN_BOARD_ID"


class ConfigError(Exception):
    """Raised when the environment is missing something the CLI needs."""


@dataclass(frozen=True)
class Config:
    api_url: str
    token: str
    board_id: int | None


def config_file_path() -> Path:
    """Path to the user config file: ``$XDG_CONFIG_HOME/kan/config.toml``, or
    ``~/.config/kan/config.toml`` when ``XDG_CONFIG_HOME`` is unset."""
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "kan" / "config.toml"


def find_mcp_json(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default CWD) to the filesystem root, returning the
    first ``.mcp.json`` found, else ``None``."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".mcp.json"
        if candidate.is_file():
            return candidate
    return None


def _from_env() -> dict[str, str]:
    """The three values as seen in the environment (missing → absent key)."""
    out: dict[str, str] = {}
    for key, env in (("api_url", _ENV_API_URL), ("token", _ENV_TOKEN), ("board_id", _ENV_BOARD_ID)):
        val = os.environ.get(env, "").strip()
        if val:
            out[key] = val
    return out


def _from_config_file() -> dict[str, str]:
    """Values from the ``[kan]`` table of the user config file. A missing or
    malformed file yields ``{}`` — a broken fallback never crashes the CLI, since
    another source (or the final ``KANBAN_TOKEN required`` error) still applies."""
    path = config_file_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    table = data.get("kan", data)  # tolerate keys at top level too
    if not isinstance(table, dict):
        return {}
    return _normalize({k: table.get(k) for k in ("api_url", "token", "board_id")})


def _from_mcp_json() -> dict[str, str]:
    """Values from ``.mcpServers.kanban.env`` of the nearest ``.mcp.json``.
    Missing/malformed → ``{}`` (see ``_from_config_file``)."""
    path = find_mcp_json()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        env = data["mcpServers"]["kanban"]["env"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    if not isinstance(env, dict):
        return {}
    return _normalize(
        {
            "api_url": env.get(_ENV_API_URL),
            "token": env.get(_ENV_TOKEN),
            "board_id": env.get(_ENV_BOARD_ID),
        }
    )


def _normalize(raw: dict[str, object]) -> dict[str, str]:
    """Coerce a source's values to stripped non-empty strings, dropping the rest.
    (``.mcp.json`` may carry ``board_id`` as a JSON number, so ``str()`` first.)"""
    out: dict[str, str] = {}
    for key, val in raw.items():
        if val is None:
            continue
        text = str(val).strip()
        if text:
            out[key] = text
    return out


def load_config(*, require_token: bool = True) -> Config:
    """Resolve config through the env → config-file → ``.mcp.json`` chain (see the
    module docstring). Raises ``ConfigError`` (mapped to a clean stderr message +
    non-zero exit by the CLI) when ``KANBAN_TOKEN`` resolves to nothing or
    ``KANBAN_BOARD_ID`` is not an integer.

    ``require_token=False`` skips the token check for commands that only hit the
    public, unauthenticated ``/api/health`` endpoint (``warmup``), so they work as
    a CI pre-step before any PAT is configured."""
    resolved = resolve_values()

    api_url = resolved.get("api_url") or DEFAULT_API_URL
    token = resolved.get("token", "")
    if require_token and not token:
        raise ConfigError(
            "KANBAN_TOKEN is required (a personal access token 'kanban_pat_…'; "
            "create one in the Tokens UI). Set it via the KANBAN_TOKEN env var, "
            "`kan config set --token-stdin`, or .mcpServers.kanban.env in .mcp.json. "
            "The /api/v1 API is auth-required."
        )
    board_id = _parse_board_id(resolved.get("board_id", ""))
    return Config(api_url=api_url, token=token, board_id=board_id)


def resolve_values() -> dict[str, str]:
    """Merge the sources with env > config-file > ``.mcp.json`` precedence,
    per value. Exposed (not just inlined in ``load_config``) so ``kan config show``
    can report the effective config without re-implementing the chain."""
    merged: dict[str, str] = {}
    for source in (_from_mcp_json(), _from_config_file(), _from_env()):
        merged.update(source)  # later (higher-precedence) sources overwrite
    return merged


def _parse_board_id(raw: str) -> int | None:
    """Parse the optional default board id; empty → None, non-integer → a clear error."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"KANBAN_BOARD_ID must be an integer, got {raw!r}") from exc


def write_config_file(
    *,
    api_url: str | None = None,
    token: str | None = None,
    board_id: str | None = None,
) -> Path:
    """Merge the given values into the user config file (``0600``), preserving any
    existing keys not being set, and return its path. Only non-``None`` args are
    written; pass an empty string to clear a key."""
    path = config_file_path()
    current: dict[str, str] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            table = data.get("kan", data)
            if isinstance(table, dict):
                current = {
                    k: str(table[k])
                    for k in ("api_url", "token", "board_id")
                    if table.get(k) is not None
                }
        except (OSError, tomllib.TOMLDecodeError):
            current = {}

    for key, val in (("api_url", api_url), ("token", token), ("board_id", board_id)):
        if val is None:
            continue
        if val.strip():
            current[key] = val.strip()
        else:
            current.pop(key, None)  # empty string clears

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_toml(current), encoding="utf-8")
    path.chmod(0o600)  # the token is a secret — owner-only
    return path


def _render_toml(values: dict[str, str]) -> str:
    """Render the ``[kan]`` table. ``board_id`` is emitted as a bare integer when
    it parses as one; everything else is a quoted string. The value set is tiny and
    known (a URL, a ``kanban_pat_…`` token, an int), so hand-rendering is safe."""
    lines = ["[kan]"]
    for key in ("api_url", "token", "board_id"):
        if key not in values:
            continue
        val = values[key]
        if key == "board_id" and val.lstrip("-").isdigit():
            lines.append(f"{key} = {val}")
        else:
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    return "\n".join(lines) + "\n"
