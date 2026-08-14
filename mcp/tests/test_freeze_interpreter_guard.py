"""Regression tests for the release's pre-freeze glibc guard (KAN-721).

`scripts/check-freeze-interpreter.sh` decides whether the interpreter uv just
resolved may be frozen into `pandan-linux-x86_64`. PyInstaller does not compile an
interpreter -- it copies the one it is pointed at, `libpython` and all -- so that
interpreter's glibc floor IS the shipped asset's glibc floor. This is KAN-81's root
cause, guarded at the point where it is still cheap to fix.

WHY THIS FILE EXISTS AT ALL. The guard it replaced could not fail. It ran
`strings dist/pandan-linux-x86_64 | grep GLIBC_` *after* the freeze, and PyInstaller
ships a PREBUILT bootloader whose visible symbols are a property of the wheel
upstream published rather than of the build host. Reported from the kaya repo
(KAN-719): applied to a published asset that definitively dies with `GLIBC_2.38 not
found` on Ubuntu 22.04, Debian 12, RHEL 9 and Amazon Linux 2023, that check reported
`GLIBC_2.14` and exited 0. Confirmed independently against *pandan's own* shipped
v0.22.0 asset, which is a known-GOOD manylinux build: also `GLIBC_2.14`. Same answer
for the broken artifact and the fixed one, which is not a guard.

So the whole point of the replacement is that it CAN be watched failing, and these
tests are that watching. The states below are not hypothetical -- every one of them
was reproduced on a real machine while writing this:

  system CPython (Ubuntu 24.04)  -> libpython requires GLIBC_2.35  -> REJECTED
  uv-managed CPython 3.12        -> libpython requires GLIBC_2.17  -> ACCEPTED

That pair is the assertion that matters: the guard must *discriminate*, which is
precisely what the `strings` check did not do.

WHAT RUNS THEM: the `mcp` job, which needs no DB/Docker/network -- the same reason
test_prepush_hook.py, test_deploy_gates.py and test_image_provenance_gate.py live
here, and this file follows test_prepush_hook.py's precedent of driving a shell
script from the Python suite. `.github/workflows/ci.yml` lists
`scripts/check-freeze-interpreter.sh` under the `mcp` paths filter so a
guard-only PR still runs these; without it this would be a guard with no watcher,
which is the exact failure mode that let the `strings` check rot unnoticed.

Nothing here touches the release. Each test invokes the script directly against an
interpreter chosen for the property under test.
"""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "check-freeze-interpreter.sh"

# The floor the linux release promises: AlmaLinux 8 / manylinux_2_28, i.e. Ubuntu
# 20.04+, Debian 11+, RHEL 8+.
RELEASE_FLOOR = "28"


def run_guard(python: str, floor: str = RELEASE_FLOOR) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(GUARD), python, floor],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


@functools.cache
def managed_python() -> str | None:
    """Path to a uv-managed CPython 3.12, or None.

    Cached because `uv python find` is the slowest thing in this file and three
    tests want the same answer — uncached, this module added two minutes to a job
    that otherwise finishes in seconds, which is its own kind of guard rot: a suite
    people start skipping locally.
    """
    uv = shutil.which("uv")
    if uv is None:
        return None
    found = subprocess.run(
        [uv, "python", "find", "3.12"], capture_output=True, text=True, cwd=ROOT
    )
    managed = found.stdout.strip()
    if found.returncode != 0 or "/uv/python/" not in managed:
        return None
    return managed


@functools.cache
def glibc_floor_of(python: str) -> int | None:
    """The highest GLIBC_2.<n> the interpreter's libpython needs, or None if it has
    no shared libpython / no readelf to ask. Mirrors the script's own lookup, and is
    used only to SELECT tests, never to assert -- a test that recomputed the answer
    the same way would prove nothing about the script."""
    if not shutil.which("readelf"):
        return None
    probe = subprocess.run(
        [python, "-c", _PROBE],
        capture_output=True,
        text=True,
    )
    lib = probe.stdout.strip()
    if not lib or lib == "STATIC" or not Path(lib).exists():
        return None
    out = subprocess.run(
        ["readelf", "-V", lib], capture_output=True, text=True
    ).stdout
    # Same expression the script greps with. readelf also emits `GLIBC_2.2.5`, so a
    # naive int() over the tail explodes; anchoring on the first numeric component
    # is what the shell's `grep -oE 'GLIBC_2\.[0-9]+'` already does.
    versions = [int(m) for m in re.findall(r"GLIBC_2\.(\d+)", out)]
    return max(versions) if versions else None


# Mirrors the script's lookup, including its direct-first ordering — a recursive
# `/usr/**` walk measured 23 SECONDS for a system interpreter, and this helper runs
# per test. It is duplicated rather than shared because the script is the artifact
# under test: importing its logic would make these tests agree with it by
# construction, which is the one thing they must not do.
_PROBE = """
import glob, os, sysconfig
if not sysconfig.get_config_var("Py_ENABLE_SHARED"):
    print("STATIC"); raise SystemExit(0)
names = [n for n in (sysconfig.get_config_var("INSTSONAME"),
                     sysconfig.get_config_var("LDLIBRARY")) if n]
names.append("libpython%s*.so*" % sysconfig.get_python_version())
roots = [r for r in (sysconfig.get_config_var(v)
                     for v in ("LIBDIR", "LIBPL", "installed_base")) if r]
def hits(pattern):
    return [p for p in glob.glob(pattern, recursive=True)
            if ".so" in os.path.basename(p)]
seen = []
for root in roots:
    for name in names:
        seen += hits(os.path.join(root, name))
if not seen:
    for root in roots:
        for name in names:
            seen += hits(os.path.join(root, "**", name))
print(sorted(seen, key=len)[0] if seen else "")
"""


