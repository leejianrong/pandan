"""RFC 9728 protected resource metadata tests (ADR 0025, KAN-1733).

Lives in the **unit** suite deliberately, mirroring ``test_health_version.py``:
the route reads no DB (no ``Depends(get_db)``) and touches no hosted-MCP
lifespan state, so a plain ``TestClient`` can exercise it against a process
that never opens a database connection or starts the Streamable HTTP session
manager.
"""
from __future__ import annotations


def test_metadata_document_shape():
    from fastapi.testclient import TestClient

    import app.main as m

    r = TestClient(m.app).get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == "http://testserver/mcp"
    assert body["authorization_servers"] == ["http://testserver"]
    assert body["bearer_methods_supported"] == ["header"]


def test_metadata_reflects_the_requests_own_origin():
    """Dev/Fly-prod/self-hosted all differ, so the document is derived per
    request from `request.base_url` rather than baked in at import time (see
    `app/oauth_metadata.py`'s module docstring) -- proven here by hitting it
    with an explicit Host header rather than trusting the TestClient default."""
    from fastapi.testclient import TestClient

    import app.main as m

    r = TestClient(m.app, base_url="https://example.pandan.dev").get(
        "/.well-known/oauth-protected-resource/mcp"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == "https://example.pandan.dev/mcp"
    assert body["authorization_servers"] == ["https://example.pandan.dev"]


def _iter_routes(routes):
    """Flatten FastAPI's route tree, descending into both a plain `APIRouter`
    (`.routes`) and FastAPI's `include_router`-time `_IncludedRouter` wrapper
    (`.original_router.routes`) -- `app.routes` alone only shows the latter,
    not the actual `APIRoute` objects with a `.dependant` inside it."""
    for r in routes:
        yield r
        if hasattr(r, "original_router"):
            yield from _iter_routes(r.original_router.routes)
        elif hasattr(r, "routes"):
            yield from _iter_routes(r.routes)


def test_route_depends_on_neither_the_db_nor_the_mcp_lifespan():
    """No `Depends(get_db)`, no reliance on `app.mcp_host._current_mcp_asgi_app`
    -- a cold client must be able to discover the AS even if the hosted MCP
    transport itself were somehow unavailable."""
    import app.main as m

    routes = {
        r.path: r for r in _iter_routes(m.app.routes) if getattr(r, "dependant", None) is not None
    }
    metadata_route = routes["/.well-known/oauth-protected-resource/mcp"]
    assert metadata_route.dependant.dependencies == []
