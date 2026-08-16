"""Regression tests for ci.yml's paths-filter classifiers (KAN-596).

THE DEFECT. `.github/workflows/ci.yml`'s `changes` job declared ten outputs. Nine
were read by a job's `if:`; the tenth, `app`, was read by nothing. Not "no longer
read" -- `git log -S 'needs.changes.outputs.app' -- .github/workflows/ci.yml`
returns NOTHING, so it was never consumed once in the file's entire history. It
was born dead in KAN-37 and sat there for the whole of milestones 6 and 7.

WHY THAT IS WORSE THAN UNTIDY. It actively misled. KAN-584's card cited that
union as "the app union" which should have matched `Dockerfile` and did not,
framing the gap as "a filter exists and is missing an entry". The truth was
stronger and different: the filter could never have caught anything, because no
job was gated on it. A reader auditing CI coverage saw a plausible union and
reasonably assumed something consumed it.

This is the same family as the milestone's recurring finding, one level out. The
recurring shape is a GUARD WITH NO WATCHER -- a check that runs nothing (KAN-452's
tag-gated release gate, KAN-484's hook tests outside their own filter, KAN-586's
cancelled main CI). This is a CLASSIFIER WITH NO CONSUMER: config that reads as
coverage and provides none. The failure mode is a reader's belief, not a red
build, which is why nothing caught it for two milestones and why the fix has to
be a test rather than a tidy-up.

THE INVARIANT, both directions:

  1. Every output the `changes` job DECLARES is referenced somewhere in ci.yml.
     A declared-but-unread output is the KAN-596 defect exactly.

  2. Every `needs.changes.outputs.X` ci.yml REFERENCES is declared. This is the
     mirror, and it fails silently in the nastier direction: GitHub resolves an
     undeclared output to the empty string rather than erroring, so a typo'd
     reference makes `if: needs.changes.outputs.frontend == 'true'` permanently
     false and the job skips its heavy steps forever while reporting success --
     the KAN-584 outcome, arrived at by a different route.

Plus a third, cheap now that both lists are read live: the declared outputs and
the declared filters are the same set. They were until `app`, and a filter with
no output is unreachable for the same reason an output with no reader is inert.

DELIBERATELY SCOPED TO ci.yml. deploy.yml has its own, separate `app` filter
which IS consumed (its `deploy` job's `if:`); job outputs are not visible across
workflows, so the two never interacted and deleting ci.yml's did not touch it.
deploy.yml's gates are pinned by test_deploy_gates.py, which owns that file.

WHAT RUNS THEM: the `mcp` CI job, which needs no DB/Docker/network -- the same
reason test_prepush_hook.py, test_deploy_gates.py and test_image_build_inputs.py
live here. The `mcp` paths filter lists `.github/workflows/**` (KAN-586), so a
workflow-only PR -- the only shape that can break this -- does run them. The last
test in this file pins that filter line, because a guard whose CI never runs it
would be precisely the thing this card is about.

Assertions are textual, matching this file's three siblings: PyYAML is not a
dependency of the `mcp` project (checked, not assumed -- `uv run python -c
'import yaml'` fails in a synced venv), and adding one to parse a file this
regular would trade a real dependency for nothing. Comments are stripped before
any reference is counted, because KAN-586 found a test of its own that stayed
green after the gate was deleted -- the file's header comment quoted the very
expression it searched for. This file's own explanatory comment in ci.yml quotes
`needs.changes.outputs.app`, so without that stripping test 1 below would pass
even if the dead output came back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"

# The job whose outputs classify the change. If it is ever renamed, the fixtures
# below fail loudly rather than silently measuring nothing.
CHANGES_JOB = "changes"


def _strip_comments(text: str) -> str:
    """Drop whole-line YAML comments.

    Every assertion here is about what ci.yml DOES. Prose describing it -- very
    much including the KAN-596 comment now sitting above the `filters:` block,
    which names `needs.changes.outputs.app` -- must not be able to satisfy an
    assertion. See the header.
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def ci_text() -> str:
    return CI.read_text()


@pytest.fixture(scope="module")
def declared_outputs(ci_text: str) -> list[str]:
    """The keys of the `changes` job's `outputs:` mapping, in file order.

    Scoped by indentation: `outputs:` sits at 4 spaces inside the job, its keys
    at 6, and the block ends at the next 4-space key (`steps:`).
    """
    job = re.search(
        rf"^  {re.escape(CHANGES_JOB)}:$(.*?)(?=^  [a-z_]+:$|\Z)",
        ci_text,
        re.MULTILINE | re.DOTALL,
    )
    assert job, f"ci.yml has no `{CHANGES_JOB}:` job -- this file measures nothing until fixed"

    block = re.search(r"^    outputs:\n((?:^      .*\n)+)", job.group(1), re.MULTILINE)
    assert block, f"ci.yml's `{CHANGES_JOB}` job has no `outputs:` mapping"

    keys = re.findall(r"^      ([A-Za-z0-9_-]+):", _strip_comments(block.group(1)), re.MULTILINE)
    # Anti-vacuity: a regex that quietly stops matching would make every
    # assertion below trivially true. Pin the parse against known-present keys.
    assert len(keys) >= 5, f"parsed only {keys} -- the outputs regex has stopped matching"
    assert {"backend", "frontend", "image"} <= set(keys), (
        f"parsed {keys}, which is missing outputs known to exist -- the regex is wrong, "
        "not the workflow"
    )
    return keys


