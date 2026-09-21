"""Outbound bot notifications (TZ 24).

Rows are always persisted; delivery happens when a gateway is available so a
Telegram outage never loses an event.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.enums import NotificationKind, NotificationStatus
from app.models.log import Notification
from app.models.topic import Topic
from app.models.user import User
from app.services.telegram_gateway import TelegramGateway

logger = get_logger(__name__)


class NotificationService:
    def __init__(self, session: AsyncSession, gateway: TelegramGateway | None = None) -> None:
        self.session = session
        self.gateway = gateway

    async def notify(
        self,
        user: User,
        kind: NotificationKind | str,
        *,
        title: str | None = None,
        body: str = "",
        topic: Topic | None = None,
        payload: dict | None = None,
        deliver: bool = True,
    ) -> Notification:
        row = Notification(
            user_id=user.id,
            topic_id=topic.id if topic else None,
            kind=str(getattr(kind, "value", kind)),
            title=title,
            body=body,
            payload=payload,
        )
        self.session.add(row)
        await self.session.flush()

        if deliver and self.gateway is not None:
            text = f"*{title}*\n{body}".strip() if title else body
            try:
                message_id = await self.gateway.send_message(user.tg_id, text)
                row.tg_message_id = message_id
                row.status = NotificationStatus.SENT.value
                row.sent_at = datetime.now(UTC)
            except Exception as exc:  # pragma: no cover - transport failure
                logger.warning("notification delivery failed user=%s: %s", user.tg_id, exc)
                row.status = NotificationStatus.FAILED.value
                row.error = str(exc)[:500]
            await self.session.flush()
        return row
