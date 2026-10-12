"""Errors the model is meant to read.

The MCP SDK (2.x) treats any exception that is not a ``ToolError`` as a crash and
shows the model only ``Error executing tool <name>``, keeping the text in the server
log. A mistake the model can correct from the message (a missing ``board_id``, an
unknown ``fields`` name) is the opposite of a crash, so those raise
:class:`ToolValueError`.

It is also a ``ValueError`` on purpose: the tools raised ``ValueError`` before this
existed, and direct callers (and their tests) still catch it as one.
"""
from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError


class ToolValueError(ToolError, ValueError):
    """A caller mistake, reported to the model verbatim."""
