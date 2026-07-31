"""Regression tests for the pre-push hook's diff ranges (KAN-484).

`scripts/git-hooks/pre-push` answers two different questions from one diff:
*what changed* (which package checks to run) and *does this branch bump the CLI
version* (the V50 / KAN-435 bump-on-fix policy). KAN-484 is the bug that came
from answering both over the same incremental `remote_sha..local_sha` range: the
version-bump policy false-positived on a merge commit, so a compliant branch got
told to bump a version it had already bumped — and two agents pushed with
`--no-verify` rather than argue with it. A guard that cries wolf gets routed
around, so these tests pin both halves: the false positive stays fixed, and the
guard still bites a branch that genuinely skips the bump.

Why these live here, in the MCP suite: `mcp/tests/test_image_provenance_gate.py`
is this repo's existing precedent for exercising a shell script from a Python
suite, and the `mcp` CI job needs no DB, no Docker and no network — the same
shape this needs. **Caveat worth knowing (reported with KAN-484):** CI's
`changes` job path-filters the `mcp` job on `mcp/**`, and the hook lives at
`scripts/git-hooks/pre-push`, which matches no filter at all. So a future PR that
edits *only* the hook will not run these tests. Adding `scripts/git-hooks/**` to
the `mcp` filter in `.github/workflows/ci.yml` closes that hole; it was outside
KAN-484's fence.

Nothing here touches the real repository. Each test builds a throwaway git repo
in `tmp_path`, fabricates the `<local-ref> <local-sha> <remote-ref> <remote-sha>`
lines git feeds a pre-push hook on stdin, and stubs `uv`/`npm` with shims on
`PATH` so the hook's package checks are no-ops and only its range logic is under
test. **Every subprocess goes through `_clean_env`** — read its docstring before
adding one; these tests run inside a git hook, and inheriting that hook's `GIT_*`
environment points them at the real repo. The fixture asserts the scratch git dir
is the scratch one before it writes anything.

Mutation-testing note (the trap this project already documented): switching
branches swaps the hook itself, so point `PREPUSH_HOOK` at a version extracted
with `git show <ref>:scripts/git-hooks/pre-push` instead of checking anything out.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# Overridable so a mutated / historical copy can be tested without checking it
# out — see the module docstring.
HOOK = Path(os.environ.get("PREPUSH_HOOK") or REPO_ROOT / "scripts" / "git-hooks" / "pre-push")

ZERO = "0" * 40
BRANCH = "feat/slice"

# Every package dir the hook may `cd` into, so a scratch repo is a valid target.
PACKAGE_DIRS = ("backend", "frontend", "mcp", "pandan-client", "pandan-cli")

NOOP = "#!/bin/sh\nexit 0\n"

# The only GIT_* names `_clean_env` is allowed to hand to git: config discovery
# pinned away from real files, plus a fixed identity so no `git config` is needed.
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

    Non-negotiable, and the reason is a scar. This suite runs from inside a git
    hook whenever the pre-push hook invokes the `mcp` tests — and a hook is
    handed `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` and friends in its
    environment. Inherit those and every `git` call below silently retargets the
    REAL repository instead of the scratch one: `git init` reuses it, `git add -A`
    + `git commit` scribble the fixture's tree into it on a `feat/slice` branch,
    and `update-ref refs/remotes/origin/main` rewrites a live remote-tracking ref.
    That is not hypothetical — it happened once while building these tests
    (KAN-484's branch ref and `origin/main` were both clobbered and had to be
    recovered from the reflog).

    Strip the whole `GIT_*` namespace rather than a denylist of the vars that bit
    us, and pin config discovery at `/dev/null` so ambient user/system git config
    (`core.hooksPath`, templates, signing) can't perturb a fixture either.

    The commit identity is supplied here as environment too, so the fixture never
    runs `git config` at all. That is deliberate: **linked worktrees share the main
    repository's `.git/config`**, so a `git config user.email …` that looks
    worktree-local is repository-global. During KAN-484 exactly that happened — the
    test identity landed in the real repo's config and authored two commits as
    `KAN-484 test <test@example.invalid>`. Nothing here may write git config.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "KAN-484 test"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "test@example.invalid"
    env.update(extra)
    return env


def _init_version(version: str) -> dict[str, str]:
    return {
        "pandan-cli/pyproject.toml": f'[project]\nname = "pandan"\nversion = "{version}"\n',
        "pandan-cli/pandan_cli/__init__.py": f'__version__ = "{version}"\n',
    }


class Scratch:
    """A throwaway git repo the hook can be run against."""

    def __init__(self, path: Path, bin_dir: Path):
        self.path = path
        self.bin_dir = bin_dir

    # --- git plumbing -----------------------------------------------------
    def git(self, *args: str) -> str:
        result = self.git_raw(*args)
        assert result.returncode == 0, f"git {args} failed:\n{result.stdout}{result.stderr}"
        return result.stdout.strip()

    def git_raw(self, *args: str):
        """Like `git` but tolerates a non-zero exit (for probing refs).

        `-C self.path` is belt-and-braces on top of `cwd` and `_clean_env`: it
        names the target repo explicitly, so a stray `git config` can never land
        in a shared config file. That is not paranoia either — linked worktrees
        share the main repository's `.git/config`, so during KAN-484 the fixture's
        `git config user.email …` wrote the test identity into the real repo (two
        commits got authored as `KAN-484 test`), and `git init` with an inherited
        `GIT_DIR` set `core.bare = true` there, breaking an unrelated checkout.
        """
        return subprocess.run(
            ["git", "-C", str(self.path), *args],
            cwd=self.path,
            env=_clean_env(),
            capture_output=True,
            text=True,
        )

    def write(self, files: dict[str, str]) -> None:
        for rel, text in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)

    def commit(self, message: str, files: dict[str, str] | None = None) -> str:
        if files:
            self.write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def set_origin_main(self, sha: str) -> None:
        """Fake a remote-tracking ref — no network, no second repo."""
        self.git("update-ref", "refs/remotes/origin/main", sha)

    # --- the hook itself --------------------------------------------------
    def push(self, local_sha: str, remote_sha: str, ref: str = BRANCH):
        """Run the hook exactly as git would for one pushed ref."""
        env = _clean_env()
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"
        # Don't let an ambient PREPUSH_HOOK leak into the hook's own environment.
        env.pop("PREPUSH_HOOK", None)
        return subprocess.run(
            [str(HOOK)],
            cwd=self.path,
            input=f"refs/heads/{ref} {local_sha} refs/heads/{ref} {remote_sha}\n",
            env=env,
            capture_output=True,
            text=True,
        )


@pytest.fixture
def scratch(tmp_path):
    """A scratch repo on `main` with a CLI at 0.9.0, plus stubbed uv/npm."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("uv", "npm"):
        shim = bin_dir / tool
        shim.write_text(NOOP)
        shim.chmod(0o755)

    repo = tmp_path / "repo"
    repo.mkdir()
    s = Scratch(repo, bin_dir)
    s.git("init", "-q", "-b", "main")

    # Safety belt, not decoration: assert we are really pointed at the scratch
    # repo before anything writes. If the env scrubbing in `_clean_env` ever
    # regresses, this fails loudly on the first fixture instead of quietly
    # committing into the developer's real repository (see `_clean_env`).
    git_dir = Path(s.git("rev-parse", "--absolute-git-dir"))
    assert git_dir == (repo / ".git").resolve(), (
        f"scratch git dir is {git_dir}, expected {(repo / '.git').resolve()} — "
        "ambient GIT_* environment is leaking; refusing to touch a real repo"
    )

    # No `git config` here on purpose — identity comes from `_clean_env`, and
    # signing can't engage because config discovery is pinned at /dev/null.

    files = {
        "docs/notes.md": "notes\n",
        "pandan-cli/pandan_cli/cli.py": "def main():\n    return 0\n",
        "pandan-cli/pandan_cli/context.py": "CONTEXT = 1\n",
        "backend/app/main.py": "app = None\n",
        **_init_version("0.9.0"),
    }
    for pkg in PACKAGE_DIRS:
        files.setdefault(f"{pkg}/.keep", "")
    base = s.commit("initial", files)
    s.set_origin_main(base)
    s.base = base
    return s


