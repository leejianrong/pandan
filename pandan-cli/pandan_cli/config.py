"""Runtime config for the ``pandan`` CLI.

Each value (``api_url`` / ``token`` / ``board_id`` / ``max_text_chars``) is
resolved independently through a precedence chain — the first source that
supplies a non-empty value wins:

1. **Environment** — ``PANDAN_API_URL`` / ``PANDAN_TOKEN`` / ``PANDAN_BOARD_ID``,
   and, as a **deprecated fallback**, the pre-rebrand ``KANBAN_*`` spellings
   (read second, with a one-line notice on stderr; V40, KAN-423, ADR 0018).
2. **User config file** — ``~/.config/pandan/config.toml`` (``$XDG_CONFIG_HOME``
   aware), a ``[pandan]`` table with ``api_url`` / ``token`` / ``board_id``. Written
   by ``pandan config set`` / ``pandan login`` at mode ``0600``. A pre-rebrand
   ``~/.config/kan/config.toml`` is migrated across on first use, and a legacy
   ``[kan]`` table is still read.
3. **``.mcp.json``** — found by walking up from the CWD, reading
   ``.mcpServers.pandan.env`` (falling back to the pre-rebrand ``.kanban.env``).
   This matches Claude Code's convention: the PAT already lives there for the MCP
   server, so the CLI can reuse it.

The point of sources 2 and 3 is that a **PAT never has to be put on a command
line or echoed into the environment by hand** — it stays machine-side, so it
can't leak into a shell transcript / model context. Vars:

- ``PANDAN_API_URL`` — base URL of the Pandan API (default the local dev backend).
  The ``/api/v1`` prefix is added by the client, so give just the origin.
- ``PANDAN_TOKEN`` — bearer token. Since M3 V8 (ADR 0013) the whole ``/api/v1``
  surface is auth-required, so this is **required**: a personal access token
  (``pandan_pat_…``, created in the SPA Tokens UI, V9/ADR 0014; a pre-rebrand
  ``kanban_pat_…`` token still authenticates). Empty/unset from every source is a
  clean CLI error before any request is made.
- ``PANDAN_BOARD_ID`` — optional default board (an integer id) for board-scoped
  commands (``list``/``create``) when they omit ``--board``. Unset → the API's own
  fallback (list = all your boards; create = your earliest board).
- ``PANDAN_REQUIRE_BOARD`` — opt-in safety switch (issue #277). When truthy, any
  board-scoped verb that is given no ``--board`` **fails** instead of silently
  falling back to ``board_id`` (or, with none set, to whatever the API picks).
  Default off, so no existing invocation changes behaviour. Config-file key:
  ``require_board``. It is **new since the rebrand**, so it has no deprecated
  ``KANBAN_*`` spelling.

  The failure mode it closes is asymmetric, which is why it is worth a whole
  setting: a stale default on a *read* is a confusing answer, but on ``create``
  it is a card filed on the wrong board — and with ten boards on one account,
  nothing in the output says so. Opt-in rather than default-on because the
  fallback is genuinely convenient on a single-board account, which is where
  most people start.
- ``PANDAN_MAX_TEXT_CHARS`` — the content-truncation limit in **characters**
  (V45, KAN-428): how much of a long free-text field (a card/epic
  ``description``, a comment/notification ``body``, an ``attention_note``) any
  output prints before it is cut and replaced with a size hint. Default
  ``DEFAULT_MAX_TEXT_CHARS``; ``0`` disables truncation entirely (the same effect
  as passing ``--full`` on every call). Config-file key: ``max_text_chars``.
  It is **new since the rebrand**, so it has no deprecated ``KANBAN_*`` spelling.

The ``KANBAN_*`` fallback exists so the cutover can't brick an existing
``.mcp.json``, config file or CI job mid-flight. It is scheduled for removal once
nothing reads it (ADR 0018 §Consequences).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_URL = "http://localhost:8000"

# How many characters of a long free-text field any output prints before it is cut
# and replaced with a size hint (V45, KAN-428 — AXI 3). Chosen to keep a `get` on a
# 3.4k-character card description cheap while still showing enough to act on;
# raise it (or pass ``--full``) when you actually want the whole body.
DEFAULT_MAX_TEXT_CHARS = 500

# Each config key's environment-variable spellings, **in precedence order**: the
# current name first, then names retired by the rebrand (V40, KAN-423).
_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "api_url": ("PANDAN_API_URL", "KANBAN_API_URL"),
    "token": ("PANDAN_TOKEN", "KANBAN_TOKEN"),
    "board_id": ("PANDAN_BOARD_ID", "KANBAN_BOARD_ID"),
    # New since the rebrand → one spelling only, no deprecated fallback to carry.
    "max_text_chars": ("PANDAN_MAX_TEXT_CHARS",),
    "require_board": ("PANDAN_REQUIRE_BOARD",),
}
# Every key the config file / .mcp.json / env chain carries, in a single tuple so
# reading, merging and re-writing the file can't drift (a `config set` that only
# knew three keys would silently drop a hand-added ``max_text_chars``).
_CONFIG_KEYS = tuple(_ENV_NAMES)
# Canonical (non-deprecated) spellings, for error messages.
_ENV_API_URL = _ENV_NAMES["api_url"][0]
_ENV_TOKEN = _ENV_NAMES["token"][0]
_ENV_BOARD_ID = _ENV_NAMES["board_id"][0]
_ENV_MAX_TEXT_CHARS = _ENV_NAMES["max_text_chars"][0]
_ENV_REQUIRE_BOARD = _ENV_NAMES["require_board"][0]

# The ``.mcp.json`` server key, current name first then the retired one.
_MCP_SERVER_NAMES = ("pandan", "kanban")
# The config file's TOML table, current name first then the retired one.
_CONFIG_TABLE_NAMES = ("pandan", "kan")
# Config directory basename, and the pre-rebrand one migrated from.
_CONFIG_DIR = "pandan"
_LEGACY_CONFIG_DIR = "kan"

# Notices are advisory and must not repeat once per lookup — resolution touches the
# environment several times per invocation.
_warned: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    """Emit ``message`` on **stderr** at most once per process.

    stderr, never stdout: every command's stdout is machine-readable (JSON or a
    stable table), so a deprecation notice there would corrupt a caller's parse.
    """
    if key in _warned:
        return
    _warned.add(key)
    print(message, file=sys.stderr)


class ConfigError(Exception):
    """Raised when the environment is missing something the CLI needs."""


@dataclass(frozen=True)
class Config:
    api_url: str
    token: str
    board_id: int | None
    # V45 (KAN-428): the content-truncation limit in characters; 0 = don't truncate.
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS
    # Issue #277: when True, a board-scoped verb with no --board is an error rather
    # than a silent fallback. Defaults False — opting in is the user's call.
    require_board: bool = False


def config_file_path() -> Path:
    """Path to the user config file: ``$XDG_CONFIG_HOME/pandan/config.toml``, or
    ``~/.config/pandan/config.toml`` when ``XDG_CONFIG_HOME`` is unset."""
    return _config_root() / _CONFIG_DIR / "config.toml"


def legacy_config_file_path() -> Path:
    """The pre-rebrand location, ``…/kan/config.toml`` (V40, KAN-423)."""
    return _config_root() / _LEGACY_CONFIG_DIR / "config.toml"


def _config_root() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(base) if base else Path.home() / ".config"


def migrate_legacy_config_file() -> Path | None:
    """Move a pre-rebrand ``…/kan/config.toml`` to ``…/pandan/config.toml``.

    Returns the new path when a migration happened, else ``None``. Copy-then-keep
    (not a move): the old file is left in place so a still-installed ``kan`` binary
    keeps working through the cutover. Idempotent, and any OS error is swallowed —
    a config file is a convenience, never a hard dependency.
    """
    new = config_file_path()
    old = legacy_config_file_path()
    if new.is_file() or not old.is_file():
        return None
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(old, new)
        new.chmod(0o600)  # it holds a token — owner-only, same as write_config_file
    except OSError:
        return None
    _warn_once(
        "config-dir",
        f"pandan: migrated your config from {old} to {new} "
        "(the old file was left in place; you can delete it).",
    )
    return new


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
    """The three values as seen in the environment (missing → absent key).

    Per key, the current ``PANDAN_*`` name wins; a retired ``KANBAN_*`` name is read
    only if the current one is empty, and resolving from one emits a deprecation
    notice naming both (V40, KAN-423).
    """
    out: dict[str, str] = {}
    for key, names in _ENV_NAMES.items():
        current, *legacy = names
        val = os.environ.get(current, "").strip()
        if val:
            out[key] = val
            continue
        for name in legacy:
            val = os.environ.get(name, "").strip()
            if val:
                out[key] = val
                _warn_once(
                    f"env:{name}",
                    f"pandan: {name} is deprecated — use {current} instead.",
                )
                break
    return out


def _from_config_file() -> dict[str, str]:
    """Values from the ``[pandan]`` table of the user config file (a pre-rebrand
    ``[kan]`` table is still read). A missing or malformed file yields ``{}`` — a
    broken fallback never crashes the CLI, since another source (or the final
    ``PANDAN_TOKEN required`` error) still applies."""
    migrate_legacy_config_file()
    path = config_file_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    table = _config_table(data)
    if not isinstance(table, dict):
        return {}
    return _normalize({k: table.get(k) for k in _CONFIG_KEYS})


def _config_table(data: dict) -> object:
    """The config table out of a parsed file: ``[pandan]``, else the pre-rebrand
    ``[kan]``, else the document itself (keys at top level are tolerated)."""
    for name in _CONFIG_TABLE_NAMES:
        if isinstance(data.get(name), dict):
            return data[name]
    return data


def _from_mcp_json() -> dict[str, str]:
    """Values from ``.mcpServers.pandan.env`` of the nearest ``.mcp.json`` (falling
    back to the pre-rebrand ``.kanban`` server key). Missing/malformed → ``{}``
    (see ``_from_config_file``)."""
    path = find_mcp_json()
    if path is None:
        return {}
    try:
        servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    if not isinstance(servers, dict):
        return {}
    for name in _MCP_SERVER_NAMES:
        env = servers.get(name, {})
        if not isinstance(env, dict):
            continue
        env = env.get("env")
        if not isinstance(env, dict):
            continue
        # Within a server block, honour both env spellings (current first).
        values = {
            key: next(
                (env[n] for n in names if env.get(n) not in (None, "")),
                None,
            )
            for key, names in _ENV_NAMES.items()
        }
        found = _normalize(values)
        if found:
            return found
    return {}


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
    non-zero exit by the CLI) when ``PANDAN_TOKEN`` resolves to nothing or
    ``PANDAN_BOARD_ID`` is not an integer.

    ``require_token=False`` skips the token check for commands that only hit the
    public, unauthenticated ``/api/health`` endpoint (``warmup``), so they work as
    a CI pre-step before any PAT is configured."""
    resolved = resolve_values()

    api_url = resolved.get("api_url") or DEFAULT_API_URL
    token = resolved.get("token", "")
    if require_token and not token:
        raise ConfigError(
            f"{_ENV_TOKEN} is required (a personal access token 'pandan_pat_…'; "
            f"create one in the Tokens UI). Set it via the {_ENV_TOKEN} env var, "
            "`pandan config set --token-stdin`, or .mcpServers.pandan.env in .mcp.json. "
            "The /api/v1 API is auth-required."
        )
    board_id = _parse_board_id(resolved.get("board_id", ""))
    return Config(
        api_url=api_url,
        token=token,
        board_id=board_id,
        max_text_chars=_parse_max_text_chars(resolved.get("max_text_chars", "")),
        require_board=parse_require_board(resolved.get("require_board", "")),
    )


