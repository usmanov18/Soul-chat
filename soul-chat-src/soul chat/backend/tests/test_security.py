"""TZ 26 — flood control, captcha, blacklist, warns."""

from __future__ import annotations

from app.core.config import settings
from app.services.security_service import FloodLevel, SecurityService


async def test_flood_control_triggers_after_threshold(session, owner, monkeypatch):
    monkeypatch.setattr(settings, "flood_threshold", 4)
    monkeypatch.setattr(settings, "flood_window_seconds", 30)
    security = SecurityService(session)

    verdicts = [await security.register_hit(owner.tg_id) for _ in range(6)]

    assert verdicts[0].level is FloodLevel.OK
    assert verdicts[-1].level is FloodLevel.THROTTLE
    assert verdicts[-1].hits > settings.flood_threshold


async def test_repeated_violations_escalate_to_captcha(session, owner, monkeypatch):
    monkeypatch.setattr(settings, "flood_threshold", 1)
    monkeypatch.setattr(settings, "captcha_after_violations", 1)
    security = SecurityService(session)
    await security.register_hit(owner.tg_id)

    verdict = await security.register_hit(owner.tg_id)

    assert verdict.level is FloodLevel.CAPTCHA
    assert verdict.captcha_id is not None


async def test_captcha_solving_unblocks(session, owner, monkeypatch):
    monkeypatch.setattr(settings, "flood_threshold", 1)
    monkeypatch.setattr(settings, "captcha_after_violations", 1)
    security = SecurityService(session)
    await security.register_hit(owner.tg_id)
    await security.register_hit(owner.tg_id)

    challenge = await security.issue_captcha(owner.tg_id)
    assert await security.solve_captcha(owner.tg_id, challenge.answer) is True
    assert await security.solve_captcha(owner.tg_id, "99999") is False


async def test_blacklist_blocks(session, owner):
    security = SecurityService(session)
    assert await security.is_blocked(owner.tg_id) is False
    await security.ban(owner.tg_id, reason="abuse")
    assert await security.is_blocked(owner.tg_id) is True
    assert owner.is_banned is True


async def test_whitelist_is_detected(session, owner):
    from app.models.user import Blacklist

    security = SecurityService(session)
    session.add(Blacklist(tg_id=owner.tg_id, kind="white", reason="staff"))
    await session.flush()
    assert await security.is_whitelisted(owner.tg_id) is True


async def test_three_warns_lead_to_ban(session, owner, admin, monkeypatch):
    monkeypatch.setattr(settings, "max_warns", 3)
    security = SecurityService(session)
    for _ in range(3):
        await security.warn(owner.tg_id, admin, "qoida buzilishi")
    assert owner.warns == 3
    assert owner.is_banned is True


async def test_mute_sets_expiry(session, owner):
    security = SecurityService(session)
    await security.mute(owner.tg_id, minutes=30, reason="spam")
    assert owner.is_muted is True
    assert owner.mute_until is not None


def test_spam_heuristics():
    assert SecurityService.looks_like_spam("xayr") == 0
    assert SecurityService.looks_like_spam("http://a.com http://b.com http://c.com") >= 45
    assert SecurityService.looks_like_spam("aaaaaaaaaaaaaaaaaaa") >= 25
    assert SecurityService.looks_like_spam("HA HA HA HA HA HA HA HA") >= 25