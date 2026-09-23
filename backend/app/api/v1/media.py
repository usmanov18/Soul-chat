"""Media library endpoint (TZ 28: Media).

Read-only listing for the admin panel: every file the couples sent, joined
with the topic code so the panel can show a recognizable label instead of a
bare foreign key.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import SessionDep, StaffUser
from app.models.message import Media
from app.models.topic import Topic

router = APIRouter(prefix="/media", tags=["media"])


@router.get("")
async def list_media(
    session: SessionDep,
    user: StaffUser,
    topic_code: str | None = None,
    kind: str | None = None,
    nsfw: bool | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> dict:
    stmt = select(Media, Topic.code).join(Topic, Media.topic_id == Topic.id)
    count_stmt = (
        select(func.count())
        .select_from(Media)
        .join(Topic, Media.topic_id == Topic.id)
    )
    if topic_code:
        stmt = stmt.where(Topic.code == topic_code)
        count_stmt = count_stmt.where(Topic.code == topic_code)
    if kind:
        stmt = stmt.where(Media.kind == kind)
        count_stmt = count_stmt.where(Media.kind == kind)
    if nsfw is not None:
        stmt = stmt.where(Media.nsfw.is_(nsfw))
        count_stmt = count_stmt.where(Media.nsfw.is_(nsfw))

    total = await session.scalar(count_stmt)
    rows = (
        (await session.execute(stmt.order_by(Media.id.desc()).limit(limit).offset(offset)))
        .all()
    )
    return {
        "total": int(total or 0),
        "items": [
            {
                "id": media.id,
                "topic_code": code,
                "kind": media.kind,
                "file_id": media.file_id,
                "file_size": media.file_size,
                "width": media.width,
                "height": media.height,
                "duration": media.duration,
                "mime_type": media.mime_type,
                "caption": media.caption,
                "published_to_channel": media.published_to_channel,
                "nsfw": media.nsfw,
                "nsfw_score": media.nsfw_score,
                "created_at": media.created_at.isoformat() if media.created_at else None,
            }
            for media, code in rows
        ],
    }
