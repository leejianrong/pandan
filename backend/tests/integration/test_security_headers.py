"""Security-headers tests (V29, KAN-293).

The response middleware in ``app.main`` sets HSTS, a report-only CSP, nosniff, frame
denial, and a referrer policy on **every** response — API, the SPA-origin catch-all,
``/docs``, and error responses alike (it is registered outermost).

Key contract: the CSP ships as **Content-Security-Policy-Report-Only** first, so it
can never block the SPA or Swagger UI — only report. That's asserted explicitly.

Per the suite convention, ``app`` imports live inside test/fixture bodies (PR #17)."""
from __future__ import annotations

EXPECTED = {
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "content-security-policy-report-only",
}


def _assert_headers(resp):
    for name in EXPECTED:
        assert name in resp.headers, f"missing header: {name}"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    # CSP is report-only — the enforcing header must be absent so nothing is blocked.
    assert "content-security-policy" not in resp.headers
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy-report-only"]


def test_headers_on_api_response(logged_in_client):
    """An authenticated API response carries the full header set."""
    resp = logged_in_client.get("/api/v1/cards")
    assert resp.status_code == 200
    _assert_headers(resp)


def test_headers_on_non_api_origin_response(client):
    """Any non-/api path goes through the same origin-wide middleware — this is the
    SPA-fallback path in prod. With no built SPA in tests it 404s, but the middleware
    still decorates it (headers apply to errors too, since it's registered outermost)."""
    resp = client.get("/")
    _assert_headers(resp)


def test_headers_on_docs_and_docs_still_loads(client):
    """/docs (Swagger UI: inline scripts/styles + a CDN bundle) still loads 200, and
    carries the headers. Report-only CSP means Swagger is reported-on, never blocked."""
    resp = client.get("/docs")
    assert resp.status_code == 200
    _assert_headers(resp)


def test_csp_is_report_only_not_enforcing(logged_in_client):
    resp = logged_in_client.get("/api/v1/cards")
    assert "content-security-policy-report-only" in resp.headers
    assert "content-security-policy" not in resp.headers


def test_headers_present_on_error_response(client):
    """Headers decorate an unauthenticated 401 too (outermost middleware)."""
    resp = client.get("/api/v1/cards")  # no session → 401
    assert resp.status_code == 401
    _assert_headers(resp)
