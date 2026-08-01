"""Regression tests for the merge -> CI -> Deploy chain (KAN-586).

A merge to main that touches app code must end up in production. On 2026-07-31
two independent routes broke that promise with nothing going red:

  1. A dependabot auto-merge armed with the built-in GITHUB_TOKEN merged PR #250
     (fastapi 0.140.9 -> 0.140.13) as github-actions[bot]. GitHub creates no
     workflow runs for GITHUB_TOKEN-triggered events, so the push to main fired
     NO CI run, and deploy.yml -- which triggers on `workflow_run: [CI]
     completed` -- never ran. Production served 0.140.9 for a day.
  2. ci.yml's concurrency group was keyed on `github.ref`, which is
     `refs/heads/main` for every merge, so each merge cancelled the previous
     merge's CI -- and a cancelled CI run suppresses that merge's deploy too.

Both fixes are single expressions in YAML that a later edit could quietly undo,
and the failure they cause is silence. Hence these tests.

WHAT RUNS THEM: the `mcp` CI job, which needs no DB/Docker/network -- the same
reason test_prepush_hook.py and test_image_provenance_gate.py live here. The
`mcp` paths filter in ci.yml lists `.github/workflows/**` precisely so a
workflow-only PR (the one shape that can break these invariants) still runs them.
Removing that filter line is itself a workflow-only change and would conceal
itself; the behavioural backstop for that is deploy.yml's `drift` job, which
asks what production actually deployed rather than reading any config.

Assertions are textual rather than parsed: PyYAML is not a dependency of this
package (and mcp/pyproject.toml is not ours to change), and every invariant here
is a claim about the exact text of an expression anyway.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
DEPLOY = WORKFLOWS / "deploy.yml"
AUTO_MERGE = WORKFLOWS / "dependabot-auto-merge.yml"

# The single definition of "paths baked into the Fly image", hoisted to a
# workflow-level env in deploy.yml so the deploy gate and the drift watcher
# cannot disagree.
IMAGE_PATHS_REGEX = r"^(backend/|frontend/|Dockerfile|fly\.toml|\.dockerignore)"


@pytest.fixture(scope="module")
def ci_text() -> str:
    return CI.read_text()


@pytest.fixture(scope="module")
def deploy_text() -> str:
    return DEPLOY.read_text()


@pytest.fixture(scope="module")
def auto_merge_text() -> str:
    return AUTO_MERGE.read_text()


def _top_level_concurrency_group(text: str) -> str:
    """The `group:` value of the workflow-level `concurrency:` block."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == "concurrency:":
            for follower in lines[i + 1 :]:
                if follower and not follower.startswith((" ", "\t", "#")):
                    break  # left the block without finding a group
                m = re.match(r"\s+group:\s*(\S.*)$", follower)
                if m:
                    return m.group(1).strip()
    raise AssertionError("ci.yml has no workflow-level `concurrency:` -> `group:`")


def test_all_three_workflow_files_exist() -> None:
    for path in (CI, DEPLOY, AUTO_MERGE):
        assert path.is_file(), f"missing {path}"


# --- 1. main's CI runs must not cancel each other --------------------------


def test_ci_concurrency_group_is_per_commit_on_main(ci_text: str) -> None:
    group = _top_level_concurrency_group(ci_text)
    assert "github.sha" in group, (
        "ci.yml's concurrency group must vary per commit on main, or one merge "
        "cancels the previous merge's CI -- which also silently suppresses that "
        f"merge's deploy (KAN-586). Got: {group}"
    )
    assert "refs/heads/main" in group, (
        "the per-commit key must be conditional on main; PR branches should keep "
        f"a ref-only group so a superseded push is still cancelled. Got: {group}"
    )


def test_ci_does_not_merely_queue_main_runs(ci_text: str) -> None:
    """`cancel-in-progress: false` on main only queues, and GitHub keeps at most
    one pending run per group -- cancelling the older pending one. That
    reintroduces KAN-586 during a merge burst, which is when it bites."""
    group = _top_level_concurrency_group(ci_text)
    assert "github.sha" in group, "see test_ci_concurrency_group_is_per_commit_on_main"


# --- 2. the tests above must actually run on a workflow-only PR -------------


def test_mcp_paths_filter_watches_the_workflows(ci_text: str) -> None:
    mcp_filter = re.search(
        r"^            mcp:\n((?:^(?:              .*|\s*)\n)+)", ci_text, re.MULTILINE
    )
    assert mcp_filter, "could not locate the `mcp:` paths-filter block in ci.yml"
    assert "'.github/workflows/**'" in mcp_filter.group(1), (
        "the `mcp` paths filter must include '.github/workflows/**', otherwise a "
        "workflow-only PR -- the only PR shape that can break the invariants in "
        "this file -- never runs the tests that guard them (KAN-586)."
    )


# --- 3. the watcher triggers must never be able to ship code ----------------


