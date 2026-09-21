"""Topic endpoints (TZ 16, 17, 18, 19, 20, 22)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import AdminUser, SessionDep, StaffUser
from app.api.schemas import TopicActionRequest, TopicList, TopicOut
from app.core.logging import get_logger
from app.models.topic import Topic
from app.services.archive_service import ArchiveService
from app.services.telegram_gateway import FakeGateway
from app.services.topic_service import TopicError, TopicService

logger = get_logger(__name__)
router = APIRouter(prefix="/topics", tags=["topics"])


def _gateway():
    """REST actions run outside the bot process; a token-less gateway is enough
    for the state machine, and ``BOT_TOKEN`` gives the real one."""
    from app.core.config import settings
    from app.services.telegram_gateway import AiogramGateway

    if settings.bot_token:
        from aiogram import Bot

        return AiogramGateway(Bot(token=settings.bot_token))
    return FakeGateway()


@router.get("", response_model=TopicList)
async def list_topics(
    session: SessionDep,
    user: StaffUser,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> TopicList:
    stmt = select(Topic).order_by(Topic.id.desc())
    count_stmt = select(func.count()).select_from(Topic)
    if status_filter:
        stmt = stmt.where(Topic.status == status_filter)
        count_stmt = count_stmt.where(Topic.status == status_filter)
    total = await session.scalar(count_stmt)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return TopicList(items=[TopicOut.model_validate(row) for row in rows], total=int(total or 0))


@router.get("/{code}", response_model=TopicOut)
async def get_topic(code: str, session: SessionDep, user: StaffUser) -> TopicOut:
    topic = (await session.execute(select(Topic).where(Topic.code == code))).scalar_one_or_none()
    if topic is None:
        raise HTTPException(404, "Topic not found")
    return TopicOut.model_validate(topic)


@router.get("/{code}/messages")
async def topic_messages(code: str, session: SessionDep, user: StaffUser, limit: int = 200) -> dict:
    from app.models.message import Message

    topic = (await session.execute(select(Topic).where(Topic.code == code))).scalar_one_or_none()
    if topic is None:
        raise HTTPException(404, "Topic not found")
    rows = (
        await session.execute(
            select(Message).where(Message.topic_id == topic.id).order_by(Message.id).limit(limit)
        )
    ).scalars().all()
    return {
        "code": topic.code,
        "count": len(rows),
        "messages": [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "type": m.content_type,
                "text": m.text or m.caption,
                "has_media": m.has_media,
                "at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ],
    }


@router.post("/{code}/freeze", response_model=TopicOut)
async def freeze(code: str, session: SessionDep, user: StaffUser, body: TopicActionRequest) -> TopicOut:
    service = TopicService(session, _gateway())
    topic = await service.by_code(code)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    try:
        await service.freeze(topic, user, body.reason)
    except TopicError as exc:
        raise HTTPException(409, str(exc)) from exc
    return TopicOut.model_validate(topic)


@router.post("/{code}/block", response_model=TopicOut)
async def block(code: str, session: SessionDep, user: StaffUser, body: TopicActionRequest) -> TopicOut:
    service = TopicService(session, _gateway())
    topic = await service.by_code(code)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    await service.block(topic, user)
    await service.schedule_deletion(topic)
    return TopicOut.model_validate(topic)


@router.post("/{code}/restore", response_model=TopicOut)
async def restore(code: str, session: SessionDep, user: StaffUser, body: TopicActionRequest) -> TopicOut:
    service = TopicService(session, _gateway())
    topic = await service.by_code(code)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    try:
        await service.restore(topic, user)
    except TopicError as exc:
        raise HTTPException(409, str(exc)) from exc
    return TopicOut.model_validate(topic)


@router.post("/{code}/archive", response_model=TopicOut)
async def archive(code: str, session: SessionDep, user: StaffUser, body: TopicActionRequest) -> TopicOut:
    service = TopicService(session, _gateway())
    topic = await service.by_code(code)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    try:
        await service.archive(topic, user)
    except TopicError as exc:
        raise HTTPException(409, str(exc)) from exc
    return TopicOut.model_validate(topic)


@router.delete("/{code}")
async def delete(code: str, session: SessionDep, user: AdminUser) -> dict:
    service = TopicService(session, _gateway())
    topic = await service.by_code(code)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    deleted = await service.hard_delete(topic, user)
    return {"code": code, "telegram_topic_deleted": deleted}


@router.get("/{code}/archive")
async def download_archive(code: str, session: SessionDep, user: StaffUser) -> FileResponse:
    """TZ 20 — build and stream the export bundle."""
    service = TopicService(session, _gateway())
    topic = await service.by_code(code)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    result = await ArchiveService(session).export(topic, user)
    return FileResponse(
        result.path,
        media_type="application/zip",
        filename=f"soulchat-{topic.code}.zip",
        headers={"X-Archive-Checksum": result.checksum},
    )
