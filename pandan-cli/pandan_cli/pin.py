"""The session board pin: ``pandan board use <id|KEY>``.

The CLI has **no default board**. A board-scoped verb with no ``--board`` fails with a
``board_required`` error that lists your boards — a stale default on a read is a
confusing answer and on a ``create`` it is a card filed on the wrong board, so an
agent has to say which board it means.

Naming it on every call is the cost of that, so an agent may *pin* a board once for
its working session. Each CLI call is a separate process, so the pin is a small state
file rather than an environment variable (many agent harnesses don't carry env between
shell calls):

- Location: ``$XDG_STATE_HOME/pandan/pins/<sha256(cwd)>.json`` (``~/.local/state`` when
  unset), one file per working directory. The nearest pinned ancestor of the cwd
  wins, so a ``cd`` into a subdirectory keeps the pin.
- It stores the board id (plus key/name for display), the API origin it was made
  against — a pin from another instance is ignored, since board ids are per-instance —
  and a last-used timestamp.
- **It expires after ``PIN_TTL_SECONDS`` (12h) idle**, and every read that honours it
  refreshes the stamp. A pin that outlived its session is exactly the stale default
  this exists to remove, so it lapses rather than lingering for weeks.
- ``--board`` always overrides it; ``pandan board use --clear`` removes it.

Nothing here is a credential; it is safe to lose, and every failure to read or write
it degrades to "no pin" rather than an error.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

#: Idle lifetime of a pin, seconds. Module-level so tests can shrink it.
PIN_TTL_SECONDS = 12 * 60 * 60

_VERSION = 1


@dataclass(frozen=True)
class Pin:
    board_id: int
    api_url: str
    key: str | None = None
    name: str | None = None


def _state_root() -> Path:
    base = os.environ.get("XDG_STATE_HOME", "").strip()
    return (Path(base) if base else Path.home() / ".local" / "state") / "pandan" / "pins"


def _file_for(directory: Path) -> Path:
    digest = hashlib.sha256(str(directory).encode("utf-8")).hexdigest()[:24]
    return _state_root() / f"{digest}.json"


def _norm(api_url: str) -> str:
    return api_url.rstrip("/")


def _read(path: Path, api_url: str, *, touch: bool) -> Pin | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("v") != _VERSION or _norm(data["api_url"]) != _norm(api_url):
            return None
        if time.time() - float(data["used_at"]) > PIN_TTL_SECONDS:
            path.unlink(missing_ok=True)
            return None
        pin = Pin(
            board_id=int(data["board_id"]),
            api_url=data["api_url"],
            key=data.get("key"),
            name=data.get("name"),
        )
        if touch:
            data["used_at"] = time.time()
            path.write_text(json.dumps(data), encoding="utf-8")
        return pin
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def read_pin(api_url: str, *, touch: bool = True, start: Path | None = None) -> Pin | None:
    """The live pin for this working directory (or its nearest pinned ancestor), else
    ``None``. ``touch`` refreshes the idle timer — pass ``False`` to only look."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        path = _file_for(directory)
        if path.is_file():
            pin = _read(path, api_url, touch=touch)
            if pin is not None:
                return pin
    return None


def write_pin(
    api_url: str,
    board_id: int,
    *,
    key: str | None = None,
    name: str | None = None,
    start: Path | None = None,
) -> Path:
    """Pin ``board_id`` for the working directory, replacing any pin there."""
    path = _file_for((start or Path.cwd()).resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "v": _VERSION,
                "api_url": _norm(api_url),
                "board_id": int(board_id),
                "key": key,
                "name": name,
                "used_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    return path


def clear_pin(*, start: Path | None = None) -> bool:
    """Remove the pin that applies here (the cwd's own, else the nearest ancestor's).
    Returns whether one was removed."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        path = _file_for(directory)
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                return False
            return True
    return False
