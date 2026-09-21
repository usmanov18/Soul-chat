"""Partner invitations (TZ 12).

One topic, at most two writers. The owner generates a single use link
``https://t.me/<bot>?start=inv_<token>``; the partner opens it, confirms, and
only then gets write access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import random_token
from app.core.timeutil import is_future, utcnow
from app.enums import (
    AuditAction,
    InviteStatus,
    NotificationKind,
    ParticipantRole,
    ParticipantStatus,
)
from app.models.topic import Invite, Topic, TopicParticipant
from app.models.user import User
from app.services.audit import AuditService
from app.services.notification import NotificationService


class InviteError(Exception):
    pass


@dataclass
class CreatedInvite:
    invite: Invite
    url: str


class InviteService:
    def __init__(self, session: AsyncSession, bot_username: str = "SoulChatBot") -> None:
        self.session = session
        self.bot_username = bot_username
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    # ------------------------------------------------------------------
    async def create(self, topic: Topic, owner: User) -> CreatedInvite:
        if topic.owner_id != owner.id:
            raise InviteError("Faqat suhbat egasi sherik taklif qila oladi.")
        if topic.partner_id:
            raise InviteError("Bu suhbatta allaqachon sherik bor.")

        token = random_token(18)
        invite = Invite(
            topic_id=topic.id,
            inviter_id=owner.id,
            token=token,
            max_uses=1,
            expires_at=utcnow() + timedelta(hours=settings.invite_ttl_hours),
        )
        self.session.add(invite)
        await self.audit.log(
            AuditAction.PARTNER_INVITE, actor=owner, topic=topic, message=f"invite {token[:8]}…"
        )
        await self.session.flush()
        return CreatedInvite(invite=invite, url=self.link_for(token))

    def link_for(self, token: str) -> str:
        return f"{settings.bot_invite_base}/{self.bot_username}?start=inv_{token}"

    # ------------------------------------------------------------------
    async def accept(self, token: str, user: User) -> Topic:
        invite = (
            await self.session.execute(select(Invite).where(Invite.token == token))
        ).scalar_one_or_none()
        if invite is None:
            raise InviteError("Taklif topilmadi.")
        if invite.status != InviteStatus.PENDING.value:
            raise InviteError("Bu taklif allaqachon ishlatilgan yoki bekor qilingan.")
        if not is_future(invite.expires_at):
            invite.status = InviteStatus.EXPIRED.value
            raise InviteError("Taklif muddati tugagan.")

        topic = await self.session.get(Topic, invite.topic_id)
        if topic is None:
            raise InviteError("Suhbat topilmadi.")
        if topic.owner_id == user.id:
            raise InviteError("Siz bu suhbatning egasisiz — sherik bo'la olmaysiz.")
        if topic.partner_id:
            raise InviteError("Bu suhbatta sherik o'rni band.")

        # one partner per user, per TZ: only a single partner slot exists
        topic.partner_id = user.id
        topic.partner_tg_id = user.tg_id
        invite.status = InviteStatus.ACCEPTED.value
        invite.uses += 1
        invite.accepted_by = user.id
        invite.accepted_at = utcnow()

        self.session.add(
            TopicParticipant(
                topic_id=topic.id,
                user_id=user.id,
                role=ParticipantRole.PARTNER.value,
                status=ParticipantStatus.ACTIVE.value,
                joined_at=utcnow(),
            )
        )
        user.last_active_topic_id = topic.id

        owner = await self.session.get(User, topic.owner_id)
        if owner:
            await self.notifications.notify(
                owner,
                NotificationKind.PARTNER_JOINED,
                title="Sherik qo'shildi",
                body=f"{user.full_name} suhbatga qo'shildi. Endi ikkovingiz yoza olasiz.",
                topic=topic,
            )
        await self.notifications.notify(
            user,
            NotificationKind.PARTNER_JOINED,
            title=f"Siz {topic.code} suhbatiga qo'shildingiz",
            body="Xabarlaringizni shu botga yozing — ular suhbatga chiqadi.",
            topic=topic,
        )
        await self.audit.log(AuditAction.PARTNER_ACCEPT, actor=user, topic=topic, message="invite accepted")
        await self.session.flush()
        return topic

    # ------------------------------------------------------------------
    async def revoke(self, invite: Invite, actor: User) -> None:
        invite.status = InviteStatus.REVOKED.value
        await self.audit.log(AuditAction.PARTNER_LEAVE, actor=actor, message="invite revoked")

    async def leave(self, topic: Topic, user: User) -> None:
        if topic.partner_id != user.id:
            raise InviteError("Siz bu suhbatning sherigi emassiz.")
        topic.partner_id = None
        topic.partner_tg_id = None
        participant = (
            await self.session.execute(
                select(TopicParticipant).where(
                    TopicParticipant.topic_id == topic.id, TopicParticipant.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if participant:
            participant.status = ParticipantStatus.LEFT.value
            participant.left_at = utcnow()
        owner = await self.session.get(User, topic.owner_id)
        if owner:
            await self.notifications.notify(
                owner,
                NotificationKind.PARTNER_LEFT,
                title="Sherik chiqib ketdi",
                body=f"{user.full_name} suhbatni tark etdi.",
                topic=topic,
            )
        await self.audit.log(AuditAction.PARTNER_LEAVE, actor=user, topic=topic, message="partner left")
