"""In-topic events (TZ 13) and the channel gallery publisher (TZ 14, 15)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.enums import AuditAction, ChannelPostType, EventKind, EventStatus
from app.models.message import ChannelPost, Event
from app.models.topic import Topic
from app.models.user import User
from app.services.audit import AuditService
from app.services.telegram_gateway import TelegramGateway

logger = get_logger(__name__)


class EventError(Exception):
    pass


@dataclass
class EventDraft:
    kind: EventKind = EventKind.DATE
    title: str = ""
    description: str = ""
    due_at: datetime | None = None
    remind_at: datetime | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    media_file_id: str | None = None
    checklist: list[str] | None = None


class EventService:
    def __init__(self, session: AsyncSession, gateway: TelegramGateway | None = None) -> None:
        self.session = session
        self.gateway = gateway
        self.audit = AuditService(session)

    async def create(self, topic: Topic, actor: User, draft: EventDraft) -> Event:
        if actor.id not in (topic.owner_id, topic.partner_id):
            raise EventError("Faqat ishtirokchilar hodisa yarata oladi.")
        if not draft.title.strip():
            raise EventError("Hodisa nomi bo'sh bo'lmasin.")

        row = Event(
            topic_id=topic.id,
            created_by=actor.id,
            kind=draft.kind.value,
            title=draft.title.strip(),
            description=draft.description,
            due_at=draft.due_at,
            remind_at=draft.remind_at,
            location=draft.location,
            latitude=draft.latitude,
            longitude=draft.longitude,
            media_file_id=draft.media_file_id,
            checklist=draft.checklist,
        )
        self.session.add(row)
        await self.audit.log(
            AuditAction.EVENT_CREATE, actor=actor, topic=topic, message=f"event {row.kind}: {row.title}"
        )
        await self.session.flush()
        return row

    async def toggle_checklist(self, event: Event, index: int) -> Event:
        items = list(event.checklist or [])
        if not 0 <= index < len(items):
            raise EventError("Bunday band yo'q.")
        item = items[index]
        items[index] = f"[x] {item[3:]}" if item.startswith("[ ]") else f"[ ] {item.lstrip('[x] ')}"
        event.checklist = items
        if all(i.startswith("[x]") for i in items):
            event.status = EventStatus.DONE.value
            event.completed_at = utcnow()
        await self.session.flush()
        return event

    async def due(self, now: datetime | None = None) -> list[Event]:
        now = now or utcnow()
        stmt = (
            select(Event)
            .where(
                Event.status.in_([EventStatus.SCHEDULED.value, EventStatus.NOTIFIED.value]),
                Event.remind_at.is_not(None),
                Event.remind_at <= now,
            )
            .limit(200)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_notified(self, event: Event) -> None:
        event.status = EventStatus.NOTIFIED.value
        event.notified_at = utcnow()
        await self.session.flush()

    async def cancel(self, event: Event, actor: User) -> Event:
        event.status = EventStatus.CANCELLED.value
        await self.audit.log(AuditAction.EVENT_CREATE, actor=actor, topic=None, message=f"cancelled {event.title}")
        await self.session.flush()
        return event


# ---------------------------------------------------------------------------
# Channel posts + gallery
# ---------------------------------------------------------------------------


@dataclass
class GalleryCard:
    topic_code: str
    owner_name: str
    partner_name: str | None
    caption: str
    location: str | None
    when: datetime | None


class ChannelService:
    """Publishes aesthetic posts to the broadcast channel (TZ 14, 15)."""

    def __init__(self, session: AsyncSession, gateway: TelegramGateway) -> None:
        self.session = session
        self.gateway = gateway
        self.audit = AuditService(session)

    # ------------------------------------------------------------ new topic
    async def announce_topic(self, topic: Topic, owner: User, partner: User | None = None) -> int | None:
        when = utcnow()
        text = (
            "✨\n\n"
            "<b>Yangi suhbat boshlandi</b>\n\n"
            f"🔖 <code>{topic.code}</code>\n"
            f"👤 {self._escape(owner.full_name)}\n"
            + (f"👤 {self._escape(partner.full_name)}\n" if partner else "")
            + f"🕒 {when.strftime('%d.%m %H:%M')}"
        )
        message_id = await self._post(text, topic, ChannelPostType.NEW_TOPIC, template="new_topic")
        if message_id:
            topic.channel_post_id = message_id
        return message_id

    # ------------------------------------------------------------- gallery
    async def publish_gallery(
        self, topic: Topic, owner: User, partner: User | None, file_id: str, card: GalleryCard
    ) -> int | None:
        caption = self.render_gallery_caption(card)
        message_id: int | None = None
        try:
            message_id = await self.gateway.send_photo(
                self._channel_id(), file_id, caption, parse_mode="HTML"
            )
        except Exception as exc:  # pragma: no cover - transport failure
            logger.warning("gallery post failed: %s", exc)
            await self._record(topic, ChannelPostType.GALLERY, caption, None, str(exc))
            return None

        await self._record(topic, ChannelPostType.GALLERY, caption, message_id, None, [file_id])
        return message_id

    def render_gallery_caption(self, card: GalleryCard) -> str:
        """🌸 / A-041 / Akbar ❤️ Salima / 📍Toshkent / 🕒 19:00"""
        names = self._escape(card.owner_name)
        if card.partner_name:
            names = f"{names} ❤️ {self._escape(card.partner_name)}"
        when = card.when.strftime("%H:%M") if card.when else ""
        day = card.when.strftime("%d.%m") if card.when else ""
        lines = [
            "🌸",
            "",
            f"<code>{card.topic_code}</code>",
            names,
        ]
        if card.caption:
            lines.append(self._escape(card.caption))
        if day:
            lines.append(f"📅 {day}")
        if card.location:
            lines.append(f"📍 {self._escape(card.location)}")
        if when:
            lines.append(f"🕒 {when}")
        return "\n".join(lines)

    # -------------------------------------------------------------- system
    async def announce_system(self, text: str, topic: Topic | None = None) -> int | None:
        return await self._post(text, topic, ChannelPostType.SYSTEM, template="system")

    # ------------------------------------------------------------- helpers
    async def _post(
        self, text: str, topic: Topic | None, kind: ChannelPostType, template: str
    ) -> int | None:
        try:
            message_id = await self.gateway.send_message(
                self._channel_id(), text, parse_mode="HTML"
            )
        except Exception as exc:  # pragma: no cover - transport failure
            logger.warning("channel post failed: %s", exc)
            await self._record(topic, kind, text, None, str(exc))
            return None
        await self._record(topic, kind, text, message_id, None, template=template)
        return message_id

    async def _record(
        self,
        topic: Topic | None,
        kind: ChannelPostType,
        text: str,
        message_id: int | None,
        error: str | None,
        media: list[str] | None = None,
        template: str | None = None,
    ) -> None:
        self.session.add(
            ChannelPost(
                topic_id=topic.id if topic else None,
                kind=kind.value,
                tg_message_id=message_id,
                text=text,
                media_file_ids=media,
                template=template,
                published_at=utcnow() if message_id else None,
                failed_reason=error,
            )
        )
        await self.session.flush()

    def _channel_id(self) -> int:
        return settings.channel_id or settings.forum_chat_id or 0

    @staticmethod
    def _escape(text: str) -> str:
        return (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )


# ---------------------------------------------------------------------------
# Scheduler (TZ 25)
# ---------------------------------------------------------------------------


@dataclass
class WindowState:
    should_be_open: bool
    in_window: bool
    days: list[int]
    start: str | None
    end: str | None


class SchedulerService:
    """Opens/closes topics on the user defined weekly window."""

    def __init__(self, session: AsyncSession, gateway: TelegramGateway) -> None:
        self.session = session
        self.gateway = gateway

    async def set_window(
        self, topic: Topic, days: list[int], start: str, end: str
    ) -> Topic:
        if not 0 <= len(days) <= 7:
            raise EventError("Kunlar ro'yxati noto'g'ri.")
        for value in (start, end):
            if not _is_hhmm(value):
                raise EventError("Vaqt HH:MM formatida bo'lishi kerak (masalan 20:00).")
        topic.schedule_days = ",".join(str(d) for d in sorted(set(days)))
        topic.schedule_window_start = start
        topic.schedule_window_end = end
        topic.schedule_enabled = True
        await self.session.flush()
        return topic

    async def clear_window(self, topic: Topic) -> Topic:
        topic.schedule_enabled = False
        topic.schedule_days = None
        topic.schedule_window_start = None
        topic.schedule_window_end = None
        await self.session.flush()
        return topic

    def evaluate(self, topic: Topic, now: datetime | None = None) -> WindowState:
        now = now or datetime.now(UTC)
        if not topic.schedule_enabled or not topic.schedule_window_start:
            return WindowState(True, True, [], None, None)
        days = [int(d) for d in (topic.schedule_days or "").split(",") if d.strip().isdigit()]
        start = _parse_hhmm(topic.schedule_window_start or "00:00")
        end = _parse_hhmm(topic.schedule_window_end or "23:59")
        today = now.isoweekday() % 7  # monday=1..sunday=0
        current = now.hour * 60 + now.minute
        in_day = (today in days) if days else True
        if start <= end:
            in_time = start <= current < end
        else:  # overnight window, e.g. 22:00 - 02:00
            in_time = current >= start or current < end
        return WindowState(in_day and in_time, in_day and in_time, days,
                           topic.schedule_window_start, topic.schedule_window_end)

    async def tick(self, now: datetime | None = None) -> dict[str, list[str]]:
        """Apply the schedule to every topic. Returns the codes that changed."""
        now = now or utcnow()
        stmt = select(Topic).where(Topic.schedule_enabled.is_(True))
        opened: list[str] = []
        closed: list[str] = []
        for topic in (await self.session.execute(stmt)).scalars().all():
            if not topic.message_thread_id:
                continue
            state = self.evaluate(topic, now)
            if state.should_be_open and topic.is_closed and topic.status == "active":
                await self.gateway.reopen_forum_topic(topic.chat_id, topic.message_thread_id)
                topic.is_closed = False
                opened.append(topic.code)
            elif not state.should_be_open and not topic.is_closed and topic.status == "active":
                await self.gateway.close_forum_topic(topic.chat_id, topic.message_thread_id)
                topic.is_closed = True
                closed.append(topic.code)
        await self.session.flush()
        return {"opened": opened, "closed": closed}

    async def upcoming(self, horizon: timedelta | None = None) -> list[Event]:
        horizon = horizon or timedelta(hours=24)
        until = utcnow() + horizon
        stmt = (
            select(Event)
            .where(
                Event.remind_at.is_not(None),
                Event.remind_at <= until,
                Event.status.in_([EventStatus.SCHEDULED.value, EventStatus.NOTIFIED.value]),
            )
            .order_by(Event.remind_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())


def _is_hhmm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return False
    hour, minute = int(parts[0]), int(parts[1])
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _parse_hhmm(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)
