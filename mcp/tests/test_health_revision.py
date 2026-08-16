"""Regression tests for baked-in build provenance and the drift watcher's
assert half (KAN-595).

Two halves have to stay wired together or neither is worth anything:

  1. the root Dockerfile bakes the shipping commit in (`ARG GIT_REVISION` ->
     `ENV`), deploy.yml passes it (`flyctl deploy --build-arg`), and the app
     republishes it on `GET /api/health/version`; and
  2. the `drift` job in deploy.yml CURLS THAT and compares it to main.

Shipping (1) without (2) is exactly the "resolve half with no assert half" that
KAN-475 rejected and KAN-513/KAN-584 declined OCI labels over. So the structural
tests below pin both ends, and the behavioural ones actually RUN the watcher's
shell against a throwaway git repo with stubbed `curl` and `gh` — because a
watcher is a guard, and a guard nobody has watched fail is a decoration
(dev-playbook principle 5).

WHAT RUNS THEM: the `mcp` CI job. No DB, no Docker, no network — the same reason
test_prepush_hook.py and test_deploy_gates.py live here, and the `mcp` paths
filter in ci.yml includes `.github/workflows/**` so a workflow-only PR still runs
them.

Deliberately a SEPARATE file from test_deploy_gates.py: that file pins the
KAN-586 chain (triggers, concurrency, the auto-merge token), this one pins the
KAN-595 provenance chain. They read the same YAML for different promises.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
DOCKERFILE = ROOT / "Dockerfile"
MAIN_PY = ROOT / "backend" / "app" / "main.py"

VERSION_PATH = "/api/health/version"


@pytest.fixture(scope="module")
def deploy_text() -> str:
    return DEPLOY.read_text()


@pytest.fixture(scope="module")
def dockerfile_text() -> str:
    return DOCKERFILE.read_text()


# --- 1. the image carries its own revision ---------------------------------


def test_dockerfile_takes_a_defaulted_git_revision_arg(dockerfile_text: str) -> None:
    assert re.search(r"^ARG GIT_REVISION=\S+", dockerfile_text, re.MULTILINE), (
        "the root Dockerfile must declare `ARG GIT_REVISION` WITH A DEFAULT. "
        "Without one a plain `docker build -f Dockerfile .` (what ci.yml's "
        "`image` job and any local build do) would bake an empty revision, and "
        "mcp/Dockerfile's ARGs set the precedent (KAN-595)."
    )


def test_dockerfile_bakes_the_arg_into_the_runtime_image(dockerfile_text: str) -> None:
    assert re.search(
        r"^ENV GIT_REVISION=\$\{GIT_REVISION\}", dockerfile_text, re.MULTILINE
    ), (
        "an ARG is build-time only — it must be promoted to an ENV or the "
        "running container knows nothing and /api/health/version reports "
        "'unknown' forever (KAN-595)."
    )


def test_the_arg_is_declared_in_the_stage_that_ships(dockerfile_text: str) -> None:
    """A stage-scoped ARG declared before the wrong FROM silently expands to the
    empty string. Pin it to the `runtime` stage, after the last FROM."""
    last_from = dockerfile_text.rfind("\nFROM ")
    arg_at = dockerfile_text.find("\nARG GIT_REVISION=")
    assert arg_at > last_from > -1, (
        "`ARG GIT_REVISION` must appear in the final (runtime) stage. An ARG "
        "declared in an earlier stage is not visible after the next FROM, and "
        "the ENV would expand to nothing."
    )


# --- 2. the deploy passes the commit it is actually shipping ---------------


def test_deploy_passes_the_revision_as_a_build_arg(deploy_text: str) -> None:
    assert "--build-arg GIT_REVISION" in deploy_text, (
        "deploy.yml must pass `flyctl deploy --build-arg GIT_REVISION=...` or "
        "the deployed image reports 'unknown' and the drift watcher fails "
        "permanently (KAN-595)."
    )


def test_the_build_arg_is_the_same_sha_the_checkout_used(deploy_text: str) -> None:
    """The checkout deploys `workflow_run.head_sha` specifically so a red-then-
    green race cannot ship a different tree. If the build-arg came from anywhere
    else (github.sha, a `git rev-parse`) the endpoint would confidently report a
    commit that is not the one in the image."""
    deploy_job = re.search(
        r"^  deploy:$(.*?)(?=^  [a-z_]+:$|\Z)", deploy_text, re.MULTILINE | re.DOTALL
    )
    assert deploy_job, "deploy.yml has no `deploy:` job"
    block = deploy_job.group(1)
    assert re.search(
        r"^\s+GIT_REVISION:\s*\$\{\{\s*github\.event\.workflow_run\.head_sha\s*\}\}",
        block,
        re.MULTILINE,
    ), (
        "GIT_REVISION must be bound to github.event.workflow_run.head_sha — the "
        "same ref the checkout step uses (KAN-595)."
    )


# --- 3. the app republishes it, cheaply ------------------------------------


def test_the_app_reads_the_revision_at_import_not_per_request() -> None:
    text = MAIN_PY.read_text()
    assert re.search(
        r"^GIT_REVISION = os\.environ\.get\(", text, re.MULTILINE
    ), (
        "backend/app/main.py must read GIT_REVISION at module scope. The "
        "endpoint sits next to a readiness probe and has to stay constant-time: "
        "no per-request env read, no file read, no subprocess (KAN-595)."
    )
    handler = re.search(
        r"^def version\(\).*?^    return \{\"revision\": GIT_REVISION\}",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert handler, "GET /api/health/version's handler is not the expected one-liner"
    # Code only — the docstring below explains what it does NOT do, and would
    # otherwise trip every check in this loop.
    body = handler.group(0).rsplit('"""', 1)[-1]
    for forbidden in ("open(", "subprocess", "Depends(", "os.environ"):
        assert forbidden not in body, (
            f"the version handler must not use {forbidden!r} — it is on the "
            "health path and must stay answerable on a cold box (KAN-595)."
        )


