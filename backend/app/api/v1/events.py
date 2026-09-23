"""Event listing endpoint (TZ 28: Events)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import SessionDep, StaffUser
from app.models.message import Event
from app.models.topic import Topic

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def list_events(
    session: SessionDep,
    user: StaffUser,
    topic_code: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> dict:
    stmt = select(Event, Topic.code).join(Topic, Event.topic_id == Topic.id)
    count_stmt = (
        select(func.count())
        .select_from(Event)
        .join(Topic, Event.topic_id == Topic.id)
    )
    if topic_code:
        stmt = stmt.where(Topic.code == topic_code)
        count_stmt = count_stmt.where(Topic.code == topic_code)
    if kind:
        stmt = stmt.where(Event.kind == kind)
        count_stmt = count_stmt.where(Event.kind == kind)
    if status:
        stmt = stmt.where(Event.status == status)
        count_stmt = count_stmt.where(Event.status == status)

    total = await session.scalar(count_stmt)
    rows = (
        (await session.execute(stmt.order_by(Event.id.desc()).limit(limit).offset(offset)))
        .all()
    )
    return {
        "total": int(total or 0),
        "items": [
            {
                "id": event.id,
                "topic_code": code,
                "kind": event.kind,
                "title": event.title,
                "description": event.description,
                "due_at": event.due_at.isoformat() if event.due_at else None,
                "remind_at": event.remind_at.isoformat() if event.remind_at else None,
                "location": event.location,
                "checklist": event.checklist,
                "status": event.status,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event, code in rows
        ],
    }
