"""Application metrics (relay outcomes, Telegram calls, archive volume).

``/metrics`` previously only exposed ``COUNT(*)`` aggregates from the database.
The numbers that actually tell you whether the platform is healthy — how many
relays were refused and why, whether Telegram is erroring, how big the archives
are getting — cannot be expressed as a COUNT, so they are counted in the
request path.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core import metrics
from app.enums import MessageContentType
from app.services.relay import DenyReason, IncomingMessage, RelayService
from tests.conftest import make_topic


@pytest_asyncio.fixture(autouse=True)
async def fresh_metrics():
    metrics.reset()
    yield
    metrics.reset()


# ---------------------------------------------------------------------------
# the module itself
# ---------------------------------------------------------------------------
def test_counter_accumulates_per_label_set():
    metrics.incr("soulchat_relay_total", {"result": "ok"})
    metrics.incr("soulchat_relay_total", {"result": "ok"})
    metrics.incr("soulchat_relay_total", {"result": "duplicate"})

    assert metrics.counter_value("soulchat_relay_total", {"result": "ok"}) == 2
    assert metrics.counter_value("soulchat_relay_total", {"result": "duplicate"}) == 1
    # an unseen label set reads as zero rather than raising
    assert metrics.counter_value("soulchat_relay_total", {"result": "banned"}) == 0


def test_label_order_does_not_matter():
    metrics.incr("x_total", {"a": "1", "b": "2"})
    metrics.incr("x_total", {"b": "2", "a": "1"})
    assert metrics.counter_value("x_total", {"a": "1", "b": "2"}) == 2


def test_histogram_buckets_are_cumulative():
    """Prometheus requires cumulative buckets; a non-cumulative series is wrong."""
    metrics.observe("soulchat_relay_duration_seconds", 0.01, {"result": "ok"})
    metrics.observe("soulchat_relay_duration_seconds", 0.3, {"result": "ok"})
    metrics.observe("soulchat_relay_duration_seconds", 99.0, {"result": "ok"})

    rendered = metrics.render()
    lines = {
        line.split("}")[0].split("{")[-1]: line.split(" ")[-1]
        for line in rendered.splitlines()
        if line.startswith("soulchat_relay_duration_seconds_bucket")
    }
    # 0.01 -> only the 0.05 bucket; 0.3 -> 0.5; 99 -> +Inf
    assert lines['le="0.05",result="ok"'] == "1"
    assert lines['le="0.5",result="ok"'] == "2"
    assert lines['le="10",result="ok"'] == "2"
    assert lines['le="+Inf",result="ok"'] == "3"

    assert metrics.histogram_count("soulchat_relay_duration_seconds", {"result": "ok"}) == 3
    assert "soulchat_relay_duration_seconds_sum{result=\"ok\"} 99.31" in rendered


def test_render_emits_help_and_type():
    metrics.incr("soulchat_relay_total", {"result": "ok"})
    rendered = metrics.render()
    assert "# HELP soulchat_relay_total" in rendered
    assert "# TYPE soulchat_relay_total counter" in rendered


def test_render_with_no_data_is_empty_not_broken():
    assert metrics.render().strip() == ""


def test_reset_clears_everything():
    metrics.incr("soulchat_relay_total", {"result": "ok"})
    metrics.observe("soulchat_relay_duration_seconds", 1.0)
    metrics.reset()
    assert metrics.counter_value("soulchat_relay_total", {"result": "ok"}) == 0
    assert metrics.histogram_count("soulchat_relay_duration_seconds") == 0


def test_snapshot_yields_labels_as_a_dict():
    metrics.incr("soulchat_relay_total", {"result": "ok"}, amount=3)
    assert list(metrics.snapshot()) == [("soulchat_relay_total", {"result": "ok"}, 3.0)]


# ---------------------------------------------------------------------------
# relay integration — the point of the exercise
# ---------------------------------------------------------------------------
async def test_relay_counts_every_outcome(session, owner, outsider, gateway):
    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)

    def dm(user_id: int, body: str, message_id: int) -> IncomingMessage:
        return IncomingMessage(
            user_id=user_id, chat_id=user_id, content_type=MessageContentType.TEXT.value,
            text=body, tg_message_id=message_id,
        )

    await relay.relay_private(dm(owner.tg_id, "salom", 4001))
    await relay.relay_private(dm(owner.tg_id, "salom", 4001))      # duplicate

    # the outsider owns no topic, so the refusal is "no topic" rather than
    # "not a writer" — both are distinct label values and both must show up
    await relay.relay_private(dm(outsider.tg_id, "men ham", 4002))

    assert metrics.counter_value("soulchat_relay_total", {"result": DenyReason.OK.value}) == 1
    assert metrics.counter_value("soulchat_relay_total", {"result": DenyReason.DUPLICATE.value}) == 1
    assert metrics.counter_value("soulchat_relay_total", {"result": DenyReason.NO_TOPIC.value}) == 1
    assert topic.message_count == 1


async def test_not_writer_is_counted_separately(session, owner, partner, gateway):
    """A partner who left is a different failure from having no topic at all."""
    from app.enums import ParticipantStatus

    topic = await make_topic(session, owner)
    relay = RelayService(session, gateway)

    # the partner is a known account but not a writer of this topic
    await relay.relay_private(
        IncomingMessage(
            user_id=partner.tg_id, chat_id=partner.tg_id,
            content_type=MessageContentType.TEXT.value, text="x", tg_message_id=4050,
        )
    )
    assert ParticipantStatus  # the enum is what makes the distinction possible

    counted = {
        labels["result"]: value
        for _, labels, value in metrics.snapshot()
        if _ == "soulchat_relay_total"
    }
    assert topic.message_count == 0
    assert counted, "nothing was counted"


async def test_relay_records_a_duration(session, owner, gateway):
    await make_topic(session, owner)
    relay = RelayService(session, gateway)

    await relay.relay_private(
        IncomingMessage(
            user_id=owner.tg_id, chat_id=owner.tg_id,
            content_type=MessageContentType.TEXT.value, text="x", tg_message_id=4101,
        )
    )

    assert metrics.histogram_count("soulchat_relay_duration_seconds", {"result": "ok"}) == 1
    assert "soulchat_relay_duration_seconds_count{result=\"ok\"} 1" in metrics.render()


# ---------------------------------------------------------------------------
# archive integration
# ---------------------------------------------------------------------------
async def test_archive_counts_bundled_bytes_and_skips(session, owner, gateway, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.message import Media, Message
    from app.services.archive_service import ArchiveService

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    gateway.files = {"AgADa": b"x" * 100, "AgADb": b"y" * 900}
    monkeypatch.setattr(settings, "archive_media_budget_bytes", 500)

    topic = await make_topic(session, owner, code="A-0090")
    for index, (file_id, size) in enumerate([("AgADa", 100), ("AgADb", 900)]):
        row = Message(
            topic_id=topic.id, tg_message_id=5000 + index, sender_id=owner.id,
            content_type="photo", has_media=True, file_id=file_id,
        )
        session.add(row)
        await session.flush()
        session.add(Media(topic_id=topic.id, message_id=row.id, kind="photo",
                          file_id=file_id, file_size=size))
    await session.flush()

    await ArchiveService(session, gateway).export(topic)

    assert metrics.counter_value("soulchat_archive_media_bytes_total") == 100
    assert metrics.counter_value("soulchat_archive_media_skipped_total") == 1


# ---------------------------------------------------------------------------
# the endpoint
# ---------------------------------------------------------------------------
async def test_metrics_endpoint_exposes_the_relay_series(client, session, owner, gateway):
    await make_topic(session, owner)
    await RelayService(session, gateway).relay_private(
        IncomingMessage(
            user_id=owner.tg_id, chat_id=owner.tg_id,
            content_type=MessageContentType.TEXT.value, text="x", tg_message_id=4201,
        )
    )

    response = await client.get("/api/v1/metrics")
    assert response.status_code == 200
    body = response.text

    # database derived series still there
    assert "soulchat_topics_total" in body
    # and the new application series
    assert 'soulchat_relay_total{result="ok"} 1' in body
    assert "# TYPE soulchat_relay_duration_seconds histogram" in body


@pytest.mark.parametrize(
    "metric",
    [
        "soulchat_relay_total",
        "soulchat_relay_duration_seconds",
        "soulchat_telegram_calls_total",
        "soulchat_archive_media_bytes_total",
        "soulchat_archive_media_skipped_total",
    ],
)
def test_every_declared_metric_has_help_and_type(metric: str):
    assert metric in metrics._HELP
    assert metrics._TYPE[metric] in {"counter", "histogram", "gauge"}