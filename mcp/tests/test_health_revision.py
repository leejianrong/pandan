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

READ `_clean_env` BEFORE ADDING A GIT CALL HERE. This file builds a synthetic
history and runs shell that shells out to git, from a suite that runs inside the
pre-push hook -- and a hook is handed `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE`
pointing at the REAL repository. This suite learned that the expensive way: an
early version scrubbed nothing, and its fixture committed "A"/"B"/"C" onto the
shared `main` ref of a linked worktree and pushed them onto a live PR, whose diff
then deleted 401 files. Everything below that touches git is contained
deliberately, and `test_a_hostile_ambient_git_env_cannot_reach_the_repo_under_test`
pins the containment. The same scar is recorded in test_prepush_hook.py from
KAN-484; this file follows its pattern rather than inventing a second one.

WHAT RUNS THEM: the `mcp` CI job. No DB, no Docker, no network -- the same reason
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
    assert re.search(r"^ENV GIT_REVISION=\$\{GIT_REVISION\}", dockerfile_text, re.MULTILINE), (
        "an ARG is build-time only -- it must be promoted to an ENV or the "
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
        "GIT_REVISION must be bound to github.event.workflow_run.head_sha -- the "
        "same ref the checkout step uses (KAN-595)."
    )


# --- 3. the app republishes it, cheaply ------------------------------------


