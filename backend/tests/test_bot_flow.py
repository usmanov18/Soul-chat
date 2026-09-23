"""End to end bot conversation driven through SoulChatBot."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.enums import MessageContentType
from app.services.bot_service import SoulChatBot
from app.services.relay import IncomingMessage


@pytest.fixture
def bot(session, gateway, monkeypatch):
    monkeypatch.setattr(settings, "subscription_required", False)
    monkeypatch.setattr(settings, "forum_chat_id", -100123)
    monkeypatch.setattr(settings, "channel_id", -100999)
    return SoulChatBot(session, gateway)


async def test_start_registers_the_user(bot, gateway):
    reply = await bot.start(111, username="akbar", first_name="Akbar")
    assert "Xush kelibsiz" in reply.text
    assert await bot.user(111) is not None


async def test_full_flow_create_invite_accept_chat(bot, session, gateway):
    await bot.start(111, username="akbar", first_name="Akbar")
    created = await bot.new_topic(111)
    assert "Suhbatingiz tayyor" in created.text

    invite = await bot.invite(111)
    token = invite.text.split("inv_")[1].split("<")[0].strip()

    await bot.start(222, payload=f"inv_{token}", username="salima", first_name="Salima")

    relayed = await bot.handle_private_message(
        IncomingMessage(user_id=111, chat_id=111, text="Salom Salima")
    )
    assert relayed is None                      # silently relayed
    relayed_texts = [call.args[1] for call in gateway.sent("send_message")]
    assert any("Salom Salima" in text for text in relayed_texts)

    reply = await bot.handle_private_message(
        IncomingMessage(user_id=222, chat_id=222, text="Va alaykum assalom")
    )
    assert reply is None
    relayed_texts = [call.args[1] for call in gateway.sent("send_message")]
    assert sum(1 for text in relayed_texts if "alaykum" in text) == 1
    assert any("Salima" in text for text in relayed_texts)


async def test_third_person_gets_refused(bot, session, gateway):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)
    await bot.start(333, username="begona", first_name="Begona")

    reply = await bot.handle_private_message(
        IncomingMessage(user_id=333, chat_id=333, text="Men ham kiraman")
    )

    # an outsider has no topic of their own, so nothing is relayed anywhere
    assert reply is not None
    assert "/new" in reply.text
    assert not any("Men ham kiraman" in (call.args[1] if len(call.args) > 1 else "")
                   for call in gateway.calls)


async def test_photo_goes_to_topic_and_gallery(bot, session, gateway):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)

    await bot.handle_private_message(
        IncomingMessage(user_id=111, chat_id=111, content_type=MessageContentType.PHOTO.value,
                        file_id="AgADBA", caption="Toshkent")
    )

    assert len(gateway.sent("send_photo")) == 2      # topic + channel gallery


async def test_close_confirm_restore_flow(bot, session, gateway):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)
    invite = await bot.invite(111)
    token = invite.text.split("inv_")[1].split("<")[0].strip()
    await bot.start(222, payload=f"inv_{token}", username="salima", first_name="Salima")

    started = await bot.close(111)
    code = started.text.split("Yopish kodi: ")[1].split("\n")[0]

    assert "Endi sherigingiz" in (await bot.confirm(111, code)).text
    closed = await bot.confirm(222, code)
    assert "yopildi" in closed.text

    restored = await bot.restore(111)
    assert "tiklandi" in restored.text


async def test_archive_returns_a_zip(bot, session, gateway, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)
    await bot.handle_private_message(IncomingMessage(user_id=111, chat_id=111, text="salom"))

    reply = await bot.archive(111)

    assert reply.document is not None
    payload, filename = reply.document
    assert filename.endswith(".zip")
    assert payload[:2] == b"PK"


async def test_event_and_schedule_commands(bot, session, gateway):
    from datetime import datetime, timedelta

    from app.services.event_service import EventDraft

    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)

    reply = await bot.create_event(111, EventDraft(title="Uchrashuv", due_at=datetime.now() + timedelta(days=1)))
    assert "Hodisa yaratildi" in reply.text

    scheduled = await bot.schedule(111, [1, 3, 5], "20:00", "22:00")
    assert "Jadval saqlandi" in scheduled.text
    assert "20:00 – 22:00" in scheduled.text


async def test_status_and_help(bot, session, gateway):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)
    status = await bot.status(111)
    assert "Suhbat:" in status.text
    assert "Sherik: hali yo'q" in status.text
    assert "/invite" in (await bot.help(111)).text


async def test_stats_requires_staff(bot, session, gateway, moderator):
    await bot.start(111, username="akbar", first_name="Akbar")
    denied = await bot.stats(111)
    assert "moderator" in denied.text.lower()
    allowed = await bot.stats(moderator.tg_id)
    assert "Statistika" in allowed.text


async def test_search_requires_staff(bot, session, gateway, moderator):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)
    result = await bot.search(moderator.tg_id, "A-")
    assert "Topics" in result.text


async def test_group_message_from_outsider_is_deleted(bot, session, gateway):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)
    topic = (await bot.relay.current_topic(111))

    await bot.handle_group_message(-100123, 777, 333, topic.message_thread_id)
    assert (-100123, 777) in gateway.deleted_messages


async def test_moderation_commands(bot, session, gateway, moderator):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)

    reply = await bot.moderate(moderator.tg_id, "warn", 111, "spam")
    assert "Ogohlantirish" in reply.text

    denied = await bot.moderate(111, "ban", 222)
    assert "Ruxsat yo'q" in denied.text


async def test_subscription_gate_blocks_new_topic(bot, session, gateway, monkeypatch):
    monkeypatch.setattr(settings, "subscription_required", True)
    gateway.set_member(-100123, 111, "left")
    gateway.set_member(-100999, 111, "left")
    await bot.start(111, username="akbar", first_name="Akbar")

    reply = await bot.new_topic(111)
    assert "obuna" in reply.text.lower()


async def test_settings_view_requires_admin(bot, session, gateway, admin, moderator):
    denied = await bot.settings_view(moderator.tg_id)
    assert "Ruxsat yo'q" in denied.text
    allowed = await bot.settings_view(admin.tg_id)
    assert "code.scheme" in allowed.text