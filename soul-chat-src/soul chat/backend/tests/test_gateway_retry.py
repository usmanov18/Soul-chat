"""Telegram flood control (HTTP 429) and relay throughput.

Under load Telegram answers 429 with a ``retry_after`` hint. Nothing in the
gateway honoured it, so a burst across topics made ``_send`` raise and the
user's message was simply lost. These tests pin the retry behaviour and measure
the relay so a regression in throughput is visible.
"""

from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio

from app.core import metrics
from app.core.config import settings
from app.enums import MessageContentType
from app.services.relay import DenyReason, IncomingMessage, RelayService
from app.services.telegram_gateway import (
    AiogramGateway,
    RetryAfterError,
    retry_after_of,
)
from tests.conftest import make_topic


class _Sent:
    def __init__(self, message_id: int = 1001) -> None:
        self.message_id = message_id


class FakeBot:
    """Just enough of ``aiogram.Bot`` for ``AiogramGateway._send``."""

    def __init__(self, failures: list[BaseException | _Sent]) -> None:
        self._script = list(failures)
        self.calls: list[str] = []

    async def send_message(self, **kwargs):
        self.calls.append("send_message")
        outcome = self._script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest_asyncio.fixture(autouse=True)
async def fresh_metrics():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """The retry path sleeps for real; in tests that would just be slow."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return slept


# ---------------------------------------------------------------------------
# the duck-typed helper
# ---------------------------------------------------------------------------
def test_retry_after_of_reads_the_hint():
    assert retry_after_of(RetryAfterError(7)) == 7


@pytest.mark.parametrize("exc", [ValueError("nope"), RuntimeError("nope"), Exception()])
def test_retry_after_of_returns_none_for_other_errors(exc: BaseException):
    assert retry_after_of(exc) is None


def test_retry_after_of_survives_a_non_numeric_hint():
    class Weird(Exception):
        retry_after = "soon"

    assert retry_after_of(Weird()) is None


# ---------------------------------------------------------------------------
# retry behaviour
# ---------------------------------------------------------------------------
async def test_rate_limited_call_is_retried_and_succeeds(no_sleep):
    bot = FakeBot([RetryAfterError(3), _Sent(1042)])
    gateway = AiogramGateway(bot)

    message_id = await gateway.send_message(1, "salom")

    assert message_id == 1042
    assert len(bot.calls) == 2
    assert no_sleep == [3], "the retry_after hint must be honoured exactly"


async def test_repeated_rate_limiting_eventually_succeeds(no_sleep):
    bot = FakeBot([RetryAfterError(1), RetryAfterError(2), _Sent(7)])
    gateway = AiogramGateway(bot)

    assert await gateway.send_message(1, "x") == 7
    assert len(bot.calls) == 3
    assert no_sleep == [1, 2]


async def test_gives_up_after_the_configured_retries(no_sleep, monkeypatch):
    monkeypatch.setattr(settings, "telegram_max_retries", 2)
    bot = FakeBot([RetryAfterError(1), RetryAfterError(1), _Sent(9)])
    gateway = AiogramGateway(bot)

    with pytest.raises(RetryAfterError):
        await gateway.send_message(1, "x")

    assert len(bot.calls) == 2, "must not exceed telegram_max_retries"


async def test_non_429_errors_are_not_retried(no_sleep):
    bot = FakeBot([ValueError("bad request"), _Sent(1)])
    gateway = AiogramGateway(bot)

    with pytest.raises(ValueError):
        await gateway.send_message(1, "x")

    assert len(bot.calls) == 1
    assert no_sleep == []


async def test_metrics_distinguish_rate_limited_from_error():
    bot = FakeBot([RetryAfterError(1), _Sent(1)])
    gateway = AiogramGateway(bot)
    await gateway.send_message(1, "x")

    assert metrics.counter_value(
        "soulchat_telegram_calls_total", {"method": "send_message", "result": "rate_limited"}
    ) == 1
    assert metrics.counter_value(
        "soulchat_telegram_calls_total", {"method": "send_message", "result": "ok"}
    ) == 1


async def test_final_failure_is_counted_as_error():
    bot = FakeBot([ValueError("nope")])
    gateway = AiogramGateway(bot)

    with pytest.raises(ValueError):
        await gateway.send_message(1, "x")

    assert metrics.counter_value(
        "soulchat_telegram_calls_total", {"method": "send_message", "result": "error"}
    ) == 1


# ---------------------------------------------------------------------------
# throughput — the measurement C2 asked for
# ---------------------------------------------------------------------------
async def test_relay_throughput_and_latency(session, owner, gateway, monkeypatch):
    """Baseline numbers, so a regression shows up as a jump rather than a break.

    The platform's own flood protection (20/min by default) kicks in long before
    the relay is the bottleneck, so it is lifted here: what is being measured is
    the relay path — permission check, moderation, DB write, Telegram call — and
    the loose bound exists to catch an accidental extra round trip or an N+1,
    not to fail CI on a slow machine.
    """
    monkeypatch.setattr(settings, "rate_limit_per_minute", 100_000)
    monkeypatch.setattr(settings, "rate_limit_burst", 100_000)
    monkeypatch.setattr(settings, "flood_threshold", 100_000)
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)

    count = 200
    started = time.perf_counter()
    for index in range(count):
        result = await relay.relay_private(
            IncomingMessage(
                user_id=owner.tg_id,
                chat_id=owner.tg_id,
                content_type=MessageContentType.TEXT.value,
                text=f"xabar {index}",
                tg_message_id=70_000 + index,
            )
        )
        assert result.ok, result.reason
    elapsed = time.perf_counter() - started

    per_message_ms = elapsed / count * 1000
    print(
        f"\nrelay: {count} xabar {elapsed * 1000:.0f} ms da "
        f"({per_message_ms:.2f} ms/xabar, {count / elapsed:.0f} xabar/s)"
    )

    assert topic.message_count == count
    assert len(gateway.sent("send_message")) == count
    assert per_message_ms < 50, f"relay slowed to {per_message_ms:.1f} ms per message"

    # every relay was metered
    assert metrics.histogram_count("soulchat_relay_duration_seconds", {"result": "ok"}) == count


async def test_interleaved_messages_from_both_writers(session, owner, partner, gateway, monkeypatch):
    """Two people in one topic — the normal case — must not lose a message.

    Interleaved rather than ``asyncio.gather``: a single ``AsyncSession`` is not
    safe for concurrent use (SQLAlchemy raises "Session is already flushing"),
    and in production each Telegram update gets its own session anyway. What
    this pins is that the two writers' messages do not interfere with each
    other's idempotency bookkeeping.
    """
    from app.models.topic import TopicParticipant

    monkeypatch.setattr(settings, "rate_limit_per_minute", 100_000)
    monkeypatch.setattr(settings, "rate_limit_burst", 100_000)
    monkeypatch.setattr(settings, "flood_threshold", 100_000)

    topic = await make_topic(session, owner)
    topic.partner_id = partner.id
    topic.partner_tg_id = partner.tg_id
    session.add(TopicParticipant(topic_id=topic.id, user_id=partner.id, role="partner"))
    await session.flush()

    relay = RelayService(session, gateway)
    outcomes: list[str] = []
    for index in range(25):
        for tg_id, offset in ((owner.tg_id, 80_000), (partner.tg_id, 90_000)):
            result = await relay.relay_private(
                IncomingMessage(
                    user_id=tg_id,
                    chat_id=tg_id,
                    content_type=MessageContentType.TEXT.value,
                    text=f"{tg_id}-{index}",
                    tg_message_id=offset + index,
                )
            )
            outcomes.append(result.reason.value)

    assert outcomes.count(DenyReason.OK.value) == 50
    assert len(gateway.sent("send_message")) == 50
    assert topic.message_count == 50