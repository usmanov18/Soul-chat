"""TZ 11/12 — the relay engine that enforces "only two people can write"."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.enums import MessageContentType, TopicStatus
from app.models.topic import TopicParticipant
from app.services.relay import DenyReason, IncomingMessage, RelayService
from tests.conftest import make_topic


def text(user_id: int, body: str) -> IncomingMessage:
    return IncomingMessage(user_id=user_id, chat_id=1, content_type=MessageContentType.TEXT.value, text=body)


async def test_owner_can_write_and_message_is_relayed_into_thread(session, owner, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)

    result = await relay.relay_private(text(owner.tg_id, "Salom"))

    assert result.ok is True
    assert result.reason is DenyReason.OK
    sent = gateway.sent("send_message")
    assert len(sent) == 1
    call = sent[0]
    assert call.args[0] == topic.chat_id
    assert call.kwargs["thread_id"] == topic.message_thread_id
    assert "Salom" in call.args[1]
    assert "Akbar" in call.args[1]  # attributed to the sender


async def test_partner_can_write_after_being_added(session, owner, partner, gateway):
    topic = await make_topic(session, owner)
    topic.partner_id = partner.id
    topic.partner_tg_id = partner.tg_id
    session.add(TopicParticipant(topic_id=topic.id, user_id=partner.id, role="partner"))
    await session.flush()
    relay = RelayService(session, gateway)

    result = await relay.relay_private(text(partner.tg_id, "Assalomu alaykum"))

    assert result.ok is True
    assert "Salima" in gateway.sent("send_message")[0].args[1]


async def test_third_person_has_no_topic_of_their_own(session, owner, outsider, gateway):
    await make_topic(session, owner)
    relay = RelayService(session, gateway)

    result = await relay.relay_private(text(outsider.tg_id, "Men ham yozmoqchiman"))

    assert result.ok is False
    assert result.reason is DenyReason.NO_TOPIC
    assert gateway.sent("send_message") == []
    assert "/new" in result.reply


async def test_third_person_is_denied_on_somebody_elses_topic(session, owner, outsider, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)

    permission = await relay.permission_for(outsider.tg_id, topic)

    assert permission.allowed is False
    assert permission.reason is DenyReason.NOT_WRITER


async def test_group_lockdown_strips_every_send_permission(session, owner, gateway):
    relay = RelayService(session, gateway)
    await relay.enforce_group_lockdown(chat_id=-100123, tg_id=owner.tg_id)

    chat_id, user_id, permissions, _until = gateway.restrictions[0]
    assert (chat_id, user_id) == (-100123, owner.tg_id)
    assert permissions["can_send_messages"] is False
    assert permissions["can_send_photos"] is False
    assert permissions["can_send_voice_notes"] is False
    assert permissions["can_manage_topics"] is False


async def test_unauthorized_group_message_is_deleted(session, owner, outsider, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)

    deleted = await relay.moderate_group_message(topic.chat_id, 555, outsider.tg_id, topic)

    assert deleted is True
    assert gateway.deleted_messages == [(topic.chat_id, 555)]


async def test_writer_group_message_is_left_alone(session, owner, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)

    deleted = await relay.moderate_group_message(topic.chat_id, 556, owner.tg_id, topic)

    assert deleted is False
    assert gateway.deleted_messages == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (TopicStatus.FROZEN.value, DenyReason.FROZEN),
        (TopicStatus.BLOCKED.value, DenyReason.BLOCKED),
        (TopicStatus.DELETE_PENDING.value, DenyReason.DELETE_PENDING),
        (TopicStatus.ARCHIVED.value, DenyReason.NOT_ACTIVE),
    ],
)
async def test_status_blocks_writing(session, owner, gateway, status, expected):
    topic = await make_topic(session, owner)
    topic.status = status
    await session.flush()
    relay = RelayService(session, gateway)

    # the topic is no longer "current", so address it explicitly
    permission = await relay.permission_for(owner.tg_id, topic)
    assert permission.reason is expected

    result = await relay.relay_private(text(owner.tg_id, "salom"))
    assert result.ok is False
    assert result.reason is DenyReason.NO_TOPIC


async def test_photo_is_relayed_and_stored(session, owner, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)
    incoming = IncomingMessage(
        user_id=owner.tg_id, chat_id=1, content_type=MessageContentType.PHOTO.value,
        file_id="AgADBA", caption="Toshkent",
    )

    result = await relay.relay_private(incoming)

    assert result.ok is True
    assert len(gateway.sent("send_photo")) == 1
    assert topic.media_count == 1
    assert topic.message_count == 1


async def test_location_is_relayed(session, owner, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)
    incoming = IncomingMessage(
        user_id=owner.tg_id, chat_id=1, content_type=MessageContentType.LOCATION.value,
        latitude=41.31, longitude=69.24,
    )

    assert (await relay.relay_private(incoming)).ok is True
    call = gateway.sent("send_location")[0]
    assert call.args[0] == topic.chat_id
    assert call.kwargs["latitude"] == 41.31
    assert call.kwargs["longitude"] == 69.24


async def test_rate_limit_kicks_in(session, owner, gateway, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    await make_topic(session, owner)
    relay = RelayService(session, gateway)

    results = [await relay.relay_private(text(owner.tg_id, f"msg {i}")) for i in range(5)]

    assert sum(1 for r in results if r.ok) == 3
    assert results[-1].reason is DenyReason.RATE_LIMITED


async def test_moderation_can_block_a_message(session, owner, gateway):
    from app.enums import ModerationAction
    from app.services.ai_service import Verdict
    from app.services.relay import RelayService as RS

    await make_topic(session, owner)

    class BlockingModerator:
        async def moderate(self, text, *, user_id=0, topic_id=None):
            return Verdict(action=ModerationAction.BLOCK.value, risk=0.95,
                           labels=["insult"], user_message="Xabar bloklandi.")

    relay = RS(session, gateway, BlockingModerator())
    result = await relay.relay_private(text(owner.tg_id, "sen ahmoqsan"))

    assert result.ok is False
    assert result.reason is DenyReason.MODERATION
    assert gateway.sent("send_message") == []


async def test_no_topic_gives_a_helpful_reply(session, outsider, gateway):
    result = await RelayService(session, gateway).relay_private(text(outsider.tg_id, "salom"))
    assert result.reason is DenyReason.NO_TOPIC
    assert "/new" in result.reply


async def test_counters_and_last_active_topic_are_updated(session, owner, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)
    await relay.relay_private(text(owner.tg_id, "birinchi"))
    await relay.relay_private(text(owner.tg_id, "ikkinchi"))

    assert topic.message_count == 2
    assert topic.first_message_at is not None
    assert owner.last_active_topic_id == topic.id
    assert owner.messages_sent == 2
