"""RFC 9728 OAuth 2.0 Protected Resource Metadata for the hosted MCP endpoint
(ADR 0025, KAN-1733).

A cold client (Claude.ai, ChatGPT, Cursor) connecting to ``/mcp`` needs to
discover, with no out-of-band configuration, which authorization server
protects it and where. RFC 9728 answers that with a metadata document at a
well-known location derived from the resource's own URL; RFC 6750 answers
"how does a client find that document" with a ``resource_metadata``
parameter on the ``WWW-Authenticate`` header of the ``401`` the resource
itself returns — wired in ``app/mcp_host.py``'s ``_unauthorized`` (this
module owns only the metadata document itself; the two share
:data:`METADATA_PATH` so they can't drift apart).

**Why this hand-writes the route instead of calling
``mcp.server.auth.routes.create_protected_resource_routes()``** (the same
SDK already vendored for the hosted transport itself, ``app/mcp_host.py``):
that helper bakes a *fixed* ``resource_url``/``authorization_servers`` into
the route at *import* time. Pandan's backend is one image deployed to more
than one origin — ``http://localhost:8000`` in dev,
``https://simple-kanban-jian.fly.dev`` today, whatever a self-hosted
operator's own reverse proxy terminates TLS at — with no build-time URL to
bake in. So this route recomputes the origin **per request** from
``request.base_url``, the exact mechanism
``app/routers/device_auth.py``'s ``verification_uri`` already uses — and
which is correct in prod for the same reason that one is: ``Dockerfile``
starts uvicorn with ``--proxy-headers --forwarded-allow-ips=*``, which
rewrites the ASGI scope's scheme/host from Fly's trusted proxy headers
*before* Starlette (and therefore ``request.base_url``) ever sees the
request — ADR 0011's own setup, reused as-is; a self-hosting operator who
fronts their own instance with a reverse proxy needs that same flag set
correctly, which is already the documented expectation for GitHub OAuth's
``redirect_uri`` today, not a new requirement this card introduces.

What *is* reused from the SDK is the shape that actually matters:
:class:`mcp.shared.auth.ProtectedResourceMetadata`, the RFC 9728-correct
Pydantic model, so the field names/types can't drift from what a real
client's parser expects even though the route construction itself is
hand-rolled.

**Self-issued, on purpose.** ``authorization_servers`` names this same
origin: Pandan's backend is both the resource server (this endpoint protects
``/mcp``) and the authorization server (the RFC 8628 device flow, ADR 0024;
the ``authorization_code``+PKCE grant, ADR 0026) — there is no separate AS to
point at.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from mcp.shared.auth import ProtectedResourceMetadata

# RFC 9728 §3.1: for a resource at `<origin>/mcp`, the metadata document lives
# at `<origin>/.well-known/oauth-protected-resource/mcp` -- the well-known
# prefix with the resource's own path appended, exactly what
# `mcp.server.auth.routes.build_resource_metadata_url` computes for a static
# resource_url. Hardcoded to `/mcp` since that's Pandan's only protected
# resource today; if a second one is ever added, generalize this alongside
# `app/mcp_host.py`'s use of it.
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"

router = APIRouter(tags=["auth"])


@router.get(METADATA_PATH, include_in_schema=False)
def protected_resource_metadata(request: Request) -> ProtectedResourceMetadata:
    """RFC 9728 discovery document for the hosted MCP endpoint (``/mcp``)."""
    origin = str(request.base_url).rstrip("/")
    return ProtectedResourceMetadata(
        resource=f"{origin}/mcp",
        authorization_servers=[origin],
    )