def api_url_is_default() -> bool:
    """True when **no source** supplied ``api_url`` and the CLI fell back to
    ``DEFAULT_API_URL`` (KAN-613).

    This lives here, not in ``pandan_client``, because it is a question about *local
    configuration*, not about the API: the client is a thin API adapter (ADR 0005),
    handed a base URL it has no way to judge. Only the resolution chain knows whether
    that URL was chosen or merely defaulted.

    It re-asks the chain rather than comparing ``config.api_url == DEFAULT_API_URL``,
    so someone deliberately pointing at a local dev backend is **not** told they
    forgot to configure one — and so a half-migrated environment that sets only the
    deprecated ``KANBAN_API_URL`` counts as configured, because the fallback resolved
    it. Only called on a failure path, so the second pass over the sources is free
    (and ``_warn_once`` keeps it from re-printing a deprecation notice).
    """
    return not resolve_values().get("api_url")


def resolve_values() -> dict[str, str]:
    """Merge the sources with env > config-file > ``.mcp.json`` precedence,
    per value. Exposed (not just inlined in ``load_config``) so ``pandan config show``
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
        raise ConfigError(f"{_ENV_BOARD_ID} must be an integer, got {raw!r}") from exc


def _parse_max_text_chars(raw: str) -> int:
    """Parse the truncation limit (V45, KAN-428): empty → the default, ``0`` →
    truncation off, a negative or non-integer value → a clear error.

    A negative limit is rejected rather than clamped: silently treating ``-1`` as
    "no truncation" would make a typo look like a working setting."""
    raw = raw.strip()
    if not raw:
        return DEFAULT_MAX_TEXT_CHARS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{_ENV_MAX_TEXT_CHARS} must be a non-negative integer "
            f"(0 disables truncation), got {raw!r}"
        ) from exc
    if value < 0:
        raise ConfigError(
            f"{_ENV_MAX_TEXT_CHARS} must be a non-negative integer "
            f"(0 disables truncation), got {raw!r}"
        )
    return value


_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def parse_require_board(raw: str) -> bool:
    """Parse the ``require_board`` switch; empty → ``False`` (the default).

    A value that is neither truthy nor falsy is a **hard error**, not a shrug. This
    is the one setting whose whole job is to prevent a write landing on the wrong
    board, so ``PANDAN_REQUIRE_BOARD=ture`` must not quietly resolve to "off" and
    hand back the exact silent fallback the user asked to disable. Failing loud
    costs a typo fix; failing soft costs a card on someone else's board.

    Accepts TOML's own ``true``/``false`` as well as the shell idioms, since the
    value arrives either from a config file or from an env var.
    """
    text = raw.strip().lower()
    if not text:
        return False
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    raise ConfigError(
        f"{_ENV_REQUIRE_BOARD} must be one of "
        f"{'/'.join(sorted(_TRUE_WORDS))} or {'/'.join(sorted(_FALSE_WORDS))}, "
        f"got {raw!r}"
    )


def write_config_file(
    *,
    api_url: str | None = None,
    token: str | None = None,
    board_id: str | None = None,
    require_board: bool | None = None,
) -> Path:
    """Merge the given values into the user config file (``0600``), preserving any
    existing keys not being set, and return its path. Only non-``None`` args are
    written; pass an empty string to clear a key."""
    migrate_legacy_config_file()
    path = config_file_path()
    current: dict[str, str] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            table = _config_table(data)
            if isinstance(table, dict):
                # Every key in ``_CONFIG_KEYS``, not just the settable three: a
                # hand-added ``max_text_chars`` must survive a `config set --board-id`.
                current = {
                    k: str(table[k]) for k in _CONFIG_KEYS if table.get(k) is not None
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
    if require_board is not None:
        # Written explicitly even when False: `config set --no-require-board` has to
        # be able to override a truthy value, and a key that vanished would instead
        # fall through to .mcp.json. Env still wins over the file either way.
        current["require_board"] = "true" if require_board else "false"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_toml(current), encoding="utf-8")
    path.chmod(0o600)  # the token is a secret — owner-only
    return path


def unset_config_keys(keys: tuple[str, ...]) -> tuple[Path, tuple[str, ...]]:
    """Remove ``keys`` from the user config file; return its path and the subset that
    was actually present.

    Exists because the file also holds the PAT (issue #277): telling a user — or an
    agent — to "just delete the line" means opening a file at mode ``0600`` whose
    other line is a live credential. Reporting which keys were really there lets the
    caller distinguish "cleared" from "was not set", instead of both printing OK.

    Unknown keys are the caller's to reject; this only touches ``_CONFIG_KEYS``.
    """
    migrate_legacy_config_file()
    path = config_file_path()
    current: dict[str, str] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            table = _config_table(data)
            if isinstance(table, dict):
                current = {
                    k: str(table[k]) for k in _CONFIG_KEYS if table.get(k) is not None
                }
        except (OSError, tomllib.TOMLDecodeError):
            current = {}

    removed = tuple(k for k in keys if k in current)
    for key in removed:
        del current[key]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_toml(current), encoding="utf-8")
    path.chmod(0o600)  # still holds the token — owner-only
    return path, removed


_INT_CONFIG_KEYS = ("board_id", "max_text_chars")
_BOOL_CONFIG_KEYS = ("require_board",)


def _render_toml(values: dict[str, str]) -> str:
    """Render the ``[pandan]`` table. The integer-valued keys are emitted as bare
    integers when they parse as one, the boolean ones as bare ``true``/``false``;
    everything else is a quoted string. The value set is tiny and known (a URL, a
    ``pandan_pat_…`` token, two ints, one bool), so hand-rendering is safe.

    A bool must not be quoted: ``tomllib`` would hand back the string ``"false"``,
    which ``parse_require_board`` reads back as ``False`` correctly today but only
    by coincidence of the word list. Emitting real TOML keeps the file honest for
    anything else that reads it.
    """
    lines = [f"[{_CONFIG_TABLE_NAMES[0]}]"]
    for key in _CONFIG_KEYS:
        if key not in values:
            continue
        val = values[key]
        if key in _INT_CONFIG_KEYS and val.lstrip("-").isdigit():
            lines.append(f"{key} = {val}")
        elif key in _BOOL_CONFIG_KEYS and val.strip().lower() in _TRUE_WORDS | _FALSE_WORDS:
            lines.append(f"{key} = {'true' if val.strip().lower() in _TRUE_WORDS else 'false'}")
        else:
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    return "\n".join(lines) + "\n"
