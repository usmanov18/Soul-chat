"""Backup, webhook, health and Prometheus metrics endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse

from app.api.deps import AdminUser, SessionDep
from app.api.schemas import BackupOut, BackupVerifyIn, WebhookIn
from app.core import metrics as app_metrics
from app.core.cache import cache
from app.core.config import settings
from app.core.db import table_names
from app.core.logging import get_logger
from app.enums import AuditAction
from app.models.security import BackupHistory
from app.services.audit import AuditService
from app.services.backup_service import BackupService

logger = get_logger(__name__)
router = APIRouter(tags=["system"])

_STARTED_AT = time.time()


@router.get("/health")
async def health(session: SessionDep) -> dict:
    from sqlalchemy import text

    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # pragma: no cover - infra failure
        database = f"error: {exc}"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": settings.app_version,
        "environment": settings.environment,
        "database": database,
        "cache": cache.backend,
        "tables": len(table_names()),
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


@router.post("/backup", response_model=BackupOut)
async def create_backup(session: SessionDep, user: AdminUser) -> BackupOut:
    result = await BackupService(session).run()
    return BackupOut(
        status=result.status, path=result.path, size=result.size,
        checksum=result.checksum, error=result.error,
    )


@router.get("/backup")
async def backup_history(session: SessionDep, user: AdminUser) -> list[dict]:
    rows = await BackupService(session).history()
    return [
        {
            "id": r.id,
            "target": r.target,
            "status": r.status,
            "path": r.path,
            "size": r.size,
            "checksum": r.checksum,
            "error": r.error,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        }
        for r in rows
    ]


@router.get("/backup/{backup_id}/file")
async def backup_file(backup_id: int, session: SessionDep, user: AdminUser) -> FileResponse:
    from pathlib import Path as FilePath

    from fastapi import HTTPException

    row = await session.get(BackupHistory, backup_id)
    if row is None or not row.path:
        raise HTTPException(404, "Backup not found")
    path = FilePath(row.path)
    if not path.is_file():
        raise HTTPException(404, "Backup file is gone from disk")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/gzip" if path.suffix == ".gz" else "application/octet-stream",
    )


@router.post("/backup/verify")
async def backup_verify(payload: BackupVerifyIn, session: SessionDep, user: AdminUser) -> dict:
    """Recompute the checksum so an operator can trust a stored backup."""
    import hashlib
    from pathlib import Path as FilePath

    from fastapi import HTTPException

    row = await session.get(BackupHistory, payload.id)
    if row is None:
        raise HTTPException(404, "Backup not found")
    if not row.checksum:
        return {"id": payload.id, "status": "no_checksum", "expected": None, "actual": None}
    if not row.path or not FilePath(row.path).is_file():
        return {"id": payload.id, "status": "missing_file", "expected": row.checksum, "actual": None}
    digest = hashlib.sha256(FilePath(row.path).read_bytes()).hexdigest()
    status = "ok" if digest == row.checksum else "mismatch"
    await AuditService(session).log(
        AuditAction.BACKUP if status == "ok" else "backup.verify_failed",
        actor=user,
        message=f"verify backup #{payload.id}: {status}",
        source="api",
    )
    return {"id": payload.id, "status": status, "expected": row.checksum, "actual": digest}


@router.post("/webhook")
async def webhook(payload: WebhookIn, request: Request, session: SessionDep) -> dict:
    """Inbound webhook for external systems (payments, storage callbacks…)."""
    await AuditService(session).log(
        AuditAction.SETTINGS_CHANGE,
        entity_type="Webhook",
        message=f"event={payload.event}",
        ip_address=request.client.host if request.client else None,
        source="api",
        meta=payload.payload,
    )
    return {"received": payload.event}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(session: SessionDep) -> str:
    """Prometheus scrape target.

    Only cheap aggregate COUNTs are exposed here, and the rendered text is
    cached for ``METRICS_CACHE_SECONDS``. Heavy analytics (top users, retention,
    averages) belong to the dashboard endpoint and the ``stats_daily`` snapshot.
    """
    cache_key = "metrics:rendered"
    cached = await cache.get(cache_key)
    if cached:
        return str(cached)

    body = await _render_metrics(session)
    await cache.set(cache_key, body, settings.metrics_cache_seconds)
    return body


async def _render_metrics(session: SessionDep) -> str:
    from sqlalchemy import func, select

    from app.core.timeutil import sql_hour
    from app.models.message import ChannelPost, Media, Message
    from app.models.topic import Topic
    from app.models.user import User

    async def count(stmt) -> int:
        return int((await session.execute(stmt)).scalar_one() or 0)

    uptime = time.time() - _STARTED_AT

    users = await count(select(func.count()).select_from(User))
    topics = await count(select(func.count()).select_from(Topic))
    active = await count(
        select(func.count()).select_from(Topic).where(Topic.status == "active")
    )
    deleted = await count(
        select(func.count()).select_from(Topic).where(Topic.status == "deleted")
    )
    messages = await count(select(func.count()).select_from(Message))
    media = await count(select(func.count()).select_from(Media))
    posts = await count(select(func.count()).select_from(ChannelPost))

    lines = [
        "# HELP soulchat_uptime_seconds Process uptime",
        "# TYPE soulchat_uptime_seconds gauge",
        f"soulchat_uptime_seconds {uptime:.0f}",
        "# HELP soulchat_users_total Registered users",
        "# TYPE soulchat_users_total gauge",
        f"soulchat_users_total {users}",
        "# HELP soulchat_topics_total Topics ever created",
        "# TYPE soulchat_topics_total gauge",
        f"soulchat_topics_total {topics}",
        "# HELP soulchat_topics_active Currently active topics",
        "# TYPE soulchat_topics_active gauge",
        f"soulchat_topics_active {active}",
        "# HELP soulchat_topics_deleted Deleted topics",
        "# TYPE soulchat_topics_deleted gauge",
        f"soulchat_topics_deleted {deleted}",
        "# HELP soulchat_messages_total Relayed messages",
        "# TYPE soulchat_messages_total counter",
        f"soulchat_messages_total {messages}",
        "# HELP soulchat_media_total Stored media items",
        "# TYPE soulchat_media_total counter",
        f"soulchat_media_total {media}",
        "# HELP soulchat_channel_posts_total Channel posts published",
        "# TYPE soulchat_channel_posts_total counter",
        f"soulchat_channel_posts_total {posts}",
    ]

    hour = sql_hour(Message.created_at).label("hour")
    hour_rows = (
        await session.execute(
            select(hour, func.count().label("total"))
            .where(Message.created_at.is_not(None))
            .group_by(hour)
        )
    ).all()
    for value, total in hour_rows:
        lines.append(f'soulchat_messages_by_hour{{hour="{int(value)}"}} {int(total)}')

    kind_rows = (
        await session.execute(select(Media.kind, func.count().label("total")).group_by(Media.kind))
    ).all()
    for kind, total in kind_rows:
        lines.append(f'soulchat_media_by_kind{{kind="{kind}"}} {int(total)}')

    body = "\n".join(lines)

    # Application level series (relay outcomes, Telegram call results, archive
    # volume) live in app.core.metrics rather than the database: they are
    # request-path counters, and a COUNT(*) cannot express them.
    return f"{body}\n{app_metrics.render()}"