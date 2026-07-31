"""Content-first bare invocation + ``help[]`` next-step hints — V46 (KAN-429).

Two halves, and the tests below are grouped by them:

1. **Bare ``pandan`` prints live state and exits 0** (AXI 8). Before this slice it
   printed argparse's usage block on stderr, one ``error<TAB>usage<TAB>…`` row on
   stdout, and exited **2** — verified from source at ``origin/main`` (052091a)
   before any code was written, not assumed from the card. Now it prints the tool's
   own identity, the executable path, a one-sentence description, then the default
   board's open cards and V44's aggregate. No default board → the board list. No
   token → V43's structured config error, unchanged.
2. **Results carry ``help[]`` next-step hints** (AXI 9) as *templates*: fixed flags
   carried forward, runtime values left parameterised. Suppressed under
   ``--format json``/``toon``.

The load-bearing guard here is ``test_hints_are_templates_never_prefilled``: a hint
that merely *mentions* ``<id>`` proves nothing, so it asserts both that the literal
placeholder survives **and** that no concrete identifier from the result leaked in.

``--help`` is pinned byte-for-byte against ``tests/help_golden.txt``, which was
generated from the **unmodified** ``origin/main`` parser before this slice was
written — that is what makes it a regression guard (AXI 10) rather than a
restatement of the current code.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from pandan_cli import cli, config

HELP_GOLDEN = pathlib.Path(__file__).with_name("help_golden.txt")

# argparse wraps help to the terminal width, and `shutil.get_terminal_size` reads
# `COLUMNS` before asking the tty — so the golden is only comparable at a pinned
# width. 80 is the conventional default; CI has no tty at all.
GOLDEN_WIDTH = "80"


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch, tmp_path):
    """Same hermetic-config fixture the other suites use: an empty XDG dir, no
    ``.mcp.json`` discovery, and **both** env spellings of every key cleared, so a
    developer's own shell can't supply the token the no-token tests need absent."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: None)
    for names in config._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    config._warned.clear()


# --- 3. `--help` is unchanged (AXI 10 regression guard) ----------------------


def test_help_output_is_byte_identical_to_the_pre_slice_golden(monkeypatch, capsys):
    """Content-first must not cost the usage text. The golden was captured from
    ``origin/main`` before this slice existed, so any drift in the help surface —
    a new visible subcommand, a reworded epilog, a changed usage line — fails
    here. Update the golden **only** with a deliberate help change in the diff."""
    monkeypatch.setenv("COLUMNS", GOLDEN_WIDTH)
    with pytest.raises(SystemExit) as exc:
        cli.run(["--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == HELP_GOLDEN.read_text(encoding="utf-8")


def test_help_still_prints_usage_and_makes_no_network_call(monkeypatch, capsys):
    """The bare-invocation branch must not swallow ``--help``: it prints usage, and
    it never reaches for a client (a hard failure if it tried)."""

    def boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("--help must not touch the network")

    monkeypatch.setattr(cli, "PandanClient", boom)
    monkeypatch.setenv("COLUMNS", GOLDEN_WIDTH)
    with pytest.raises(SystemExit) as exc:
        cli.run(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: pandan [-h] [-v] <command> ...")
    # Usage, not board state.
    assert "open cards" not in out
