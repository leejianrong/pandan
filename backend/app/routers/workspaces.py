"""Workspace endpoints (M9 V65-V66, KAN-1054/1055; ADR 0021).

A workspace is the tenant tier above a ``User`` — see
[ADR 0021](../../../docs/adr/0021-organization-workspace-tier.md) (renamed Team -> Workspace by
ADR 0023; the ADR 0021 file itself was retitled in place by KAN-1724). Optional ``workspace_id``
on board create/update is V67 (KAN-1056); the workspace-default board-access authz rung
is V68 (KAN-1057). Mounted by ``main.py`` under ``/api/v1`` (e.g. ``/api/v1/workspaces``):

- GET    /workspaces      — list the workspaces the caller is a member of
- POST   /workspaces      — create a workspace; the creator is auto-added as an owner-role
                        workspace_member (the same bootstrap ``authorize_board`` already
                        gives a board's creator)
- GET    /workspaces/{id} — read one workspace (any member)
- PATCH  /workspaces/{id} — rename (owner-role members only, V66); does not touch any
                        board's ``workspace_id``
- DELETE /workspaces/{id} — hard-delete (owner-role members only, V66); boards
                        pointing at it are unclaimed via ``ON DELETE SET NULL``,
                        not deleted or reassigned

Workspace-member management (add/remove/re-role, V66) is a sibling router mounted
under ``/workspaces/{workspace_id}/members`` — see :mod:`app.routers.workspace_members`.

**Authorization.** Unlike a board, a workspace has no ``owner_id`` (ADR 0021 §Shape) —
membership *is* the whole visibility rule, and holding the ``owner`` role (a workspace
may have several) is the whole management rule, via
:func:`app.authz.visible_workspace_ids` / :func:`app.authz.authorize_workspace`. A non-member
gets ``403`` on a read, a non-owner ``403`` on rename/delete, an unknown workspace
``404``, an unauthenticated caller ``401`` — mirroring the board authz shape
(ADR 0013) even though a workspace's "owner" is a role rather than a single principal.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import authorize_workspace, get_principal, visible_workspace_ids
from ..db import get_db
from ..models import Workspace, WorkspaceMember
from ..schemas import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[Workspace]:
    """List the workspaces the caller is a member of, oldest-first. Unlike
    ``GET /boards`` there is no owner rung to union in (ADR 0021) — membership is
    the entire visibility rule."""
    query = (
        select(Workspace)
        .order_by(Workspace.id)
        .where(Workspace.id.in_(visible_workspace_ids(principal)))
    )
    workspaces = list(db.scalars(query).all())
    roles = dict(
        db.execute(
            select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(
                WorkspaceMember.user_id == principal.id
            )
        ).all()
    )
    for workspace in workspaces:
        workspace.role = roles.get(workspace.id)
    return workspaces


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Workspace:
    """Create a workspace. The creator is auto-added as an **owner**-role
    ``workspace_member`` in the same transaction — a workspace with no members would be
    unreachable by anyone, since membership is the only way in (ADR 0021 §New
    surface)."""
    workspace = Workspace(name=payload.name)
    db.add(workspace)
    db.flush()  # assign workspace.id before inserting the membership row
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=principal.id, role="owner"))
    db.commit()
    db.refresh(workspace)
    workspace.role = "owner"
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Workspace:
    """Read one workspace. Any member may read it; 403/404/401 via
    :func:`app.authz.authorize_workspace`."""
    return authorize_workspace(db, principal, workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Workspace:
    """Rename a workspace (M9 V66, KAN-1055). Owner-role members only. Renaming never
    touches ``board.workspace_id`` — a workspace's boards are a separate pointer this schema
    has no field for."""
    workspace = authorize_workspace(db, principal, workspace_id, require_owner=True)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        workspace.name = data["name"]
    db.commit()  # updated_at bumped server-side via onupdate
    db.refresh(workspace)
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Hard-delete a workspace (M9 V66, KAN-1055). Owner-role members only. Any board
    pointing at it is **unclaimed, not destroyed** — ``board.workspace_id``'s
    ``ON DELETE SET NULL`` FK does the unclaiming (ADR 0021 §Shape); its member
    rows cascade away with it."""
    workspace = authorize_workspace(db, principal, workspace_id, require_owner=True)
    db.delete(workspace)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