def test_the_readiness_probe_body_was_not_widened() -> None:
    """Provenance went on a sibling route on purpose. `GET /api/health` is what
    Fly's health check and keepalive.yml poll, and its body is asserted by
    equality in backend/tests/integration/test_health.py."""
    text = MAIN_PY.read_text()
    probe = re.search(
        r"^def health\(.*?^    return \{\"status\": \"ok\"\}", text, re.MULTILINE | re.DOTALL
    )
    assert probe, "could not locate the /api/health handler"
    assert "GIT_REVISION" not in probe.group(0), (
        "keep the revision off the readiness probe's body — it is a different "
        "question with a different consumer, and widening the probe is a "
        "contract change (KAN-595)."
    )


# --- 4. the watcher actually asserts it ------------------------------------


def _drift_step_script(text: str) -> str:
    """The literal shell of the drift job's one step, dedented and runnable.

    Extracting the real block (rather than keeping a second copy here) is the
    point: a test against a copy would stay green while the workflow rotted.
    """
    marker = "      - name: Is production running main's app code?\n"
    assert marker in text, "deploy.yml lost the drift watcher's step"
    after = text.split(marker, 1)[1]
    run_at = after.index("        run: |\n")
    lines = after[run_at + len("        run: |\n") :].splitlines()
    script: list[str] = []
    for line in lines:
        if line.strip() and not line.startswith("          "):
            break
        script.append(line[10:] if line.startswith("          ") else "")
    assert "${{" not in "\n".join(script), (
        "the drift script grew a `${{ }}` expression — it must stay pure shell "
        "reading from `env:`, or it can no longer be executed and tested here."
    )
    return "\n".join(script) + "\n"


def test_the_watcher_asks_production_directly(deploy_text: str) -> None:
    script = _drift_step_script(deploy_text)
    assert "curl" in script, (
        "the drift watcher must OBSERVE production, not infer it from this "
        "workflow's own run history (KAN-595). That inference cannot see a "
        "Fly-side rollback, a machine that never restarted, or a laptop deploy."
    )
    assert VERSION_PATH in deploy_text, (
        f"the drift watcher must fetch {VERSION_PATH} — the endpoint KAN-595 "
        "added for exactly this."
    )


