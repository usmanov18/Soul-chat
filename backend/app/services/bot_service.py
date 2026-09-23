"""Bot command orchestration.

:class:`SoulChatBot` owns the conversation logic and returns plain
:class:`BotReply` objects. It deliberately does **not** import aiogram — the
aiogram router in :mod:`app.bot.handlers` is a thin adapter that turns these
replies into Telegram updates. That is what makes the whole bot flow testable
without a network connection.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.i18n import t
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.enums import (
    AuditAction,
    MessageContentType,
    Role,
    TopicStatus,
)
from app.models.message import Message
from app.models.security import BanAppeal
from app.models.topic import Topic
from app.models.user import User
from app.services.ai_service import AIModerator
from app.services.analytics_service import AnalyticsService
from app.services.archive_service import ArchiveService
from app.services.audit import AuditService
from app.services.close_service import CloseService
from app.services.event_service import ChannelService, EventDraft, EventService, GalleryCard, SchedulerService
from app.services.invite_service import InviteError, InviteService
from app.services.relationship import MemoryService, RelationshipService
from app.services.relay import IncomingMessage, RelayService
from app.services.security_service import SecurityService
from app.services.settings_service import SettingsService
from app.services.subscription_gate import SubscriptionGate
from app.services.telegram_gateway import TelegramGateway
from app.services.topic_service import TopicError, TopicService

logger = get_logger(__name__)

STAFF_ROLES = {Role.MODERATOR.value, Role.ADMIN.value, Role.SUPER_ADMIN.value}


@dataclass
class Button:
    text: str
    callback: str


@dataclass
class BotReply:
    text: str = ""
    buttons: list[list[Button]] = field(default_factory=list)
    parse_mode: str | None = "HTML"
    file: tuple[str, str] | None = None  # (kind, file_id)
    document: tuple[bytes, str] | None = None  # (payload, filename)

    def row(self, *buttons: Button) -> BotReply:
        self.buttons.append(list(buttons))
        return self


Handler = Callable[..., Coroutine[Any, Any, BotReply]]


class SoulChatBot:
    def __init__(self, session: AsyncSession, gateway: TelegramGateway, bot_username: str = "SoulChatBot") -> None:
        self.session = session
        self.gateway = gateway
        self.bot_username = bot_username

        self.settings = SettingsService(session)
        self.security = SecurityService(session)
        self.gate = SubscriptionGate(session, gateway)
        self.topics = TopicService(session, gateway)
        self.invites = InviteService(session, bot_username)
        self.closing = CloseService(session, self.topics)
        self.events = EventService(session, gateway)
        self.channel = ChannelService(session, gateway)
        self.scheduler = SchedulerService(session, gateway)
        self.archives = ArchiveService(session, gateway)
        self.analytics = AnalyticsService(session)
        self.ai = AIModerator(session, self.security)
        self.relay = RelayService(session, gateway, self.ai)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------
    async def user(self, tg_id: int) -> User | None:
        return (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()

    async def ensure_user(
        self,
        tg_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
        is_bot: bool = False,
        role: str | None = None,
    ) -> User:
        user = await self.user(tg_id)
        if user is None:
            user = User(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code or "uz",
                is_bot=is_bot,
                role=role or Role.USER.value,
            )
            self.session.add(user)
            await self.session.flush()
            await self.audit.log(AuditAction.LOGIN, actor=user, message="user registered")
        else:
            changed = False
            for attr, value in (
                ("username", username),
                ("first_name", first_name),
                ("last_name", last_name),
                ("language_code", language_code),
            ):
                if value is not None and getattr(user, attr) != value:
                    setattr(user, attr, value)
                    changed = True
            if changed:
                await self.session.flush()
        return user

    # ------------------------------------------------------------ /start
    async def start(self, tg_id: int, payload: str = "", **profile: Any) -> BotReply:
        user = await self.ensure_user(tg_id, **profile)

        if await self.security.is_blocked(tg_id):
            return BotReply("⛔ Siz qora ro'yxatdasiz. Administratorga murojaat qiling.")

        if settings.subscription_required:
            result = await self.gate.check(tg_id)
            if not result.allowed:
                missing = []
                if "group" in result.missing:
                    missing.append("guruhga a'zo")
                if "channel" in result.missing:
                    missing.append("kanalga obuna")
                bullet_list = "\n  • ".join(missing)
                return BotReply(
                    "🔒 Botdan foydalanish uchun ikkala shart bajarilishi kerak:\n"
                    f"  • {bullet_list}\n\n"
                    "Iltimos, avval obuna bo'ling, so'ng /start ni qayta bosing.",
                    buttons=[[Button("📢 Kanal", "open_channel"), Button("👥 Guruh", "open_group")]],
                )

        if payload.startswith("inv_"):
            try:
                topic = await self.invites.accept(payload.removeprefix("inv_"), user)
            except InviteError as exc:
                return BotReply(f"⚠️ {exc}")
            return BotReply(
                f"✅ Siz <code>{topic.code}</code> suhbatiga sherik bo'ldingiz.\n"
                "Xabarlaringizni shu botga yozing — ular suhbatga chiqadi.",
                buttons=[self._owner_menu_row()],
            )

        return BotReply(
            f"👋 Xush kelibsiz, {user.full_name}!\n\n"
            "SoulChat — ikki kishilik shaxsiy suhbatlar platformasi.\n\n"
            "• /new — yangi suhbat yaratish\n"
            "• Bu botga yozgan har bir xabaringiz suhbatingizga chiqadi\n"
            "• Hamma o'qiy oladi, faqat siz va sherigingiz yoza olasiz",
            buttons=[[Button("✨ Yangi suhbat", "new")], [Button("📖 Qo'llanma", "help")]],
        )

    # -------------------------------------------------------------- /new
    async def new_topic(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        if user is None:
            return await self.start(tg_id)
        gate = await self.gate.check(tg_id)
        if not gate.allowed:
            return BotReply("🔒 Avval guruh va kanalga obuna bo'ling.")
        try:
            created = await self.topics.create(tg_id)
        except TopicError as exc:
            return BotReply(f"⚠️ {exc}")

        owner = await self.session.get(User, created.topic.owner_id)
        await self.channel.announce_topic(created.topic, owner or user)

        return BotReply(
            f"✨ Suhbatingiz tayyor!\n\n"
            f"🔖 Kod: <code>{created.code}</code>\n"
            f"💫 {created.display}\n\n"
            "Sherigingizni taklif qiling — keyin xabar yozishni boshlang.",
            buttons=[
                [Button("🤝 Sherik taklif qilish", "invite")],
                [Button("🔗 Suhbatni ochish", f"open_topic:{created.topic.id}")],
            ],
        )

    # ---------------------------------------------------------- /invite
    async def invite(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        topic = await self.relay.writable_topic(tg_id)
        if user is None or topic is None:
            return BotReply("Sizda faol suhbat yo'q. /new bilan yarating.")
        if topic.owner_id != user.id:
            return BotReply("Faqat suhbat egasi sherik taklif qila oladi.")
        try:
            created = await self.invites.create(topic, user)
        except InviteError as exc:
            return BotReply(f"⚠️ {exc}")
        return BotReply(
            "📨 Taklif havolasi tayyor:\n\n"
            f"<code>{created.url}</code>\n\n"
            "Havolani sherigingizga yuboring. U bosganda suhbatga qo'shiladi va "
            "ikkovingiz yozish huquqiga ega bo'lasiz.",
            buttons=[[Button("🔗 Havolani ulashish", f"share:{created.invite.token}")]],
        )

    # ------------------------------------------------------------ relay
    async def handle_private_message(self, message: IncomingMessage) -> BotReply | None:
        """Any DM that is not a command ends up here."""
        user = await self.user(message.user_id)
        if user is None:
            return await self.start(message.user_id)

        flood = await self.security.register_hit(message.user_id)
        if flood.level.value == "captcha":
            return BotReply("⚠️ Juda tez yozmoqdasiz. Tasdiqlash uchun javob bering.")
        if flood.level.value == "mute":
            return BotReply("⏳ Vaqtincha yozolmaysiz.")

        gate = await self.gate.check(message.user_id)
        if not gate.allowed:
            return BotReply("🔒 Yozish uchun guruh va kanalga obuna bo'lishingiz kerak.")

        result = await self.relay.relay_private(message)
        if not result.ok:
            return BotReply(result.reply or "Yozib bo'lmadi.")
        await self.session.flush()

        # gallery: photos/videos go to the channel too (TZ 14)
        if message.content_type in {MessageContentType.PHOTO.value, MessageContentType.VIDEO.value} and message.file_id:
            topic = result.topic
            if topic is not None:
                owner = await self.session.get(User, topic.owner_id)
                partner = await self.session.get(User, topic.partner_id) if topic.partner_id else None
                card = GalleryCard(
                    topic_code=topic.code,
                    owner_name=owner.full_name if owner else "?",
                    partner_name=partner.full_name if partner else None,
                    caption=message.caption or "",
                    location=message.extra.get("location") if message.extra else None,
                    when=utcnow(),
                )
                await self.channel.publish_gallery(topic, owner or user, partner, message.file_id, card)
        return None  # silently relayed — echoing back would be noise

    async def handle_private_edit(self, message: IncomingMessage) -> BotReply | None:
        """Mirror a DM edit onto the topic copy (silently)."""
        result = await self.relay.relay_edit(message)
        if not result.ok:
            return None
        await self.session.flush()
        return None

    # -------------------------------------------------- TZ 27 power commands
    async def summary(self, tg_id: int) -> BotReply:
        """TZ 27: AI conversation summary for the current topic."""
        topic = await self.relay.current_topic(tg_id)
        if topic is None:
            return BotReply("Suhbat topilmadi. /new bilan boshlang.")
        rows = (
            await self.session.execute(
                select(Message)
                .where(Message.topic_id == topic.id)
                .order_by(Message.id.desc())
                .limit(300)
            )
        ).scalars().all()
        texts = [row.text or row.caption or "" for row in rows]
        stamps = [int(row.created_at.timestamp()) for row in rows if row.created_at]
        result = await self.ai.summarize(list(reversed(texts)), list(reversed(stamps)))
        return BotReply(f"🧠 <b>Xulosa</b>\n{result.text}")

    async def timeline(self, tg_id: int) -> BotReply:
        """TZ 27: relationship timeline (events + activity)."""
        topic = await self.relay.current_topic(tg_id)
        if topic is None:
            return BotReply("Suhbat topilmadi. /new bilan boshlang.")
        service = RelationshipService(self.session)
        data = await service.timeline(topic)
        return BotReply(service.render_timeline(data))

    async def suggest(self, tg_id: int) -> BotReply:
        """TZ 27: AI reply suggestions for the partner's last message."""
        topic = await self.relay.current_topic(tg_id)
        if topic is None:
            return BotReply("Suhbat topilmadi. /new bilan boshlang.")
        last = (
            await self.session.execute(
                select(Message)
                .where(Message.topic_id == topic.id, Message.text.is_not(None))
                .order_by(Message.id.desc())
                .limit(1)
            )
        ).scalars().first()
        options = await self.ai.suggest_replies(last.text if last else "")
        lines = [f"{index}. {text}" for index, text in enumerate(options, 1)]
        return BotReply("💡 <b>Takliflar</b>\n" + "\n".join(lines))

    async def remember(self, tg_id: int, text: str) -> BotReply:
        """TZ 27: save a memory for the current topic."""
        topic = await self.relay.writable_topic(tg_id)
        if topic is None:
            return BotReply("Yozish uchun faol suhbat yo'q.")
        if not text.strip():
            return BotReply("Foydalanish: /remember matn")
        user = await self.user(tg_id)
        if user is None:
            return BotReply("Avval /start ni bosing.")
        await MemoryService(self.session).add(topic, user.id, text)
        return BotReply("🧷 Eslatib qo'yildi. /memory bilan ko'ring.")

    async def memory(self, tg_id: int) -> BotReply:
        topic = await self.relay.current_topic(tg_id)
        if topic is None:
            return BotReply("Suhbat topilmadi.")
        rows = await MemoryService(self.session).list_for(topic)
        if not rows:
            return BotReply("Hozircha eslatmalar yo'q. /remember matn bilan qo'shing.")
        lines = [f"{row.id}. {row.text}" for row in rows]
        return BotReply("🧷 <b>Eslatmalar</b>\n" + "\n".join(lines))

    async def forget(self, tg_id: int, memory_id: int) -> BotReply:
        topic = await self.relay.current_topic(tg_id)
        if topic is None:
            return BotReply("Suhbat topilmadi.")
        user = await self.user(tg_id)
        if user is None:
            return BotReply("Avval /start ni bosing.")
        removed = await MemoryService(self.session).forget(topic, memory_id, user.id)
        if removed:
            return BotReply("🗑 O'chirildi.")
        return BotReply("Bunday eslatma topilmadi (faqat o'zingiznikini o'chira olasiz).")

    # -------------------------------------------------- D-block commands
    _DURATION = re.compile(r"^\s*(\d{1,4})\s*(m|h|d)\s*$", re.IGNORECASE)

    async def timer(self, tg_id: int, duration: str) -> BotReply:
        """D1: mark the user's last relayed message to be deleted later."""
        topic = await self.relay.writable_topic(tg_id)
        if topic is None:
            return BotReply("Yozish uchun faol suhbat yo'q.")
        match = self._DURATION.match(duration or "")
        if match is None:
            return BotReply("Foydalanish: /timer 30m  (yoki 12h, 3d)")
        amount, unit = int(match.group(1)), match.group(2).lower()
        seconds = amount * {"m": 60, "h": 3600, "d": 86400}[unit]
        if seconds > 7 * 86400:
            return BotReply("Maksimal taymer: 7d.")
        user = await self.user(tg_id)
        if user is None:
            return BotReply("Avval /start ni bosing.")
        row = (
            await self.session.execute(
                select(Message)
                .where(Message.topic_id == topic.id, Message.sender_id == user.id)
                .order_by(Message.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if row is None:
            return BotReply("Sizning xabaringiz topilmadi.")
        row.self_destruct_at = utcnow() + timedelta(seconds=seconds)
        await self.session.flush()
        return BotReply(f"⏲ Xabar {amount}{unit} dan keyin o'chib ketadi.")

    async def appeal(self, tg_id: int, text: str) -> BotReply:
        """D5: banned/muted user asks the staff to reconsider."""
        if not text.strip():
            return BotReply("Foydalanish: /appeal murojaat matni")
        user = await self.user(tg_id)
        pending = (
            await self.session.execute(
                select(BanAppeal).where(BanAppeal.tg_id == tg_id, BanAppeal.status == "pending")
            )
        ).scalars().first()
        if pending is not None:
            return BotReply("Murojaatingiz allaqachon ko'rib chiqilmoqda.")
        self.session.add(
            BanAppeal(user_id=user.id if user else None, tg_id=tg_id, text=text.strip()[:1000])
        )
        await self.session.flush()
        await self.audit.log(
            "appeal.create",
            actor=user,
            message=f"appeal from {tg_id}: {text.strip()[:80]}",
        )
        return BotReply("📨 Murojaatingiz moderatorlarga yuborildi.")

    async def invite_qr(self, tg_id: int) -> BotReply | None:
        """D6: QR for the fresh invite link, when ``qrcode`` is installed."""
        topic = await self.relay.writable_topic(tg_id)
        if topic is None:
            return BotReply("Sizda faol suhbat yo'q. /new bilan yarating.")
        user = await self.user(tg_id)
        if user is None or topic.owner_id != user.id:
            return BotReply("Faqat suhbat egasi sherik taklif qila oladi.")
        try:
            created = await self.invites.create(topic, user)
        except InviteError as exc:
            return BotReply(f"⚠️ {exc}")
        reply = BotReply(f"🔗 Taklif havolasi (bitta martalik):\n{created.url}")
        link = created.url
        if not link:
            return reply
        try:
            import io

            import qrcode

            image = qrcode.make(link)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            reply.document = (buffer.getvalue(), "invite-qr.png")
        except Exception:  # noqa: BLE001 - QR is decoration, the link is the point
            pass
        return reply

    async def undo_last(self, tg_id: int) -> BotReply:
        """Delete the user's most recent relayed message from the topic.

        The Bot API never notifies a bot about a user deleting their own DM, so
        an explicit command is the only reliable entry point.
        """
        from sqlalchemy import select

        from app.models.message import Message

        user = await self.user(tg_id)
        if user is None:
            return BotReply("Avval /start ni bosing.")
        row = (
            await self.session.execute(
                select(Message)
                .where(
                    Message.sender_id == user.id,
                    Message.deleted.is_(False),
                    Message.relayed.is_(True),
                )
                .order_by(Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return BotReply(t("undo.none", await self._lang(tg_id)))
        await self.relay.relay_delete(tg_id, row.source_message_id or 0)
        await self.session.flush()
        return BotReply(t("undo.done", await self._lang(tg_id)))

    # ----------------------------------------------------------- group
    async def handle_group_message(
        self, chat_id: int, tg_message_id: int, author_tg_id: int, thread_id: int | None = None
    ) -> BotReply | None:
        """Delete anything posted into the forum by a non-writer."""
        topic = None
        if thread_id:
            topic = (
                await self.session.execute(
                    select(Topic).where(Topic.message_thread_id == thread_id, Topic.chat_id == chat_id)
                )
            ).scalar_one_or_none()
        await self.relay.moderate_group_message(chat_id, tg_message_id, author_tg_id, topic)
        return None

    # ----------------------------------------------------------- /close
    async def close(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        # current_topic, not writable_topic: closing and confirming are exactly
        # what a user does *after* the chat stopped being writable.
        topic = await self.relay.current_topic(tg_id)
        if user is None or topic is None:
            return BotReply("Faol suhbat topilmadi.")
        from app.services.close_service import CloseError

        try:
            started = await self.closing.start(topic, user)
        except CloseError as exc:
            return BotReply(f"⚠️ {exc}")
        if started.completed:
            return BotReply(started.message, buttons=[[Button("↩️ Tiklash", "restore")]])
        return BotReply(
            started.message,
            buttons=[[Button("❌ Bekor qilish", "cancel_close")]],
        )

    async def confirm(self, tg_id: int, code: str) -> BotReply:
        user = await self.user(tg_id)
        topic = await self.relay.current_topic(tg_id)
        if user is None or topic is None:
            return BotReply("Faol suhbat topilmadi.")
        from app.services.close_service import CloseError

        try:
            state = await self.closing.confirm(topic, user, code)
        except CloseError as exc:
            return BotReply(f"⚠️ {exc}")

        if state.completed:
            return BotReply(
                f"✅ Suhbat {topic.code} yopildi.\n"
                f"{settings.delete_pending_hours} soat ichida /restore bosmasangiz, u o'chadi.",
                buttons=[[Button("↩️ Tiklash", "restore")]],
            )
        waiting = "sherigingiz" if user.id == topic.owner_id else "suhbat egasi"
        return BotReply(f"👌 Tasdiqlandi. Endi {waiting} kodni kiritishi kerak.")

    async def restore(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        if user is None:
            return BotReply("Avval /start ni bosing.")
        topic = await self._find_closed_topic(user)
        if topic is None:
            return BotReply("Tiklanadigan suhbat topilmadi.")
        from app.services.close_service import CloseError

        try:
            request = await self.closing.request_restore(topic, user, "user /restore")
            await self.closing.approve_restore(request, user)
        except CloseError as exc:
            return BotReply(f"⚠️ {exc}")
        return BotReply(
            f"↩️ Suhbat <code>{topic.code}</code> tiklandi. Yana yoza olasiz.",
            buttons=[self._owner_menu_row()],
        )

    async def archive(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        topic = await self.relay.current_topic(tg_id)
        if user is None or topic is None:
            return BotReply("Faol suhbat topilmadi.")
        result = await self.archives.export(topic, user)
        with open(result.path, "rb") as handle:
            payload = handle.read()
        await self.audit.log(AuditAction.EXPORT, actor=user, topic=topic,
                             message=f"archive sent ({result.size} bytes)")
        return BotReply(
            f"📦 Arxiv tayyor: {result.message_count} xabar, {result.media_count} media.\n"
            f"Formatlar: {', '.join(result.formats)}",
            document=(payload, f"soulchat-{topic.code}.zip"),
        )

    # ----------------------------------------------------------- events
    async def create_event(self, tg_id: int, draft: EventDraft) -> BotReply:
        user = await self.user(tg_id)
        topic = await self.relay.writable_topic(tg_id)
        if user is None or topic is None:
            return BotReply("Faol suhbat topilmadi.")
        from app.services.event_service import EventError

        try:
            event = await self.events.create(topic, user, draft)
        except EventError as exc:
            return BotReply(f"⚠️ {exc}")
        when = event.due_at.strftime("%d.%m %H:%M") if event.due_at else "—"
        return BotReply(
            f"📌 Hodisa yaratildi: <b>{event.title}</b>\n"
            f"Turi: {event.kind} · Vaqt: {when}\n"
            f"ID: <code>{event.id}</code>",
            buttons=[[Button("✅ Bajarildi", f"event_done:{event.id}")]],
        )

    async def schedule(self, tg_id: int, days: list[int], start: str, end: str) -> BotReply:
        user = await self.user(tg_id)
        topic = await self.relay.writable_topic(tg_id)
        if user is None or topic is None:
            return BotReply("Faol suhbat topilmadi.")
        from app.services.event_service import EventError

        try:
            await self.scheduler.set_window(topic, days, start, end)
        except EventError as exc:
            return BotReply(f"⚠️ {exc}")
        names = {0: "Yak", 1: "Dush", 2: "Sesh", 3: "Chor", 4: "Pay", 5: "Jum", 6: "Shan"}
        day_names = ", ".join(names.get(d, str(d)) for d in days) or "har kuni"
        return BotReply(
            f"⏰ Jadval saqlandi.\n\n"
            f"Kunlar: {day_names}\n"
            f"Vaqt: {start} – {end}\n\n"
            "Shu vaqtda suhbat avtomatik ochiladi, vaqt tugagach yopiladi."
        )

    # ---------------------------------------------------------- profile
    async def status(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        topic = await self.relay.current_topic(tg_id)
        if user is None:
            return BotReply("Avval /start ni bosing.")
        lines = [
            f"👤 <b>{user.full_name}</b>",
            f"ID: <code>{user.tg_id}</code>",
            f"Rol: {user.role}",
            f"Yuborilgan xabarlar: {user.messages_sent}",
            f"Yaratilgan suhbatlar: {user.topics_created}",
            "",
        ]
        if topic:
            lines += [
                f"🔖 Suhbat: <code>{topic.code}</code>",
                f"Holat: {topic.status}",
                f"Xabarlar: {topic.message_count} · Media: {topic.media_count}",
            ]
            if topic.partner_id:
                partner = await self.session.get(User, topic.partner_id)
                lines.append(f"🤝 Sherik: {partner.full_name if partner else '—'}")
            else:
                lines.append("🤝 Sherik: hali yo'q")
            if topic.delete_at:
                lines.append(f"⏳ O'chish vaqti: {topic.delete_at.strftime('%d.%m %H:%M')}")
        else:
            lines.append("Faol suhbat yo'q.")
        return BotReply("\n".join(lines), buttons=[self._owner_menu_row()])

    async def _lang(self, tg_id: int) -> str:
        """The account's stored Telegram language, Uzbek by default."""
        user = await self.user(tg_id)
        return user.language_code if user is not None else None

    async def help(self, tg_id: int) -> BotReply:
        """Localised command list (uz / ru / en, from ``users.language_code``)."""
        return BotReply(t("help.body", await self._lang(tg_id)))

    # ------------------------------------------------------------- staff
    async def stats(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        if user is None or user.role not in STAFF_ROLES:
            return BotReply("Bu bo'lim faqat moderator va adminlar uchun.")
        data = await self.analytics.dashboard()
        return BotReply(
            "📊 <b>Statistika</b>\n\n"
            f"Foydalanuvchilar: {data.total_users}\n"
            f"Suhbatlar: {data.total_topics} (bugun +{data.new_topics_today})\n"
            f"Faol: {data.active_topics} · Yopilgan: {data.closed_topics} · O'chirilgan: {data.deleted_topics}\n"
            f"Tiklangan: {data.restored_topics}\n"
            f"Xabarlar: {data.total_messages} (bugun {data.messages_today})\n"
            f"Media: {data.total_media} (bugun {data.media_today})\n"
            f"Kanal postlari: {data.channel_posts} · Galereya: {data.gallery_posts}\n"
            f"O'rtacha chat uzunligi: {data.average_chat_length:.1f} xabar\n"
            f"O'rtacha umr: {data.average_days:.1f} kun · D7 retention: {data.retention_d7:.1%}"
        )

    async def search(self, tg_id: int, query: str) -> BotReply:
        user = await self.user(tg_id)
        if user is None or user.role not in STAFF_ROLES:
            return BotReply("Bu bo'lim faqat moderator va adminlar uchun.")
        result = await self.analytics.search(query=query or "")
        lines = [f"🔎 <b>'{query}' bo'yicha natijalar</b>", ""]
        for section, items in result.items():
            if not items:
                continue
            lines.append(f"<b>{section.title()} ({len(items)})</b>")
            for item in items[:5]:
                if section == "topics":
                    lines.append(f"  • <code>{item['code']}</code> — {item['status']}, {item['messages']} xabar")
                elif section == "users":
                    lines.append(f"  • {item['name']} (@{item['username'] or '—'}), {item['messages']} xabar")
                else:
                    lines.append(f"  • [{item['type']}] {item['text'][:60]}")
            lines.append("")
        if len(lines) == 2:
            lines.append("Hech narsa topilmadi.")
        return BotReply("\n".join(lines))

    async def moderate(self, tg_id: int, action: str, target_tg_id: int, reason: str = "") -> BotReply:
        user = await self.user(tg_id)
        if user is None or user.role not in STAFF_ROLES:
            return BotReply("Ruxsat yo'q.")
        if action == "warn":
            target, warns = await self.security.warn(target_tg_id, user, reason or "qoida buzilishi")
            return BotReply(f"⚠️ Ogohlantirish berildi. Jami: {warns}/{settings.max_warns}")
        if action == "mute":
            await self.security.mute(target_tg_id, minutes=30, reason=reason)
            return BotReply("🔇 Foydalanuvchi 30 daqiqaga muzlatildi.")
        if action == "ban":
            await self.security.ban(target_tg_id, user, reason)
            return BotReply("⛔ Foydalanuvchi bloklandi.")
        if action == "freeze":
            topic = await self.relay.current_topic(target_tg_id)
            if topic:
                await self.topics.freeze(topic, user, reason)
                return BotReply(f"❄️ {topic.code} muzlatildi.")
        if action == "unfreeze":
            # current_topic, not writable_topic: a frozen topic is by definition
            # not writable, and unfreezing is how it becomes writable again.
            topic = await self.relay.current_topic(target_tg_id)
            if topic:
                await self.topics.unfreeze(topic, user, reason)
                return BotReply(f"☀️ {topic.code} muzlatishi bekor qilindi.")
        if action == "restore":
            topic = await self._find_closed_topic_by_tg(target_tg_id, include_frozen=True)
            if topic:
                # a frozen topic must be unfrozen, not restored: restore() also
                # clears is_closed/delete_at, which a freeze never set.
                if topic.status == TopicStatus.FROZEN.value:
                    await self.topics.unfreeze(topic, user, reason)
                    return BotReply(f"☀️ {topic.code} muzlatishi bekor qilindi.")
                await self.topics.restore(topic, user)
                return BotReply(f"↩️ {topic.code} tiklandi.")
        return BotReply(f"Noma'lum amal: {action}")

    async def settings_view(self, tg_id: int) -> BotReply:
        user = await self.user(tg_id)
        if user is None or user.role not in {Role.ADMIN.value, Role.SUPER_ADMIN.value}:
            return BotReply("Ruxsat yo'q.")
        values = await self.settings.all()
        lines = ["⚙️ <b>Sozlamalar</b>", ""]
        for key in sorted(values):
            lines.append(f"  <code>{key}</code> = {values[key]}")
        return BotReply("\n".join(lines))

    async def set_setting(self, tg_id: int, key: str, value: str) -> BotReply:
        user = await self.user(tg_id)
        if user is None or user.role not in {Role.ADMIN.value, Role.SUPER_ADMIN.value}:
            return BotReply("Ruxsat yo'q.")
        await self.settings.set(key, value, user)
        return BotReply(f"✅ <code>{key}</code> = {value}")

    # --------------------------------------------------------- internal
    async def _find_closed_topic(self, user: User, *, include_frozen: bool = False) -> Topic | None:
        """A topic the caller may bring back to life.

        ``include_frozen`` is staff-only on purpose: a freeze is a moderator
        decision, and letting the frozen user undo it with ``/restore`` would
        make the moderation tool useless.
        """
        statuses = [
            TopicStatus.BLOCKED.value,
            TopicStatus.DELETE_PENDING.value,
            TopicStatus.ARCHIVED.value,
        ]
        if include_frozen:
            statuses.append(TopicStatus.FROZEN.value)
        stmt = (
            select(Topic)
            .where(
                Topic.owner_id == user.id,
                Topic.status.in_(statuses),
            )
            .order_by(Topic.id.desc())
            .limit(1)
        )
        topic = (await self.session.execute(stmt)).scalar_one_or_none()
        if topic:
            return topic
        stmt2 = (
            select(Topic)
            .where(
                Topic.partner_id == user.id,
                Topic.status.in_(
                    [TopicStatus.BLOCKED.value, TopicStatus.DELETE_PENDING.value, TopicStatus.ARCHIVED.value]
                ),
            )
            .order_by(Topic.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt2)).scalar_one_or_none()

    async def _find_closed_topic_by_tg(self, tg_id: int, *, include_frozen: bool = False) -> Topic | None:
        user = await self.user(tg_id)
        if user is None:
            return None
        return await self._find_closed_topic(user, include_frozen=include_frozen)

    def _owner_menu_row(self) -> list[Button]:
        return [
            Button("🤝 Sherik", "invite"),
            Button("📊 Holat", "status"),
            Button("🔒 Yopish", "close"),
            Button("📦 Arxiv", "archive"),
        ]