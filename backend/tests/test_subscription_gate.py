"""TZ 5 — mandatory group + channel membership."""

from __future__ import annotations

from app.core.config import settings
from app.enums import SubscriptionKind, SubscriptionStatus
from app.services.subscription_gate import SubscriptionGate

GROUP = -100123
CHANNEL = -100999


def _setup(monkeypatch):
    monkeypatch.setattr(settings, "subscription_required", True)
    monkeypatch.setattr(settings, "forum_chat_id", GROUP)
    monkeypatch.setattr(settings, "channel_id", CHANNEL)


async def test_member_of_both_is_allowed(session, owner, gateway, monkeypatch):
    _setup(monkeypatch)
    gateway.set_member(GROUP, owner.tg_id, "member")
    gateway.set_member(CHANNEL, owner.tg_id, "member")

    result = await SubscriptionGate(session, gateway).check(owner.tg_id)

    assert result.allowed is True
    assert result.missing == []


async def test_missing_channel_blocks(session, owner, gateway, monkeypatch):
    _setup(monkeypatch)
    gateway.set_member(GROUP, owner.tg_id, "member")
    gateway.set_member(CHANNEL, owner.tg_id, "left")

    result = await SubscriptionGate(session, gateway).check(owner.tg_id)

    assert result.allowed is False
    assert result.missing == ["channel"]


async def test_missing_both_blocks(session, owner, gateway, monkeypatch):
    _setup(monkeypatch)
    gateway.set_member(GROUP, owner.tg_id, "kicked")
    gateway.set_member(CHANNEL, owner.tg_id, "left")

    result = await SubscriptionGate(session, gateway).check(owner.tg_id)

    assert result.allowed is False
    assert set(result.missing) == {"group", "channel"}


async def test_administrator_counts_as_member(session, owner, gateway, monkeypatch):
    _setup(monkeypatch)
    gateway.set_member(GROUP, owner.tg_id, "administrator")
    gateway.set_member(CHANNEL, owner.tg_id, "creator")

    assert (await SubscriptionGate(session, gateway).check(owner.tg_id)).allowed is True


async def test_membership_is_persisted(session, owner, gateway, monkeypatch):
    from sqlalchemy import select

    from app.models.user import Subscription

    _setup(monkeypatch)
    gateway.set_member(GROUP, owner.tg_id, "member")
    gateway.set_member(CHANNEL, owner.tg_id, "left")

    await SubscriptionGate(session, gateway).check(owner.tg_id)

    rows = (await session.execute(select(Subscription))).scalars().all()
    assert len(rows) == 2
    by_kind = {row.kind: row for row in rows}
    assert by_kind[SubscriptionKind.GROUP.value].is_member is True
    assert by_kind[SubscriptionKind.CHANNEL.value].status == SubscriptionStatus.LEFT.value


async def test_result_is_cached(session, owner, gateway, monkeypatch):
    _setup(monkeypatch)
    gateway.set_member(GROUP, owner.tg_id, "member")
    gateway.set_member(CHANNEL, owner.tg_id, "member")
    gate = SubscriptionGate(session, gateway)
    await gate.check(owner.tg_id)

    gateway.set_member(CHANNEL, owner.tg_id, "left")     # stale until invalidated
    assert (await gate.check(owner.tg_id)).allowed is True

    await gate.invalidate(owner.tg_id)
    assert (await gate.check(owner.tg_id)).allowed is False


async def test_gate_can_be_disabled(session, owner, gateway, monkeypatch):
    monkeypatch.setattr(settings, "subscription_required", False)
    gateway.set_member(GROUP, owner.tg_id, "left")
    gateway.set_member(CHANNEL, owner.tg_id, "left")

    assert (await SubscriptionGate(session, gateway).check(owner.tg_id)).allowed is True


async def test_bot_start_is_blocked_without_membership(session, owner, gateway, monkeypatch):
    from app.services.bot_service import SoulChatBot

    _setup(monkeypatch)
    gateway.set_member(GROUP, owner.tg_id, "left")
    gateway.set_member(CHANNEL, owner.tg_id, "left")
    bot = SoulChatBot(session, gateway)

    reply = await bot.start(owner.tg_id, username="akbar", first_name="Akbar")

    assert "obuna" in reply.text.lower()
    assert any(button.callback in {"open_channel", "open_group"} for row in reply.buttons for button in row)
