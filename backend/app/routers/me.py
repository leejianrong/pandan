"""Who-am-I for the acting principal (KAN-530, issue #253).

``GET /api/v1/me`` answers "which pandan user is this credential?" and nothing
else. Until now a PAT holder had no way to ask: fastapi-users' ``/users/me`` lives
on the **async cookie path** and won't accept a bearer, while the PAT branch of
:func:`app.authz.get_principal` guards ``/api/v1`` only. That gap is invisible
while pandan is its own only consumer — every ``/api/v1`` route already knows the
caller — and becomes load-bearing the moment another app authenticates against
pandan. The first such consumer is **kaya**, which delegates identity here rather
than minting tokens of its own (kaya ADR 0002): it forwards the caller's bearer,
caches the answer, and mirrors the returned UUID locally.

Deliberately thin, per the issue:

- **Sync** and reuses ``get_principal`` unchanged (ADR 0008/0013/0015) — no new
  auth path, no new dependency, no touch of the async engine. Cookie sessions
  resolve here too; the bearer is simply what has nowhere else to go.
- **No board is involved**, so there is nothing to authorize and
  :func:`app.authz.authorize_board` is not called. The only outcomes are **200**
  and the resolver's **401**; a scoped ``read`` PAT is unaffected because ``GET``
  is a safe method. Pinned by ``tests/integration/test_me.py``.
- Returns the **minimum** — id + email (:class:`app.schemas.PrincipalRead`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth_models import User
from ..authz import require_user
from ..schemas import PrincipalRead

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=PrincipalRead)
def read_me(user: User = Depends(require_user)) -> User:
    """Return the authenticated principal's id + email (401 if there isn't one)."""
    return user
