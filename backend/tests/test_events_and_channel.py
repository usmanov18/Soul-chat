"""TZ 13/14/15/25 — events, channel posts, gallery caption, scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.enums import EventKind, EventStatus
from app.services.event_service import (
    ChannelService,
    EventDraft,
    EventError,
    EventService,
    GalleryCard,
    SchedulerService,
)
from tests.conftest import make_topic


async def test_owner_creates_an_event(session, owner, gateway):
    topic = await make_topic(session, owner)
    due = datetime.now(UTC) + timedelta(days=1)
    event = await EventService(session, gateway).create(
        topic, owner, EventDraft(kind=EventKind.DATE, title="Ilk uchrashuv", due_at=due, location="Toshkent")
    )
    assert event.kind == EventKind.DATE.value
    assert event.location == "Toshkent"
    assert event.status == EventStatus.SCHEDULED.value


async def test_outsider_cannot_create_event(session, owner, outsider, gateway):
    topic = await make_topic(session, owner)
    with pytest.raises(EventError):
        await EventService(session, gateway).create(topic, outsider, EventDraft(title="x"))


async def test_checklist_completes_when_all_ticked(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = EventService(session, gateway)
    event = await service.create(
        topic, owner, EventDraft(kind=EventKind.CHECKLIST, title="Reja", checklist=["[ ] a", "[ ] b"])
    )
    await service.toggle_checklist(event, 0)
    assert event.status == EventStatus.SCHEDULED.value
    await service.toggle_checklist(event, 1)
    assert event.status == EventStatus.DONE.value
    assert event.completed_at is not None


async def test_due_events_are_found(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = EventService(session, gateway)
    await service.create(
        topic, owner, EventDraft(title="Ertaga", remind_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await service.create(
        topic, owner, EventDraft(title="Keyingi hafta", remind_at=datetime.now(UTC) + timedelta(days=7))
    )
    due = await service.due()
    assert [event.title for event in due] == ["Ertaga"]


async def test_new_topic_announcement_contains_code_not_names(session, owner, partner, gateway):
    topic = await make_topic(session, owner, code="A-0028")
    service = ChannelService(session, gateway)
    message_id = await service.announce_topic(topic, owner, partner)

    text = gateway.sent("send_message")[0].args[1]
    assert message_id is not None
    assert "A-0028" in text
    assert "Yangi suhbat boshlandi" in text
    assert topic.channel_post_id == message_id


def test_gallery_caption_layout():
    service = ChannelService.__new__(ChannelService)
    card = GalleryCard(
        topic_code="A-041", owner_name="Akbar", partner_name="Salima", caption="Bugun ilk uchrashuv.",
        location="Toshkent", when=datetime(2026, 9, 20, 19, 0, tzinfo=UTC),
    )
    caption = service.render_gallery_caption(card)
    assert caption.splitlines()[0] == "🌸"
    assert "A-041" in caption
    assert "Akbar ❤️ Salima" in caption
    assert "📍 Toshkent" in caption
    assert "🕒 19:00" in caption


async def test_gallery_post_is_published_and_recorded(session, owner, partner, gateway):
    from sqlalchemy import select

    from app.models.message import ChannelPost

    topic = await make_topic(session, owner)
    service = ChannelService(session, gateway)
    card = GalleryCard("A-041", "Akbar", "Salima", "ilk uchrashuv", "Toshkent", datetime.now(UTC))

    message_id = await service.publish_gallery(topic, owner, partner, "AgADBA", card)

    assert message_id is not None
    assert len(gateway.sent("send_photo")) == 1
    rows = (await session.execute(select(ChannelPost))).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "gallery"


async def test_channel_failure_is_recorded_not_raised(session, owner, gateway):
    from sqlalchemy import select

    from app.models.message import ChannelPost

    topic = await make_topic(session, owner)
    gateway.fail_on.add("send_message")

    assert await ChannelService(session, gateway).announce_topic(topic, owner) is None
    row = (await session.execute(select(ChannelPost))).scalar_one()
    assert row.failed_reason is not None


async def test_schedule_window_evaluation(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = SchedulerService(session, gateway)
    await service.set_window(topic, [1, 2, 3], "20:00", "22:00")

    inside = datetime(2026, 9, 21, 21, 0, tzinfo=UTC)     # Monday 21:00
    outside = datetime(2026, 9, 21, 23, 0, tzinfo=UTC)    # Monday 23:00
    assert service.evaluate(topic, inside).should_be_open is True
    assert service.evaluate(topic, outside).should_be_open is False


async def test_overnight_window(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = SchedulerService(session, gateway)
    await service.set_window(topic, [0, 1, 2, 3, 4, 5, 6], "22:00", "02:00")
    assert service.evaluate(topic, datetime(2026, 9, 21, 23, 30, tzinfo=UTC)).should_be_open is True
    assert service.evaluate(topic, datetime(2026, 9, 21, 1, 30, tzinfo=UTC)).should_be_open is True
    assert service.evaluate(topic, datetime(2026, 9, 21, 12, 0, tzinfo=UTC)).should_be_open is False


async def test_tick_opens_and_closes_topics(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = SchedulerService(session, gateway)
    await service.set_window(topic, [1], "20:00", "22:00")

    closed = await service.tick(datetime(2026, 9, 21, 23, 0, tzinfo=UTC))
    assert closed["closed"] == [topic.code]
    assert topic.is_closed is True
    assert gateway.closed_topics == [(topic.chat_id, topic.message_thread_id)]

    opened = await service.tick(datetime(2026, 9, 21, 21, 0, tzinfo=UTC))
    assert opened["opened"] == [topic.code]
    assert topic.is_closed is False


async def test_invalid_window_is_rejected(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = SchedulerService(session, gateway)
    with pytest.raises(EventError):
        await service.set_window(topic, [1], "25:00", "22:00")
