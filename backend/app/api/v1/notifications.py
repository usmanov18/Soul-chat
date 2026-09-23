"""Notification feed endpoint (TZ 24, TZ 28: Notifications)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import SessionDep, StaffUser
from app.models.log import Notification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    session: SessionDep,
    user: StaffUser,
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> dict:
    stmt = select(Notification, User.tg_id, User.username).join(User, Notification.user_id == User.id)
    count_stmt = (
        select(func.count())
        .select_from(Notification)
        .join(User, Notification.user_id == User.id)
    )
    if status:
        stmt = stmt.where(Notification.status == status)
        count_stmt = count_stmt.where(Notification.status == status)
    if kind:
        stmt = stmt.where(Notification.kind == kind)
        count_stmt = count_stmt.where(Notification.kind == kind)

    total = await session.scalar(count_stmt)
    rows = (
        (
            await session.execute(
                stmt.order_by(Notification.id.desc()).limit(limit).offset(offset)
            )
        )
        .all()
    )
    return {
        "total": int(total or 0),
        "items": [
            {
                "id": notification.id,
                "tg_id": tg_id,
                "username": username,
                "kind": notification.kind,
                "title": notification.title,
                "body": notification.body,
                "status": notification.status,
                "sent_at": notification.sent_at.isoformat() if notification.sent_at else None,
                "error": notification.error,
                "created_at": notification.created_at.isoformat()
                if notification.created_at
                else None,
            }
            for notification, tg_id, username in rows
        ],
    }
