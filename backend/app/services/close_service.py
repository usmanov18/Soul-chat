"""Two sided chat closing (TZ 17) and restore requests (TZ 19).

Flow: either writer presses "close chat" -> the bot generates a 6 digit code and
sends it to **both** of them -> each of them submits the code -> when both
confirmations are in, the topic goes to ``blocked`` and the 96h deletion timer
starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import random_numeric_code
from app.core.timeutil import is_future, utcnow
from app.enums import (
    AuditAction,
    CloseCodeStatus,
    NotificationKind,
    RestoreStatus,
    Role,
    TopicStatus,
)
from app.models.topic import CloseCode, RestoreRequest, Topic
from app.models.user import User
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.topic_service import TopicService

logger = get_logger(__name__)


class CloseError(Exception):
    pass


@dataclass
class ConfirmationState:
    completed: bool
    both_confirmed: bool
    owner_confirmed: bool
    partner_confirmed: bool
    code: CloseCode


@dataclass
class StartResult:
    """``completed=True`` means the chat closed immediately (no partner yet)."""

    completed: bool
    code: CloseCode | None
    message: str


class CloseService:
    def __init__(self, session: AsyncSession, topic_service: TopicService) -> None:
        self.session = session
        self.topics = topic_service
        self.audit = AuditService(session)
        self.notifications = NotificationService(session, topic_service.gateway)

    # ------------------------------------------------------------------
    async def start(self, topic: Topic, actor: User) -> StartResult:
        if actor.id not in (topic.owner_id, topic.partner_id):
            raise CloseError("Faqat suhbat egasi yoki sherigi chatni yopa oladi.")
        if topic.partner_id is None:
            # no partner yet — closing is instant, nobody else has to agree
            await self.topics.block(topic, actor)
            await self.topics.schedule_deletion(topic)
            return StartResult(
                completed=True,
                code=None,
                message=(
                    f"Suhbat {topic.code} yopildi.\n"
                    f"{settings.delete_pending_hours} soat ichida /restore bosmasangiz, u o'chadi."
                ),
            )

        existing = (
            await self.session.execute(
                select(CloseCode)
                .where(CloseCode.topic_id == topic.id, CloseCode.status == CloseCodeStatus.PENDING.value)
                .order_by(CloseCode.id.desc())
            )
        ).scalars().first()
        if existing and self._fresh(existing):
            return StartResult(
                completed=False,
                code=existing,
                message=f"Kod allaqachon yuborilgan: {existing.code}",
            )

        close_code = CloseCode(
            topic_id=topic.id,
            code=random_numeric_code(settings.close_code_length),
            created_by=actor.id,
            expires_at=utcnow() + timedelta(minutes=settings.close_code_ttl_minutes),
        )
        self.session.add(close_code)
        await self.session.flush()

        owner = await self.session.get(User, topic.owner_id)
        partner = await self.session.get(User, topic.partner_id)
        topic.close_code = close_code.code
        for user in (owner, partner):
            if user:
                await self.notifications.notify(
                    user,
                    NotificationKind.DELETE_PENDING,
                    title="Suhbatni yopish tasdiqlanishi kerak",
                    body=(
                        f"Suhbat {topic.code} yopilishi uchun ikkala tomon ham "
                        f"{close_code.code} kodini kiritishi kerak.\n"
                        f"/confirm {close_code.code}"
                    ),
                    topic=topic,
                )
        await self.audit.log(
            AuditAction.TOPIC_CLOSE, actor=actor, topic=topic, message="close code issued"
        )
        return StartResult(
            completed=False,
            code=close_code,
            message=(
                f"Yopish kodi: {close_code.code}\n"
                "Ikkala ishtirokchi ham shu kodni kiritishi kerak:\n"
                f"/confirm {close_code.code}"
            ),
        )

    # ------------------------------------------------------------------
    async def confirm(self, topic: Topic, actor: User, code: str) -> ConfirmationState:
        close_code = (
            await self.session.execute(
                select(CloseCode)
                .where(CloseCode.topic_id == topic.id, CloseCode.status == CloseCodeStatus.PENDING.value)
                .order_by(CloseCode.id.desc())
            )
        ).scalars().first()
        if close_code is None:
            raise CloseError("Faol yopish so'rovi yo'q. /close bilan qayta boshlang.")
        if not self._fresh(close_code):
            close_code.status = CloseCodeStatus.EXPIRED.value
            raise CloseError("Kod muddati tugagan. /close bilan yangi kod oling.")
        if close_code.code != code.strip():
            raise CloseError("Kod noto'g'ri.")
        if actor.id not in (topic.owner_id, topic.partner_id):
            raise CloseError("Siz bu suhbatning ishtirokchisi emassiz.")

        if actor.id == topic.owner_id:
            close_code.owner_confirmed = True
        else:
            close_code.partner_confirmed = True
        await self.session.flush()

        both = close_code.owner_confirmed and close_code.partner_confirmed
        if both:
            close_code.status = CloseCodeStatus.CONFIRMED.value
            close_code.confirmed_at = utcnow()
            await self.topics.block(topic, actor)
            await self.topics.schedule_deletion(topic)
            await self.session.flush()

        return ConfirmationState(
            completed=both,
            both_confirmed=both,
            owner_confirmed=close_code.owner_confirmed,
            partner_confirmed=close_code.partner_confirmed,
            code=close_code,
        )

    # ------------------------------------------------------------------
    async def request_restore(self, topic: Topic, actor: User, reason: str = "") -> RestoreRequest:
        if topic.status == TopicStatus.DELETED.value:
            raise CloseError("Suhbat allaqachon o'chirilgan, tiklab bo'lmaydi.")
        row = RestoreRequest(
            topic_id=topic.id,
            requested_by=actor.id,
            reason=reason,
            expires_at=topic.delete_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def approve_restore(self, request: RestoreRequest, actor: User) -> Topic:
        is_staff = actor.role in {Role.MODERATOR.value, Role.ADMIN.value, Role.SUPER_ADMIN.value}
        topic = await self.session.get(Topic, request.topic_id)
        if topic is None:
            raise CloseError("Suhbat topilmadi.")
        if not is_staff and actor.id not in (topic.owner_id, topic.partner_id):
            raise CloseError("Faqat ishtirokchilar yoki admin tiklay oladi.")
        if topic.delete_at and not is_future(topic.delete_at):
            request.status = RestoreStatus.EXPIRED.value
            raise CloseError("96 soatlik oyna yopildi.")

        request.status = RestoreStatus.APPROVED.value
        request.decided_by = actor.id
        request.decided_at = datetime.now(UTC)
        return await self.topics.restore(topic, actor)

    @staticmethod
    def _fresh(close_code: CloseCode) -> bool:
        return is_future(close_code.expires_at)
