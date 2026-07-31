"""Regression tests for the MCP image build-provenance gate (KAN-452, KAN-475).

`scripts/assert-image-provenance.sh` is the container mirror of the CLI's
`--version` release smoke test: it fails the release if the image about to be
pushed doesn't carry `org.opencontainers.image.revision` equal to the release
commit. That promise is only worth something if the gate is *watched going red*,
and the release workflow is tag-gated (it never runs on a PR), so these tests are
the only CI-visible proof the gate still bites.

They stub `docker` with a shim on `PATH` that replays canned labels, so they need
no Docker daemon and run in the ordinary `mcp` CI job. The shim ignores the Go
template and just prints `key=value` lines; that the real
`docker image inspect --format` produces exactly that shape was verified by hand
against images built from `mcp/Dockerfile` (see the KAN-452 PR).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "scripts" / "assert-image-provenance.sh"

SHA = "5da9ace0000000000000000000000000000abcde"
OTHER_SHA = "0000000000000000000000000000000000000000"

# A plausible 64-hex image digest, and the two build-input labels KAN-475 added.
DIGEST = "a" * 64
PYTHON_LABEL = "io.github.leejianrong.pandan.build.python"
UV_LABEL = "io.github.leejianrong.pandan.build.uv"

FULL_LABELS = "\n".join(
    [
        "org.opencontainers.image.created=2026-07-31T12:00:00.000Z",
        "org.opencontainers.image.description=Pandan MCP server",
        f"org.opencontainers.image.revision={SHA}",
        "org.opencontainers.image.version=0.2.3",
        f"{PYTHON_LABEL}=python@sha256:{DIGEST}",
        f"{UV_LABEL}=ghcr.io/astral-sh/uv@sha256:{DIGEST}",
    ]
)


def _labels_without(substring: str) -> str:
    """FULL_LABELS with any line containing `substring` dropped."""
    return "\n".join(line for line in FULL_LABELS.splitlines() if substring not in line)


def _labels_with(key: str, value: str) -> str:
    """FULL_LABELS with `key` replaced by `value`."""
    return "\n".join(
        f"{key}={value}" if line.startswith(f"{key}=") else line
        for line in FULL_LABELS.splitlines()
    )

# A shim standing in for `docker`. It answers `docker image inspect <ref> ...`
# from $FAKE_DOCKER_LABELS for exactly $FAKE_DOCKER_REF and exits 1 (like the
# real daemon) for any other ref, so the "image isn't here" branch is covered.
SHIM = """#!/usr/bin/env python3
import os, sys
argv = sys.argv[1:]
if argv[:2] != ["image", "inspect"]:
    sys.exit("fake docker: unexpected argv %r" % (argv,))
ref = argv[2]
if ref != os.environ["FAKE_DOCKER_REF"]:
    print("Error: No such image: %s" % ref, file=sys.stderr)
    sys.exit(1)
labels = os.environ["FAKE_DOCKER_LABELS"]
sys.stdout.write(labels + ("\\n" if labels else ""))
"""


@pytest.fixture
def run_gate(tmp_path):
    """Run the gate with a stubbed `docker`; returns the CompletedProcess."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "docker"
    shim.write_text(SHIM)
    shim.chmod(0o755)

    def _run(*args: str, labels: str = FULL_LABELS, ref: str = "pandan-mcp:gate"):
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["FAKE_DOCKER_REF"] = ref
        env["FAKE_DOCKER_LABELS"] = labels
        return subprocess.run(
            [str(GATE), *args],
            env=env,
            capture_output=True,
            text=True,
        )

    return _run


def test_gate_is_executable():
    assert GATE.is_file(), f"{GATE} is missing — the release workflow calls it by path"
    assert os.access(GATE, os.X_OK), f"{GATE} is not executable; the workflow runs it directly"


def test_passes_when_the_image_carries_this_commit(run_gate):
    result = run_gate("pandan-mcp:gate", SHA, "0.2.3")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "build provenance OK" in result.stdout
    # The gate must say out loud what it checked — a silent pass is
    # indistinguishable from a step that never ran.
    assert "org.opencontainers.image.revision" in result.stdout


def test_fails_when_the_image_was_built_from_another_commit(run_gate):
    """The staleness case: `:latest` rebuilt from the wrong commit."""
    result = run_gate("pandan-mcp:gate", OTHER_SHA, "0.2.3")
    assert result.returncode == 1
    assert "does not carry the release commit" in result.stdout
    assert "gate FAILED" in result.stdout


def test_fails_when_the_labels_were_never_applied(run_gate):
    """The regression this exists for: someone drops `labels:` from the build."""
    result = run_gate("pandan-mcp:gate", SHA, "0.2.3", labels="")
    assert result.returncode == 1
    assert "carries no org.opencontainers.image.revision label" in result.stdout
    assert "gate FAILED" in result.stdout


