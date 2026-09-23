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


# ---------------------------------------------------------------------------
# concurrency + partner slot limit
# ---------------------------------------------------------------------------
async def test_concurrent_claims_leave_exactly_one_partner(session, owner, partner, outsider, gateway):
    """Two people open the same link at the same instant — only one may win."""
    import asyncio

    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)

    async def claim(user):
        try:
            await service.accept(created.invite.token, user)
            return "ok"
        except InviteError as exc:
            return f"err:{exc}"

    results = await asyncio.gather(claim(partner), claim(outsider))

    assert results.count("ok") == 1
    assert topic.partner_id in {partner.id, outsider.id}
    assert created.invite.uses == 1


async def test_user_cannot_hold_two_partner_slots(session, owner, partner, gateway, monkeypatch):
    from app.core.config import settings
    from app.models.user import User

    monkeypatch.setattr(settings, "max_partner_topics", 1)

    second_owner = User(tg_id=555, username="ikkinchi", first_name="Ikkinchi", gender="male")
    session.add(second_owner)
    await session.flush()

    first_topic = await make_topic(session, owner, code="A-0001")
    second_topic = await make_topic(session, second_owner, code="A-0002")

    service = InviteService(session)
    first_invite = await service.create(first_topic, owner)
    await service.accept(first_invite.invite.token, partner)

    second_invite = await service.create(second_topic, second_owner)
    with pytest.raises(InviteError):
        await service.accept(second_invite.invite.token, partner)


async def test_partner_slot_limit_is_configurable(session, owner, partner, gateway, monkeypatch):
    from app.core.config import settings
    from app.models.user import User

    monkeypatch.setattr(settings, "max_partner_topics", 2)

    second_owner = User(tg_id=556, username="uchinchi", first_name="Uchinchi", gender="male")
    session.add(second_owner)
    await session.flush()

    first_topic = await make_topic(session, owner, code="A-0003")
    second_topic = await make_topic(session, second_owner, code="A-0004")

    service = InviteService(session)
    await service.accept((await service.create(first_topic, owner)).invite.token, partner)
    await service.accept((await service.create(second_topic, second_owner)).invite.token, partner)

    assert first_topic.partner_id == partner.id
    assert second_topic.partner_id == partner.id


async def test_leaving_frees_the_slot(session, owner, partner, gateway, monkeypatch):
    from app.core.config import settings
    from app.models.user import User

    monkeypatch.setattr(settings, "max_partner_topics", 1)
    second_owner = User(tg_id=557, username="tortinchi", first_name="Tortinchi", gender="male")
    session.add(second_owner)
    await session.flush()

    first_topic = await make_topic(session, owner, code="A-0005")
    second_topic = await make_topic(session, second_owner, code="A-0006")

    service = InviteService(session)
    await service.accept((await service.create(first_topic, owner)).invite.token, partner)
    await service.leave(first_topic, partner)

    await service.accept((await service.create(second_topic, second_owner)).invite.token, partner)
    assert second_topic.partner_id == partner.id


async def test_invite_into_a_closed_topic_is_refused(session, owner, partner, gateway):
    from app.enums import TopicStatus

    topic = await make_topic(session, owner)
    service = InviteService(session)
    created = await service.create(topic, owner)
    topic.status = TopicStatus.ARCHIVED.value
    await session.flush()

    with pytest.raises(InviteError):
        await service.accept(created.invite.token, partner)