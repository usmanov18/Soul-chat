"""Celery application and periodic tasks.

Every scheduled behaviour described in the TZ lives here:

* ``sweep_delete_pending``  — the 96 hour delete timer (TZ 18)
* ``scheduler_tick``        — open/close topics on their weekly window (TZ 25)
* ``event_reminders``       — event reminders (TZ 13)
* ``daily_snapshot``        — analytics snapshot (TZ 21)
* ``daily_backup``          — automatic backup (TZ 31)
* ``subscription_sweep``    — re-check mandatory membership (TZ 5)

Tasks call into the same service layer the bot and the REST API use, so there is
exactly one implementation of each rule.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

celery_app = Celery(
    "soulchat",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)
celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    task_track_started=True,
    beat_schedule={
        "sweep-delete-pending": {
            "task": "app.tasks.sweep_delete_pending",
            "schedule": 300.0,
        },
        "scheduler-tick": {
            "task": "app.tasks.scheduler_tick",
            "schedule": float(settings.scheduler_tick_seconds),
        },
        "event-reminders": {
            "task": "app.tasks.event_reminders",
            "schedule": 120.0,
        },
        "daily-snapshot": {
            "task": "app.tasks.daily_snapshot",
            "schedule": crontab(hour=0, minute=5),
        },
        "daily-backup": {
            "task": "app.tasks.daily_backup",
            "schedule": crontab(hour=2, minute=0),
        },
        "subscription-sweep": {
            "task": "app.tasks.subscription_sweep",
            "schedule": crontab(minute="*/15"),
        "self-destruct-sweep": {
            "task": "app.tasks.self_destruct_sweep",
            "schedule": 60.0,
        },
        "birthday-sweep": {
            "task": "app.tasks.birthday_sweep",
            "schedule": crontab(hour=9, minute=0),
        },
        },
    },
)


def _run(coro_factory: Any) -> Any:
    """Run an async routine from a sync celery worker."""
    return asyncio.run(coro_factory())


# ---------------------------------------------------------------------------
async def _sweep_delete_pending() -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.topic import Topic
    from app.services.archive_service import ArchiveService
    from app.services.topic_service import TopicService

    now = datetime.now(UTC)
    archived: list[str] = []
    failed: dict[str, str] = {}
    async with session_scope() as session:
        gateway = await _gateway()
        topics_svc = TopicService(session, gateway)
        archives = ArchiveService(session, gateway)
        stmt = select(Topic).where(
            Topic.status == "delete_pending", Topic.delete_at.is_not(None), Topic.delete_at <= now
        )
        topics = list((await session.execute(stmt)).scalars().all())
        for topic in topics:
            # TZ 20 says the archive comes *before* the delete, so a failing
            # export must never reach hard_delete. But one bad topic must not
            # strand the rest of the batch either: this task runs every 5
            # minutes, so without per-topic handling the first failure would
            # abort the sweep forever and every other user's data would sit in
            # delete_pending past its 96 hours.
            try:
                await archives.export(topic)
            except Exception as exc:
                failed[topic.code] = f"archive: {exc}"
                logger.exception("sweep: archive failed for %s", topic.code)
                continue
            try:
                await topics_svc.hard_delete(topic)
            except Exception as exc:
                failed[topic.code] = f"delete: {exc}"
                logger.exception("sweep: delete failed for %s", topic.code)
                continue
            archived.append(topic.code)
    return {"archived": archived, "failed": failed, "count": len(archived)}


async def _scheduler_tick() -> dict[str, Any]:
    from app.core.db import session_scope
    from app.services.event_service import SchedulerService

    async with session_scope() as session:
        gateway = await _gateway()
        return await SchedulerService(session, gateway).tick()


async def _event_reminders() -> dict[str, Any]:
    from app.core.db import session_scope
    from app.enums import NotificationKind
    from app.models.user import User
    from app.services.event_service import EventService
    from app.services.notification import NotificationService

    sent = 0
    async with session_scope() as session:
        events_svc = EventService(session)
        notifications = NotificationService(session, await _gateway())
        for event in await events_svc.due():
            from app.models.topic import Topic

            topic = await session.get(Topic, event.topic_id)
            if topic is None:
                continue
            for user_id in (topic.owner_id, topic.partner_id):
                if not user_id:
                    continue
                user = await session.get(User, user_id)
                if user:
                    await notifications.notify(
                        user,
                        NotificationKind.REMINDER,
                        title=f"Eslatma: {event.title}",
                        body=event.description or "",
                        topic=topic,
                    )
                    sent += 1
            await events_svc.mark_notified(event)
    return {"sent": sent}


async def _daily_snapshot() -> dict[str, Any]:
    from app.core.db import session_scope
    from app.services.analytics_service import AnalyticsService

    async with session_scope() as session:
        row = await AnalyticsService(session).snapshot()
        return {"day": row.day.isoformat(), "messages": row.messages, "topics": row.new_topics}


async def _daily_backup() -> dict[str, Any]:
    if not settings.backup_enabled:
        return {"skipped": True}
    from app.core.db import session_scope
    from app.services.backup_service import BackupService

    async with session_scope() as session:
        result = await BackupService(session).run()
        return {"status": result.status, "path": result.path, "size": result.size}


async def _self_destruct_sweep() -> dict[str, Any]:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.message import Message
    from app.models.topic import Topic

    now = datetime.now(UTC)
    deleted = 0
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Message).where(
                    Message.self_destruct_at.is_not(None),
                    Message.self_destruct_at <= now,
                    Message.deleted.is_(False),
                )
            )
        ).scalars().all()
        if not rows:
            return {"deleted": 0}

        gateway = await _gateway()
        topics = {}
        for row in rows:
            topics[row.topic_id] = None
        for row in rows:
            topic = topics.get(row.topic_id)
            if topic is None:
                topics[row.topic_id] = topic = await session.get(Topic, row.topic_id)
            chat_id = topic.chat_id if topic else None
            if chat_id and row.tg_message_id:
                await gateway.delete_message(chat_id, row.tg_message_id)
            row.deleted = True
            deleted += 1
    return {"deleted": deleted}


async def _birthday_sweep() -> dict[str, Any]:
    from app.core.db import session_scope
    from app.services.notification import NotificationService

    async with session_scope() as session:
        return await NotificationService(session, await _gateway()).birthday_sweep()


async def _subscription_sweep() -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.user import User
    from app.services.subscription_gate import SubscriptionGate

    checked = 0
    async with session_scope() as session:
        gate = SubscriptionGate(session, await _gateway())
        for user in (await session.execute(select(User).limit(500))).scalars().all():
            await gate.check(user.tg_id, force=True)
            checked += 1
    return {"checked": checked}


async def _gateway() -> Any:
    """Real aiogram gateway when a token is configured, fake otherwise."""
    from app.services.telegram_gateway import AiogramGateway, FakeGateway

    if not settings.bot_token:
        return FakeGateway()
    from aiogram import Bot

    return AiogramGateway(Bot(token=settings.bot_token))


# ---------------------------------------------------------------------------
@celery_app.task(name="app.tasks.sweep_delete_pending")
def sweep_delete_pending() -> dict[str, Any]:
    return _run(_sweep_delete_pending)


@celery_app.task(name="app.tasks.scheduler_tick")
def scheduler_tick() -> dict[str, Any]:
    return _run(_scheduler_tick)


@celery_app.task(name="app.tasks.event_reminders")
def event_reminders() -> dict[str, Any]:
    return _run(_event_reminders)


@celery_app.task(name="app.tasks.daily_snapshot")
def daily_snapshot() -> dict[str, Any]:
    return _run(_daily_snapshot)


@celery_app.task(name="app.tasks.daily_backup")
def daily_backup() -> dict[str, Any]:
    return _run(_daily_backup)


@celery_app.task(name="app.tasks.self_destruct_sweep")
def self_destruct_sweep() -> dict[str, Any]:
    return _run(_self_destruct_sweep)


@celery_app.task(name="app.tasks.birthday_sweep")
def birthday_sweep() -> dict[str, Any]:
    return _run(_birthday_sweep)


@celery_app.task(name="app.tasks.subscription_sweep")
def subscription_sweep() -> dict[str, Any]:
    return _run(_subscription_sweep)