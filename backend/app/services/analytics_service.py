"""Analytics (TZ 21) — the numbers behind the admin dashboard."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.timeutil import aware, sql_hour, utcnow
from app.enums import ChannelPostType, MediaKind, MessageContentType, TopicStatus
from app.models.log import StatDaily
from app.models.message import ChannelPost, Media, Message
from app.models.topic import Topic
from app.models.user import User

logger = get_logger(__name__)


@dataclass
class DashboardStats:
    total_users: int = 0
    total_topics: int = 0
    new_topics_today: int = 0
    active_topics: int = 0
    closed_topics: int = 0
    deleted_topics: int = 0
    restored_topics: int = 0
    total_messages: int = 0
    messages_today: int = 0
    total_media: int = 0
    media_today: int = 0
    channel_posts: int = 0
    gallery_posts: int = 0
    average_chat_length: float = 0.0
    average_days: float = 0.0
    retention_d7: float = 0.0
    top_users: list[dict] = field(default_factory=list)
    top_active_hours: list[dict] = field(default_factory=list)
    top_media: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ``app.core.timeutil.sql_hour`` is the dialect-aware hour extraction.
# Doing this in SQL instead of Python is what keeps /metrics cheap: the
# previous implementation loaded every messages.created_at into memory on
# every Prometheus scrape.
hour_expression = sql_hour  # backwards compatible alias


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    async def dashboard(self) -> DashboardStats:
        now = utcnow()
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)

        stats = DashboardStats()
        stats.total_users = await self._count(select(func.count()).select_from(User))
        stats.total_topics = await self._count(select(func.count()).select_from(Topic))
        stats.new_topics_today = await self._count(
            select(func.count()).select_from(Topic).where(Topic.created_at >= today_start)
        )
        stats.active_topics = await self._status_count(TopicStatus.ACTIVE)
        stats.closed_topics = await self._status_count(TopicStatus.BLOCKED)
        stats.deleted_topics = await self._status_count(TopicStatus.DELETED)
        stats.restored_topics = await self._count(
            select(func.coalesce(func.sum(Topic.restore_count), 0))
        )
        stats.total_messages = await self._count(select(func.count()).select_from(Message))
        stats.messages_today = await self._count(
            select(func.count()).select_from(Message).where(Message.created_at >= today_start)
        )
        stats.total_media = await self._count(select(func.count()).select_from(Media))
        stats.media_today = await self._count(
            select(func.count()).select_from(Media).where(Media.created_at >= today_start)
        )
        stats.channel_posts = await self._count(select(func.count()).select_from(ChannelPost))
        stats.gallery_posts = await self._count(
            select(func.count())
            .select_from(ChannelPost)
            .where(ChannelPost.kind == ChannelPostType.GALLERY.value)
        )

        stats.average_chat_length = await self._float(self._average_length_stmt())
        stats.average_days = await self._average_topic_days()
        stats.retention_d7 = await self._retention(days=7)
        stats.top_users = await self._top_users()
        stats.top_active_hours = await self._top_hours()
        stats.top_media = await self._top_media()
        return stats

    # ------------------------------------------------------------ series
    async def daily_series(self, days: int = 30) -> list[dict]:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(
                func.date(Message.created_at).label("day"),
                func.count().label("messages"),
            )
            .where(Message.created_at >= since)
            .group_by(func.date(Message.created_at))
            .order_by(func.date(Message.created_at))
        )
        rows = (await self.session.execute(stmt)).all()
        topics_stmt = (
            select(func.date(Topic.created_at).label("day"), func.count().label("topics"))
            .where(Topic.created_at >= since)
            .group_by(func.date(Topic.created_at))
        )
        topic_rows = {str(day): int(count) for day, count in (await self.session.execute(topics_stmt)).all()}
        series = [
            {"day": str(day), "messages": int(messages), "topics": topic_rows.get(str(day), 0)}
            for day, messages in rows
        ]
        return self._fill_gaps(series, days)

    async def weekly(self, weeks: int = 12) -> list[dict]:
        buckets: dict[str, dict[str, int]] = {}
        now = utcnow()
        for offset in range(weeks):
            start = now - timedelta(days=7 * (offset + 1))
            end = now - timedelta(days=7 * offset)
            messages = await self._count(
                select(func.count()).select_from(Message).where(
                    Message.created_at >= start, Message.created_at < end
                )
            )
            topics = await self._count(
                select(func.count()).select_from(Topic).where(
                    Topic.created_at >= start, Topic.created_at < end
                )
            )
            buckets[f"W-{offset + 1}"] = {"messages": messages, "topics": topics}
        return [{"week": key, **value} for key, value in reversed(list(buckets.items()))]

    async def monthly(self, months: int = 12) -> list[dict]:
        out: list[dict] = []
        now = utcnow()
        for offset in range(months):
            year = now.year - (now.month - 1 - offset) // 12
            month = (now.month - 1 - offset) % 12 + 1
            start = datetime(year, month, 1, tzinfo=UTC)
            end = (datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=UTC))
            messages = await self._count(
                select(func.count()).select_from(Message).where(
                    Message.created_at >= start, Message.created_at < end
                )
            )
            topics = await self._count(
                select(func.count()).select_from(Topic).where(
                    Topic.created_at >= start, Topic.created_at < end
                )
            )
            out.append({"month": f"{year}-{month:02d}", "messages": messages, "topics": topics})
        return out

    # ---------------------------------------------------------- snapshot
    async def snapshot(self, day: date | None = None) -> StatDaily:
        stats = await self.dashboard()
        day = day or datetime.now(UTC).date()
        row = (
            await self.session.execute(select(StatDaily).where(StatDaily.day == day))
        ).scalar_one_or_none()
        if row is None:
            row = StatDaily(day=day)
            self.session.add(row)
        row.new_topics = stats.new_topics_today
        row.active_topics = stats.active_topics
        row.closed_topics = stats.closed_topics
        row.deleted_topics = stats.deleted_topics
        row.restored_topics = stats.restored_topics
        row.messages = stats.messages_today
        row.media = stats.media_today
        row.gallery_posts = stats.gallery_posts
        row.channel_posts = stats.channel_posts
        row.active_users = len(
            {u for (u,) in (await self.session.execute(select(Message.sender_id).distinct())).all()}
        )
        row.new_users = await self._count(
            select(func.count())
            .select_from(User)
            .where(func.date(User.created_at) == day)
        )
        row.avg_messages_per_topic = round(stats.average_chat_length, 2)
        row.avg_topic_days = round(stats.average_days, 2)
        row.retention_d7 = round(stats.retention_d7, 3)
        await self.session.flush()
        return row

    async def search(
        self,
        query: str = "",
        *,
        code: str | None = None,
        username: str | None = None,
        tg_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        media_only: bool = False,
        hashtag: str | None = None,
        limit: int = 50,
    ) -> dict[str, list[dict]]:
        """TZ 23: search by code / username / id / name / date / media / text / hashtag."""
        topics: Select = select(Topic).limit(limit)
        if code:
            topics = topics.where(func.upper(Topic.code) == code.upper())
        if query:
            topics = topics.where(func.upper(Topic.code).contains(query.upper()))
        topic_rows = (await self.session.execute(topics)).scalars().all()

        users_stmt = select(User).limit(limit)
        if tg_id:
            users_stmt = users_stmt.where(User.tg_id == tg_id)
        if username:
            users_stmt = users_stmt.where(User.username.ilike(f"%{username}%"))
        if query:
            users_stmt = users_stmt.where(
                User.username.ilike(f"%{query}%")
                | User.first_name.ilike(f"%{query}%")
                | User.last_name.ilike(f"%{query}%")
            )
        user_rows = (await self.session.execute(users_stmt)).scalars().all()

        messages_stmt = select(Message).order_by(Message.id.desc()).limit(limit)
        if query:
            messages_stmt = messages_stmt.where(
                Message.text.ilike(f"%{query}%") | Message.caption.ilike(f"%{query}%")
            )
        if media_only:
            messages_stmt = messages_stmt.where(Message.has_media.is_(True))
        if hashtag:
            tag = hashtag.lstrip("#").strip()
            messages_stmt = messages_stmt.where(Message.text.ilike(f"%#{tag}%"))
        if since:
            messages_stmt = messages_stmt.where(Message.created_at >= since)
        if until:
            messages_stmt = messages_stmt.where(Message.created_at <= until)
        message_rows = (await self.session.execute(messages_stmt)).scalars().all()
        if hashtag:
            # keep only whole tags: '#bash' must not match '#bashraf'
            pattern = re.compile(rf"(^|\s)#{re.escape(hashtag.lstrip('#').strip())}(\s|$|[.,!?])")
            message_rows = [
                row
                for row in message_rows
                if row.text and pattern.search(row.text)
            ]

        return {
            "topics": [
                {"id": t.id, "code": t.code, "status": t.status, "messages": t.message_count}
                for t in topic_rows
            ],
            "users": [
                {"id": u.id, "tg_id": u.tg_id, "username": u.username, "name": u.full_name,
                 "role": u.role, "messages": u.messages_sent}
                for u in user_rows
            ],
            "messages": [
                {"id": m.id, "topic_id": m.topic_id, "type": m.content_type,
                 "text": (m.text or m.caption or "")[:200], "at": m.created_at.isoformat()
                 if m.created_at else None}
                for m in message_rows
            ],
        }

    # ----------------------------------------------------------- helpers
    @staticmethod
    def _average_length_stmt() -> Select:
        """Average messages per topic, computed from the messages table itself.

        ``Topic.message_count`` is a denormalised counter maintained by the relay
        and can lag (or be zero for rows written by migrations/scripts), so the
        dashboard derives the number from the source of truth.
        """
        per_topic = (
            select(Message.topic_id.label("topic_id"), func.count().label("total"))
            .group_by(Message.topic_id)
            .subquery()
        )
        return select(func.coalesce(func.avg(per_topic.c.total), 0.0)).select_from(per_topic)

    async def _count(self, stmt: Select) -> int:
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def _float(self, stmt: Select) -> float:
        return float((await self.session.execute(stmt)).scalar_one() or 0.0)

    async def _status_count(self, status: TopicStatus) -> int:
        return await self._count(
            select(func.count()).select_from(Topic).where(Topic.status == status.value)
        )

    async def _average_topic_days(self) -> float:
        rows = (
            await self.session.execute(
                select(Topic.created_at, Topic.closed_at).where(Topic.closed_at.is_not(None))
            )
        ).all()
        if not rows:
            return 0.0
        deltas = [
            (aware(closed) - aware(created)).total_seconds() / 86400.0
            for created, closed in rows
            if created and closed
        ]
        return round(sum(deltas) / len(deltas), 2) if deltas else 0.0

    async def _retention(self, days: int = 7) -> float:
        cutoff = utcnow() - timedelta(days=days)
        cohort = await self._count(
            select(func.count()).select_from(User).where(User.created_at < cutoff)
        )
        if cohort == 0:
            return 0.0
        active = await self._count(
            select(func.count(func.distinct(Message.sender_id))).where(Message.created_at >= cutoff)
        )
        return round(active / cohort, 3)

    async def _top_users(self, limit: int = 10) -> list[dict]:
        rows = (
            await self.session.execute(
                select(User)
                .where(User.messages_sent > 0)
                .order_by(User.messages_sent.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [
            {"id": u.id, "tg_id": u.tg_id, "name": u.full_name, "username": u.username,
             "messages": u.messages_sent, "topics": u.topics_created}
            for u in rows
        ]

    async def _top_hours(self) -> list[dict]:
        """Hour-of-day histogram, aggregated by the database."""
        hour = hour_expression(Message.created_at).label("hour")
        rows = (
            await self.session.execute(
                select(hour, func.count().label("total"))
                .where(Message.created_at.is_not(None))
                .group_by(hour)
                .order_by(func.count().desc())
            )
        ).all()
        return [{"hour": int(value), "messages": int(total)} for value, total in rows]

    async def _top_media(self, limit: int = 5) -> list[dict]:
        rows = (
            await self.session.execute(
                select(Media.kind, func.count().label("total"), func.sum(Media.file_size).label("size"))
                .group_by(Media.kind)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
        return [{"kind": kind, "count": int(total), "bytes": int(size or 0)} for kind, total, size in rows]

    @staticmethod
    def _fill_gaps(series: list[dict], days: int) -> list[dict]:
        by_day = {item["day"]: item for item in series}
        out: list[dict] = []
        now = utcnow().date()
        for offset in range(days - 1, -1, -1):
            day = (now - timedelta(days=offset)).isoformat()
            out.append(by_day.get(day, {"day": day, "messages": 0, "topics": 0}))
        return out


MEDIA_KINDS = [kind.value for kind in MediaKind]
CONTENT_TYPES = [ct.value for ct in MessageContentType]