def test_the_fixture_is_isolated_from_the_real_repository(scratch):
    """The containment invariant, pinned as a test rather than a comment.

    A linked worktree shares the main repository's `.git/config` and object store,
    so a fixture that leaks is not a test-hygiene nit — it edits the developer's
    repo. This asserts the two properties that keep it contained.
    """
    # 1. Every git call targets the scratch repo, whatever GIT_* is ambient.
    assert Path(scratch.git("rev-parse", "--absolute-git-dir")) == (
        scratch.path / ".git"
    ).resolve()

    # 2. The env handed to git carries no inherited GIT_DIR/GIT_WORK_TREE/etc, and
    #    pins config discovery away from any real file.
    env = _clean_env()
    leaked = [k for k in env if k.startswith("GIT_") and k not in _ALLOWED_GIT_ENV]
    assert not leaked, f"unexpected GIT_* passed to git: {leaked}"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull

    # 3. The fixture wrote no repo config at all (identity comes from the env), so
    #    it cannot scribble on a shared .git/config.
    config = scratch.path / ".git" / "config"
    assert "test@example.invalid" not in config.read_text()


def assert_passed(result):
    assert result.returncode == 0, (
        "expected the hook to pass, got:\n" + result.stdout + result.stderr
    )
    assert "pre-push ▸ OK" in result.stdout


