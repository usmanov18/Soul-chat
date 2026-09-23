"""Subscription overview endpoint (TZ 5, TZ 28: Subscriptions).

The per-user view already lives at ``GET /users/{tg_id}/subscriptions``; this
router gives the panel the whole picture: who is missing which mandatory
membership, without paging through every user one by one.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import SessionDep, StaffUser
from app.models.user import Subscription, User

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("")
async def list_subscriptions(
    session: SessionDep,
    user: StaffUser,
    kind: str | None = None,
    is_member: bool | None = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
) -> dict:
    stmt = select(Subscription, User.tg_id, User.username, User.first_name).join(
        User, Subscription.user_id == User.id
    )
    count_stmt = (
        select(func.count())
        .select_from(Subscription)
        .join(User, Subscription.user_id == User.id)
    )
    if kind:
        stmt = stmt.where(Subscription.kind == kind)
        count_stmt = count_stmt.where(Subscription.kind == kind)
    if is_member is not None:
        stmt = stmt.where(Subscription.is_member.is_(is_member))
        count_stmt = count_stmt.where(Subscription.is_member.is_(is_member))

    total = await session.scalar(count_stmt)
    rows = (
        (
            await session.execute(
                stmt.order_by(Subscription.id.desc()).limit(limit).offset(offset)
            )
        )
        .all()
    )
    return {
        "total": int(total or 0),
        "items": [
            {
                "tg_id": tg_id,
                "username": username,
                "first_name": first_name,
                "kind": subscription.kind,
                "chat_id": subscription.chat_id,
                "is_member": subscription.is_member,
                "status": subscription.status,
                "checked_at": subscription.checked_at.isoformat()
                if subscription.checked_at
                else None,
            }
            for subscription, tg_id, username, first_name in rows
        ],
    }