def test_fails_when_the_version_label_does_not_match_the_tag(run_gate):
    result = run_gate("pandan-mcp:gate", SHA, "9.9.9")
    assert result.returncode == 1
    assert "does not carry the release version" in result.stdout


def test_fails_when_the_created_label_is_missing(run_gate):
    result = run_gate("pandan-mcp:gate", SHA, labels=_labels_without(".created="))
    assert result.returncode == 1
    assert "carries no org.opencontainers.image.created label" in result.stdout


def test_version_is_only_checked_when_asked(run_gate):
    result = run_gate("pandan-mcp:gate", SHA, labels=_labels_without("image.version="))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "<not checked>" in result.stdout


# --- build-input provenance (KAN-475) ---------------------------------------
#
# "Which commit?" and "which toolchain?" are different questions. mcp/Dockerfile
# floats `python:3.12-slim` and `ghcr.io/astral-sh/uv:latest`, so two images can
# legitimately carry the same `.revision` and still contain a different
# interpreter and a different uv. The release workflow resolves both to digests
# and records them; these tests are the CI-visible proof that the gate notices
# when that stops happening (the workflow itself is tag-gated and never runs on a
# PR, so nothing else would).


@pytest.mark.parametrize(
    ("label", "what"),
    [(PYTHON_LABEL, "interpreter"), (UV_LABEL, "uv")],
)
def test_fails_when_a_build_input_label_is_missing(run_gate, label, what):
    """The regression: the resolve step is dropped from the build's `labels:`."""
    result = run_gate("pandan-mcp:gate", SHA, "0.2.3", labels=_labels_without(label))
    assert result.returncode == 1
    assert f"carries no {label} label" in result.stdout
    assert f"which {what} it was built with" in result.stdout
    assert "gate FAILED" in result.stdout


@pytest.mark.parametrize("label", [PYTHON_LABEL, UV_LABEL])
def test_fails_when_a_build_input_is_recorded_as_a_floating_tag(run_gate, label):
    """The subtle one: the label is present but restates the float.

    Recording `python:3.12-slim` looks like provenance and is worth nothing — that
    tag resolved to Debian 12/glibc 2.36 once and Debian 13/glibc 2.41 later. Only
    a digest actually identifies the input.
    """
    result = run_gate(
        "pandan-mcp:gate", SHA, "0.2.3", labels=_labels_with(label, "python:3.12-slim")
    )
    assert result.returncode == 1
    assert "must be digest-pinned" in result.stdout
    assert "gate FAILED" in result.stdout


@pytest.mark.parametrize(
    "bad_digest",
    [
        "a" * 63,  # too short
        "a" * 65,  # too long
        "A" * 64,  # uppercase is not a valid OCI hex digest
        "g" * 64,  # not hex at all
    ],
)
def test_fails_when_a_build_input_digest_is_malformed(run_gate, bad_digest):
    labels = _labels_with(UV_LABEL, f"ghcr.io/astral-sh/uv@sha256:{bad_digest}")
    result = run_gate("pandan-mcp:gate", SHA, "0.2.3", labels=labels)
    assert result.returncode == 1
    assert "not 64 lowercase hex characters" in result.stdout


def test_reports_the_recorded_build_inputs_on_success(run_gate):
    """A silent pass is indistinguishable from a step that never ran."""
    result = run_gate("pandan-mcp:gate", SHA, "0.2.3")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"OK   {PYTHON_LABEL} = python@sha256:{DIGEST}" in result.stdout
    assert f"OK   {UV_LABEL} = ghcr.io/astral-sh/uv@sha256:{DIGEST}" in result.stdout
    assert "digest-pinned" in result.stdout


def test_build_inputs_are_checked_even_without_an_expected_version(run_gate):
    """They are not gated behind the optional third argument."""
    labels = _labels_without(PYTHON_LABEL)
    result = run_gate("pandan-mcp:gate", SHA, labels=labels)
    assert result.returncode == 1
    assert f"carries no {PYTHON_LABEL} label" in result.stdout


def test_fails_when_the_image_is_not_present(run_gate):
    result = run_gate("pandan-mcp:missing", SHA, ref="pandan-mcp:gate")
    assert result.returncode == 1
    assert "not in the local docker daemon" in result.stdout


def test_usage_error_is_distinct_from_an_assertion_failure(run_gate):
    """Exit 2, not 1 — a mis-called gate must not read as 'the image is bad'."""
    result = run_gate("pandan-mcp:gate")
    assert result.returncode == 2
    assert "need an image ref and an expected revision" in result.stderr
