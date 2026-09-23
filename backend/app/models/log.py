"""Audit log, notifications, statistics and dynamic settings."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Integer as _Int,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.enums import AuditAction, NotificationKind, NotificationStatus, SettingType
from app.models.base import TimestampMixin


class AuditLog(TimestampMixin, Base):
    """TZ 32: who / when / where / what / ip / telegram id / device."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_actor_action", "actor_tg_id", "action"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(_Int, "sqlite"), primary_key=True, autoincrement=True
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(40), index=True, default=AuditAction.TOPIC_CREATE.value)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    device: Mapped[str | None] = mapped_column(String(255))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16), default="bot")  # bot | api | panel | task
    meta: Mapped[dict | None] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(Text)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notification_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24), default=NotificationKind.SYSTEM_NEWS.value)
    title: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=NotificationStatus.PENDING.value)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)


class StatDaily(TimestampMixin, Base):
    """Pre-aggregated analytics snapshot (TZ 21)."""

    __tablename__ = "stats_daily"
    __table_args__ = (Index("ix_stats_day", "day", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    new_topics: Mapped[int] = mapped_column(Integer, default=0)
    active_topics: Mapped[int] = mapped_column(Integer, default=0)
    closed_topics: Mapped[int] = mapped_column(Integer, default=0)
    deleted_topics: Mapped[int] = mapped_column(Integer, default=0)
    restored_topics: Mapped[int] = mapped_column(Integer, default=0)
    messages: Mapped[int] = mapped_column(Integer, default=0)
    media: Mapped[int] = mapped_column(Integer, default=0)
    new_users: Mapped[int] = mapped_column(Integer, default=0)
    active_users: Mapped[int] = mapped_column(Integer, default=0)
    gallery_posts: Mapped[int] = mapped_column(Integer, default=0)
    channel_posts: Mapped[int] = mapped_column(Integer, default=0)
    avg_messages_per_topic: Mapped[float] = mapped_column(Float, default=0.0)
    avg_topic_days: Mapped[float] = mapped_column(Float, default=0.0)
    retention_d7: Mapped[float] = mapped_column(Float, default=0.0)


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(16), default=SettingType.STRING.value)
    description: Mapped[str | None] = mapped_column(Text)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)