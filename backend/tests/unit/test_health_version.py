"""Build-provenance endpoint tests (KAN-595): ``GET /api/health/version``.

These live in the **unit** suite deliberately. The route is a constant-time
handler with no ``Depends(get_db)``, so a ``TestClient`` can exercise it against
a process that never opens a database connection — SQLAlchemy engines are built
lazily at import and nothing here makes them connect. That is the whole point of
the endpoint's shape: the drift watcher must be able to hit it on a cold box
without waking Neon.

``app.main`` is imported inside each test body rather than at module top. It is
not strictly required here (this suite has no ``DATABASE_URL``-rewriting
fixture), but the import is heavy and env-sensitive — ``GIT_REVISION`` is read
once at import — and keeping it in the body is the convention the sibling
integration suite enforces (the PR #17 trap).
"""
from __future__ import annotations

import importlib


def _fresh_app(monkeypatch, revision: str | None):
    """Re-import ``app.main`` with ``GIT_REVISION`` set (or unset).

    The constant is read at import time on purpose, so the only honest way to
    test both branches is to re-import the module under a different environment.
    """
    import app.main

    if revision is None:
        monkeypatch.delenv("GIT_REVISION", raising=False)
    else:
        monkeypatch.setenv("GIT_REVISION", revision)
    return importlib.reload(app.main)


def test_reports_the_baked_in_revision(monkeypatch):
    from fastapi.testclient import TestClient

    sha = "0123456789abcdef0123456789abcdef01234567"
    main = _fresh_app(monkeypatch, sha)

    r = TestClient(main.app).get("/api/health/version")
    assert r.status_code == 200
    assert r.json() == {"revision": sha}


def test_reports_unknown_when_the_build_passed_no_revision(monkeypatch):
    """A plain ``docker build`` with no ``--build-arg`` (and every image that
    predates KAN-595) must say so rather than invent a value. The watcher keys
    off exactly this: it refuses to pass on a revision it cannot use."""
    from fastapi.testclient import TestClient

    main = _fresh_app(monkeypatch, None)

    r = TestClient(main.app).get("/api/health/version")
    assert r.status_code == 200
    assert r.json() == {"revision": "unknown"}


def test_blank_revision_is_treated_as_unknown(monkeypatch):
    """``--build-arg GIT_REVISION=`` sets the var to the empty string, which is
    an absent revision wearing a present var's clothes."""
    from fastapi.testclient import TestClient

    main = _fresh_app(monkeypatch, "   ")

    assert TestClient(main.app).get("/api/health/version").json() == {
        "revision": "unknown"
    }


def test_the_readiness_probe_contract_is_untouched(monkeypatch):
    """Provenance went on a SIBLING route, not into ``/api/health``. The probe's
    body is asserted by equality elsewhere in the suite and is what Fly's health
    check and the keepalive poller read; widening it is a contract change nobody
    asked for."""
    main = _fresh_app(monkeypatch, "a" * 40)

    routes = {
        r.path: r for r in main.app.routes if getattr(r, "dependant", None) is not None
    }
    assert "/api/health/version" in routes

    # The readiness probe still depends on the DB session (that IS the probe);
    # the version route must not, or it stops being answerable on a cold box.
    health = routes["/api/health"]
    version = routes["/api/health/version"]
    assert version.dependant.dependencies == [], (
        "GET /api/health/version must stay dependency-free — no DB, no file "
        "read, no subprocess (KAN-595)."
    )
    assert health.dependant.dependencies, (
        "the readiness probe should still be doing its SELECT 1"
    )
