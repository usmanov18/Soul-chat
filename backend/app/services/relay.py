"""Relay engine — the mechanism that makes "only two people can write" real.

Why this exists
---------------
Telegram's Bot API has **no per-topic permissions**. ``ChatPermissions`` is a
group-wide structure and a closed forum topic is writable *only* by admins with
``can_manage_topics`` — there is no way to say "in topic A-001 only users X and
Y may post". Verified against aiogram 3.31 (``ChatPermissions`` fields) and the
Bot API docs for ``closeForumTopic`` / ``createForumTopic``.

So the platform locks the group instead and relays:

1. On startup :meth:`enforce_group_lockdown` sets ``can_send_messages=False``
   (plus every media permission) for all members, so the forum is read-only for
   everyone except admins — the bot is an admin.
2. The owner and the partner of a topic talk to the bot in DM (or via inline
   mode inside the topic). :meth:`relay_private` checks that they are one of the
   two writers and re-posts their message into the topic, attributed to them.
3. :meth:`moderate_group_message` deletes anything that still reaches the group
   from a non-writer (belt and braces — it should not happen once locked).

The net effect is exactly the product requirement: everybody reads the topic,
exactly two people can write to it, and no MTProto userbot is needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.cache import cache
from app.core.config import settings
from app.core.logging import get_logger
from app.enums import MessageContentType, ModerationAction, TopicStatus
from app.models.message import Media, Message
from app.models.topic import Topic
from app.models.user import User
from app.services.telegram_gateway import TelegramGateway

logger = get_logger(__name__)

# Permissions we strip from ordinary members of the forum supergroup.
LOCKDOWN_PERMISSIONS: dict[str, bool] = {
    "can_send_messages": False,
    "can_send_audios": False,
    "can_send_documents": False,
    "can_send_photos": False,
    "can_send_videos": False,
    "can_send_video_notes": False,
    "can_send_voice_notes": False,
    "can_send_polls": False,
    "can_send_other_messages": False,
    "can_add_web_page_previews": False,
    "can_change_info": False,
    "can_invite_users": False,
    "can_pin_messages": False,
    "can_manage_topics": False,
}

# content_type -> gateway method name
_MEDIA_METHOD: dict[str, str] = {
    MessageContentType.PHOTO.value: "send_photo",
    MessageContentType.VIDEO.value: "send_video",
    MessageContentType.VOICE.value: "send_voice",
    MessageContentType.DOCUMENT.value: "send_document",
    MessageContentType.AUDIO.value: "send_audio",
    MessageContentType.ANIMATION.value: "send_animation",
    MessageContentType.STICKER.value: "send_sticker",
    MessageContentType.VIDEO_NOTE.value: "send_video_note",
}


class DenyReason(StrEnum):
    OK = "ok"
    NO_TOPIC = "no_topic"
    NOT_WRITER = "not_writer"
    NOT_ACTIVE = "not_active"
    FROZEN = "frozen"
    BLOCKED = "blocked"
    DELETE_PENDING = "delete_pending"
    MUTED = "muted"
    BANNED = "banned"
    RATE_LIMITED = "rate_limited"
    MODERATION = "moderation"
    DUPLICATE = "duplicate"
    FORWARD = "forward"


@dataclass
class IncomingMessage:
    """Normalised inbound update coming from the bot layer."""

    user_id: int
    chat_id: int
    content_type: str = MessageContentType.TEXT.value
    text: str | None = None
    caption: str | None = None
    file_id: str | None = None
    unique_file_id: str | None = None
    file_size: int = 0
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    mime_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    tg_message_id: int | None = None
    is_forward: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> str:
        return self.text or self.caption or ""


@dataclass
class Permission:
    allowed: bool
    reason: DenyReason
    topic: Topic | None = None
    detail: str = ""


@dataclass
class RelayResult:
    ok: bool
    reason: DenyReason
    topic: Topic | None = None
    tg_message_id: int | None = None
    message_id: int | None = None
    reply: str | None = None
    detail: str = ""


class RelayService:
    def __init__(
        self,
        session: AsyncSession,
        gateway: TelegramGateway,
        moderator: Any | None = None,
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.moderator = moderator  # app.services.ai_service.AIModerator | None

    # ------------------------------------------------------------------
    # 1. group lockdown
    # ------------------------------------------------------------------
    async def enforce_group_lockdown(self, chat_id: int | None = None, tg_id: int | None = None) -> bool:
        """Make the whole forum read-only for non admins.

        Called on boot and whenever a new member joins. ``tg_id`` limits the call
        to a single member (``restrictChatMember``), ``None`` means the global
        ``setChatPermissions`` variant handled by the caller.
        """
        chat_id = chat_id or settings.forum_chat_id
        if not chat_id:
            return False
        if tg_id is not None:
            return await self.gateway.restrict_chat_member(chat_id, tg_id, dict(LOCKDOWN_PERMISSIONS))
        return await self.gateway.restrict_chat_member(0, 0, dict(LOCKDOWN_PERMISSIONS))

    # ------------------------------------------------------------------
    # 2. permission checks
    # ------------------------------------------------------------------
    async def permission_for(self, tg_id: int, topic: Topic | None = None) -> Permission:
        """Can ``tg_id`` write into ``topic`` (or into their current topic)?"""
        # Resolve without a status filter: a frozen or blocked topic must still
        # be found, so the precise reason below reaches the user instead of a
        # generic "you have no chat".
        topic = topic or await self.current_topic(tg_id)
        if topic is None:
            return Permission(False, DenyReason.NO_TOPIC)

        if tg_id not in topic.writer_ids:
            return Permission(False, DenyReason.NOT_WRITER, topic)

        status = TopicStatus(topic.status)
        if status is TopicStatus.ACTIVE and topic.is_closed:
            return Permission(False, DenyReason.BLOCKED, topic)
        if status is TopicStatus.FROZEN:
            return Permission(False, DenyReason.FROZEN, topic)
        if status is TopicStatus.BLOCKED:
            return Permission(False, DenyReason.BLOCKED, topic)
        if status is TopicStatus.DELETE_PENDING:
            return Permission(False, DenyReason.DELETE_PENDING, topic)
        if status is not TopicStatus.ACTIVE:
            return Permission(False, DenyReason.NOT_ACTIVE, topic)

        user = await self._user(tg_id)
        if user is not None:
            if user.is_banned and self._not_expired(user.ban_until):
                return Permission(False, DenyReason.BANNED, topic)
            if user.is_muted and self._not_expired(user.mute_until):
                return Permission(False, DenyReason.MUTED, topic)

        allowed, _hits = await self._rate_limited(tg_id)
        if not allowed:
            return Permission(False, DenyReason.RATE_LIMITED, topic)

        return Permission(True, DenyReason.OK, topic)

    async def current_topic(self, tg_id: int) -> Topic | None:
        """The topic a user is currently involved in, whatever its status.

        Preference order: the last topic they used -> the topic they own -> the
        topic they partner in.

        Deliberately *not* filtered by status. Hiding a frozen, blocked or
        pending topic here used to make every downstream command report
        "you have no chat" — so a user sitting in the 96h deletion window could
        not run ``/archive``, ``/restore`` or even ``/status`` on the very topic
        they needed it for. Status is a *permission* question, and
        :meth:`permission_for` already answers it with the precise reason.
        """
        user = await self._user(tg_id)
        if user is not None and user.last_active_topic_id:
            topic = await self.session.get(Topic, user.last_active_topic_id)
            if topic is not None and tg_id in topic.writer_ids:
                return topic

        stmt = (
            select(Topic)
            .where(Topic.owner_id == user.id if user is not None else Topic.id == -1)
            .order_by(Topic.id.desc())
            .limit(20)
        )
        candidates = list((await self.session.execute(stmt)).scalars().all())
        if user is not None:
            stmt2 = (
                select(Topic)
                .where(Topic.partner_id == user.id)
                .order_by(Topic.id.desc())
                .limit(20)
            )
            candidates += list((await self.session.execute(stmt2)).scalars().all())

        for topic in candidates:
            if tg_id in topic.writer_ids:
                return topic
        return None

    async def writable_topic(self, tg_id: int) -> Topic | None:
        """Like :meth:`current_topic`, but only if the user may still act on it.

        For commands that would *change* the topic (``/invite``, ``/event``,
        ``/schedule``). Anything that merely reads or rescues it — ``/status``,
        ``/archive``, ``/close``, ``/confirm`` — must use ``current_topic`` so a
        closed conversation stays reachable.
        """
        topic = await self.current_topic(tg_id)
        if topic is None:
            return None
        if tg_id not in topic.writer_ids or not self._usable(topic):
            return None
        return topic

    # ------------------------------------------------------------------
    # 3. relay
    # ------------------------------------------------------------------
    async def relay_private(self, incoming: IncomingMessage) -> RelayResult:
        """Relay a DM (or inline-mode query) into the user's topic."""
        started = time.perf_counter()
        result = await self._relay_private(incoming)
        metrics.incr("soulchat_relay_total", {"result": result.reason.value})
        metrics.observe(
            "soulchat_relay_duration_seconds",
            time.perf_counter() - started,
            {"result": result.reason.value},
        )
        return result

    async def _relay_private(self, incoming: IncomingMessage) -> RelayResult:
        perm = await self.permission_for(incoming.user_id)
        if not perm.allowed or perm.topic is None:
            return RelayResult(False, perm.reason, perm.topic, reply=self._deny_text(perm.reason))

        topic = perm.topic

        # --- topic policy --------------------------------------------------
        policy = self._policy_violation(topic, incoming)
        if policy is not None:
            return RelayResult(False, DenyReason.FORWARD, topic, reply=policy)

        # --- idempotency --------------------------------------------------
        # Telegram redelivers updates when a webhook/polling cycle errors out.
        # Without this a retried update would post the same line twice.
        if incoming.tg_message_id is not None:
            existing = (
                await self.session.execute(
                    select(Message).where(
                        Message.topic_id == topic.id,
                        Message.sender_id == await self._user_id(incoming.user_id),
                        Message.source_message_id == incoming.tg_message_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return RelayResult(
                    False,
                    DenyReason.DUPLICATE,
                    topic,
                    tg_message_id=existing.tg_message_id,
                    message_id=existing.id,
                    reply=None,          # already relayed: stay silent
                )

        # --- AI moderation ------------------------------------------------
        if self.moderator is not None and incoming.body:
            verdict = await self.moderator.moderate(
                text=incoming.body, user_id=incoming.user_id, topic_id=topic.id
            )
            if verdict.action in {ModerationAction.DELETE.value, ModerationAction.BLOCK.value}:
                return RelayResult(
                    False,
                    DenyReason.MODERATION,
                    topic,
                    reply=verdict.user_message,
                    detail=verdict.summary(),
                )

        tg_message_id = await self._post_to_topic(topic, incoming)
        row = await self._store_message(topic, incoming, tg_message_id)
        await self._touch(topic, incoming.user_id, row)
        await self.session.flush()

        return RelayResult(
            True, DenyReason.OK, topic, tg_message_id=tg_message_id, message_id=row.id
        )

    def _policy_violation(self, topic: Topic, incoming: IncomingMessage) -> str | None:
        """Enforce the per-topic forward/copy switches.

        ``forward_enabled`` is real: a forwarded DM carries ``forward_origin``
        and is refused. ``copy_enabled`` is only advisory — a silently copied
        message is indistinguishable from a typed one, so nothing can reject it
        (the flag is surfaced in the admin panel, not enforced).
        """
        if incoming.is_forward and not topic.forward_enabled:
            return (
                "⛔ Ushbu suhbatda boshqa chatdan ko'chirilgan xabar yuborish mumkin emas. "
                "Matnni qo'lda yozing yoki faylni ulang."
            )
        return None

    async def strip_reaction(self, topic: Topic, tg_message_id: int) -> bool:
        """Remove reactions from a topic message when the topic forbids them.

        The Bot API cannot disable reactions per topic, so they are cleared
        after the fact; call this from the ``message_reaction`` update handler.
        """
        if topic.reactions_enabled:
            return False
        if not topic.message_thread_id:
            return False
        return await self.gateway.set_message_reaction(topic.chat_id, tg_message_id, [])

    async def relay_edit(self, incoming: IncomingMessage) -> RelayResult:
        """Mirror an edit made in the DM onto the topic copy."""
        if incoming.tg_message_id is None:
            return RelayResult(False, DenyReason.NO_TOPIC, reply=None)

        row = await self._by_source(incoming.user_id, incoming.tg_message_id)
        if row is None:
            return RelayResult(False, DenyReason.NO_TOPIC, reply=None)

        topic = await self.session.get(Topic, row.topic_id)
        if topic is None:
            return RelayResult(False, DenyReason.NO_TOPIC, reply=None)

        new_text = incoming.text or incoming.caption or ""
        row.text = incoming.text
        row.caption = incoming.caption
        row.edited = True

        if topic.message_thread_id and row.tg_message_id:
            header = await self._sender_header(incoming.user_id)
            await self.gateway.edit_message_text(
                topic.chat_id, row.tg_message_id, f"{header}\n{new_text}" if header else new_text
            )
        await self.session.flush()
        return RelayResult(True, DenyReason.OK, topic, tg_message_id=row.tg_message_id, message_id=row.id)

    async def relay_delete(self, tg_id: int, source_message_id: int) -> RelayResult:
        """Mirror a deletion made in the DM onto the topic copy."""
        row = await self._by_source(tg_id, source_message_id)
        if row is None:
            return RelayResult(False, DenyReason.NO_TOPIC, reply=None)

        topic = await self.session.get(Topic, row.topic_id)
        row.deleted = True
        if topic is not None and topic.message_thread_id and row.tg_message_id:
            await self.gateway.delete_message(topic.chat_id, row.tg_message_id)
        await self.session.flush()
        return RelayResult(True, DenyReason.OK, topic, message_id=row.id)

    async def _by_source(self, tg_id: int, source_message_id: int) -> Message | None:
        sender_id = await self._user_id(tg_id)
        return (
            await self.session.execute(
                select(Message)
                .where(
                    Message.sender_id == sender_id,
                    Message.source_message_id == source_message_id,
                )
                .order_by(Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def moderate_group_message(
        self, chat_id: int, tg_message_id: int, author_tg_id: int, topic: Topic | None = None
    ) -> bool:
        """Delete a group message authored by somebody who is not a writer.

        With the lockdown in place this should never fire; it exists so a
        mis-configured group (or a fresh member before ``restrictChatMember``
        lands) cannot leak a third voice into a two-person chat.
        """
        topic = topic or await self.current_topic(author_tg_id)
        if topic is not None and author_tg_id in topic.writer_ids:
            return False
        deleted = await self.gateway.delete_message(chat_id, tg_message_id)
        if deleted:
            logger.info("deleted unauthorized group message %s from %s", tg_message_id, author_tg_id)
        return deleted

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    async def _post_to_topic(self, topic: Topic, incoming: IncomingMessage) -> int:
        thread_id = topic.message_thread_id
        method = _MEDIA_METHOD.get(incoming.content_type)

        if incoming.content_type == MessageContentType.LOCATION.value and incoming.latitude is not None:
            return await self.gateway.send_location(
                topic.chat_id,
                incoming.latitude,
                incoming.longitude or 0.0,
                thread_id=thread_id,
            )

        if method and incoming.file_id:
            sender = await self._user(incoming.user_id)
            signature = f"— {sender.full_name if sender else incoming.user_id}"
            payload = self._signature_block(topic, signature, incoming)
            send = getattr(self.gateway, method)
            if incoming.content_type == MessageContentType.STICKER.value:
                return await send(topic.chat_id, incoming.file_id, thread_id=thread_id)
            return await send(topic.chat_id, incoming.file_id, payload, thread_id=thread_id)

        header = await self._sender_header(incoming.user_id)
        body = incoming.text or incoming.caption or ""
        text = f"{header}\n{body}" if header else body
        return await self.gateway.send_message(topic.chat_id, text, thread_id=thread_id)

    def _signature_block(self, topic: Topic, signature: str, incoming: IncomingMessage) -> str:
        lines = [signature]
        if incoming.caption:
            lines.insert(0, incoming.caption)
        return "\n".join(lines)

    async def _sender_header(self, tg_id: int) -> str | None:
        user = await self._user(tg_id)
        return f"👤 {user.full_name}" if user else None

    async def _store_message(self, topic: Topic, incoming: IncomingMessage, tg_message_id: int) -> Message:
        row = Message(
            topic_id=topic.id,
            tg_message_id=tg_message_id,
            source_message_id=incoming.tg_message_id,
            thread_id=topic.message_thread_id,
            sender_id=(await self._user_id(incoming.user_id)),
            content_type=incoming.content_type,
            text=incoming.text,
            caption=incoming.caption,
            file_id=incoming.file_id,
            has_media=bool(incoming.file_id)
            or incoming.content_type == MessageContentType.LOCATION.value,
            forwarded=incoming.is_forward,
            relayed=True,
        )
        self.session.add(row)
        await self.session.flush()

        if incoming.file_id:
            media_row = Media(
                    topic_id=topic.id,
                    message_id=row.id,
                    kind=incoming.content_type,
                    file_id=incoming.file_id,
                    unique_file_id=incoming.unique_file_id,
                    file_size=incoming.file_size,
                    width=incoming.width,
                    height=incoming.height,
                    duration=incoming.duration,
                    mime_type=incoming.mime_type,
                    caption=incoming.caption,
            )
            self.session.add(media_row)
            topic.media_count = (topic.media_count or 0) + 1
            if incoming.content_type == "photo":
                # TZ 33: generate the 320px preview once, at receive time. Never
                # raises - a missing thumbnail must not cost the relay.
                try:
                    from app.services.thumbs import ensure_thumbnail

                    await ensure_thumbnail(self.session, media_row, self.gateway)
                except Exception:  # noqa: BLE001
                    logger.debug("thumbnail skipped", exc_info=True)
        return row

    async def _touch(self, topic: Topic, tg_id: int, row: Message) -> None:
        now = datetime.now(UTC)
        topic.message_count = (topic.message_count or 0) + 1
        topic.last_message_at = now
        if topic.first_message_at is None:
            topic.first_message_at = now

        user = await self._user(tg_id)
        if user is not None:
            user.messages_sent = (user.messages_sent or 0) + 1
            user.last_active_at = now
            user.last_active_topic_id = topic.id
        row.sender_id = user.id if user else row.sender_id

    async def _user(self, tg_id: int) -> User | None:
        return (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()

    async def _user_id(self, tg_id: int) -> int:
        user = await self._user(tg_id)
        return user.id if user else 0

    async def _rate_limited(self, tg_id: int) -> tuple[bool, int]:
        return await cache.hit_window(
            f"rl:{tg_id}", window=60, limit=settings.rate_limit_per_minute
        )

    @staticmethod
    def _usable(topic: Topic) -> bool:
        """A topic the relay may treat as "the user's current chat".

        Only writable ones qualify: a frozen/blocked/pending topic is resolved
        through ``permission_for`` (so the user gets the right reason), never
        silently adopted as the active chat.
        """
        return topic.status == TopicStatus.ACTIVE.value and not topic.is_closed

    @staticmethod
    def _not_expired(value: datetime | None) -> bool:
        if value is None:
            return True
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value > datetime.now(UTC)

    @staticmethod
    def _deny_text(reason: DenyReason) -> str:
        return {
            DenyReason.NO_TOPIC: "Sizda faol suhbat yo'q. Yangi suhbat uchun /new ni bosing.",
            DenyReason.NOT_WRITER: "Bu suhbatda faqat egasi va sherigi yoza oladi.",
            DenyReason.FROZEN: "Suhbat moderator tomonidan muzlatilgan.",
            DenyReason.BLOCKED: "Suhbat yopilgan.",
            DenyReason.DELETE_PENDING: "Suhbat o'chirish navbatida. /restore bilan tiklang.",
            DenyReason.MUTED: "Siz vaqtincha yozolmaysiz (mute).",
            DenyReason.BANNED: "Siz bloklangansiz.",
            DenyReason.RATE_LIMITED: "Juda tez yozmoqdasiz. Birozdan so'ng qayta urinib ko'ring.",
            DenyReason.MODERATION: "Xabar jamoa qoidalariga mos kelmadi.",
        }.get(reason, "Yozish imkoni yo'q.")