def test_the_watcher_does_not_trust_the_status_code_alone(deploy_text: str) -> None:
    """backend/app/main.py mounts the SPA catch-all as `GET /{full_path:path}`
    with no /api exclusion, so an image predating this endpoint answers
    /api/health/version with **200 and index.html**. `curl -f` is perfectly
    happy with that. Only the body's shape tells them apart."""
    script = _drift_step_script(deploy_text)
    assert "[0-9a-f]{40}" in script, (
        "the watcher must validate that production returned a 40-char hex "
        "revision. A 200 is not evidence: the SPA catch-all serves index.html "
        "for an unknown /api path (KAN-595)."
    )


# --- 5. …and it goes red. Run it. ------------------------------------------


def _run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> dict[str, object]:
    """A throwaway history: A (docs) -> B (backend) -> C (docs) on main, plus a
    commit D on a side branch that main does not contain."""
    path = tmp_path_factory.mktemp("drift-repo")
    _run_git(path, "init", "-q", "-b", "main")
    _run_git(path, "config", "user.email", "t@example.invalid")
    _run_git(path, "config", "user.name", "t")
    _run_git(path, "config", "commit.gpgsign", "false")

    shas: dict[str, str] = {}
    for label, rel in (("A", "docs/a.md"), ("B", "backend/app/b.py"), ("C", "docs/c.md")):
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(label)
        _run_git(path, "add", "-A")
        _run_git(path, "commit", "-qm", label)
        shas[label] = _run_git(path, "rev-parse", "HEAD")

    _run_git(path, "checkout", "-q", "-b", "side", shas["A"])
    (path / "docs" / "d.md").write_text("D")
    _run_git(path, "add", "-A")
    _run_git(path, "commit", "-qm", "D")
    shas["D"] = _run_git(path, "rev-parse", "HEAD")
    _run_git(path, "checkout", "-q", "main")

    return {"path": path, "shas": shas}


@pytest.fixture(scope="module")
def stub_bin(tmp_path_factory) -> Path:
    """Stubs for the two things the watcher reaches outside the repo for."""
    d = tmp_path_factory.mktemp("stub-bin")

    (d / "curl").write_text(
        "#!/bin/sh\n"
        'if [ "${CURL_STUB_EXIT:-0}" != "0" ]; then\n'
        '  echo "curl: (7) Failed to connect" >&2\n'
        '  exit "$CURL_STUB_EXIT"\n'
        "fi\n"
        'printf "%s" "$CURL_STUB_BODY"\n'
    )
    (d / "gh").write_text(
        "#!/bin/sh\n"
        'if [ "${GH_STUB_EXIT:-0}" != "0" ]; then exit "$GH_STUB_EXIT"; fi\n'
        'case "$*" in\n'
        '  *"/runs?per_page=40&event=workflow_run"*) echo 111 ;;\n'
        '  *"/runs/111/jobs"*) echo 1 ;;\n'
        '  *"/runs/111"*) printf "%s\\n" "$GH_STUB_SHA" ;;\n'
        "esac\n"
    )
    for name in ("curl", "gh"):
        (d / name).chmod(0o755)
    return d


def _watch(deploy_text, repo, stub_bin, **env) -> subprocess.CompletedProcess:
    script = _drift_step_script(deploy_text)
    path = repo["path"]
    (path / ".drift.sh").write_text(script)
    full_env = {
        **os.environ,
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        # The one definition of "image-affecting", copied from deploy.yml's
        # workflow-level env (test_deploy_gates.py pins that it stays single).
        "IMAGE_PATHS": r"^(backend/|frontend/|Dockerfile|fly\.toml|\.dockerignore)",
        "REPO": "leejianrong/pandan",
        "GH_TOKEN": "unused-by-the-stub",
        "PROD_VERSION_URL": "https://example.invalid/api/health/version",
        "GH_STUB_SHA": repo["shas"]["C"],
        "CURL_STUB_EXIT": "0",
        "GH_STUB_EXIT": "0",
        **env,
    }
    return subprocess.run(
        ["bash", ".drift.sh"], cwd=path, env=full_env, capture_output=True, text=True
    )


