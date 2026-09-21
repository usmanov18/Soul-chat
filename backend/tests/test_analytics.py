"""TZ 21/23 — analytics and search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.enums import MessageContentType, TopicStatus
from app.models.message import Media, Message
from app.services.analytics_service import AnalyticsService
from tests.conftest import make_topic


async def _seed(session, owner, partner):
    topic = await make_topic(session, owner, code="A-0001")
    topic.partner_id = partner.id
    topic.status = TopicStatus.ACTIVE.value
    topic.closed_at = datetime.now(UTC)
    for index in range(5):
        session.add(Message(topic_id=topic.id, sender_id=owner.id, content_type="text",
                            text=f"salom {index}"))
    session.add(Message(topic_id=topic.id, sender_id=partner.id,
                        content_type=MessageContentType.PHOTO.value, has_media=True, file_id="f1"))
    session.add(Media(topic_id=topic.id, kind=MessageContentType.PHOTO.value, file_id="f1", file_size=2048))
    await session.flush()
    return topic


async def test_dashboard_counts(session, owner, partner):
    await _seed(session, owner, partner)
    stats = await AnalyticsService(session).dashboard()

    assert stats.total_topics == 1
    assert stats.total_messages == 6
    assert stats.total_media == 1
    assert stats.active_topics == 1
    assert stats.average_chat_length == 6.0
    assert stats.average_days >= 0.0


async def test_top_users_and_hours(session, owner, partner):
    await _seed(session, owner, partner)
    owner.messages_sent = 5
    partner.messages_sent = 1
    await session.flush()

    stats = await AnalyticsService(session).dashboard()
    assert stats.top_users[0]["tg_id"] == owner.tg_id
    assert stats.top_active_hours
    assert stats.top_media[0]["kind"] == MessageContentType.PHOTO.value


async def test_daily_series_fills_missing_days(session, owner, partner):
    await _seed(session, owner, partner)
    series = await AnalyticsService(session).daily_series(days=7)
    assert len(series) == 7
    assert sum(item["messages"] for item in series) == 6


async def test_weekly_and_monthly_buckets(session, owner, partner):
    await _seed(session, owner, partner)
    service = AnalyticsService(session)
    assert len(await service.weekly(4)) == 4
    assert len(await service.monthly(6)) == 6


async def test_snapshot_is_idempotent(session, owner, partner):
    from sqlalchemy import select

    from app.models.log import StatDaily

    await _seed(session, owner, partner)
    service = AnalyticsService(session)
    first = await service.snapshot()
    second = await service.snapshot()
    assert first.id == second.id
    rows = (await session.execute(select(StatDaily))).scalars().all()
    assert len(rows) == 1


async def test_search_by_code_username_and_text(session, owner, partner):
    await _seed(session, owner, partner)
    service = AnalyticsService(session)

    by_code = await service.search(code="a-0001")
    assert len(by_code["topics"]) == 1

    by_user = await service.search(username="akbar")
    assert len(by_user["users"]) == 1

    by_text = await service.search(query="salom")
    assert len(by_text["messages"]) == 5

    media_only = await service.search(media_only=True)
    assert len(media_only["messages"]) == 1


async def test_search_by_tg_id_and_date_range(session, owner, partner):
    await _seed(session, owner, partner)
    service = AnalyticsService(session)
    assert len((await service.search(tg_id=owner.tg_id))["users"]) == 1
    future = datetime.now(UTC) + timedelta(days=1)
    assert (await service.search(query="salom", since=future))["messages"] == []
