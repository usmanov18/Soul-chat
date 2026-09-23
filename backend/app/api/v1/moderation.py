"""Moderation endpoints (TZ 22) and audit log."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import AdminUser, SessionDep, StaffUser
from app.api.schemas import AppealDecision, ModerationRequest, WarnOut
from app.core.logging import get_logger
from app.enums import AuditAction
from app.models.log import AuditLog
from app.models.security import BanAppeal, SpamEvent
from app.models.user import User
from app.services.audit import AuditService
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
    if payload.action == "unban":
        if user.role == "moderator":
            raise HTTPException(403, "Only admins can ban")
        await security.unban(payload.tg_id, user, payload.reason)
        return WarnOut(user_id=target.id, warns=target.warns)
    if payload.action == "unmute":
        await security.unmute(payload.tg_id, user, payload.reason)
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


@router.get("/appeals")
async def list_appeals(
    session: SessionDep, user: StaffUser, status: str = "pending", limit: int = Query(default=50, le=200)
) -> list[dict]:
    """D5: ban/mute appeals awaiting a decision."""
    stmt = select(BanAppeal).where(BanAppeal.status == status).order_by(BanAppeal.id.desc()).limit(limit)
    if status == "all":
        stmt = select(BanAppeal).order_by(BanAppeal.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "tg_id": r.tg_id,
            "text": r.text,
            "status": r.status,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "decision_note": r.decision_note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/appeals/{appeal_id}/decision")
async def decide_appeal(
    appeal_id: int, payload: AppealDecision, session: SessionDep, user: StaffUser
) -> dict:
    """D5: approve (lift the ban through the audited unban) or reject."""
    appeal = await session.get(BanAppeal, appeal_id)
    if appeal is None:
        raise HTTPException(404, "Appeal not found")
    if appeal.status != "pending":
        raise HTTPException(409, "Appeal already decided")

    if payload.decision == "approve":
        from app.enums import Role

        if user.role == Role.MODERATOR.value:
            raise HTTPException(403, "Only admins can lift a ban")
        await SecurityService(session).unban(appeal.tg_id, user, payload.note or "appeal approved")
    appeal.status = "approved" if payload.decision == "approve" else "rejected"
    appeal.decided_by = user.id
    appeal.decided_at = datetime.now(UTC)
    appeal.decision_note = payload.note
    await session.flush()
    await AuditService(session).log(
        f"appeal.{payload.decision}",
        actor=user,
        message=f"appeal #{appeal.id} from {appeal.tg_id}: {payload.decision}",
        source="api",
    )
    return {"id": appeal.id, "status": appeal.status}


@router.get("/fake-accounts")
async def fake_accounts(session: SessionDep, user: StaffUser, limit: int = Query(default=20, le=100)) -> list[dict]:
    """TZ 27: fake-account suspicion score (profile shape + spam history)."""
    security = SecurityService(session)
    rows = (await session.execute(select(User).order_by(User.id.desc()).limit(200))).scalars().all()
    scored: list[tuple[int, User, list[str]]] = []
    for row in rows:
        score, signals = await security.fake_account_score(row)
        if score > 0:
            scored.append((score, row, signals))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "tg_id": row.tg_id,
            "username": row.username,
            "first_name": row.first_name,
            "score": score,
            "signals": signals,
            "is_banned": row.is_banned,
        }
        for score, row, signals in scored[:limit]
    ]


@router.get("/actions")
async def actions() -> list[str]:
    return [a.value for a in AuditAction]