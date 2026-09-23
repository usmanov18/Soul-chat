"""Audit log writer (TZ 32)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AuditAction
from app.models.log import AuditLog
from app.models.topic import Topic
from app.models.user import User


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        action: AuditAction | str,
        *,
        actor: User | None = None,
        topic: Topic | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        ip_address: str | None = None,
        device: str | None = None,
        user_agent: str | None = None,
        source: str = "bot",
        message: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AuditLog:
        row = AuditLog(
            actor_id=actor.id if actor else None,
            actor_tg_id=actor.tg_id if actor else None,
            action=str(getattr(action, "value", action)),
            entity_type=entity_type or (type(topic).__name__ if topic else None),
            entity_id=entity_id or (topic.id if topic else None),
            topic_id=topic.id if topic else None,
            ip_address=ip_address,
            device=device,
            user_agent=user_agent,
            source=source,
            message=message,
            meta=meta,
        )
        self.session.add(row)
        await self.session.flush()
        return row