def assert_version_guard_fired(result):
    assert result.returncode == 1, (
        "expected the version-bump guard to FAIL, got:\n" + result.stdout + result.stderr
    )
    assert "changed in this branch but the version did not" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# Baseline: the guard's two original outcomes on a brand-new branch, which the
# hook already got right. If these break, the fix broke the easy case.
# ---------------------------------------------------------------------------


def test_new_branch_with_a_bump_passes(scratch):
    scratch.git("switch", "-q", "-c", BRANCH)
    tip = scratch.commit(
        "feat: cli change + bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n", **_init_version("0.10.0")},
    )
    result = scratch.push(tip, ZERO)
    assert_passed(result)
    assert "version bump present" in result.stdout


def test_new_branch_without_a_bump_fails(scratch):
    scratch.git("switch", "-q", "-c", BRANCH)
    tip = scratch.commit(
        "feat: cli change, no bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n"},
    )
    assert_version_guard_fired(scratch.push(tip, ZERO))


# ---------------------------------------------------------------------------
# KAN-484: the false positive. Both of these are a SECOND push on a branch that
# already carries its bump, and both fired before the fix.
# ---------------------------------------------------------------------------


def test_second_push_of_a_merge_commit_passes(scratch):
    """The reported bug, replaying the real shape of commit 608e2f3.

    Branch bumps to 0.11.0 and pushes. main independently lands a CLI slice that
    bumps to 0.10.0. Merging main in conflicts on the version line; resolving it
    the *correct* way — keep the branch's already-higher 0.11.0 — leaves the
    version files byte-identical on both ends of `remote_sha..local_sha`, so they
    vanish from the incremental diff while main's pandan_cli/ files stay in it.
    Incremental range: CLI code changed, version didn't → guard fires. Branch
    range (what CI evaluates): version bumped → passes.
    """
    scratch.git("switch", "-q", "-c", BRANCH)
    first = scratch.commit(
        "feat: cli change + bump to 0.11.0",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n", **_init_version("0.11.0")},
    )
    assert_passed(scratch.push(first, ZERO))

    # main lands its own CLI slice with its own (lower) bump.
    scratch.git("switch", "-q", "main")
    landed = scratch.commit(
        "feat: another cli slice + bump to 0.10.0",
        {"pandan-cli/pandan_cli/context.py": "CONTEXT = 2\n", **_init_version("0.10.0")},
    )
    scratch.set_origin_main(landed)

    # Merge main into the branch, keeping our higher version on conflict.
    scratch.git("switch", "-q", BRANCH)
    merge = scratch.git_raw("merge", "--no-ff", "-m", "Merge origin/main into the branch", landed)
    # Be specific about WHY it failed. `assert returncode != 0` alone is the
    # classic blind assertion — any unrelated git error satisfies it, and one did
    # (this call once ran without the scrubbed env and failed on an unknown sha,
    # which looked exactly like a conflict).
    assert "CONFLICT" in merge.stdout + merge.stderr, (
        "expected a version-line conflict, got:\n" + merge.stdout + merge.stderr
    )
    assert scratch.git_raw("rev-parse", "--verify", "-q", "MERGE_HEAD").returncode == 0, (
        "no merge in progress — the conflict never happened"
    )
    scratch.write(_init_version("0.11.0"))
    scratch.git("add", "-A")
    scratch.git("commit", "-q", "--no-edit")
    tip = scratch.git("rev-parse", "HEAD")

    # Pin the shape this test exists for: the incremental range really does show
    # CLI code and no version file. Without this the test could pass for the
    # wrong reason (e.g. a merge that never brought CLI code in at all).
    incremental = scratch.git("diff", "--name-only", first, tip).splitlines()
    assert "pandan-cli/pandan_cli/context.py" in incremental
    assert "pandan-cli/pandan_cli/__init__.py" not in incremental
    assert "pandan-cli/pyproject.toml" not in incremental

    assert_passed(scratch.push(tip, first))


def test_second_push_when_the_bump_was_in_an_earlier_push_passes(scratch):
    """No merge needed: the bump is simply outside the incremental range."""
    scratch.git("switch", "-q", "-c", BRANCH)
    first = scratch.commit(
        "feat: cli change + bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n", **_init_version("0.10.0")},
    )
    assert_passed(scratch.push(first, ZERO))

    tip = scratch.commit(
        "feat: more of the same slice, same version",
        {"pandan-cli/pandan_cli/context.py": "CONTEXT = 2\n"},
    )
    assert_passed(scratch.push(tip, first))


# ---------------------------------------------------------------------------
# Not weakened. These are the assertions a careless fix silently loses.
# ---------------------------------------------------------------------------


