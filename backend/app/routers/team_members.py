"""Team-membership endpoints (M9 V66, KAN-1055; ADR 0021).

Mirrors :mod:`app.routers.members` (board membership, KAN-12) almost exactly — a
team can have members with a role (``viewer``/``editor``/``owner``, the same
``VALID_ROLES`` vocabulary), managed by anyone holding the ``owner`` role on the
team (ADR 0021 §New surface: "gated on the acting principal holding owner on the
team" — a team may have several owners, unlike a board's single ``owner_id``).
Listing is member-gated (any role); add/update/remove is owner-role gated.

Mounted by ``main.py`` under ``/api/v1`` (e.g. ``/api/v1/teams/{id}/members``):

- GET    /teams/{team_id}/members             — list members (any member)
- POST   /teams/{team_id}/members             — add a member by user_id or email (owner-role only)
- PATCH  /teams/{team_id}/members/{member_id} — change a member's role (owner-role only)
- DELETE /teams/{team_id}/members/{member_id} — remove a member (owner-role only)

**The one thing board membership doesn't need and team membership does: a
last-owner guard.** A board is always administered by its ``owner_id`` regardless
of any ``board_member`` row, so removing every board_member never orphans it. A
team has no such fallback — ``owner`` is *only* a role on ``team_member`` rows, so
demoting or removing the team's last owner would leave a team nobody can rename,
delete, or manage membership on ever again. Both mutating routes reject that with
``409`` (a state conflict, not a permissions problem — the actor plainly has
permission, the *result* is what's disallowed).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import authorize_team, get_principal
from ..db import get_db
from ..models import TeamMember
from ..schemas import TeamMemberCreate, TeamMemberRead, TeamMemberUpdate

# The team id lives in the prefix so every route is naturally scoped to it.
router = APIRouter(prefix="/teams/{team_id}/members", tags=["teams"])


def _with_email(db: Session, member: TeamMember) -> TeamMember:
    """Attach the member's email transiently (not an ORM column) so
    ``TeamMemberRead`` can surface it. Mirrors ``members._with_email``."""
    member.email = db.scalar(select(User.email).where(User.id == member.user_id))
    return member


def _resolve_user(db: Session, payload: TeamMemberCreate) -> User:
    """Resolve the target user from ``user_id`` or ``email`` (the schema guarantees
    exactly one is set); 404 if no such user exists. Mirrors
    ``members._resolve_user``."""
    if payload.user_id is not None:
        user = db.get(User, payload.user_id)
    else:
        # Case-insensitive, matching fastapi-users' own email lookup.
        user = db.scalars(
            select(User).where(func.lower(User.email) == payload.email.lower())
        ).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _get_member_or_404(db: Session, team_id: int, member_id: int) -> TeamMember:
    member = db.get(TeamMember, member_id)
    if member is None or member.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    return member


def _owner_count(db: Session, team_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(TeamMember)
        .where(TeamMember.team_id == team_id, TeamMember.role == "owner")
    )


def _reject_if_last_owner(db: Session, member: TeamMember) -> None:
    """409 if ``member`` is the team's sole remaining owner — demoting or removing
    them would leave the team with no one able to manage it (see module
    docstring)."""
    if member.role == "owner" and _owner_count(db, member.team_id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a team must keep at least one owner-role member",
        )


@router.get("", response_model=list[TeamMemberRead])
def list_team_members(
    team_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> list[TeamMember]:
    """List a team's members, oldest-first. Member-gated (any role); 401/403/404
    via :func:`app.authz.authorize_team`."""
    authorize_team(db, principal, team_id)
    rows = db.execute(
        select(TeamMember, User.email)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.id)
    ).all()
    members: list[TeamMember] = []
    for member, email in rows:
        member.email = email
        members.append(member)
    return members


@router.post("", response_model=TeamMemberRead, status_code=status.HTTP_201_CREATED)
def add_team_member(
    team_id: int,
    payload: TeamMemberCreate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> TeamMember:
    """Add a member to the team by ``user_id`` or ``email``. Owner-role gated.
    **404** if the target user doesn't exist; **409** if they are already a
    member."""
    authorize_team(db, principal, team_id, require_owner=True)
    user = _resolve_user(db, payload)
    existing = db.scalars(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user.id,
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user is already a member of this team",
        )
    member = TeamMember(team_id=team_id, user_id=user.id, role=payload.role.value)
    db.add(member)
    db.commit()
    db.refresh(member)
    member.email = user.email
    return member


@router.patch("/{member_id}", response_model=TeamMemberRead)
def update_team_member(
    team_id: int,
    member_id: int,
    payload: TeamMemberUpdate,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> TeamMember:
    """Change a member's role. Owner-role gated. **404** if no such member is on
    the team; **409** if this would demote the team's last owner."""
    authorize_team(db, principal, team_id, require_owner=True)
    member = _get_member_or_404(db, team_id, member_id)
    if payload.role.value != member.role:
        _reject_if_last_owner(db, member)
    member.role = payload.role.value
    db.commit()  # updated_at bumped server-side via onupdate
    db.refresh(member)
    return _with_email(db, member)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(
    team_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    principal: User = Depends(get_principal),
) -> Response:
    """Remove a member from the team. Owner-role gated. **404** if no such member
    is on the team; **409** if they are the team's last owner."""
    authorize_team(db, principal, team_id, require_owner=True)
    member = _get_member_or_404(db, team_id, member_id)
    _reject_if_last_owner(db, member)
    db.delete(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