def _body(sha: str) -> str:
    return '{"revision":"%s"}' % sha


def test_green_when_production_is_on_mains_tip(deploy_text, repo, stub_bin) -> None:
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_BODY=_body(repo["shas"]["C"]))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "In step" in r.stdout


def test_green_when_only_non_image_paths_moved_since(deploy_text, repo, stub_bin) -> None:
    """Production on B, main on C, and C only touched docs/. Not drift."""
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_BODY=_body(repo["shas"]["B"]))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "production is current" in r.stdout


def test_red_when_production_is_missing_image_affecting_commits(
    deploy_text, repo, stub_bin
) -> None:
    """Production on A; B added backend/. THE case the watcher exists for."""
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_BODY=_body(repo["shas"]["A"]))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error title=DEPLOY DRIFT::" in r.stdout
    assert repo["shas"]["A"] in r.stdout and repo["shas"]["C"] in r.stdout


def test_red_when_production_is_unreachable(deploy_text, repo, stub_bin) -> None:
    """The deliberate choice: NOT observing production is a failure, not a pass
    and not a quiet fall back to the Actions-history inference. A watcher that
    shrugs when it cannot see is the blind-guard family this milestone keeps
    finding. A false alarm costs one look at the Actions tab."""
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_EXIT="7", CURL_STUB_BODY="")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not observe production" in r.stdout


def test_red_when_the_image_predates_the_endpoint(deploy_text, repo, stub_bin) -> None:
    """An old image answers /api/health/version with 200 + index.html via the SPA
    catch-all. The realistic first-run case, and it must not read as green."""
    r = _watch(
        deploy_text,
        repo,
        stub_bin,
        CURL_STUB_BODY="<!doctype html><html><body>pandan</body></html>",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "did not report a git revision" in r.stdout


def test_red_when_the_build_passed_no_revision(deploy_text, repo, stub_bin) -> None:
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_BODY='{"revision":"unknown"}')
    assert r.returncode == 1, r.stdout + r.stderr
    assert "did not report a git revision" in r.stdout


def test_red_when_production_reports_a_commit_we_do_not_have(
    deploy_text, repo, stub_bin
) -> None:
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_BODY=_body("d" * 40))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "unknown commit" in r.stdout


def test_red_when_production_is_not_on_main(deploy_text, repo, stub_bin) -> None:
    """The rollback / laptop-deploy shape the Actions-history walk cannot see."""
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_BODY=_body(repo["shas"]["D"]))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Production is not on main" in r.stdout


def test_the_actions_history_walk_survives_as_a_diagnostic(
    deploy_text, repo, stub_bin
) -> None:
    """Demoted, not deleted: on a failure it says whether GitHub even tried, which
    separates 'the merge never triggered a deploy' (KAN-586) from 'the deploy ran
    and production is still on the old image'."""
    r = _watch(deploy_text, repo, stub_bin, CURL_STUB_BODY=_body(repo["shas"]["A"]))
    assert r.returncode == 1
    assert repo["shas"]["C"] in r.stdout, (
        "the drift error should carry GitHub's last successful deploy SHA"
    )


def test_a_broken_diagnostic_does_not_change_the_verdict(
    deploy_text, repo, stub_bin
) -> None:
    """The diagnostic is best-effort. If the GitHub API is down the watcher must
    still report the drift it observed — the observation is the assertion now."""
    r = _watch(
        deploy_text,
        repo,
        stub_bin,
        CURL_STUB_BODY=_body(repo["shas"]["A"]),
        GH_STUB_EXIT="1",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error title=DEPLOY DRIFT::" in r.stdout
    assert "unavailable" in r.stdout
