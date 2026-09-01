"""Team endpoints (M9 V65-V66, KAN-1054/1055; ADR 0021).

A team is the tenant tier above a ``User`` — see
[ADR 0021](../../../docs/adr/0021-organization-team-tier.md). Optional ``team_id``
on board create/update is V67 (KAN-1056); the team-default board-access authz rung
is V68 (KAN-1057). Mounted by ``main.py`` under ``/api/v1`` (e.g. ``/api/v1/teams``):

- GET    /teams      — list the teams the caller is a member of
- POST   /teams      — create a team; the creator is auto-added as an owner-role
                        team_member (the same bootstrap ``authorize_board`` already
                        gives a board's creator)
- GET    /teams/{id} — read one team (any member)
- PATCH  /teams/{id} — rename (owner-role members only, V66); does not touch any
                        board's ``team_id``
- DELETE /teams/{id} — hard-delete (owner-role members only, V66); boards
                        pointing at it are unclaimed via ``ON DELETE SET NULL``,
                        not deleted or reassigned

Team-member management (add/remove/re-role, V66) is a sibling router mounted
under ``/teams/{team_id}/members`` — see :mod:`app.routers.team_members`.

**Authorization.** Unlike a board, a team has no ``owner_id`` (ADR 0021 §Shape) —
membership *is* the whole visibility rule, and holding the ``owner`` role (a team
may have several) is the whole management rule, via
:func:`app.authz.visible_team_ids` / :func:`app.authz.authorize_team`. A non-member
gets ``403`` on a read, a non-owner ``403`` on rename/delete, an unknown team
``404``, an unauthenticated caller ``401`` — mirroring the board authz shape
(ADR 0013) even though a team's "owner" is a role rather than a single principal.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import authorize_team, get_principal, visible_team_ids
from ..db import get_db
from ..models import Team, TeamMember
from ..schemas import TeamCreate, TeamRead, TeamUpdate

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamRead])
def list_teams(
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[Team]:
    """List the teams the caller is a member of, oldest-first. Unlike
    ``GET /boards`` there is no owner rung to union in (ADR 0021) — membership is
    the entire visibility rule."""
    query = select(Team).order_by(Team.id).where(Team.id.in_(visible_team_ids(principal)))
    teams = list(db.scalars(query).all())
    roles = dict(
        db.execute(
            select(TeamMember.team_id, TeamMember.role).where(
                TeamMember.user_id == principal.id
            )
        ).all()
    )
    for team in teams:
        team.role = roles.get(team.id)
    return teams


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Team:
    """Create a team. The creator is auto-added as an **owner**-role
    ``team_member`` in the same transaction — a team with no members would be
    unreachable by anyone, since membership is the only way in (ADR 0021 §New
    surface)."""
    team = Team(name=payload.name)
    db.add(team)
    db.flush()  # assign team.id before inserting the membership row
    db.add(TeamMember(team_id=team.id, user_id=principal.id, role="owner"))
    db.commit()
    db.refresh(team)
    team.role = "owner"
    return team


@router.get("/{team_id}", response_model=TeamRead)
def get_team(
    team_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Team:
    """Read one team. Any member may read it; 403/404/401 via
    :func:`app.authz.authorize_team`."""
    return authorize_team(db, principal, team_id)


@router.patch("/{team_id}", response_model=TeamRead)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Team:
    """Rename a team (M9 V66, KAN-1055). Owner-role members only. Renaming never
    touches ``board.team_id`` — a team's boards are a separate pointer this schema
    has no field for."""
    team = authorize_team(db, principal, team_id, require_owner=True)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        team.name = data["name"]
    db.commit()  # updated_at bumped server-side via onupdate
    db.refresh(team)
    return team


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Hard-delete a team (M9 V66, KAN-1055). Owner-role members only. Any board
    pointing at it is **unclaimed, not destroyed** — ``board.team_id``'s
    ``ON DELETE SET NULL`` FK does the unclaiming (ADR 0021 §Shape); its member
    rows cascade away with it."""
    team = authorize_team(db, principal, team_id, require_owner=True)
    db.delete(team)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
