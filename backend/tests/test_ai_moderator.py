"""TZ 27 — AI moderator, summaries and emotion analysis."""

from __future__ import annotations

from app.core.config import settings
from app.enums import ModerationAction
from app.services.ai_service import AIModerator


async def test_clean_message_is_allowed(session, owner):
    verdict = await AIModerator(session).moderate("Bugun uchrashamizmi?", user_id=owner.tg_id)
    assert verdict.action == ModerationAction.ALLOW.value
    assert verdict.risk < settings.ai_risk_review_threshold


async def test_insult_is_blocked(session, owner):
    verdict = await AIModerator(session).moderate("Sen ahmoqсан, tentak", user_id=owner.tg_id)
    assert verdict.action == ModerationAction.BLOCK.value
    assert "insult" in verdict.labels


async def test_spam_links_are_flagged(session, owner):
    text = "Buy now https://bit.ly/abc123 https://t.me/freebtc casino bonus credit tez"
    verdict = await AIModerator(session).moderate(text, user_id=owner.tg_id)
    assert verdict.risk >= settings.ai_risk_review_threshold
    assert verdict.action in {ModerationAction.REVIEW.value, ModerationAction.BLOCK.value}


async def test_nsfw_is_detected(session, owner):
    verdict = await AIModerator(session).moderate("send me nudes 18+ xxx", user_id=owner.tg_id)
    assert "nsfw" in verdict.labels
    assert verdict.action == ModerationAction.BLOCK.value


async def test_moderation_is_recorded_as_spam_event(session, owner):
    from sqlalchemy import select

    from app.models.security import SpamEvent

    await AIModerator(session).moderate("sen tentak", user_id=owner.tg_id)

    rows = (await session.execute(select(SpamEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].score > 0


async def test_risk_score_accumulates_on_the_user(session, owner):
    moderator = AIModerator(session)
    await moderator.moderate("sen ahmoq", user_id=owner.tg_id)
    assert owner.risk_score > 0


async def test_summarize_reports_volume_and_tone(session, owner):
    texts = ["Assalomu alaykum", "Yaxshi ko'raman seni ❤", "Bugun uchrashamiz", "Xafa bo'ldim"]
    summary = await AIModerator(session).summarize(texts)
    assert summary.message_count == 4
    assert summary.top_words
    assert set(summary.emotions) >= {"joy", "sadness", "neutral"}
    assert "4 ta xabar" in summary.text


async def test_summarize_with_timestamps_finds_peak_hours(session, owner):
    from datetime import UTC, datetime

    stamps = [
        int(datetime(2026, 1, 1, 20, 0, tzinfo=UTC).timestamp()),
        int(datetime(2026, 1, 2, 20, 30, tzinfo=UTC).timestamp()),
        int(datetime(2026, 1, 3, 9, 0, tzinfo=UTC).timestamp()),
    ]
    summary = await AIModerator(session).summarize(["a", "b", "c"], stamps)
    assert summary.peak_hours[0][0] == 20


async def test_emotion_analysis(session, owner):
    moderator = AIModerator(session)
    assert await moderator.analyze_emotion("Men juda xafa bo'ldim, yig'ladim") == "sadness"
    assert await moderator.analyze_emotion("Baxtliман, yaxshi ko'raman") == "joy"
    assert await moderator.analyze_emotion("") == "neutral"


async def test_empty_text_short_circuits(session, owner):
    verdict = await AIModerator(session).moderate("   ", user_id=owner.tg_id)
    assert verdict.action == ModerationAction.ALLOW.value
    assert verdict.risk == 0.0
