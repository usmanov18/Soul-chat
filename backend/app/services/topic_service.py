"""Topic lifecycle: create, block, delete-pending, restore, archive, delete.

Every state change goes through :meth:`transition`, which enforces
:data:`app.enums.TopicStatusFlow` so no illegal jump (e.g. ``deleted ->
active``) can ever reach the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.enums import (
    AuditAction,
    NotificationKind,
    ParticipantRole,
    ParticipantStatus,
    TopicStatus,
    TopicStatusFlow,
)
from app.models.topic import Topic, TopicParticipant
from app.models.user import User
from app.core.timeutil import utcnow
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.telegram_gateway import TelegramGateway
from app.services.topic_code import TopicCodeGenerator

logger = get_logger(__name__)


class TopicError(Exception):
    """Raised for business rule violations that must reach the user."""


@dataclass
class CreatedTopic:
    topic: Topic
    code: str
    display: str
    thread_id: int | None


class TopicService:
    def __init__(self, session: AsyncSession, gateway: TelegramGateway) -> None:
        self.session = session
        self.gateway = gateway
        self.codes = TopicCodeGenerator(session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    # ------------------------------------------------------------------
    async def can_create(self, tg_id: int) -> tuple[bool, str]:
        user = await self.user_by_tg(tg_id)
        if user is None:
            return False, "Foydalanuvchi topilmadi."
        if user.is_banned:
            return False, "Siz bloklangansiz, suhbat yarata olmaysiz."
        active = (
            await self.session.execute(
                select(func.count())
                .select_from(Topic)
                .where(Topic.owner_id == user.id, Topic.status.in_(self.OPEN_STATES))
            )
        ).scalar_one()
        if int(active) >= settings.max_topics_per_user:
            return False, f"Sizda allaqachon {active} ta faol suhbat bor (limit {settings.max_topics_per_user})."
        return True, "ok"

    OPEN_STATES: tuple[str, ...] = (
        TopicStatus.ACTIVE.value,
        TopicStatus.FROZEN.value,
        TopicStatus.DELETE_PENDING.value,
    )

    # ------------------------------------------------------------------
    async def create(self, tg_id: int) -> CreatedTopic:
        """Create the Telegram forum topic + local row (TZ 6, 10, 11)."""
        ok, reason = await self.can_create(tg_id)
        if not ok:
            raise TopicError(reason)

        user = await self.user_by_tg(tg_id)
        assert user is not None  # guarded by can_create

        generated = await self.codes.next_code(user.gender)
        chat_id = settings.forum_chat_id or 0
        thread_id = await self.gateway.create_forum_topic(
            chat_id, generated.code, icon_color=settings.topic_icon_color
        )

        topic = Topic(
            code=generated.code,
            title=generated.code,  # TZ 10: the topic name is *only* the code
            chat_id=chat_id,
            message_thread_id=thread_id,
            owner_id=user.id,
            owner_tg_id=user.tg_id,
            status=TopicStatus.ACTIVE.value,
            icon_color=settings.topic_icon_color,
            reactions_enabled=settings.reactions_enabled,
            forward_enabled=settings.forward_enabled,
            copy_enabled=settings.copy_enabled,
        )
        self.session.add(topic)
        await self.session.flush()

        self.session.add(
            TopicParticipant(
                topic_id=topic.id,
                user_id=user.id,
                role=ParticipantRole.OWNER.value,
                status=ParticipantStatus.ACTIVE.value,
                joined_at=datetime.now(UTC),
            )
        )
        user.topics_created = (user.topics_created or 0) + 1
        user.last_active_topic_id = topic.id

        await self.audit.log(
            AuditAction.TOPIC_CREATE,
            actor=user,
            topic=topic,
            message=f"created topic {topic.code}",
            source="bot",
        )
        await self.notifications.notify(
            user,
            NotificationKind.TOPIC_CREATED,
            title=f"Suhbat yaratildi — {topic.code}",
            body=(
                f"{generated.display}\n\n"
                "Siz egasisiz. Sherigingizni /invite bilan taklif qiling.\n"
                "Xabarlarni shu botga yozing — ular suhbatga chiqadi."
            ),
            topic=topic,
        )
        await self.session.flush()
        return CreatedTopic(topic=topic, code=generated.code, display=generated.display, thread_id=thread_id)

    # ------------------------------------------------------------------
    async def block(self, topic: Topic, actor: User | None = None) -> Topic:
        """Both users confirmed the close code -> topic is blocked (TZ 17)."""
        topic.status = TopicStatus.BLOCKED.value
        topic.is_closed = True
        topic.closed_at = utcnow()
        if topic.message_thread_id:
            await self.gateway.close_forum_topic(topic.chat_id, topic.message_thread_id)
        await self.audit.log(AuditAction.TOPIC_BLOCK, actor=actor, topic=topic, message="topic blocked")
        await self._notify_both(topic, NotificationKind.DELETE_PENDING, "Suhbat yopildi")
        return topic

    async def schedule_deletion(self, topic: Topic) -> datetime:
        """Move to DELETE_PENDING and arm the 96h timer (TZ 18)."""
        delete_at = utcnow() + timedelta(hours=settings.delete_pending_hours)
        await self.transition(topic, TopicStatus.DELETE_PENDING)
        topic.delete_at = delete_at
        await self.audit.log(
            AuditAction.TOPIC_DELETE,
            actor=None,
            topic=topic,
            message=f"delete scheduled at {delete_at.isoformat()}",
            source="task",
        )
        await self._notify_both(
            topic,
            NotificationKind.DELETE_PENDING,
            "Suhbat o'chirilishi kutilmoqda",
            body=f"{settings.delete_pending_hours} soat ichida /restore bosmasangiz, suhbat o'chadi.",
        )
        return delete_at

    async def restore(self, topic: Topic, actor: User | None = None) -> Topic:
        """Restore inside the 96h window (TZ 19)."""
        if topic.status == TopicStatus.DELETED.value:
            raise TopicError("Suhbat allaqachon o'chirilgan.")
        await self.transition(topic, TopicStatus.ACTIVE)
        topic.delete_at = None
        topic.is_closed = False
        topic.closed_at = None
        topic.restore_count = (topic.restore_count or 0) + 1
        if topic.message_thread_id:
            await self.gateway.reopen_forum_topic(topic.chat_id, topic.message_thread_id)
        await self.audit.log(AuditAction.TOPIC_RESTORE, actor=actor, topic=topic, message="topic restored")
        await self._notify_both(topic, NotificationKind.RESTORED, "Suhbat tiklandi")
        return topic

    async def freeze(self, topic: Topic, actor: User | None = None, reason: str = "") -> Topic:
        await self.transition(topic, TopicStatus.FROZEN)
        await self.audit.log(
            AuditAction.TOPIC_FREEZE, actor=actor, topic=topic, message=f"frozen: {reason}"
        )
        return topic

    async def archive(self, topic: Topic, actor: User | None = None) -> Topic:
        await self.transition(topic, TopicStatus.ARCHIVED)
        topic.is_closed = True
        if topic.message_thread_id:
            await self.gateway.close_forum_topic(topic.chat_id, topic.message_thread_id)
        await self.audit.log(AuditAction.TOPIC_ARCHIVE, actor=actor, topic=topic, message="archived")
        await self._notify_both(topic, NotificationKind.ARCHIVED, "Suhbat arxivlandi")
        return topic

    async def hard_delete(self, topic: Topic, actor: User | None = None) -> bool:
        """Archive + delete the Telegram topic. Called by the 96h sweeper."""
        topic.status = TopicStatus.DELETED.value
        topic.deleted_at = utcnow()
        topic.is_closed = True
        deleted = False
        if topic.message_thread_id:
            deleted = await self.gateway.delete_forum_topic(topic.chat_id, topic.message_thread_id)
        await self.audit.log(
            AuditAction.TOPIC_DELETE,
            actor=actor,
            topic=topic,
            message=f"hard delete (telegram_deleted={deleted})",
            source="task",
        )
        return deleted

    # ------------------------------------------------------------------
    async def transition(self, topic: Topic, target: TopicStatus) -> None:
        current = TopicStatus(topic.status)
        if current is target:
            return
        if not TopicStatusFlow.can(current, target):
            raise TopicError(f"{current.value} -> {target.value} holat o'tishi ruxsat etilmagan.")
        topic.status = target.value

    # ------------------------------------------------------------------
    async def by_code(self, code: str) -> Topic | None:
        return (
            await self.session.execute(select(Topic).where(func.upper(Topic.code) == code.upper()))
        ).scalar_one_or_none()

    async def user_by_tg(self, tg_id: int) -> User | None:
        return (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()

    async def _notify_both(
        self, topic: Topic, kind: NotificationKind, title: str, body: str = ""
    ) -> None:
        for user_id in (topic.owner_id, topic.partner_id):
            if not user_id:
                continue
            user = await self.session.get(User, user_id)
            if user:
                await self.notifications.notify(user, kind, title=title, body=body, topic=topic)
