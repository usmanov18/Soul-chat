"""TZ 6/17/18/19/20 — topic lifecycle and the state machine."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.enums import TopicStatus, TopicStatusFlow
from app.services.topic_service import TopicError, TopicService
from tests.conftest import make_topic


async def test_create_makes_a_telegram_topic_named_only_with_the_code(session, owner, gateway, monkeypatch):
    monkeypatch.setattr(settings, "forum_chat_id", -100123)
    monkeypatch.setattr(settings, "subscription_required", False)
    service = TopicService(session, gateway)

    created = await service.create(owner.tg_id)

    assert created.topic.code == created.topic.title          # TZ 10: name == code only
    assert created.code.startswith("A")
    assert gateway.topics_created == [(-100123, created.code, settings.topic_icon_color)]
    assert created.topic.message_thread_id is not None
    assert created.topic.owner_id == owner.id
    assert owner.topics_created == 1

    from sqlalchemy import select

    from app.models.topic import TopicParticipant

    participants = (
        await session.execute(
            select(TopicParticipant).where(TopicParticipant.topic_id == created.topic.id)
        )
    ).scalars().all()
    assert len(participants) == 1
    assert participants[0].role == "owner"


async def test_create_respects_per_user_limit(session, owner, gateway, monkeypatch):
    monkeypatch.setattr(settings, "max_topics_per_user", 2)
    service = TopicService(session, gateway)
    await service.create(owner.tg_id)
    await service.create(owner.tg_id)

    with pytest.raises(TopicError):
        await service.create(owner.tg_id)


async def test_block_closes_the_telegram_topic(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)

    await service.block(topic, owner)

    assert topic.status == TopicStatus.BLOCKED.value
    assert topic.is_closed is True
    assert topic.closed_at is not None
    assert gateway.closed_topics == [(topic.chat_id, topic.message_thread_id)]


async def test_delete_pending_arms_the_96_hour_timer(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)

    delete_at = await service.schedule_deletion(topic)

    assert topic.status == TopicStatus.DELETE_PENDING.value
    assert topic.delete_at == delete_at
    from app.core.timeutil import aware

    remaining = (delete_at - aware(topic.created_at)).total_seconds() / 3600
    assert settings.delete_pending_hours - 1 <= remaining <= settings.delete_pending_hours + 1


async def test_restore_reopens_the_topic(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)
    await service.block(topic, owner)
    await service.schedule_deletion(topic)

    await service.restore(topic, owner)

    assert topic.status == TopicStatus.ACTIVE.value
    assert topic.is_closed is False
    assert topic.delete_at is None
    assert topic.restore_count == 1
    assert gateway.reopened_topics == [(topic.chat_id, topic.message_thread_id)]


async def test_hard_delete_removes_the_telegram_topic(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)

    assert await service.hard_delete(topic) is True
    assert topic.status == TopicStatus.DELETED.value
    assert gateway.deleted_topics == [(topic.chat_id, topic.message_thread_id)]


async def test_illegal_transitions_are_rejected(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)
    await service.hard_delete(topic)

    with pytest.raises(TopicError):
        await service.transition(topic, TopicStatus.ACTIVE)


def test_status_flow_matrix():
    assert TopicStatusFlow.can(TopicStatus.ACTIVE, TopicStatus.DELETE_PENDING)
    assert TopicStatusFlow.can(TopicStatus.DELETE_PENDING, TopicStatus.ACTIVE)
    assert not TopicStatusFlow.can(TopicStatus.DELETED, TopicStatus.ACTIVE)
    assert not TopicStatusFlow.can(TopicStatus.DRAFT, TopicStatus.BLOCKED)


async def test_freeze_and_archive(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)

    await service.freeze(topic, owner, "spam")
    assert topic.status == TopicStatus.FROZEN.value

    await service.archive(topic, owner)
    assert topic.status == TopicStatus.ARCHIVED.value
    assert gateway.closed_topics == [(topic.chat_id, topic.message_thread_id)]


async def test_by_code_is_case_insensitive(session, owner, gateway):
    topic = await make_topic(session, owner, code="M-1002")
    service = TopicService(session, gateway)
    assert (await service.by_code("m-1002")).id == topic.id