def test_second_push_that_adds_cli_code_with_no_bump_anywhere_fails(scratch):
    """An incremental push must not be a hole in the policy."""
    scratch.git("switch", "-q", "-c", BRANCH)
    first = scratch.commit("docs: notes", {"docs/notes.md": "more notes\n"})
    assert_passed(scratch.push(first, ZERO))

    tip = scratch.commit(
        "feat: cli change, still no bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n"},
    )
    assert_version_guard_fired(scratch.push(tip, first))


def test_a_bump_undone_later_in_the_branch_fails(scratch):
    """Strictly stronger than the old range: the branch, not the last push.

    Push 1 bumps; push 2 puts the version back. The incremental range shows a
    version file *changed*, so the old logic passed this — but the branch as CI
    sees it carries CLI changes and no bump, and now so does the hook.
    """
    scratch.git("switch", "-q", "-c", BRANCH)
    first = scratch.commit(
        "feat: cli change + bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n", **_init_version("0.10.0")},
    )
    assert_passed(scratch.push(first, ZERO))

    tip = scratch.commit("oops: revert the bump", _init_version("0.9.0"))
    assert_version_guard_fired(scratch.push(tip, first))


def test_a_branch_that_never_touches_the_cli_is_not_asked_for_a_bump(scratch):
    scratch.git("switch", "-q", "-c", BRANCH)
    tip = scratch.commit("feat: backend only", {"backend/app/main.py": "app = 1\n"})
    result = scratch.push(tip, ZERO)
    assert_passed(result)
    assert "version" not in result.stdout.lower()


# ---------------------------------------------------------------------------
# The range/speed decision, pinned: test selection stays incremental while the
# policy goes branch-wide. If someone "simplifies" the hook to one range, this
# is the test that says which half they broke.
# ---------------------------------------------------------------------------


def test_test_selection_stays_incremental_while_the_policy_goes_branch_wide(scratch):
    scratch.git("switch", "-q", "-c", BRANCH)
    first = scratch.commit(
        "feat: cli change + bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n", **_init_version("0.10.0")},
    )
    assert_passed(scratch.push(first, ZERO))

    tip = scratch.commit("feat: backend only", {"backend/app/main.py": "app = 1\n"})
    result = scratch.push(tip, first)
    assert_passed(result)
    # Test selection: incremental — the CLI suite is NOT re-run for a push that
    # changed no CLI file, even though the branch touched pandan-cli/.
    assert "pandan-cli: skipped (no pandan-cli/ changes)" in result.stdout
    assert "pandan-cli: ruff + tests" not in result.stdout
    assert "backend: ruff + unit tests" in result.stdout
    # Policy: branch-wide — still evaluated, and satisfied by the earlier bump.
    assert "version bump present" in result.stdout


# ---------------------------------------------------------------------------
# The fail-safe when the branch range can't be computed. Two empty-range causes
# that need opposite treatment, which is why the hook tracks `base_resolved`.
# ---------------------------------------------------------------------------


def test_policy_falls_back_to_the_push_when_no_base_ref_exists(scratch):
    """No `main` and no `origin/main`: policy over nothing would fail OPEN."""
    scratch.git("switch", "-q", "-c", BRANCH)
    scratch.git("update-ref", "-d", "refs/remotes/origin/main")
    scratch.git("branch", "-q", "-D", "main")

    first = scratch.commit("docs: notes", {"docs/notes.md": "more notes\n"})
    tip = scratch.commit(
        "feat: cli change, no bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n"},
    )
    # No base means no branch range at all — confirm that, so this test can't
    # pass by accidentally still having one.
    for ref in ("refs/heads/main", "refs/remotes/origin/main"):
        probe = scratch.git_raw("rev-parse", "--verify", "-q", ref)
        assert probe.returncode != 0, f"{ref} still exists: {probe.stdout}"
    assert_version_guard_fired(scratch.push(tip, first))


def test_a_tip_already_merged_into_the_base_is_not_policed(scratch):
    """The other empty-range cause. CI computes the same empty diff and skips.

    Falling back to the push range here would re-open KAN-484 in this corner, so
    the fallback is gated on the base ref being genuinely unresolvable.
    """
    scratch.git("switch", "-q", "-c", BRANCH)
    first = scratch.commit("docs: notes", {"docs/notes.md": "more notes\n"})
    tip = scratch.commit(
        "feat: cli change, no bump",
        {"pandan-cli/pandan_cli/cli.py": "def main():\n    return 1\n"},
    )
    # main (and origin/main) now contain the branch tip.
    scratch.set_origin_main(tip)
    assert scratch.git("merge-base", "refs/remotes/origin/main", tip) == tip

    result = scratch.push(tip, first)
    assert_passed(result)
    assert "the version did not" not in result.stdout