def test_the_app_reads_the_revision_at_import_not_per_request() -> None:
    text = MAIN_PY.read_text()
    assert re.search(r"^GIT_REVISION = os\.environ\.get\(", text, re.MULTILINE), (
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
    # Code only -- the docstring explains what the handler does NOT do, and would
    # otherwise trip every check in this loop.
    body = handler.group(0).rsplit('"""', 1)[-1]
    for forbidden in ("open(", "subprocess", "Depends(", "os.environ"):
        assert forbidden not in body, (
            f"the version handler must not use {forbidden!r} -- it is on the "
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
        "keep the revision off the readiness probe's body -- it is a different "
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
        "the drift script grew a `${{ }}` expression -- it must stay pure shell "
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
        f"the drift watcher must fetch {VERSION_PATH} -- the endpoint KAN-595 "
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


# --- 5. ...and it goes red. Run it, contained. -----------------------------

# The only GIT_* names `_clean_env` may hand to git: config discovery pinned away
# from real files, plus a fixed identity so no `git config` is ever needed.
_ALLOWED_GIT_ENV = frozenset(
    {
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    }
)


def _clean_env(**extra: str) -> dict[str, str]:
    """A subprocess env with git's ambient state stripped.

    Non-negotiable, and the reason is a scar this file earned itself. These tests
    run inside the pre-push hook whenever the hook invokes the `mcp` suite, and a
    hook is handed `GIT_DIR`, `GIT_WORK_TREE` and `GIT_INDEX_FILE` pointing at the
    real repository. Inherit them and every git call below silently retargets it:
    `git init` reuses it, `git add -A` + `git commit` scribble the synthetic
    "A"/"B"/"C" history into it -- which is exactly what happened, onto the shared
    `main` ref of a linked worktree, and then onto a live PR whose diff deleted
    401 files.

    Strip the whole `GIT_*` namespace rather than a denylist of the names that bit
    us, and pin config discovery at `/dev/null` so ambient user/system git config
    (`core.hooksPath`, templates, signing) cannot perturb a fixture either.

    Identity comes from the environment so the fixture never runs `git config` at
    all. That is deliberate: **linked worktrees share the main repository's
    `.git/config`**, so a `git config user.email ...` that looks worktree-local is
    repository-global (KAN-484 wrote a test identity into the real repo that way).
    Nothing here may write git config.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "KAN-595 test"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "test@example.invalid"
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    """`git -C <repo>` under `_clean_env`.

    `-C` is belt-and-braces on top of `cwd` and the scrubbed env: it names the
    target repository explicitly, so no amount of ambient state can redirect the
    call to a repo the test does not own.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        cwd=repo,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git {args} failed:\n{result.stdout}{result.stderr}"
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    """`git init` a directory and PROVE the result is the directory we asked for."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    # Safety belt, not decoration. If the scrubbing in `_clean_env` ever
    # regresses, this fails loudly on the first fixture instead of quietly
    # committing into the developer's real repository.
    git_dir = Path(_git(path, "rev-parse", "--absolute-git-dir"))
    assert git_dir == (path / ".git").resolve(), (
        f"git dir resolved to {git_dir}, expected {(path / '.git').resolve()} -- "
        "ambient GIT_* environment is leaking; refusing to touch a real repo"
    )
    return path


def _commit(path: Path, label: str, files: dict[str, str]) -> str:
    for rel, content in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", label)
    return _git(path, "rev-parse", "HEAD")


def _build_history(path: Path) -> dict[str, object]:
    """A throwaway history: A (docs) -> B (backend) -> C (docs) on main, plus a
    commit D on a side branch that main does not contain."""
    _init_repo(path)
    shas: dict[str, str] = {}
    for label, rel in (("A", "docs/a.md"), ("B", "backend/app/b.py"), ("C", "docs/c.md")):
        shas[label] = _commit(path, label, {rel: label})

    _git(path, "checkout", "-q", "-b", "side", shas["A"])
    shas["D"] = _commit(path, "D", {"docs/d.md": "D"})
    _git(path, "checkout", "-q", "main")
    return {"path": path, "shas": shas}


def _snapshot(repo: Path) -> tuple:
    """Everything about `repo` a leaking test could plausibly disturb."""
    return (
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
        _git(repo, "status", "--porcelain"),
        (repo / ".git" / "config").read_text(),
    )


@pytest.fixture(scope="module")
def history(tmp_path_factory) -> dict[str, object]:
    return _build_history(tmp_path_factory.mktemp("drift-repo") / "repo")


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


def _watch(deploy_text, history, stub_bin, **env) -> subprocess.CompletedProcess:
    """Run the workflow's real drift shell against the synthetic history.

    The script is deploy.yml's verbatim text, so it cannot be given `git -C`;
    its containment is `cwd` plus the scrubbed env, the same way
    test_prepush_hook.py contains the hook script it runs. The assertion below
    checks that containment held BEFORE the script gets to run any git at all.
    """
    path = history["path"]
    script = path / ".drift.sh"
    script.write_text(_drift_step_script(deploy_text))

    full_env = _clean_env(
        **{
            "PATH": f"{stub_bin}:{os.environ['PATH']}",
            # The one definition of "image-affecting", copied from deploy.yml's
            # workflow-level env (test_deploy_gates.py pins that it stays single).
            "IMAGE_PATHS": r"^(backend/|frontend/|Dockerfile|fly\.toml|\.dockerignore)",
            "REPO": "leejianrong/pandan",
            "GH_TOKEN": "unused-by-the-stub",
            "PROD_VERSION_URL": "https://example.invalid/api/health/version",
            "GH_STUB_SHA": history["shas"]["C"],
            "CURL_STUB_EXIT": "0",
            "GH_STUB_EXIT": "0",
            **env,
        }
    )
    probe = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=path,
        env=full_env,
        capture_output=True,
        text=True,
    )
    assert Path(probe.stdout.strip()) == (path / ".git").resolve(), (
        "the environment handed to the drift script resolves git to "
        f"{probe.stdout.strip()!r}, not the throwaway repo -- refusing to run "
        "shell that commits, against a repo this test does not own"
    )

    return subprocess.run(
        ["bash", ".drift.sh"], cwd=path, env=full_env, capture_output=True, text=True
    )


def _body(sha: str) -> str:
    return '{"revision":"%s"}' % sha


def test_green_when_production_is_on_mains_tip(deploy_text, history, stub_bin) -> None:
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_BODY=_body(history["shas"]["C"]))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "In step" in r.stdout


def test_green_when_only_non_image_paths_moved_since(deploy_text, history, stub_bin) -> None:
    """Production on B, main on C, and C only touched docs/. Not drift."""
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_BODY=_body(history["shas"]["B"]))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "production is current" in r.stdout


def test_red_when_production_is_missing_image_affecting_commits(
    deploy_text, history, stub_bin
) -> None:
    """Production on A; B added backend/. THE case the watcher exists for."""
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_BODY=_body(history["shas"]["A"]))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error title=DEPLOY DRIFT::" in r.stdout
    assert history["shas"]["A"] in r.stdout and history["shas"]["C"] in r.stdout


def test_red_when_production_is_unreachable(deploy_text, history, stub_bin) -> None:
    """The deliberate choice: NOT observing production is a failure, not a pass
    and not a quiet fall back to the Actions-history inference. A watcher that
    shrugs when it cannot see is the blind-guard family this milestone keeps
    finding. A false alarm costs one look at the Actions tab."""
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_EXIT="7", CURL_STUB_BODY="")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not observe production" in r.stdout


def test_red_when_the_image_predates_the_endpoint(deploy_text, history, stub_bin) -> None:
    """An old image answers /api/health/version with 200 + index.html via the SPA
    catch-all. The realistic first-run case, and it must not read as green."""
    r = _watch(
        deploy_text,
        history,
        stub_bin,
        CURL_STUB_BODY="<!doctype html><html><body>pandan</body></html>",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "did not report a git revision" in r.stdout


def test_red_when_the_build_passed_no_revision(deploy_text, history, stub_bin) -> None:
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_BODY='{"revision":"unknown"}')
    assert r.returncode == 1, r.stdout + r.stderr
    assert "did not report a git revision" in r.stdout


def test_red_when_production_reports_a_commit_we_do_not_have(
    deploy_text, history, stub_bin
) -> None:
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_BODY=_body("d" * 40))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "unknown commit" in r.stdout


def test_red_when_production_is_not_on_main(deploy_text, history, stub_bin) -> None:
    """The rollback / laptop-deploy shape the Actions-history walk cannot see."""
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_BODY=_body(history["shas"]["D"]))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Production is not on main" in r.stdout


def test_the_actions_history_walk_survives_as_a_diagnostic(
    deploy_text, history, stub_bin
) -> None:
    """Demoted, not deleted: on a failure it says whether GitHub even tried, which
    separates 'the merge never triggered a deploy' (KAN-586) from 'the deploy ran
    and production is still on the old image'."""
    r = _watch(deploy_text, history, stub_bin, CURL_STUB_BODY=_body(history["shas"]["A"]))
    assert r.returncode == 1
    assert history["shas"]["C"] in r.stdout, (
        "the drift error should carry GitHub's last successful deploy SHA"
    )


def test_a_broken_diagnostic_does_not_change_the_verdict(
    deploy_text, history, stub_bin
) -> None:
    """The diagnostic is best-effort. If the GitHub API is down the watcher must
    still report the drift it observed -- the observation is the assertion now."""
    r = _watch(
        deploy_text,
        history,
        stub_bin,
        CURL_STUB_BODY=_body(history["shas"]["A"]),
        GH_STUB_EXIT="1",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error title=DEPLOY DRIFT::" in r.stdout
    assert "unavailable" in r.stdout


# --- 6. the blast radius of section 5, pinned ------------------------------


def test_a_hostile_ambient_git_env_cannot_reach_the_repo_under_test(
    deploy_text, stub_bin, tmp_path, monkeypatch
) -> None:
    """The containment invariant, mutation-tested rather than asserted by comment.

    This reproduces the exact condition that caused the incident -- `GIT_DIR`,
    `GIT_WORK_TREE` and `GIT_INDEX_FILE` in the ambient environment, as the
    pre-push hook supplies them -- then builds the synthetic history and runs the
    watcher, and asserts the pointed-at repository is byte-for-byte unchanged.

    It points them at a DECOY repo rather than the real one on purpose. Proving
    containment must not require risking the thing being contained: if the fix
    below ever regresses, this test fails against a directory under `tmp_path`
    instead of rewriting the developer's `main` (dev-playbook principle 5, and
    the same reason test_prepush_hook.py's mutation is a file append).
    """
    decoy = _init_repo(tmp_path / "decoy")
    _commit(decoy, "decoy base", {"README.md": "do not touch\n"})
    before = _snapshot(decoy)

    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))

    hostile = _build_history(tmp_path / "synthetic")
    result = _watch(
        deploy_text, hostile, stub_bin, CURL_STUB_BODY=_body(hostile["shas"]["A"])
    )
    assert result.returncode == 1, "the watcher should still work while contained"

    assert _snapshot(decoy) == before, (
        "building the synthetic history or running the drift script mutated the "
        "repository named by the ambient GIT_* environment. That is the KAN-595 "
        "incident verbatim: fixture commits landed on a shared `main` and were "
        "pushed onto a live PR. See `_clean_env`."
    )


def test_no_git_call_here_may_carry_inherited_git_state() -> None:
    """The property `_clean_env` exists for, asserted directly so a regression is
    named rather than merely observed downstream."""
    env = _clean_env()
    leaked = [k for k in env if k.startswith("GIT_") and k not in _ALLOWED_GIT_ENV]
    assert not leaked, f"unexpected GIT_* passed to git: {leaked}"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull


def test_the_fixtures_never_write_git_config(history) -> None:
    """Linked worktrees share the main repository's `.git/config`, so a fixture
    that runs `git config` is not writing worktree-local state -- KAN-484 authored
    two real commits under a test identity exactly that way. Identity comes from
    the environment instead, and this pins that it stayed that way."""
    config = Path(history["path"]) / ".git" / "config"
    assert "test@example.invalid" not in config.read_text()
