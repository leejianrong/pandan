"""Bearer-token plumbing for the principal resolver (M2 V4 → M3 V10).

Originally (V4, ADR 0010) this module guarded *writes* with an optional shared
``API_TOKENS`` bearer. V8 (ADR 0013) folded that into one owner-gated principal
resolver, keeping a transitional ``API_TOKENS`` → SERVICE bypass. **V10 (ADR
0015) retires that bypass entirely** — agents now authenticate with per-user
personal access tokens (V9, ADR 0014).

What survives here is just the HTTP bearer *scheme*: the presented credentials
are resolved to their owning ``User`` (a valid PAT) by :mod:`app.authz`, which
returns 401 when there is no cookie session and no valid PAT.
"""
from __future__ import annotations

from fastapi.security import HTTPBearer

# auto_error=False: the presence of a bearer is optional at the scheme level; the
# principal resolver (app.authz) decides whether the *request* is authorized
# (cookie session OR a valid personal access token), returning 401 itself otherwise.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Personal access token (pandan_pat_…) — see the Tokens UI (V9, ADR 0014).",
)
