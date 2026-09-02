"""The ``pandan`` CLI over the Pandan REST API (`/api/v1`).

A thin adapter over the shared ``PandanClient`` (like the MCP server), so the API
stays the single source of truth (API-first, ADR 0005). This slice (KAN-22) is
the card subcommands: create / get / list / update / move / delete. Board and
epic subcommands are KAN-23; packaging polish + README + CI are KAN-24.
"""
from __future__ import annotations

# Bumped on every user-visible CLI change, in the SAME PR as the change (V50,
# KAN-435 — enforced by the CI `CLI version bump` guard + the pre-push hook).
# Must stay equal to `version` in pyproject.toml; a unit test asserts it.
__version__ = "0.41.0"
