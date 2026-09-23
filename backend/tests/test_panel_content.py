"""Admin panel content endpoints (TZ 28) — media, events, channel posts,
notifications, subscriptions overview.

Each new router is a read-only listing over tables that already existed; the
tests pin three things: the joined topic code reaches the panel, the filters
actually filter, and the staff guard holds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import create_access_token
from app.enums import (
    ChannelPostType,
    EventKind,
    EventStatus,
    MediaKind,
    NotificationKind,
    NotificationStatus,
    SubscriptionKind,
    SubscriptionStatus,
)
from app.models.log import Notification
from app.models.message import ChannelPost, Event, Media, Message
from app.models.user import Subscription
from tests.conftest import make_topic


@pytest.fixture
async def topic(session, owner):
    return await make_topic(session, owner, code="A-0042")


async def _add_message(session, topic, *, has_media: bool = False) -> Message:
    message = Message(
        topic_id=topic.id,
        sender_id=topic.owner_tg_id or 0,
        text="salom" if not has_media else None,
        has_media=has_media,
    )
    session.add(message)
    await session.flush()
    return message


async def test_media_list_joins_topic_code(client, session, topic):
    message = await _add_message(session, topic, has_media=True)
    session.add(
        Media(
            topic_id=topic.id,
            message_id=message.id,
            kind=MediaKind.PHOTO.value,
            file_id="photo-file-id",
            file_size=2048,
            width=800,
            height=600,
            mime_type="image/jpeg",
        )
    )
    await session.flush()

    response = await client.get("/api/v1/media")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["topic_code"] == "A-0042"
    assert item["kind"] == "photo"
    assert item["file_size"] == 2048
    assert item["width"] == 800


async def test_media_kind_filter(client, session, topic):
    message = await _add_message(session, topic, has_media=True)
    session.add(
        Media(topic_id=topic.id, message_id=message.id, kind=MediaKind.PHOTO.value, file_id="p1")
    )
    session.add(
        Media(topic_id=topic.id, message_id=message.id, kind=MediaKind.VIDEO.value, file_id="v1")
    )
    await session.flush()

    response = await client.get("/api/v1/media", params={"kind": "video"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["kind"] == "video"


async def test_media_topic_code_filter(client, session, topic, owner):
    message = await _add_message(session, topic, has_media=True)
    session.add(
        Media(topic_id=topic.id, message_id=message.id, kind=MediaKind.PHOTO.value, file_id="p1")
    )
    other = await make_topic(session, owner, code="A-0002", thread_id=2000)
    session.add(Media(topic_id=other.id, kind=MediaKind.PHOTO.value, file_id="p2"))
    await session.flush()

    response = await client.get("/api/v1/media", params={"topic_code": "A-0002"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["topic_code"] == "A-0002"


async def test_media_requires_staff(client, owner):
    client.headers["Authorization"] = f"Bearer {create_access_token(owner.id, {'role': owner.role})}"
    response = await client.get("/api/v1/media")
    assert response.status_code == 403


async def test_events_list_and_status_filter(client, session, topic, owner):
    session.add(
        Event(
            topic_id=topic.id,
            created_by=owner.id,
            kind=EventKind.DATE.value,
            title="Ilk uchrashuv",
            due_at=datetime.now(UTC) + timedelta(days=1),
            location="Toshkent",
        )
    )
    session.add(
        Event(
            topic_id=topic.id,
            created_by=owner.id,
            kind=EventKind.REMINDER.value,
            title="Eslatma",
            status=EventStatus.DONE.value,
        )
    )
    await session.flush()

    listing = await client.get("/api/v1/events")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert listing.json()["items"][0]["topic_code"] == "A-0042"

    done = await client.get("/api/v1/events", params={"status": "done"})
    assert done.status_code == 200
    body = done.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Eslatma"


async def test_channel_posts_include_orphans(client, session, topic):
    session.add(
        ChannelPost(
            topic_id=topic.id,
            kind=ChannelPostType.NEW_TOPIC.value,
            tg_message_id=41,
            text="✨ Yangi suhbat boshlandi",
            published_at=datetime.now(UTC),
        )
    )
    # a gallery post whose topic row is gone must still be visible
    session.add(
        ChannelPost(
            kind=ChannelPostType.GALLERY.value,
            failed_reason="chat not found",
        )
    )
    await session.flush()

    response = await client.get("/api/v1/channel-posts")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    by_kind = {item["kind"]: item for item in body["items"]}
    assert by_kind["new_topic"]["topic_code"] == "A-0042"
    assert by_kind["gallery"]["topic_code"] is None
    assert by_kind["gallery"]["failed_reason"] == "chat not found"


async def test_channel_posts_kind_filter(client, session, topic):
    session.add(ChannelPost(topic_id=topic.id, kind=ChannelPostType.NEW_TOPIC.value))
    session.add(ChannelPost(topic_id=topic.id, kind=ChannelPostType.GALLERY.value))
    await session.flush()

    response = await client.get("/api/v1/channel-posts", params={"kind": "gallery"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["kind"] == "gallery"


async def test_notifications_list_with_user(client, session, owner):
    session.add(
        Notification(
            user_id=owner.id,
            kind=NotificationKind.REMINDER.value,
            title="Eslatma",
            body="2 soatdan keyin uchrashuv",
            status=NotificationStatus.SENT.value,
        )
    )
    session.add(
        Notification(
            user_id=owner.id,
            kind=NotificationKind.SYSTEM_NEWS.value,
            body="yangilik",
            status=NotificationStatus.FAILED.value,
            error="bot blocked",
        )
    )
    await session.flush()

    response = await client.get("/api/v1/notifications")
    assert response.status_code == 200
    assert response.json()["total"] == 2
    item = response.json()["items"][0]
    assert item["tg_id"] == owner.tg_id
    assert item["username"] == "akbar"

    failed = await client.get("/api/v1/notifications", params={"status": "failed"})
    assert failed.status_code == 200
    body = failed.json()
    assert body["total"] == 1
    assert body["items"][0]["error"] == "bot blocked"


async def test_subscriptions_overview(client, session, owner):
    session.add(
        Subscription(
            user_id=owner.id,
            kind=SubscriptionKind.GROUP.value,
            chat_id=-100123,
            is_member=True,
            status=SubscriptionStatus.MEMBER.value,
            checked_at=datetime.now(UTC),
        )
    )
    session.add(
        Subscription(
            user_id=owner.id,
            kind=SubscriptionKind.CHANNEL.value,
            chat_id=-100321,
            is_member=False,
            status=SubscriptionStatus.LEFT.value,
        )
    )
    await session.flush()

    response = await client.get("/api/v1/subscriptions")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2

    missing = await client.get("/api/v1/subscriptions", params={"is_member": "false"})
    assert missing.status_code == 200
    items = missing.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "channel"
    assert items[0]["username"] == "akbar"
