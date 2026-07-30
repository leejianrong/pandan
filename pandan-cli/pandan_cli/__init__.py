"""The ``kan`` CLI over the Simple Kanban REST API (`/api/v1`).

A thin adapter over the shared ``KanbanClient`` (like the MCP server), so the API
stays the single source of truth (API-first, ADR 0005). This slice (KAN-22) is
the card subcommands: create / get / list / update / move / delete. Board and
epic subcommands are KAN-23; packaging polish + README + CI are KAN-24.
"""
from __future__ import annotations

__version__ = "0.3.0"
