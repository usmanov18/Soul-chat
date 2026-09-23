"""Celery task bodies (TZ 18, 25, 13, 21, 31).

These are the highest risk routines in the platform — the sweeper *deletes data*
— so they are exercised directly against a real database and a fake gateway.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.enums import EventKind, EventStatus, TopicStatus
from app.models.log import StatDaily
from app.models.message import Event, Message
from app.models.security import Archive
from app.models.topic import Topic, TopicParticipant
from app.models.user import User
from app.services.telegram_gateway import FakeGateway
from tests.conftest import make_topic


@pytest_asyncio.fixture
async def task_env(engine, monkeypatch):
    """Point the tasks' own ``session_scope`` at the test engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.core.db as db_module

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", factory)

    gateway = FakeGateway()
    monkeypatch.setattr(settings, "forum_chat_id", -100123)
    monkeypatch.setattr(settings, "archive_dir", "/tmp/soulchat-test-archives")
    monkeypatch.setattr(settings, "backup_dir", "/tmp/soulchat-test-backups")

    async def fake_gateway() -> FakeGateway:
        return gateway

    import app.tasks as tasks

    monkeypatch.setattr(tasks, "_gateway", fake_gateway)
    return {"gateway": gateway, "factory": factory}


async def _seed_owner(session) -> User:
    user = User(tg_id=111, username="akbar", first_name="Akbar", gender="male")
    session.add(user)
    await session.flush()
    return user


async def test_sweeper_archives_then_deletes_expired_topics(task_env, engine, monkeypatch):
    """96h elapsed -> archive is written, Telegram topic removed, status deleted."""

    from app.tasks import _sweep_delete_pending

    gateway = task_env["gateway"]
    async with AsyncSession(engine) as session:
        owner = await _seed_owner(session)
        topic = await make_topic(session, owner, code="A-0001")
        topic.status = TopicStatus.DELETE_PENDING.value
        topic.delete_at = datetime.now(UTC) - timedelta(minutes=1)
        thread_id = topic.message_thread_id
        await session.commit()

    result = await _sweep_delete_pending()

    assert result["count"] == 1
    assert result["archived"] == ["A-0001"]
    assert gateway.deleted_topics == [(-100123, thread_id)]

    async with AsyncSession(engine) as session:
        row = (await session.execute(select(Topic))).scalar_one()
        assert row.status == TopicStatus.DELETED.value

    async with AsyncSession(engine) as session:
        archives = (await session.execute(select(Archive))).scalars().all()
        assert len(archives) == 1
        assert archives[0].checksum
        assert archives[0].size > 0


async def test_sweeper_leaves_topics_inside_the_window_alone(task_env, engine):
    from sqlalchemy import select

    from app.tasks import _sweep_delete_pending

    gateway = task_env["gateway"]
    async with AsyncSession(engine) as session:
        owner = await _seed_owner(session)
        topic = await make_topic(session, owner, code="A-0002")
        topic.status = TopicStatus.DELETE_PENDING.value
        topic.delete_at = datetime.now(UTC) + timedelta(hours=48)
        await session.commit()

    result = await _sweep_delete_pending()

    assert result["count"] == 0
    assert gateway.deleted_topics == []

    async with AsyncSession(engine) as session:
        row = (await session.execute(select(Topic))).scalar_one()
        assert row.status == TopicStatus.DELETE_PENDING.value


async def test_scheduler_tick_closes_outside_the_window(task_env, engine):

    import app.tasks as tasks

    gateway = task_env["gateway"]
    async with AsyncSession(engine) as session:
        owner = await _seed_owner(session)
        topic = await make_topic(session, owner, code="A-0003")
        topic.schedule_enabled = True
        topic.schedule_days = "1"
        topic.schedule_window_start = "20:00"
        topic.schedule_window_end = "22:00"
        await session.commit()

    original = tasks._scheduler_tick

    async def tick_at(moment: datetime):
        from app.core.db import session_scope
        from app.services.event_service import SchedulerService

        async with session_scope() as session:
            return await SchedulerService(session, gateway).tick(moment)

    closed = await tick_at(datetime(2026, 9, 21, 23, 0, tzinfo=UTC))  # Monday 23:00
    assert closed["closed"] == ["A-0003"]
    assert gateway.closed_topics == [(-100123, 1000)]

    opened = await tick_at(datetime(2026, 9, 21, 21, 0, tzinfo=UTC))  # Monday 21:00
    assert opened["opened"] == ["A-0003"]
    assert original is not None


