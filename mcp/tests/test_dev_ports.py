"""Regression tests for `make dev`'s port picking (`scripts/free-port.sh`).

THE DEFECT THIS PREVENTS. `make dev` binds three ports — Postgres, uvicorn, Vite —
at fixed defaults (5432/8000/5173). On a machine running more than one project those
are routinely held by something else, and the resulting failures do not look like
port conflicts:

  * a foreign Postgres on :5432 answers the connection and rejects the credentials,
    so `alembic upgrade head` dies with `password authentication failed for user
    "kanban"` — an error that reads like broken config;
  * a foreign app on :8000 accepts Vite's proxied `/api` calls, so the SPA loads and
    every request returns someone else's answer;
  * and a compose container whose bind failed stays "up" while publishing no host
    port at all, so `docker compose ps` says running and nothing can reach it.

All three were reproduced on a real machine while writing this (a `postgis` container
on :5432, an MCP server on :8000). CLAUDE.md already documents the e2e half of this
trap for worktrees; this is the `make dev` half.

WHAT RUNS THEM: the `mcp` job, which needs no DB/Docker/network — the same reason
test_prepush_hook.py and test_freeze_interpreter_guard.py live here, and this file
follows their precedent of driving a shell script from the Python suite.
`.github/workflows/ci.yml` lists `scripts/free-port.sh` and `scripts/dev-db.sh` under
the `mcp` paths filter so a script-only PR still runs these.

Only `free-port.sh` is exercised directly: it is pure (a port in, a port out) and
needs nothing but a socket. `dev-db.sh` drives Docker, so it is checked structurally
rather than executed — the assertions below pin the decisions that make it correct,
not its output.
"""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FREE_PORT = REPO_ROOT / "scripts" / "free-port.sh"
DEV_DB = REPO_ROOT / "scripts" / "dev-db.sh"


def run_free_port(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(FREE_PORT), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def held_port():
    """Bind a real socket and yield its port, so 'taken' means actually taken."""
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def test_the_scripts_exist_and_are_executable():
    """A Makefile recipe calls these by path; a non-executable script fails at run
    time with a permission error rather than anything diagnostic."""
    for script in (FREE_PORT, DEV_DB):
        assert script.is_file(), f"{script} is missing"
        assert script.stat().st_mode & 0o111, f"{script} is not executable"


def test_a_free_port_is_returned_unchanged():
    """The whole point is that a normal machine is UNAFFECTED: when the preferred
    port is free it must come back exactly, so CI and single-project dev keep
    binding the documented defaults."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    # The probe socket is closed, so `free` is now genuinely available.
    result = run_free_port(str(free))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(free)


def test_a_taken_port_is_skipped(held_port):
    """The defect itself: a bound port must not be handed back."""
    result = run_free_port(str(held_port))
    assert result.returncode == 0, result.stderr
    chosen = int(result.stdout.strip())
    assert chosen != held_port
    assert chosen > held_port, "it should scan upward from the preferred port"


def test_the_substitution_is_announced_on_stderr(held_port):
    """A silently different port is its own confusion — the run must say so. And it
    must say so on STDERR, because stdout is consumed by `$(…)` in the Makefile: a
    diagnostic on stdout would be captured as part of the port number."""
    result = run_free_port(str(held_port))
    assert str(held_port) in result.stderr
    assert "taken" in result.stderr
    # stdout stays parseable as a bare integer.
    assert result.stdout.strip().isdigit()


def test_a_chosen_port_is_actually_bindable(held_port):
    """The end-to-end promise: whatever comes back can be bound right now. A connect
    test that returned a port something is already listening on would be worse than
    no check at all."""
    chosen = int(run_free_port(str(held_port)).stdout.strip())
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", chosen))  # raises if the script lied


def test_a_non_numeric_preferred_port_is_rejected():
    """Fail loudly on a bad argument rather than emitting something the Makefile
    would happily pass to uvicorn as `--port`."""
    result = run_free_port("not-a-port")
    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_giving_up_is_an_error_not_an_empty_string():
    """With a search window of zero there is no port to find. Exiting 0 with empty
    stdout would make the Makefile run `uvicorn --port ''`."""
    result = run_free_port("8000", "0")
    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_dev_db_honours_a_preset_database_url():
    """A worktree exports its own DATABASE_URL (`make worktree-db`). `make dev` must
    not start a second Postgres underneath it — the KAN-240 trap, one level up."""
    body = DEV_DB.read_text()
    assert 'if [ -n "${DATABASE_URL:-}" ]' in body
    assert body.index('if [ -n "${DATABASE_URL:-}" ]') < body.index("docker compose"), (
        "the DATABASE_URL check must come before any docker call, or the side effect "
        "has already happened by the time it is honoured"
    )


def test_dev_db_recreates_a_container_that_publishes_no_port():
    """The state that wastes an afternoon: `docker compose ps` says running, and
    nothing on the host can reach it. Reusing it is the bug; recreating is the fix."""
    body = DEV_DB.read_text()
    assert "docker compose port db 5432" in body
    assert "docker compose rm -sf db" in body


def test_compose_publishes_the_db_on_an_overridable_port():
    """`dev-db.sh` passes DB_PORT to compose; if the compose file hardcodes 5432 the
    whole mechanism is inert — a classifier with no consumer (KAN-596's shape)."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "${DB_PORT:-5432}:5432" in compose


def test_make_dev_passes_the_chosen_port_to_uvicorn():
    """Vite reads BACKEND_PORT itself, but uvicorn does not — it needs `--port`
    explicitly. Without this the backend keeps binding 8000 while the proxy points
    at the port we picked, which fails as a connection refused on every API call."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    dev = makefile[makefile.index("\ndev:") :]
    dev = dev[: dev.index("\ntest:")]
    assert "--port $$BACKEND_PORT" in dev
    assert "free-port.sh" in dev
    assert "dev-db.sh" in dev
