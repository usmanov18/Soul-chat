"""A moderator freeze must be reversible.

``TopicStatusFlow`` always allowed ``FROZEN -> ACTIVE``, but the only way to
perform it was ``POST /topics/{code}/restore``, which borrows the deletion
rescue path (it also clears ``is_closed`` / ``delete_at`` and logs
``topic.restore``). Nothing in the bot could do it at all:

* a frozen user running ``/restore`` got "Tiklanadigan suhbat topilmadi."
* a moderator running ``moderate(action="restore")`` got "Noma'lum amal: restore"

Both were measured against the code before this test was written. These tests
pin the fix and — importantly — that lifting a freeze stays a *staff* action.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.enums import AuditAction, MessageContentType, TopicStatus
from app.models.log import AuditLog
from app.services.bot_service import SoulChatBot
from app.services.relay import IncomingMessage, RelayService
from app.services.topic_service import TopicError, TopicService
from tests.conftest import make_topic


@pytest.fixture
def bot(session, gateway, monkeypatch):
    monkeypatch.setattr(settings, "subscription_required", False)
    monkeypatch.setattr(settings, "forum_chat_id", -100123)
    monkeypatch.setattr(settings, "channel_id", -100999)
    return SoulChatBot(session, gateway)


@pytest.fixture
async def topic(session, owner):
    return await make_topic(session, owner, code="A-0042")


def text(uid: int, body: str = "salom") -> IncomingMessage:
    return IncomingMessage(
        user_id=uid, chat_id=1, content_type=MessageContentType.TEXT.value, text=body
    )


# ---------------------------------------------------------------- service
async def test_unfreeze_returns_the_topic_to_active(session, owner, moderator, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)

    await service.freeze(topic, moderator, "spam")
    assert topic.status == TopicStatus.FROZEN.value

    await service.unfreeze(topic, moderator, "tekshirildi, toza")

    assert topic.status == TopicStatus.ACTIVE.value
    # a freeze never set these, so unfreeze must not pretend to clear them
    assert topic.is_closed is False
    assert topic.delete_at is None


async def test_unfreeze_writes_its_own_audit_entry(session, owner, moderator, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)
    await service.freeze(topic, moderator, "spam")
    await service.unfreeze(topic, moderator, "toza")

    rows = list(
        (
            await session.execute(
                select(AuditLog).where(AuditLog.action == AuditAction.TOPIC_UNFREEZE.value)
            )
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].topic_id == topic.id
    assert "toza" in (rows[0].message or "")


async def test_unfreezing_a_topic_that_is_not_frozen_is_refused(session, owner, moderator, gateway):
    """409 on the API; the transition table is the single source of truth."""
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)

    with pytest.raises(TopicError):
        await service.unfreeze(topic, moderator)  # already ACTIVE


async def test_owner_can_write_again_after_unfreeze(session, owner, moderator, gateway):
    topic = await make_topic(session, owner)
    service = TopicService(session, gateway)
    relay = RelayService(session, gateway)

    await service.freeze(topic, moderator, "spam")
    assert (await relay.relay_private(text(owner.tg_id))).ok is False

    await service.unfreeze(topic, moderator, "toza")

    assert (await relay.relay_private(text(owner.tg_id, "yana salom"))).ok is True
    assert len(gateway.sent("send_message")) == 1


# -------------------------------------------------------------------- API
async def test_unfreeze_endpoint(client, topic):
    frozen = await client.post("/api/v1/topics/A-0042/freeze", json={"reason": "spam"})
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "frozen"

    unfrozen = await client.post("/api/v1/topics/A-0042/unfreeze", json={"reason": "toza"})
    assert unfrozen.status_code == 200
    assert unfrozen.json()["status"] == "active"


async def test_unfreeze_endpoint_rejects_a_topic_that_is_not_frozen(client, topic):
    response = await client.post("/api/v1/topics/A-0042/unfreeze", json={})
    assert response.status_code == 409


async def test_unfreeze_endpoint_404_for_unknown_code(client, topic):
    response = await client.post("/api/v1/topics/ZZZZ/unfreeze", json={})
    assert response.status_code == 404


# -------------------------------------------------------------------- bot
async def test_moderator_unfreezes_through_the_bot(bot, session, owner, moderator):
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.FROZEN.value
    await session.flush()

    reply = await bot.moderate(moderator.tg_id, "unfreeze", owner.tg_id, "toza")

    assert "☀️" in reply.text
    assert topic.code in reply.text
    assert topic.status == TopicStatus.ACTIVE.value


async def test_moderator_restore_also_lifts_a_freeze(bot, session, owner, moderator):
    """`restore` used to answer "Noma'lum amal" for a frozen topic."""
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.FROZEN.value
    await session.flush()

    reply = await bot.moderate(moderator.tg_id, "restore", owner.tg_id, "toza")

    assert "Noma'lum amal" not in reply.text
    assert topic.status == TopicStatus.ACTIVE.value


async def test_restore_still_restores_a_blocked_topic(bot, session, owner, moderator):
    """The unfreeze branch must not steal the normal restore path."""
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.BLOCKED.value
    topic.is_closed = True
    await session.flush()

    reply = await bot.moderate(moderator.tg_id, "restore", owner.tg_id, "")

    assert "↩️" in reply.text
    assert topic.status == TopicStatus.ACTIVE.value


# --------------------------------------------------------------- security
async def test_a_frozen_user_cannot_unfreeze_themselves(bot, session, owner):
    """The whole point of a freeze: only staff can lift it.

    ``/restore`` shares the same lookup, so this is the test that would fail if
    ``include_frozen`` leaked into the user-facing path.
    """
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.FROZEN.value
    await session.flush()

    reply = await bot.restore(owner.tg_id)

    assert "topilmadi" in reply.text
    assert topic.status == TopicStatus.FROZEN.value


async def test_a_plain_user_cannot_call_moderate_unfreeze(bot, session, owner, partner):
    topic = await make_topic(session, owner)
    topic.status = TopicStatus.FROZEN.value
    topic.partner_id = partner.id
    topic.partner_tg_id = partner.tg_id
    await session.flush()

    reply = await bot.moderate(partner.tg_id, "unfreeze", owner.tg_id, "iltimos")

    assert reply.text == "Ruxsat yo'q."
    assert topic.status == TopicStatus.FROZEN.value