"""TZ 12 — one partner, invite link only."""

from __future__ import annotations

import pytest

from app.enums import InviteStatus, ParticipantRole
from app.services.invite_service import InviteError, InviteService
from tests.conftest import make_topic


async def test_owner_creates_a_single_use_link(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = InviteService(session)

    created = await service.create(topic, owner)

    assert created.invite.max_uses == 1
    assert created.invite.status == InviteStatus.PENDING.value
    assert created.url.endswith(f"inv_{created.invite.token}")
    assert "start=inv_" in created.url


async def test_partner_accepts_and_gains_write_access(session, owner, partner, gateway):
    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)

    accepted = await service.accept(created.invite.token, partner)

    assert accepted.partner_id == partner.id
    assert created.invite.status == InviteStatus.ACCEPTED.value
    assert created.invite.uses == 1
    from sqlalchemy import select

    from app.models.topic import TopicParticipant

    rows = (
        await session.execute(select(TopicParticipant).where(TopicParticipant.topic_id == topic.id))
    ).scalars().all()
    assert {row.role for row in rows} == {ParticipantRole.OWNER.value, ParticipantRole.PARTNER.value}


async def test_invite_cannot_be_used_twice(session, owner, partner, outsider, gateway):
    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)
    await service.accept(created.invite.token, partner)

    with pytest.raises(InviteError):
        await service.accept(created.invite.token, outsider)


async def test_owner_cannot_become_partner_of_own_topic(session, owner, gateway):
    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)

    with pytest.raises(InviteError):
        await service.accept(created.invite.token, owner)


async def test_only_one_partner_slot(session, owner, partner, outsider, gateway):
    topic = await make_topic(session, owner)
    service = InviteService(session)
    first = await service.create(topic, owner)
    await service.accept(first.invite.token, partner)

    with pytest.raises(InviteError):
        await service.create(topic, owner)


async def test_partner_cannot_invite(session, owner, partner, gateway):
    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)
    await service.accept(created.invite.token, partner)

    with pytest.raises(InviteError):
        await service.create(topic, partner)


async def test_expired_invite_is_refused(session, owner, partner, gateway):
    from datetime import UTC, datetime, timedelta

    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)
    created.invite.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await session.flush()

    with pytest.raises(InviteError):
        await service.accept(created.invite.token, partner)


async def test_partner_can_leave_and_slot_frees_up(session, owner, partner, outsider, gateway):
    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)
    await service.accept(created.invite.token, partner)

    await service.leave(topic, partner)
    assert topic.partner_id is None

    second = await service.create(topic, owner)
    await service.accept(second.invite.token, outsider)
    assert topic.partner_id == outsider.id
