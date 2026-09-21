"""Backup, webhook, health and Prometheus metrics endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.deps import AdminUser, SessionDep
from app.api.schemas import BackupOut, WebhookIn
from app.core.cache import cache
from app.core.config import settings
from app.core.db import table_names
from app.core.logging import get_logger
from app.enums import AuditAction
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
    """Prometheus scrape target."""
    from app.services.analytics_service import AnalyticsService

    stats = await AnalyticsService(session).dashboard()
    uptime = time.time() - _STARTED_AT

    lines = [
        "# HELP soulchat_uptime_seconds Process uptime",
        "# TYPE soulchat_uptime_seconds gauge",
        f"soulchat_uptime_seconds {uptime:.0f}",
        "# HELP soulchat_users_total Registered users",
        "# TYPE soulchat_users_total gauge",
        f"soulchat_users_total {stats.total_users}",
        "# HELP soulchat_topics_total Topics ever created",
        "# TYPE soulchat_topics_total gauge",
        f"soulchat_topics_total {stats.total_topics}",
        "# HELP soulchat_topics_active Currently active topics",
        "# TYPE soulchat_topics_active gauge",
        f"soulchat_topics_active {stats.active_topics}",
        "# HELP soulchat_topics_deleted Deleted topics",
        "# TYPE soulchat_topics_deleted gauge",
        f"soulchat_topics_deleted {stats.deleted_topics}",
        "# HELP soulchat_messages_total Relayed messages",
        "# TYPE soulchat_messages_total counter",
        f"soulchat_messages_total {stats.total_messages}",
        "# HELP soulchat_media_total Stored media items",
        "# TYPE soulchat_media_total counter",
        f"soulchat_media_total {stats.total_media}",
        "# HELP soulchat_channel_posts_total Channel posts published",
        "# TYPE soulchat_channel_posts_total counter",
        f"soulchat_channel_posts_total {stats.channel_posts}",
        "# HELP soulchat_average_chat_length Average messages per topic",
        "# TYPE soulchat_average_chat_length gauge",
        f"soulchat_average_chat_length {stats.average_chat_length:.2f}",
        "# HELP soulchat_retention_d7 7 day retention ratio",
        "# TYPE soulchat_retention_d7 gauge",
        f"soulchat_retention_d7 {stats.retention_d7:.3f}",
    ]
    for item in stats.top_active_hours[:24]:
        lines.append(
            f'soulchat_messages_by_hour{{hour="{item["hour"]}"}} {item["messages"]}'
        )
    lines.append("")
    return "\n".join(lines)