def test_deploy_gate_requires_a_workflow_run_event(deploy_text: str) -> None:
    assert "github.event_name == 'workflow_run'" in deploy_text, (
        "deploy.yml's `changes` gate must require a workflow_run event. The "
        "`schedule:`/`workflow_dispatch:` triggers exist only for the drift "
        "watcher and must not be able to reach `flyctl deploy` (KAN-586)."
    )
    assert "github.event.workflow_run.conclusion == 'success'" in deploy_text, (
        "deploy.yml must still gate on CI having SUCCEEDED -- a red build never "
        "ships (ADR 0004)."
    )
    assert "github.event.workflow_run.head_branch == 'main'" in deploy_text, (
        "deploy.yml must still gate on the CI run being main's."
    )


def test_deploy_trigger_is_not_a_push_on_main(deploy_text: str) -> None:
    """A push trigger here would look like a fix and is not one: GitHub's
    recursion protection suppresses the push EVENT, so a GITHUB_TOKEN merge
    fires no push-triggered workflow either (verified: ef607856 has zero
    push-event runs while every other merge to main has two). What it WOULD do
    is deploy before CI has validated the merge commit -- and branch protection
    here has `strict: false`, so a PR's green checks are not evidence about the
    merge commit."""
    triggers = deploy_text.split("\njobs:", 1)[0]
    assert not re.search(r"^\s+push:", triggers, re.MULTILINE), (
        "deploy.yml must not gain a `push:` trigger -- see the KAN-586 block at "
        "the top of the file for why it does not fix anything."
    )


# --- 4. one definition of "image-affecting", two consumers ------------------


def test_image_paths_are_defined_exactly_once(deploy_text: str) -> None:
    occurrences = deploy_text.count(IMAGE_PATHS_REGEX)
    assert occurrences == 1, (
        "the image-path pattern must appear exactly once in deploy.yml (the "
        "workflow-level `IMAGE_PATHS` env). A second copy lets the drift watcher "
        f"go blind in exactly the place the deploy gate is blind. Found "
        f"{occurrences}."
    )
    assert deploy_text.count('grep -qE "$IMAGE_PATHS"') == 2, (
        "both the deploy gate and the drift watcher must consume $IMAGE_PATHS."
    )


# --- 5. the drift watcher exists and is scheduled ---------------------------


def test_drift_watcher_exists_and_has_something_running_it(deploy_text: str) -> None:
    assert re.search(r"^  drift:", deploy_text, re.MULTILINE), (
        "deploy.yml must keep the `drift` job -- the only signal that catches "
        "'main merged app code and production never got it', which no structural "
        "check can see (KAN-586)."
    )
    triggers = deploy_text.split("\njobs:", 1)[0]
    assert re.search(r"^\s+- cron:", triggers, re.MULTILINE), (
        "the drift watcher needs a `schedule:` cron -- a guard nothing runs is "
        "how this project has been bitten seven times."
    )
    assert "github.event_name != 'workflow_run'" in deploy_text, (
        "the drift job must not run on workflow_run, or it doubles every real "
        "deploy run."
    )


def test_drift_watcher_looks_at_the_deploy_job_not_the_run(deploy_text: str) -> None:
    """A docs-only Deploy run reports workflow-level `success` with the
    `Deploy to Fly.io` job SKIPPED. Reading the run conclusion would call that a
    deploy and the watcher would never fire."""
    assert '.name == "Deploy to Fly.io" and .conclusion == "success"' in deploy_text, (
        "the drift watcher must find the last run whose Deploy JOB succeeded, "
        "not the last run whose workflow-level conclusion was success."
    )
    assert re.search(r"^  deploy:\n    name: Deploy to Fly\.io$", deploy_text, re.MULTILINE), (
        "the drift watcher matches the deploy job by the literal name "
        "'Deploy to Fly.io'; renaming the job blinds it."
    )


# --- 6. the auto-merge must not hand gh a bare GITHUB_TOKEN -----------------


def test_auto_merge_uses_a_non_github_token(auto_merge_text: str) -> None:
    m = re.search(r"^\s+GH_TOKEN:\s*(.+)$", auto_merge_text, re.MULTILINE)
    assert m, "dependabot-auto-merge.yml has no GH_TOKEN for the merge step"
    value = m.group(1).strip()
    assert "AUTOMERGE_TOKEN" in value, (
        "the merge must be armed with secrets.AUTOMERGE_TOKEN (falling back to "
        "GITHUB_TOKEN). A merge armed with the built-in GITHUB_TOKEN lands as "
        "github-actions[bot], and GitHub creates no workflow runs for events it "
        f"triggers -- no CI on main, hence no Deploy (KAN-586). Got: {value}"
    )


def test_auto_merge_warns_when_running_degraded(auto_merge_text: str) -> None:
    """The GITHUB_TOKEN fallback keeps today's behaviour rather than breaking
    auto-merge outright, so the degraded state has to announce itself."""
    assert "::warning title=This merge will not trigger CI or Deploy::" in auto_merge_text, (
        "when AUTOMERGE_TOKEN is unset the step must emit a warning annotation "
        "saying the merge will not deploy (KAN-586)."
    )
