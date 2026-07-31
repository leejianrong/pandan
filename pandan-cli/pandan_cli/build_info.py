"""Build provenance for ``pandan --version`` (V50, KAN-435).

Two false bug reports were caused by a *stale binary that was indistinguishable
from current source*: ``0.3.0`` was released, two user-visible fixes landed the
same day, the version was never bumped, and ``--version`` said ``pandan 0.3.0``
for both. The version number alone therefore cannot answer "which build is
this?" — so a released binary also carries the **commit it was built from**.

How the stamp gets here: ``packaging/stamp_build.py`` writes a tiny
``pandan_cli/_build_stamp.py`` (git-ignored, generated) immediately before
PyInstaller freezes the package, and ``--collect-submodules pandan_cli`` pulls it
into the onefile. A source checkout has no such module, so the import below
fails and ``BUILD_SHA`` stays empty — which is reported honestly as a source run
rather than being dressed up as a release. Nothing here shells out to ``git``:
a released binary has no repo to ask.
"""
from __future__ import annotations

from . import __version__

try:  # pragma: no cover - generated at package time, absent in a source tree
    from ._build_stamp import BUILD_SHA  # type: ignore[import-not-found]
except ImportError:  # source run (or an unstamped local build)
    BUILD_SHA = ""

# What an unstamped run prints instead of a commit. Deliberately not a fake sha
# and not silence: it must never be mistaken for a released build.
SOURCE_LABEL = "source checkout, not a released build"


def version_string(version: str = __version__, build_sha: str | None = BUILD_SHA) -> str:
    """One stdout line for ``--version``: ``pandan <version> (<provenance>)``.

    Released build → ``pandan 0.5.0 (a10eaee)``; source run → ``pandan 0.5.0
    (source checkout, not a released build)``. Both args are injectable so tests
    can render either form without producing a real frozen binary. ASCII only —
    this is machine-readable stdout on every platform.
    """
    sha = (build_sha or "").strip()
    return f"pandan {version} ({sha or SOURCE_LABEL})"
