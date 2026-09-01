"""Team endpoints (M9 V65, KAN-1054; ADR 0021).

A team is the tenant tier above a ``User`` — see
[ADR 0021](../../../docs/adr/0021-organization-team-tier.md). **Minimal CRUD for
this slice**: create/list/get only. Membership management (add/remove/re-role a
member, rename/delete a team) is V66 (KAN-1055); optional ``team_id`` on board
create/update is V67 (KAN-1056); the team-default board-access authz rung is V68
(KAN-1057). Mounted by ``main.py`` under ``/api/v1`` (e.g. ``/api/v1/teams``):

- GET  /teams      — list the teams the caller is a member of
- POST /teams      — create a team; the creator is auto-added as an owner-role
                      team_member (the same bootstrap ``authorize_board`` already
                      gives a board's creator)
- GET  /teams/{id} — read one team (any member)

**Authorization.** Unlike a board, a team has no ``owner_id`` (ADR 0021 §Shape) —
membership *is* the whole visibility/access rule for this slice, via
:func:`app.authz.visible_team_ids` / :func:`app.authz.authorize_team`. A non-member
gets ``403`` on ``GET /{id}``, an unknown team ``404``, an unauthenticated caller
``401`` — mirroring the board authz shape (ADR 0013) even though a team has no
graded roles to enforce yet.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import authorize_team, get_principal, visible_team_ids
from ..db import get_db
from ..models import Team, TeamMember
from ..schemas import TeamCreate, TeamRead

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