# --- 0. the guard exists and is wired in ------------------------------------


def test_the_guard_script_exists_and_is_executable() -> None:
    assert GUARD.is_file(), f"missing {GUARD}"
    assert GUARD.stat().st_mode & 0o111, (
        f"{GUARD} must be executable — the release workflow runs it directly"
    )


def test_the_release_workflow_runs_the_guard_before_the_freeze() -> None:
    """Order is the entire point (KAN-721): judging the interpreter AFTER the build
    would cost a full freeze to learn what a second could have told us, and judging
    the ARTIFACT after the build is the inert check this replaced."""
    workflow = (ROOT / ".github" / "workflows" / "release-cli.yml").read_text()
    lines = [ln for ln in workflow.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(lines)
    assert "check-freeze-interpreter.sh" in body, (
        "release-cli.yml must run scripts/check-freeze-interpreter.sh — without it "
        "the KAN-81 fix has no guard that can fail (KAN-721)."
    )
    guard_at = body.index("check-freeze-interpreter.sh")
    freeze_at = body.index("pyinstaller --onefile")
    assert guard_at < freeze_at, (
        "the interpreter guard must run BEFORE `pyinstaller --onefile`; after the "
        "freeze it cannot save the build it was meant to save."
    )


def test_the_inert_strings_guard_is_gone_and_stays_gone() -> None:
    """The replaced check was measured returning GLIBC_2.14 for a definitively
    broken asset AND for a good one. Reintroducing it would re-add something that
    reads as protection in review while being incapable of failing."""
    workflow = (ROOT / ".github" / "workflows" / "release-cli.yml").read_text()
    body = "\n".join(
        ln for ln in workflow.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "strings" not in body, (
        "release-cli.yml reintroduced a `strings`-based GLIBC check. It cannot "
        "fail: PyInstaller's bootloader is prebuilt, so its symbols do not vary "
        "with the build host (KAN-721). Judge the interpreter before the freeze."
    )


def test_the_mcp_paths_filter_watches_the_guard() -> None:
    """This file's input lives outside mcp/, so without the filter line a
    guard-only PR would run none of these tests — the same hole KAN-484/584 each
    had to report from outside their own fence."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "'scripts/check-freeze-interpreter.sh'" in ci, (
        "ci.yml's `mcp` paths filter must list scripts/check-freeze-interpreter.sh, "
        "or editing the guard skips the tests that guard the guard."
    )


# --- 1. it rejects what it must reject --------------------------------------


def test_a_missing_interpreter_is_rejected() -> None:
    result = run_guard("/nonexistent/python")
    assert result.returncode == 1
    assert "not an executable interpreter" in result.stderr


def test_a_directory_is_rejected_cleanly() -> None:
    """`-x` is true for a directory, so an early version got past the first check
    and died several lines later as a bash 'Is a directory' error instead."""
    result = run_guard("/tmp")
    assert result.returncode == 1
    assert "not an executable interpreter" in result.stderr


def test_an_interpreter_above_the_floor_is_rejected() -> None:
    """**The KAN-81 defect itself.** Runs against whatever interpreter is available
    with a floor of 2.16 — below python-build-standalone's 2.17 — so the comparison
    is exercised on a real libpython regardless of what this machine ships."""
    floor = glibc_floor_of(sys.executable)
    if floor is None:
        pytest.skip("no shared libpython/readelf here to measure")
    result = run_guard(sys.executable, "16")
    assert result.returncode == 1, (
        f"a libpython requiring GLIBC_2.{floor} must be refused against a 2.16 floor"
    )
    assert "above the GLIBC_2.16 floor" in result.stderr
    # The message has to name the consequence, not just the numbers — this is the
    # one place a release engineer learns why the build is being stopped.
    assert "will not start on Ubuntu" in result.stderr


# --- 2. …and accepts what it must accept ------------------------------------


def test_the_interpreter_the_release_actually_uses_is_accepted() -> None:
    """The other half of "discriminates". A guard that rejected everything would
    pass every test above and still be useless.

    python-build-standalone (what `UV_PYTHON_PREFERENCE=only-managed` gets in the
    release container) is built against glibc ~2.17, comfortably under the 2.28
    floor. Skipped rather than failed when uv has no managed CPython here, since
    that is a property of the machine, not of the guard.
    """
    managed = managed_python()
    if managed is None:
        pytest.skip("no uv-managed CPython 3.12 available here")

    result = run_guard(managed)
    assert result.returncode == 0, (
        "the uv-managed interpreter the release freezes must PASS the guard; "
        f"stderr: {result.stderr}"
    )
    assert "requires at most" in result.stdout


def test_the_guard_discriminates_between_the_two_interpreters() -> None:
    """The single assertion the replaced `strings` check could not make.

    Same guard, same floor, two interpreters, two different answers. If this ever
    goes green-both-ways the guard has quietly become inert again, which is exactly
    how the last one lasted months.
    """
    managed = managed_python()
    if managed is None:
        pytest.skip("no uv-managed CPython 3.12 available here")

    system_floor = glibc_floor_of(sys.executable)
    if system_floor is None or system_floor <= int(RELEASE_FLOOR):
        pytest.skip(
            "this machine's default interpreter is already under the release floor, "
            "so there is no bad case here to contrast with"
        )

    bad = run_guard(sys.executable)
    good = run_guard(managed)
    assert (bad.returncode, good.returncode) == (1, 0), (
        "the guard must reject the system interpreter "
        f"(GLIBC_2.{system_floor}) and accept the uv-managed one. Got "
        f"{bad.returncode}/{good.returncode} — if both are 0 the guard has gone "
        "inert, which is the KAN-721 failure repeating."
    )
