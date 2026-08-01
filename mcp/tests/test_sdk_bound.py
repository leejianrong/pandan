"""The `mcp` SDK requirement must carry an UPPER BOUND (KAN-585).

## The defect this pins

``pyproject.toml`` declared ``mcp>=1.2`` — unbounded. The SDK is not one dependency
among several here: **every tool in ``pandan_mcp/server.py`` is registered through
its high-level decorator layer**, so a major bump is a rewrite of the module's
entry point, not a version number. SDK 2.0.0 duly deleted ``mcp.server.fastmcp``
and renamed ``FastMCP`` → ``MCPServer``; dependabot offered it because nothing said
no, and its CI failed at *import* in three test modules before a single assertion
ran. The SDK's own README says to carry an upper bound. This asserts we do.

## Why a test and not just a comment

A comment in ``pyproject.toml`` is what the next person deletes while "cleaning up
the pin". The unbounded range is the thing that let the breakage in, so the *bound*
is the invariant, not the particular version behind it: this test deliberately does
**not** assert ``<3`` or ``>=2.0``. Bumping to the next major stays a normal
one-line edit; *removing* the ceiling does not.

## What watches the ceiling

Dependabot's ``uv`` ecosystem on ``/mcp`` (weekly; majors ungrouped, so a 3.x bump
arrives as its own reviewable PR) plus the ``mcp`` CI job. That is the exact loop
that surfaced 2.0.0 — the ceiling is watched by the same machinery that found the
problem, which is what distinguishes it from the unwatched-pin shape KAN-475
refused for the docker ecosystem.

Parsed with ``tomllib`` against the real file rather than imported, for the same
reason ``test_prepush_hook.py`` reads a shell script: the artefact under test is
config, and the test should fail if the *file* changes, not if some accessor does.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"

#: An upper bound on the `mcp` requirement, in any spelling PEP 508 allows:
#: `<3`, `<3.0`, `<=2.9`, `==2.*`, `~=2.0`. Anything that caps the major.
_UPPER_BOUND = re.compile(r"(<=?|==|~=)\s*\d")


def _requirements() -> list[str]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]


def _mcp_requirement() -> str:
    """The one dependency line naming the SDK.

    Matched on the distribution name at the start of the string, so a substring
    like `pandan-client` can never be mistaken for it.
    """
    matches = [r for r in _requirements() if re.match(r"^mcp\s*[<>=~!\[]", r)]
    # Non-vacuity: every assertion below is about this line, so "there is exactly
    # one" has to be asserted before anything is asserted *about* it. A rename that
    # made this list empty would otherwise turn the whole file green and silent.
    assert len(matches) == 1, (
        f"expected exactly one `mcp` requirement in {PYPROJECT}, found {matches!r}. "
        "If the SDK dependency was renamed or removed, this guard needs updating "
        "deliberately — it is the only thing asserting the major is capped."
    )
    return matches[0]


def test_the_sdk_requirement_is_capped_at_a_major():
    requirement = _mcp_requirement()
    assert _UPPER_BOUND.search(requirement), (
        f"the `mcp` SDK requirement is {requirement!r} — it has no upper bound.\n\n"
        "That is exactly how SDK 2.0.0 arrived (KAN-585): it deleted "
        "`mcp.server.fastmcp`, the module every tool in pandan_mcp/server.py is "
        "registered through, and CI went red at import. The SDK's own README asks "
        "consumers to carry a ceiling.\n\n"
        "Bumping the ceiling to the next major after porting is fine and expected. "
        "Removing it is not: dependabot would then land a major SDK rework as an "
        "ordinary weekly bump."
    )


def test_the_guard_is_looking_at_a_requirement_it_can_actually_read():
    """Non-vacuity, the other half. ``_UPPER_BOUND`` could match nothing at all if
    someone rewrote it, and the test above would then be a permanent red — but it
    could also be *widened* into something that matches any string, making it a
    permanent green. Pin both ends against known-good and known-bad literals."""
    assert _UPPER_BOUND.search("mcp>=2.0,<3")
    assert _UPPER_BOUND.search("mcp~=2.0")
    assert not _UPPER_BOUND.search("mcp>=1.2")
    assert not _UPPER_BOUND.search("mcp")
    # And the real line is a lower bound too, so `uv` cannot resolve backwards to
    # an SDK that predates `mcp.server.mcpserver`.
    assert re.search(r">=\s*\d", _mcp_requirement()), (
        "the `mcp` requirement lost its lower bound — nothing stops a resolver "
        "picking a 1.x that has no `mcp.server.mcpserver`"
    )
