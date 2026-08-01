"""Regression tests for the container-image build inputs (KAN-584).

Two invariants, both of which were true-by-luck rather than by construction:

  1. CI BUILDS THE IMAGES AT ALL. Until KAN-584, `.github/workflows/ci.yml`
     contained no reference to `Dockerfile` anywhere. A Dockerfile-only PR
     matched no paths filter, every job reported success having skipped its heavy
     steps in 3-5 seconds, and deploy.yml -- whose filter DOES match `Dockerfile`
     -- then shipped it to production. PR #248 is the worked example: it changed
     only ./Dockerfile and .github/dependabot.yml, and all 13 checks passed
     having built nothing.

  2. deploy.yml's IMAGE_PATHS STILL DESCRIBES THE IMAGE. That one regex decides
     both whether a merge deploys and whether the drift watcher considers
     production stale (KAN-586 hoisted it to a workflow-level env so its two
     consumers cannot disagree). But nothing checked it against the Dockerfile
     it claims to summarise. KAN-586's own failure table names this:
     "IMAGE_PATHS drifts from the Dockerfile COPY set -> detected by nothing --
     same blind spot in both consumers." Add a `COPY scripts/ ...` to the
     Dockerfile and, without this file, the deploy gate silently stops deploying
     changes to scripts/ and the watcher silently stops noticing.

     As of KAN-584 the list is CORRECT: the root Dockerfile COPYs exactly
     backend/ and frontend/, verified not only by reading the COPY lines but by
     building the image from a context containing only
     `backend/ frontend/ Dockerfile .dockerignore` -- it succeeds, so no other
     repo path is a build input. These tests keep it that way.

WHAT RUNS THEM: the `mcp` CI job, which needs no DB/Docker/network -- the same
reason test_prepush_hook.py, test_image_provenance_gate.py and
test_deploy_gates.py live here. The `mcp` paths filter lists `.github/workflows/**`
(KAN-586) and, for this file, `Dockerfile` + `.dockerignore` (KAN-584), because
this file's inputs are ci.yml, deploy.yml and the root Dockerfile -- and a
Dockerfile-only PR is precisely the shape that can break invariant 1. A test
whose input lives outside its own paths filter is the KAN-502 shape; the last
test in this file pins that filter line so the trap cannot be reopened silently.

Assertions are textual for the same reason as test_deploy_gates.py: PyYAML is not
a dependency here, and these are claims about the exact text of expressions.
Where a claim is about workflow YAML the block is scoped and comments are
stripped first -- KAN-586 found a test of its own that stayed green after the
gate was deleted because the file's header comment quoted the very expression it
searched for.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
MCP_DOCKERFILE = ROOT / "mcp" / "Dockerfile"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"

# The build recipe itself is not COPYed into the image but absolutely changes it,
# so IMAGE_PATHS must cover these too.
RECIPE_FILES = ("Dockerfile", ".dockerignore")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    """Drop whole-line YAML/shell comments.

    Every assertion below is about what the workflow DOES. Prose that merely
    describes it must not be able to satisfy the assertion -- that is exactly how
    KAN-586's first draft of test_deploy_gate_requires_a_workflow_run_event
    stayed green with the gate removed.
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _ci_job_block(job: str) -> str:
    """One job's YAML block from ci.yml, up to the next job header.

    The leading comment block sits ABOVE the job key and is therefore excluded,
    which is the point.
    """
    text = CI.read_text()
    m = re.search(rf"^  {re.escape(job)}:$(.*?)(?=^  [a-z_]+:$|\Z)", text, re.MULTILINE | re.DOTALL)
    assert m, f"ci.yml has no `{job}:` job"
    return m.group(1)


def _ci_filter_entries(name: str) -> list[str]:
    """The quoted path globs of one `dorny/paths-filter` filter in ci.yml."""
    text = CI.read_text()
    m = re.search(
        rf"^            {re.escape(name)}:\n((?:^(?:              .*)?\n)+)", text, re.MULTILINE
    )
    assert m, f"could not locate the `{name}:` paths-filter block in ci.yml"
    return re.findall(r"^\s*- '([^']+)'", _strip_comments(m.group(1)), re.MULTILINE)


def _image_paths_regex() -> str:
    """deploy.yml's single IMAGE_PATHS definition, read live rather than copied.

    test_deploy_gates.py::test_image_paths_are_defined_exactly_once pins the
    literal value; this reads whatever is actually there, so the two tests
    disagree loudly if someone edits the env and updates only one of them.
    """
    m = re.search(r"^  IMAGE_PATHS: '(.+)'$", DEPLOY.read_text(), re.MULTILINE)
    assert m, "deploy.yml has no workflow-level `IMAGE_PATHS:` env"
    return m.group(1)


def _dockerfile_copy_sources(dockerfile: Path) -> list[str]:
    """Repo-relative paths a Dockerfile COPYs in from the build context.

    `COPY --from=<stage-or-image>` reads from another stage or a registry image,
    not the context, so those lines contribute nothing the build context (and
    hence IMAGE_PATHS) has to cover.
    """
    sources: list[str] = []
    for raw in dockerfile.read_text().splitlines():
        line = raw.strip()
        if not line.upper().startswith("COPY "):
            continue
        args = shlex.split(line)[1:]
        if any(a.startswith("--from=") for a in args):
            continue
        operands = [a for a in args if not a.startswith("--")]
        assert len(operands) >= 2, f"unparseable COPY in {dockerfile}: {line}"
        sources.extend(operands[:-1])  # the last operand is the destination
    assert sources, f"parsed no context COPY sources out of {dockerfile} — parser is broken"
    return sources


