"""Notification inbox endpoints (V37, KAN-301; per-user, owner-scoped).

The read side of the notification store: a board owner polls their inbox and marks
items read. Poll/pull only (ADR 0007) — no websockets, no real-time. The write path
(emit-on-event) is :mod:`app.notifications`. Mounted by ``main.py`` under
``/api/v1``:

- GET   /notifications         — list the caller's notifications (``?unread=true`` → only unread)
- PATCH /notifications/{id}     — mark one of the caller's notifications read

Every route is **per-user** (like ``/tokens``): it requires an authenticated
``User`` principal (cookie session or a PAT) and scopes strictly to that user's own
rows — a notification belonging to another user **404s** (never revealing it
exists), mirroring ``routers/tokens.py``'s revoke.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth_models import User
from ..authz import require_user
from ..db import get_db
from ..models import Notification
from ..schemas import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[Notification]:
    """List the caller's own notifications, newest-first. ``unread=true`` filters to
    only the unread ones (``read_at IS NULL``); default returns all. Owner-scoped:
    a caller only ever sees notifications addressed to them."""
    query = select(Notification).where(Notification.user_id == user.id)
    if unread:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(Notification.id.desc())
    return list(db.scalars(query).all())


@router.patch("/{notification_id}", response_model=NotificationRead)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Notification:
    """Mark one of the caller's notifications read (stamp ``read_at``). Idempotent —
    re-marking an already-read one leaves its timestamp untouched. **404** if it
    doesn't exist or belongs to another user (don't reveal that the id exists)."""
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    if notification.read_at is None:
        notification.read_at = func.now()
    db.commit()
    db.refresh(notification)
    return notification
