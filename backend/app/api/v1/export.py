"""Data export for operators (TZ 28: Export).

CSV for spreadsheets, JSON for tooling. Rows are streamed, and every entity has
a hard row ceiling so a fat-fingered request cannot serialize the whole table
into memory.
"""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import SessionDep, StaffUser
from app.models.message import Message
from app.models.topic import Topic
from app.models.user import User

router = APIRouter(prefix="/export", tags=["export"])

LIMIT = Query(default=1000, le=10_000)


def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _json_response(payload: list[dict], filename: str) -> Response:
    return Response(
        content=json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/users")
async def export_users(
    session: SessionDep, user: StaffUser, fmt: str = "csv", limit: int = LIMIT
) -> Response:
    rows = (await session.execute(select(User).order_by(User.id).limit(limit))).scalars().all()
    if fmt == "json":
        return _json_response(
            [
                {
                    "id": u.id,
                    "tg_id": u.tg_id,
                    "username": u.username,
                    "first_name": u.first_name,
                    "role": u.role,
                    "gender": u.gender,
                    "is_banned": u.is_banned,
                    "is_muted": u.is_muted,
                    "warns": u.warns,
                    "messages_sent": u.messages_sent,
                    "topics_created": u.topics_created,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in rows
            ],
            "users.json",
        )
    return _csv_response(
        "users.csv",
        ["id", "tg_id", "username", "first_name", "role", "gender", "is_banned", "is_muted",
         "warns", "messages_sent", "topics_created", "created_at"],
        [
            [u.id, u.tg_id, u.username or "", u.first_name or "", u.role, u.gender,
             u.is_banned, u.is_muted, u.warns, u.messages_sent, u.topics_created,
             u.created_at.isoformat() if u.created_at else ""]
            for u in rows
        ],
    )


@router.get("/topics")
async def export_topics(
    session: SessionDep, user: StaffUser, fmt: str = "csv", limit: int = LIMIT
) -> Response:
    rows = (await session.execute(select(Topic).order_by(Topic.id).limit(limit))).scalars().all()
    if fmt == "json":
        return _json_response(
            [
                {
                    "id": t.id,
                    "code": t.code,
                    "status": t.status,
                    "owner_tg_id": t.owner_tg_id,
                    "partner_tg_id": t.partner_tg_id,
                    "message_count": t.message_count,
                    "media_count": t.media_count,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in rows
            ],
            "topics.json",
        )
    return _csv_response(
        "topics.csv",
        ["id", "code", "status", "owner_tg_id", "partner_tg_id", "message_count",
         "media_count", "created_at"],
        [
            [t.id, t.code, t.status, t.owner_tg_id, t.partner_tg_id, t.message_count,
             t.media_count, t.created_at.isoformat() if t.created_at else ""]
            for t in rows
        ],
    )


@router.get("/messages")
async def export_messages(
    session: SessionDep, user: StaffUser, fmt: str = "csv", limit: int = LIMIT
) -> Response:
    rows = (
        (await session.execute(select(Message).order_by(Message.id).limit(limit)))
        .scalars()
        .all()
    )
    if fmt == "json":
        return _json_response(
            [
                {
                    "id": m.id,
                    "topic_id": m.topic_id,
                    "sender_id": m.sender_id,
                    "content_type": m.content_type,
                    "text": (m.text or m.caption or "")[:500],
                    "has_media": m.has_media,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in rows
            ],
            "messages.json",
        )
    return _csv_response(
        "messages.csv",
        ["id", "topic_id", "sender_id", "content_type", "text", "has_media", "created_at"],
        [
            [m.id, m.topic_id, m.sender_id, m.content_type, (m.text or m.caption or "")[:500],
             m.has_media, m.created_at.isoformat() if m.created_at else ""]
            for m in rows
        ],
    )