# --------------------------------------------------------------------------
# 1. IMAGE_PATHS still describes what the image is built from
# --------------------------------------------------------------------------


def test_image_paths_covers_every_root_dockerfile_copy_source() -> None:
    pattern = re.compile(_image_paths_regex())
    uncovered = [src for src in _dockerfile_copy_sources(DOCKERFILE) if not pattern.match(src)]
    assert not uncovered, (
        "the root Dockerfile COPYs paths that deploy.yml's IMAGE_PATHS does not "
        f"match: {uncovered}. Both consumers of IMAGE_PATHS go blind together -- "
        "a merge changing those paths would not deploy, and the drift watcher "
        "would not notice it hadn't (KAN-586's named blind spot, KAN-584's to "
        "close). Add the path to IMAGE_PATHS in deploy.yml (and to the `image` "
        "paths filter in ci.yml if it is a build input rather than just content)."
    )


@pytest.mark.parametrize("recipe", RECIPE_FILES)
def test_image_paths_covers_the_build_recipe_itself(recipe: str) -> None:
    assert re.match(_image_paths_regex(), recipe), (
        f"IMAGE_PATHS must match `{recipe}` — it is not COPYed into the image but "
        "it decides what the image contains, so a change to it must deploy."
    )


def test_the_copy_parser_would_notice_a_new_path() -> None:
    """A guard that cannot go red is not a guard.

    The failure mode this file exists for is someone adding a COPY of a path
    IMAGE_PATHS does not list. Prove the parser + matcher pair actually rejects
    that, rather than trusting a green run over the current Dockerfile.
    """
    pattern = re.compile(_image_paths_regex())
    assert not pattern.match("scripts/entrypoint.sh")
    assert not pattern.match("docs-tooling/x.py")
    assert pattern.match("backend/app/main.py")
    assert pattern.match("frontend/src/App.svelte")
    # ...and the parser must really read the COPY lines, not return a constant.
    assert any(s.startswith("backend/") for s in _dockerfile_copy_sources(DOCKERFILE))
    assert any(s.startswith("frontend/") for s in _dockerfile_copy_sources(DOCKERFILE))
    # mcp/Dockerfile has a different context set; if the parser were hardcoded to
    # the root Dockerfile's answer this would fail.
    mcp_sources = _dockerfile_copy_sources(MCP_DOCKERFILE)
    assert any(s.startswith("pandan-client/") for s in mcp_sources), mcp_sources
    assert not any(s.startswith("backend/") for s in mcp_sources), mcp_sources


# --------------------------------------------------------------------------
# 2. CI actually builds the images
# --------------------------------------------------------------------------


def test_ci_builds_the_root_dockerfile() -> None:
    body = _strip_comments(_ci_job_block("image"))
    assert re.search(r"^\s+run: docker build -f Dockerfile .*\.$", body, re.MULTILINE), (
        "ci.yml's `image` job must run `docker build -f Dockerfile .`. Without it "
        "a Dockerfile-only PR is green having built nothing and deploy.yml ships "
        "it unvalidated (KAN-584)."
    )


def test_ci_builds_the_mcp_dockerfile() -> None:
    """publish-mcp-image.yml builds it too, but only on a `v*` tag (KAN-452), so
    on any non-tag change this job is the only build."""
    body = _strip_comments(_ci_job_block("image"))
    assert re.search(r"^\s+run: docker build -f mcp/Dockerfile .*\.$", body, re.MULTILINE), (
        "ci.yml's `image` job must also build mcp/Dockerfile — nothing else does "
        "outside a release tag (KAN-584)."
    )


def test_ci_asserts_more_than_a_zero_exit_from_docker_build() -> None:
    """`docker build` exiting 0 does not mean the image works: an empty vite dist
    still builds, and `uv sync --no-dev` here vs `--group dev` everywhere else
    means a misfiled runtime dependency passes every other job in the workflow."""
    body = _strip_comments(_ci_job_block("image"))
    assert "docker run" in body, (
        "the `image` job must run the images it builds, not just build them — "
        "'it built' is a weak claim (KAN-584)."
    )
    assert "import app.main" in body, (
        "the app-image assertion must import the application, which is what "
        "catches a runtime dependency misfiled into the dev group."
    )


@pytest.mark.parametrize("entry", [*RECIPE_FILES, "fly.toml"])
def test_the_image_job_filter_fires_for_the_build_recipe(entry: str) -> None:
    """The trigger is the whole point: KAN-584 was a guard that did not exist,
    and a guard whose filter misses its own subject is the KAN-484 shape."""
    assert entry in _ci_filter_entries("image"), (
        f"ci.yml's `image` paths filter must include '{entry}' — otherwise a "
        "change to it still reaches production with nothing having built it."
    )


def test_the_mcp_image_job_filter_fires_for_its_own_dockerfile() -> None:
    assert "mcp/Dockerfile" in _ci_filter_entries("mcp_image")


# --------------------------------------------------------------------------
# 3. the watcher for this watcher
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entry", RECIPE_FILES)
def test_the_mcp_filter_runs_this_file_on_a_dockerfile_only_pr(entry: str) -> None:
    """This file's inputs are ci.yml, deploy.yml and the root Dockerfile, but it
    is executed by the `mcp` job. `.github/workflows/**` is already in that
    filter (KAN-586); the root Dockerfile had to be added (KAN-584). Drop it and
    the one PR shape that can break invariant 1 -- a Dockerfile-only PR -- is the
    one shape that never runs these tests."""
    assert entry in _ci_filter_entries("mcp"), (
        f"the `mcp` paths filter must include '{entry}', or the tests in this "
        "file do not run on the change shape they exist for (KAN-502's shape: a "
        "test whose input lives outside its own filter)."
    )
