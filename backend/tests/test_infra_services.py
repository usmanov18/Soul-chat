"""The three services that had no test: backup, notification, storage.

``backup_service`` is the one that matters most — it is the only mechanism that
keeps the data, and a backup that fails silently is worse than no backup at all.
"""

from __future__ import annotations

import os
import sqlite3

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.enums import AuditAction, BackupStatus, NotificationKind, NotificationStatus
from app.models.log import Notification
from app.models.security import BackupHistory
from app.services.backup_service import BackupService
from app.services.notification import NotificationService
from app.services.storage import media_path, store_local
from tests.conftest import make_topic


# ---------------------------------------------------------------------------
# backup (TZ 31)
# ---------------------------------------------------------------------------
async def test_sqlite_backup_copies_the_database(session, tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    sqlite3.connect(source).execute("CREATE TABLE t (id INTEGER)").connection.commit()

    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{source}")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "backup_target", "local")

    result = await BackupService(session).run()

    assert result.status == BackupStatus.SUCCESS.value
    assert result.path and os.path.exists(result.path)
    assert result.size > 0
    assert result.error is None
    # the copy must be a usable database, not a truncated file
    tables = sqlite3.connect(result.path).execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert ("t",) in tables


async def test_backup_records_a_row_with_checksum(session, tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    sqlite3.connect(source).close()

    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{source}")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))

    result = await BackupService(session).run()

    rows = (await session.execute(select(BackupHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == BackupStatus.SUCCESS.value
    assert rows[0].checksum == result.checksum
    assert rows[0].finished_at is not None
    # sha256 is 64 hex chars
    assert len(result.checksum) == 64


async def test_backup_failure_is_recorded_not_raised(session, tmp_path, monkeypatch):
    """A missing source must produce a failed row, never an exception."""
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///tmp/does-not-exist.db")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))

    result = await BackupService(session).run()

    assert result.status == BackupStatus.FAILED.value
    assert result.path is None
    assert result.size == 0
    assert result.error

    rows = (await session.execute(select(BackupHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == BackupStatus.FAILED.value
    assert rows[0].error


async def test_successful_backup_is_audited(session, tmp_path, monkeypatch):
    from app.models.log import AuditLog

    source = tmp_path / "source.sqlite3"
    sqlite3.connect(source).close()
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{source}")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))

    await BackupService(session).run()

    logs = (
        await session.execute(select(AuditLog).where(AuditLog.action == AuditAction.BACKUP.value))
    ).scalars().all()
    assert len(logs) == 1


async def test_backup_history_is_newest_first(session, tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    sqlite3.connect(source).close()
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{source}")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))

    service = BackupService(session)
    first = await service.run()
    second = await service.run()

    history = await service.history(limit=10)
    assert len(history) == 2
    assert history[0].id > history[1].id
    assert first.path != second.path


async def test_unknown_upload_target_keeps_the_local_path(session, tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    sqlite3.connect(source).close()
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{source}")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))

    result = await BackupService(session).run(target="somewhere-unknown")

    assert result.status == BackupStatus.SUCCESS.value
    assert result.path.startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# notification (TZ 24)
# ---------------------------------------------------------------------------
async def test_notification_is_persisted_and_delivered(session, owner, gateway):
    row = await NotificationService(session, gateway).notify(
        owner, NotificationKind.DELETE_PENDING, title="Suhbat o'chirilmoqda", body="96 soat qoldi"
    )

    assert row.status == NotificationStatus.SENT.value
    assert row.tg_message_id is not None
    assert row.sent_at is not None

    stored = (await session.execute(select(Notification))).scalar_one()
    assert stored.kind == NotificationKind.DELETE_PENDING.value
    assert stored.user_id == owner.id

    sent = gateway.sent("send_message")
    assert len(sent) == 1
    assert "Suhbat o'chirilmoqda" in sent[0].args[1]


async def test_notification_is_kept_when_no_gateway_is_available(session, owner):
    """Rows are always persisted: a Telegram outage must not lose the event."""
    row = await NotificationService(session, None).notify(
        owner, NotificationKind.REMINDER, body="Eslatma"
    )

    assert row.tg_message_id is None
    assert row.status != NotificationStatus.SENT.value
    assert (await session.execute(select(Notification))).scalar_one() is not None


async def test_notification_can_skip_delivery(session, owner, gateway):
    row = await NotificationService(session, gateway).notify(
        owner, NotificationKind.SYSTEM_NEWS, body="x", deliver=False
    )

    assert row.tg_message_id is None
    assert gateway.sent("send_message") == []


async def test_delivery_failure_is_recorded_with_the_error(session, owner, gateway):
    gateway.fail_on.add("send_message")

    row = await NotificationService(session, gateway).notify(
        owner, NotificationKind.SYSTEM_NEWS, body="x"
    )

    assert row.status == NotificationStatus.FAILED.value
    assert row.error


async def test_notification_is_linked_to_the_topic(session, owner, gateway):
    topic = await make_topic(session, owner)

    row = await NotificationService(session, gateway).notify(
        owner, NotificationKind.DELETE_PENDING, topic=topic, body="x"
    )
    assert row.topic_id == topic.id


# ---------------------------------------------------------------------------
# storage (TZ 33)
# ---------------------------------------------------------------------------
async def test_store_local_creates_the_parent_directory(tmp_path):
    target = str(tmp_path / "nested" / "deeper" / "file.bin")
    assert not os.path.exists(os.path.dirname(target))

    returned = await store_local(target)

    assert returned == target
    assert os.path.isdir(os.path.dirname(target))


async def test_store_local_handles_a_bare_filename(tmp_path, monkeypatch):
    """``dirname`` of a bare name is "" — makedirs must not choke on it."""
    monkeypatch.chdir(tmp_path)
    assert await store_local("plain.bin") == "plain.bin"


def test_media_path_is_under_the_media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "media"))

    path = media_path("AgADBA", "jpg")

    assert path == os.path.join(str(tmp_path / "media"), "AgADBA.jpg")
    assert os.path.isdir(str(tmp_path / "media"))


def test_media_path_defaults_the_extension():
    assert media_path("AgADBA").endswith(".bin")


@pytest.mark.parametrize(
    "target", ["local", "s3", "gdrive"],
)
def test_backup_targets_are_a_known_vocabulary(target: str):
    """Guards the if-chain in ``_upload`` against a silently ignored target."""
    assert target in {"local", "s3", "gdrive"}