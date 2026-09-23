"""Moderation endpoints (TZ 22) and audit log."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import AdminUser, SessionDep, StaffUser
from app.api.schemas import ModerationRequest, WarnOut
from app.core.logging import get_logger
from app.enums import AuditAction
from app.models.log import AuditLog
from app.models.security import SpamEvent
from app.models.user import User
from app.services.security_service import SecurityService
from app.services.telegram_gateway import FakeGateway
from app.services.topic_service import TopicService

logger = get_logger(__name__)
router = APIRouter(prefix="/moderation", tags=["moderation"])


@router.post("/action", response_model=WarnOut)
async def action(payload: ModerationRequest, session: SessionDep, user: StaffUser) -> WarnOut:
    security = SecurityService(session)
    target = (await session.execute(select(User).where(User.tg_id == payload.tg_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "User not found")

    topic = None
    if payload.topic_code:
        topic = await TopicService(session, FakeGateway()).by_code(payload.topic_code)

    if payload.action == "warn":
        _, warns = await security.warn(payload.tg_id, user, payload.reason, topic)
        return WarnOut(user_id=target.id, warns=warns)
    if payload.action == "mute":
        await security.mute(payload.tg_id, 30, payload.reason)
        return WarnOut(user_id=target.id, warns=target.warns)
    if payload.action == "ban":
        if user.role == "moderator":
            raise HTTPException(403, "Only admins can ban")
        await security.ban(payload.tg_id, user, payload.reason)
        return WarnOut(user_id=target.id, warns=target.warns)
    if payload.action == "freeze":
        service = TopicService(session, FakeGateway())
        if topic:
            await service.freeze(topic, user, payload.reason)
        return WarnOut(user_id=target.id, warns=target.warns)
    if payload.action == "restore":
        from app.models.topic import Topic

        service = TopicService(session, FakeGateway())
        stmt = (
            select(Topic)
            .where(
                Topic.owner_id == target.id,
                Topic.status.in_(["blocked", "delete_pending", "archived"]),
            )
            .order_by(Topic.id.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            await service.restore(row, user)
        return WarnOut(user_id=target.id, warns=target.warns)
    raise HTTPException(422, f"Unknown action: {payload.action}")


@router.get("/spam")
async def spam_events(session: SessionDep, user: StaffUser, limit: int = Query(default=50, le=200)) -> list[dict]:
    rows = (
        await session.execute(select(SpamEvent).order_by(SpamEvent.id.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "kind": r.kind,
            "score": r.score,
            "action": r.action,
            "excerpt": r.text_excerpt,
            "at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/audit")
async def audit_logs(
    session: SessionDep,
    user: AdminUser,
    action: str | None = None,
    limit: int = Query(default=100, le=500),
) -> list[dict]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "actor_tg_id": r.actor_tg_id,
            "topic_id": r.topic_id,
            "ip": r.ip_address,
            "device": r.device,
            "source": r.source,
            "message": r.message,
            "at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/actions")
async def actions() -> list[str]:
    return [a.value for a in AuditAction]