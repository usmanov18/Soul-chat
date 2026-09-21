"""Database backup (TZ 31).

``pg_dump`` for PostgreSQL, SQLite file copy for local development. The result
is written to ``backup_dir`` (local target) or streamed to S3 / Google Drive
through the storage adapters in :mod:`app.services.storage`.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.enums import AuditAction, BackupStatus
from app.models.log import Setting
from app.models.security import BackupHistory
from app.services.audit import AuditService

logger = get_logger(__name__)


@dataclass
class BackupResult:
    status: str
    path: str | None
    size: int
    checksum: str | None
    error: str | None = None


class BackupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def run(self, target: str | None = None) -> BackupResult:
        target = target or settings.backup_target
        row = BackupHistory(target=target, status=BackupStatus.RUNNING.value,
                            started_at=datetime.now(UTC))
        self.session.add(row)
        await self.session.flush()

        try:
            path = await self._dump()
            size = os.path.getsize(path)
            checksum = _sha256(path)
            if target != "local":
                path = await self._upload(path, target)
            row.status = BackupStatus.SUCCESS.value
            row.path = path
            row.size = size
            row.checksum = checksum
            row.finished_at = datetime.now(UTC)
            await self.audit.log(AuditAction.BACKUP, message=f"{target} backup -> {path}", source="task")
            return BackupResult(BackupStatus.SUCCESS.value, path, size, checksum)
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.exception("backup failed")
            row.status = BackupStatus.FAILED.value
            row.error = str(exc)[:500]
            row.finished_at = datetime.now(UTC)
            return BackupResult(BackupStatus.FAILED.value, None, 0, None, str(exc))

    async def history(self, limit: int = 20) -> list[BackupHistory]:
        from sqlalchemy import select

        stmt = select(BackupHistory).order_by(BackupHistory.id.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    async def _dump(self) -> str:
        os.makedirs(settings.backup_dir, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        if settings.is_sqlite:
            source = settings.database_url.split("///")[-1]
            destination = os.path.join(settings.backup_dir, f"soulchat-{stamp}.sqlite3")
            shutil.copyfile(source, destination)
            return destination

        destination = os.path.join(settings.backup_dir, f"soulchat-{stamp}.sql")
        dsn = settings.database_url.replace("+asyncpg", "").replace("postgresql://", "postgres://")
        command = ["pg_dump", "--no-owner", "--no-privileges", "--file", destination, dsn]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:  # pragma: no cover - requires pg_dump
            raise RuntimeError(f"pg_dump failed: {proc.stderr[:300]}")
        return destination

    async def _upload(self, path: str, target: str) -> str:  # pragma: no cover - external services
        """Hook point for S3 / Google Drive adapters."""
        if target == "s3":
            from app.services.storage import upload_to_s3

            return await upload_to_s3(path)
        if target == "gdrive":
            from app.services.storage import upload_to_gdrive

            return await upload_to_gdrive(path)
        return path


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["BackupResult", "BackupService", "Setting"]
