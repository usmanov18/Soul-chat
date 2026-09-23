"""TZ 17/18/19 — two sided close code, 96h window, restore."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.enums import TopicStatus
from app.models.topic import TopicParticipant
from app.services.close_service import CloseError, CloseService
from app.services.topic_service import TopicService
from tests.conftest import make_topic


async def _with_partner(session, owner, partner):
    topic = await make_topic(session, owner)
    topic.partner_id = partner.id
    topic.partner_tg_id = partner.tg_id
    session.add(TopicParticipant(topic_id=topic.id, user_id=partner.id, role="partner"))
    await session.flush()
    return topic


async def test_close_requires_both_confirmations(session, owner, partner, gateway):
    topic = await _with_partner(session, owner, partner)
    service = CloseService(session, TopicService(session, gateway))

    started = await service.start(topic, owner)
    assert started.completed is False
    code = started.code.code
    assert len(code) == settings.close_code_length

    first = await service.confirm(topic, owner, code)
    assert first.completed is False
    assert first.owner_confirmed is True
    assert first.partner_confirmed is False
    assert topic.status == TopicStatus.ACTIVE.value   # not closed yet

    second = await service.confirm(topic, partner, code)
    assert second.completed is True
    assert topic.status == TopicStatus.DELETE_PENDING.value
    assert topic.is_closed is True
    assert topic.delete_at is not None


async def test_wrong_code_is_rejected(session, owner, partner, gateway):
    topic = await _with_partner(session, owner, partner)
    service = CloseService(session, TopicService(session, gateway))
    await service.start(topic, owner)

    with pytest.raises(CloseError):
        await service.confirm(topic, owner, "000000")


async def test_outsider_cannot_confirm(session, owner, partner, outsider, gateway):
    topic = await _with_partner(session, owner, partner)
    service = CloseService(session, TopicService(session, gateway))
    started = await service.start(topic, owner)

    with pytest.raises(CloseError):
        await service.confirm(topic, outsider, started.code.code)


async def test_solo_owner_closes_instantly(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = CloseService(session, TopicService(session, gateway))

    started = await service.start(topic, owner)

    assert started.completed is True
    assert started.code is None
    assert topic.status == TopicStatus.DELETE_PENDING.value


async def test_restore_inside_window(session, owner, partner, gateway):
    topic = await _with_partner(session, owner, partner)
    service = CloseService(session, TopicService(session, gateway))
    started = await service.start(topic, owner)
    await service.confirm(topic, owner, started.code.code)
    await service.confirm(topic, partner, started.code.code)

    request = await service.request_restore(topic, owner, "tasodifan")
    await service.approve_restore(request, owner)

    assert topic.status == TopicStatus.ACTIVE.value
    assert topic.is_closed is False


async def test_restore_outside_window_is_refused(session, owner, partner, gateway):
    from datetime import UTC, datetime, timedelta

    topic = await _with_partner(session, owner, partner)
    service = CloseService(session, TopicService(session, gateway))
    started = await service.start(topic, owner)
    await service.confirm(topic, owner, started.code.code)
    await service.confirm(topic, partner, started.code.code)
    topic.delete_at = datetime.now(UTC) - timedelta(hours=1)   # window closed
    await session.flush()

    request = await service.request_restore(topic, owner)
    with pytest.raises(CloseError):
        await service.approve_restore(request, owner)


async def test_expired_close_code_cannot_be_used(session, owner, partner, gateway):
    from datetime import UTC, datetime, timedelta

    topic = await _with_partner(session, owner, partner)
    service = CloseService(session, TopicService(session, gateway))
    started = await service.start(topic, owner)
    started.code.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.flush()

    with pytest.raises(CloseError):
        await service.confirm(topic, owner, started.code.code)