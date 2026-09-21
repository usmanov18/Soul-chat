"""User management endpoints (TZ 28)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import AdminUser, SessionDep, StaffUser
from app.api.schemas import UserOut, UserUpdate
from app.enums import Role
from app.models.user import Subscription, User

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    session: SessionDep,
    user: StaffUser,
    role: str | None = None,
    banned: bool | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
) -> list[UserOut]:
    stmt = select(User).order_by(User.id.desc())
    if role:
        stmt = stmt.where(User.role == role)
    if banned is not None:
        stmt = stmt.where(User.is_banned.is_(banned))
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return [UserOut.model_validate(row) for row in rows]


@router.get("/count")
async def count_users(session: SessionDep, user: StaffUser) -> dict:
    total = await session.scalar(select(func.count()).select_from(User))
    banned = await session.scalar(
        select(func.count()).select_from(User).where(User.is_banned.is_(True))
    )
    premium = await session.scalar(select(func.count()).select_from(User).where(User.premium.is_(True)))
    return {"total": int(total or 0), "banned": int(banned or 0), "premium": int(premium or 0)}


@router.get("/{tg_id}", response_model=UserOut)
async def get_user(tg_id: int, session: SessionDep, user: StaffUser) -> UserOut:
    row = (await session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "User not found")
    return UserOut.model_validate(row)


@router.patch("/{tg_id}", response_model=UserOut)
async def update_user(
    tg_id: int, payload: UserUpdate, session: SessionDep, admin: AdminUser
) -> UserOut:
    row = (await session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"] not in {r.value for r in Role}:
        raise HTTPException(422, "Unknown role")
    for key, value in data.items():
        setattr(row, key, value)
    await session.flush()
    return UserOut.model_validate(row)


@router.get("/{tg_id}/subscriptions")
async def subscriptions(tg_id: int, session: SessionDep, user: StaffUser) -> list[dict]:
    row = (await session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "User not found")
    rows = (
        await session.execute(select(Subscription).where(Subscription.user_id == row.id))
    ).scalars().all()
    return [
        {
            "kind": s.kind,
            "chat_id": s.chat_id,
            "is_member": s.is_member,
            "status": s.status,
            "checked_at": s.checked_at.isoformat() if s.checked_at else None,
        }
        for s in rows
    ]
