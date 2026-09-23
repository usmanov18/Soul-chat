"""Public stats endpoint (docs/07 D7).

One small, anonymous, cache-friendly payload the channel can quote: is this
place alive? No names, no codes — just counts. Reachable without a token so a
landing page or bot description link can embed it; the API rate limiter still
applies.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.enums import TopicStatus
from app.models.message import Message
from app.models.topic import Topic
from app.models.user import User

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/public")
async def public_stats(session: SessionDep) -> dict:
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = datetime.now(UTC) - timedelta(days=7)

    total_users = await session.scalar(select(func.count()).select_from(User))
    new_topics_today = await session.scalar(
        select(func.count())
        .select_from(Topic)
        .where(Topic.created_at >= day_start)
    )
    active_topics = await session.scalar(
        select(func.count())
        .select_from(Topic)
        .where(Topic.status == TopicStatus.ACTIVE.value)
    )
    messages_today = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.created_at >= day_start)
    )
    messages_week = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.created_at >= week_ago)
    )
    couples = await session.scalar(
        select(func.count())
        .select_from(Topic)
        .where(Topic.partner_id.is_not(None))
    )
    return {
        "users": int(total_users or 0),
        "couples": int(couples or 0),
        "new_topics_today": int(new_topics_today or 0),
        "active_topics": int(active_topics or 0),
        "messages_today": int(messages_today or 0),
        "messages_week": int(messages_week or 0),
        "generated_at": datetime.now(UTC).isoformat(),
    }
