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

    async def birthdays_today(self, now: datetime | None = None) -> list[User]:
        """Users whose birthday is today (UTC month/day)."""
        from sqlalchemy import func, select

        now = now or datetime.now(UTC)
        stmt = select(User).where(
            func.extract("month", User.birthday) == now.month,
            func.extract("day", User.birthday) == now.day,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def birthday_sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Congratulate today's birthdays once (TZ 24: Birthday)."""
        from sqlalchemy import func, select

        from app.enums import NotificationKind, NotificationStatus

        now = now or datetime.now(UTC)
        users = await self.birthdays_today(now)
        sent = 0
        for user in users:
            already = await self.session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user.id,
                    Notification.kind == NotificationKind.BIRTHDAY.value,
                    Notification.status != NotificationStatus.FAILED.value,
                    func.date(Notification.created_at) == now.date(),
                )
            )
            if already:
                continue
            await self.notify(
                user,
                NotificationKind.BIRTHDAY,
                title="🎉 Tug'ilgan kuningiz bilan!",
                body="Bugun sizning kuningiz. Yorqin kunlar tilaymiz!",
            )
            sent += 1
        return {"birthdays": len(users), "congratulated": sent}
