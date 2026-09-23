"""A closed conversation must stay *reachable*.

TZ 18-20 promise a 96 hour window in which either user can ``/restore``, and
that an archive is produced before anything is deleted. Both of those only work
if the bot can still find the topic after it stopped being writable.

``current_topic`` used to filter by status, so a frozen / blocked / pending
topic resolved to ``None`` and every command answered "you have no chat, press
/new" — pushing the user towards creating a fresh topic and silently
abandoning the one they could still have rescued. These tests pin the fix.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.enums import MessageContentType, TopicStatus
from app.services.bot_service import SoulChatBot
from app.services.relay import DenyReason, IncomingMessage, RelayService
from tests.conftest import make_topic


@pytest.fixture
def bot(session, gateway, monkeypatch):
    monkeypatch.setattr(settings, "subscription_required", False)
    monkeypatch.setattr(settings, "forum_chat_id", -100123)
    monkeypatch.setattr(settings, "channel_id", -100999)
    return SoulChatBot(session, gateway)


def text(uid: int, body: str = "salom") -> IncomingMessage:
    return IncomingMessage(
        user_id=uid, chat_id=1, content_type=MessageContentType.TEXT.value, text=body
    )


# --------------------------------------------------------------------------
# 1. the relay reports the precise reason on the real (bot) code path
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "expected", "snippet"),
    [
        (TopicStatus.FROZEN.value, DenyReason.FROZEN, "muzlatilgan"),
        (TopicStatus.BLOCKED.value, DenyReason.BLOCKED, "yopilgan"),
        (TopicStatus.DELETE_PENDING.value, DenyReason.DELETE_PENDING, "/restore"),
        (TopicStatus.ARCHIVED.value, DenyReason.NOT_ACTIVE, "imkoni yo'q"),
    ],
)
async def test_user_is_told_why_not_told_they_have_no_chat(
    session, owner, gateway, status, expected, snippet
):
    """Regression: all four of these used to answer NO_TOPIC ("press /new")."""
    topic = await make_topic(session, owner)
    topic.status = status  # already the enum's value string
    await session.flush()

    result = await RelayService(session, gateway).relay_private(text(owner.tg_id))

    assert result.ok is False
    assert result.reason is expected
    assert result.reason is not DenyReason.NO_TOPIC
    assert snippet in result.reply


async def test_the_topic_is_still_resolvable_when_closed(session, owner, gateway):
    """`current_topic` is the lookup every command depends on."""
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)
    assert await relay.current_topic(owner.tg_id) is topic

    for status in TopicStatus:
        topic.status = status.value
        await session.flush()
        found = await relay.current_topic(owner.tg_id)
        assert found is topic, f"{status.value}: topic lost"


async def test_writable_topic_still_refuses_to_hand_out_a_closed_topic(
    session, owner, gateway
):
    """The split must not leak: mutating commands stay locked to ACTIVE."""
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)
    assert await relay.writable_topic(owner.tg_id) is topic

    topic.status = TopicStatus.BLOCKED.value
    await session.flush()
    assert await relay.writable_topic(owner.tg_id) is None
    # ...while the read path still sees it
    assert await relay.current_topic(owner.tg_id) is topic


# --------------------------------------------------------------------------
# 2. the commands that rescue a closed chat
# --------------------------------------------------------------------------
async def test_archive_works_on_a_blocked_topic(bot, session, owner, tmp_path, monkeypatch):
    """The whole point of the 96h window: take the archive with you."""
    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.BLOCKED.value
    await session.flush()

    reply = await bot.archive(owner.tg_id)

    assert "topilmadi" not in reply.text
    assert reply.document is not None
    payload, filename = reply.document
    assert filename.endswith(".zip")
    assert payload.startswith(b"PK")  # a real zip, not an empty stub


async def test_archive_works_while_deletion_is_pending(bot, session, owner, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.DELETE_PENDING.value
    await session.flush()

    reply = await bot.archive(owner.tg_id)

    assert "topilmadi" not in reply.text
    assert reply.document is not None
    assert reply.document[1].endswith(".zip")


async def test_status_reports_a_frozen_topic(bot, session, owner):
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.FROZEN.value
    await session.flush()

    reply = await bot.status(owner.tg_id)

    assert topic.code in reply.text


async def test_invite_is_refused_on_a_frozen_topic(bot, session, owner):
    """Inviting mutates the topic, so a frozen one must not accept it."""
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.FROZEN.value
    await session.flush()

    reply = await bot.invite(owner.tg_id)

    assert "inv_" not in reply.text


# --------------------------------------------------------------------------
# 3. the central promise survives every state: only two people write
# --------------------------------------------------------------------------
async def test_only_the_two_writers_ever_get_through(session, owner, partner, outsider, gateway):
    topic = await make_topic(session, owner)
    topic.partner_id = partner.id
    topic.partner_tg_id = partner.tg_id
    await session.flush()

    relay = RelayService(session, gateway)

    for status in TopicStatus:
        topic.status = status.value
        await session.flush()
        before = len(gateway.sent("send_message"))

        owner_result = await relay.relay_private(text(owner.tg_id, "egadan"))
        partner_result = await relay.relay_private(text(partner.tg_id, "sherikdan"))
        outsider_result = await relay.relay_private(text(outsider.tg_id, "begonadan"))

        # a non-writer never gets in, whatever the status
        assert outsider_result.ok is False
        assert outsider_result.reason is DenyReason.NO_TOPIC
        # and nothing reaches the group from any of them unless ACTIVE
        allowed = status is TopicStatus.ACTIVE
        assert owner_result.ok is allowed
        assert partner_result.ok is allowed
        assert len(gateway.sent("send_message")) - before == (2 if allowed else 0)


async def test_removing_the_partner_revokes_writing_immediately(
    session, owner, partner, outsider, gateway
):
    topic = await make_topic(session, owner)
    topic.partner_id = partner.id
    topic.partner_tg_id = partner.tg_id
    await session.flush()
    relay = RelayService(session, gateway)

    assert (await relay.relay_private(text(partner.tg_id, "salom"))).ok is True

    topic.partner_id = None
    topic.partner_tg_id = None
    await session.flush()

    result = await relay.relay_private(text(partner.tg_id, "yana salom"))
    assert result.ok is False
    assert result.reason is DenyReason.NO_TOPIC
    assert len(topic.writer_ids) == 1