async def test_event_reminders_notify_both_participants(task_env, engine):

    from app.tasks import _event_reminders

    gateway = task_env["gateway"]
    async with AsyncSession(engine) as session:
        owner = await _seed_owner(session)
        partner = User(tg_id=222, username="salima", first_name="Salima", gender="female")
        session.add(partner)
        await session.flush()

        topic = await make_topic(session, owner, code="A-0004")
        topic.partner_id = partner.id
        topic.partner_tg_id = partner.tg_id
        session.add(
            TopicParticipant(topic_id=topic.id, user_id=partner.id, role="partner")
        )
        session.add(
            Event(
                topic_id=topic.id,
                created_by=owner.id,
                kind=EventKind.DATE.value,
                title="Ilk uchrashuv",
                remind_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    result = await _event_reminders()

    assert result["sent"] == 2
    recipients = {call.args[0] for call in gateway.sent("send_message")}
    assert recipients == {111, 222}
    assert any("Ilk uchrashuv" in (call.args[1] or "") for call in gateway.sent("send_message"))

    async with AsyncSession(engine) as session:
        event = (await session.execute(select(Event))).scalar_one()
        assert event.notified_at is not None
        # not spammed twice on the next run
        assert event.status == EventStatus.NOTIFIED.value


async def test_daily_snapshot_writes_one_row_per_day(task_env, engine):

    from app.tasks import _daily_snapshot

    async with AsyncSession(engine) as session:
        owner = await _seed_owner(session)
        topic = await make_topic(session, owner, code="A-0005")
        session.add(
            Message(topic_id=topic.id, sender_id=owner.id, content_type="text", text="salom")
        )
        await session.commit()

    first = await _daily_snapshot()
    second = await _daily_snapshot()

    assert first["day"] == second["day"]
    async with AsyncSession(engine) as session:
        rows = (await session.execute(select(StatDaily))).scalars().all()
        assert len(rows) == 1


async def test_backup_task_reports_success(task_env, engine, monkeypatch):

    from app.tasks import _daily_backup

    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:////tmp/soulchat-backup-src.db")

    import sqlite3

    sqlite3.connect("/tmp/soulchat-backup-src.db").close()
    result = await _daily_backup()

    assert result["status"] == "success"
    assert result["size"] >= 0


async def test_subscription_sweep_checks_every_user(task_env, engine, monkeypatch):

    from app.tasks import _subscription_sweep

    monkeypatch.setattr(settings, "subscription_required", True)
    monkeypatch.setattr(settings, "channel_id", -100999)
    gateway = task_env["gateway"]

    async with AsyncSession(engine) as session:
        await _seed_owner(session)
        await session.commit()
    gateway.set_member(-100123, 111, "member")
    gateway.set_member(-100999, 111, "member")

    result = await _subscription_sweep()
    assert result["checked"] == 1


async def test_sweeper_survives_a_failing_archive(task_env, engine, monkeypatch):
    """One broken topic must not strand the rest of the batch.

    The sweep runs every 5 minutes, so before per-topic error handling the
    first failing archive aborted the loop and every *other* user's data sat in
    delete_pending forever — past its 96 hours, never archived, never deleted.
    """
    from app.services.archive_service import ArchiveService
    from app.tasks import _sweep_delete_pending

    gateway = task_env["gateway"]
    async with AsyncSession(engine) as session:
        owner = await _seed_owner(session)
        bad = await make_topic(session, owner, code="A-0001", thread_id=1001)
        bad.status = TopicStatus.DELETE_PENDING.value
        bad.delete_at = datetime.now(UTC) - timedelta(minutes=1)
        good = await make_topic(session, owner, code="A-0002", thread_id=1002)
        good.status = TopicStatus.DELETE_PENDING.value
        good.delete_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    real_export = ArchiveService.export

    async def flaky_export(self, topic, *_args, **_kwargs):
        if topic.code == "A-0001":
            raise OSError("disk to'lgan")
        return await real_export(self, topic, *_args, **_kwargs)

    monkeypatch.setattr(ArchiveService, "export", flaky_export)

    result = await _sweep_delete_pending()

    assert result["archived"] == ["A-0002"]
    assert result["count"] == 1
    assert "A-0001" in result["failed"]
    assert "disk to'lgan" in result["failed"]["A-0001"]
    # the healthy one really was deleted, the broken one really was not
    assert (-100123, 1002) in gateway.deleted_topics
    assert (-100123, 1001) not in gateway.deleted_topics

    async with AsyncSession(engine) as session:
        rows = {t.code: t.status for t in (await session.execute(select(Topic))).scalars()}
    assert rows["A-0001"] == TopicStatus.DELETE_PENDING.value  # retried next tick
    assert rows["A-0002"] == TopicStatus.DELETED.value


async def test_sweeper_never_deletes_when_the_archive_failed(task_env, engine, monkeypatch):
    """TZ 20: the archive comes *before* the delete — never the other way."""
    from app.services.archive_service import ArchiveService
    from app.tasks import _sweep_delete_pending

    gateway = task_env["gateway"]
    async with AsyncSession(engine) as session:
        owner = await _seed_owner(session)
        topic = await make_topic(session, owner, code="A-0007", thread_id=1007)
        topic.status = TopicStatus.DELETE_PENDING.value
        topic.delete_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    async def always_fails(self, topic, *_a, **_k):
        raise OSError("arxiv yozib bo'lmadi")

    monkeypatch.setattr(ArchiveService, "export", always_fails)

    result = await _sweep_delete_pending()

    assert result["count"] == 0
    assert gateway.deleted_topics == []
    async with AsyncSession(engine) as session:
        row = (await session.execute(select(Topic))).scalar_one()
        assert row.status == TopicStatus.DELETE_PENDING.value