@pytest.fixture(scope="module")
def declared_filters(ci_text: str) -> list[str]:
    """The filter names inside the `dorny/paths-filter` `filters:` literal block.

    Names sit at 12 spaces; their globs at 14. Matching only the 12-space keys is
    what keeps a glob from being mistaken for a filter name.
    """
    block = re.search(
        r"^          filters: \|\n((?:^(?:            .*)?\n)+)", ci_text, re.MULTILINE
    )
    assert block, "could not locate the `filters: |` block in ci.yml"
    names = re.findall(
        r"^            ([A-Za-z0-9_-]+):$", _strip_comments(block.group(1)), re.MULTILINE
    )
    assert len(names) >= 5, f"parsed only {names} -- the filters regex has stopped matching"
    return names


@pytest.fixture(scope="module")
def referenced_outputs(ci_text: str) -> set[str]:
    """Every `needs.changes.outputs.X` ci.yml actually evaluates.

    Comments are stripped FIRST -- see the header for why that is load-bearing
    rather than tidy.
    """
    refs = set(
        re.findall(
            rf"needs\.{re.escape(CHANGES_JOB)}\.outputs\.([A-Za-z0-9_-]+)",
            _strip_comments(ci_text),
        )
    )
    assert refs, "no `needs.changes.outputs.*` references found at all -- the regex is wrong"
    return refs


# --- 1. no classifier without a consumer (the KAN-596 defect) ---------------


def test_every_declared_output_is_consumed(
    declared_outputs: list[str], referenced_outputs: set[str]
) -> None:
    """A job output nothing reads is inert config that reads as coverage.

    `app` was exactly this from KAN-37 until KAN-596 -- and it did not merely sit
    there, it misled KAN-584's author into describing a gap in a filter that
    could never have caught anything.
    """
    orphans = [k for k in declared_outputs if k not in referenced_outputs]
    assert not orphans, (
        f"ci.yml's `{CHANGES_JOB}` job declares output(s) {orphans} that no `if:` in the file "
        f"reads. A paths filter nothing is gated on is a CLASSIFIER WITH NO CONSUMER: it reads "
        f"as CI coverage and provides none, which is how KAN-584 came to describe `app` as a "
        f"filter that should have matched Dockerfile when in truth no job consulted it. Either "
        f"gate a job on it, or delete BOTH the output and its filter entry (KAN-596)."
    )


# --- 2. the mirror: no consumer without a classifier ------------------------


def test_every_referenced_output_is_declared(
    declared_outputs: list[str], referenced_outputs: set[str]
) -> None:
    """The nastier direction, because GitHub does not error on it.

    An undeclared output resolves to the empty string, so `== 'true'` is
    permanently false: the job skips its heavy steps on every PR forever and
    still reports success. That is KAN-584's outcome reached by a typo.
    """
    dangling = sorted(referenced_outputs - set(declared_outputs))
    assert not dangling, (
        f"ci.yml evaluates `needs.{CHANGES_JOB}.outputs.{{{','.join(dangling)}}}` but the "
        f"`{CHANGES_JOB}` job declares no such output(s). GitHub resolves these to the EMPTY "
        f"STRING rather than failing, so every `== 'true'` guarded by one is permanently false "
        f"and the job silently skips its real work while reporting success."
    )


# --- 3. outputs and filters describe the same set ---------------------------


def test_declared_outputs_and_filters_agree(
    declared_outputs: list[str], declared_filters: list[str]
) -> None:
    """A filter with no output is unreachable; an output with no filter is always
    empty (the same silent-skip failure as test 2). They must be one set."""
    assert sorted(declared_outputs) == sorted(declared_filters), (
        f"ci.yml's `{CHANGES_JOB}` outputs {sorted(declared_outputs)} and its paths filters "
        f"{sorted(declared_filters)} have drifted apart. A filter with no output cannot be read "
        f"by any job; an output with no filter always resolves to the empty string."
    )


# --- 4. and the guard's own CI actually runs it -----------------------------


def test_the_mcp_filter_watches_the_workflows_dir(ci_text: str) -> None:
    """This file's only input is ci.yml, which lives outside mcp/.

    Without `.github/workflows/**` in the `mcp` filter, the one PR shape that can
    break the invariants above -- a workflow-only PR -- is the one shape that
    would never run these tests. That is the KAN-452 / KAN-484 / KAN-502 shape,
    and shipping it in the very card about unwatched config would be its own
    punchline.
    """
    block = re.search(r"^            mcp:\n((?:^(?:              .*)?\n)+)", ci_text, re.MULTILINE)
    assert block, "could not locate the `mcp:` paths-filter block in ci.yml"
    globs = re.findall(r"^\s*- '([^']+)'", _strip_comments(block.group(1)), re.MULTILINE)
    assert ".github/workflows/**" in globs, (
        "ci.yml's `mcp` paths filter must list '.github/workflows/**' -- otherwise a "
        "workflow-only PR skips the `mcp` job, and this file (whose only input IS a workflow) "
        "never runs on the exact change shape it exists to catch."
    )
