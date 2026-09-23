"""Channel post listing (TZ 28: Channel Posts, TZ 15 gallery)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import SessionDep, StaffUser
from app.models.message import ChannelPost
from app.models.topic import Topic

router = APIRouter(prefix="/channel-posts", tags=["channel"])


@router.get("")
async def list_channel_posts(
    session: SessionDep,
    user: StaffUser,
    kind: str | None = None,
    topic_code: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> dict:
    # topic_id is nullable (SET NULL on topic delete), so an outer join keeps
    # orphaned posts visible in the panel instead of silently hiding them.
    stmt = select(ChannelPost, Topic.code).outerjoin(Topic, ChannelPost.topic_id == Topic.id)
    count_stmt = (
        select(func.count())
        .select_from(ChannelPost)
        .outerjoin(Topic, ChannelPost.topic_id == Topic.id)
    )
    if kind:
        stmt = stmt.where(ChannelPost.kind == kind)
        count_stmt = count_stmt.where(ChannelPost.kind == kind)
    if topic_code:
        stmt = stmt.where(Topic.code == topic_code)
        count_stmt = count_stmt.where(Topic.code == topic_code)

    total = await session.scalar(count_stmt)
    rows = (
        (await session.execute(stmt.order_by(ChannelPost.id.desc()).limit(limit).offset(offset)))
        .all()
    )
    return {
        "total": int(total or 0),
        "items": [
            {
                "id": post.id,
                "topic_code": code,
                "kind": post.kind,
                "tg_message_id": post.tg_message_id,
                "text": post.text,
                "template": post.template,
                "media_file_ids": post.media_file_ids,
                "published_at": post.published_at.isoformat() if post.published_at else None,
                "failed_reason": post.failed_reason,
                "created_at": post.created_at.isoformat() if post.created_at else None,
            }
            for post, code in rows
        ],
    }
