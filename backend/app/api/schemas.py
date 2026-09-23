"""Pydantic schemas for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    username: str
    password: str


class TelegramAuthRequest(BaseModel):
    """Panel login for staff accounts that already exist as Telegram users."""

    tg_id: int
    secret: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# -------------------------------------------------------------------- users
class UserOut(ORMModel):
    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    gender: str
    role: str
    is_banned: bool
    is_muted: bool
    warns: int
    messages_sent: int
    topics_created: int
    created_at: datetime


class UserUpdate(BaseModel):
    role: str | None = None
    gender: str | None = None
    is_banned: bool | None = None
    is_muted: bool | None = None
    warns: int | None = None
    premium: bool | None = None


# ------------------------------------------------------------------- topics
class TopicOut(ORMModel):
    id: int
    code: str
    title: str
    chat_id: int
    message_thread_id: int | None = None
    owner_id: int
    partner_id: int | None = None
    status: str
    is_closed: bool
    message_count: int
    media_count: int
    restore_count: int
    delete_at: datetime | None = None
    created_at: datetime


class TopicList(BaseModel):
    items: list[TopicOut]
    total: int


class TopicActionRequest(BaseModel):
    reason: str = ""


# ---------------------------------------------------------------- analytics
class DashboardOut(BaseModel):
    stats: dict[str, Any]
    daily: list[dict[str, Any]]
    weekly: list[dict[str, Any]]
    monthly: list[dict[str, Any]]


class SearchRequest(BaseModel):
    hashtag: str | None = None
    query: str = ""
    code: str | None = None
    username: str | None = None
    tg_id: int | None = None
    since: datetime | None = None
    until: datetime | None = None
    media_only: bool = False
    limit: int = Field(default=50, le=200)


# --------------------------------------------------------------- moderation
class ModerationRequest(BaseModel):
    action: str  # warn | mute | ban | freeze | unfreeze | restore
    tg_id: int
    reason: str = ""
    topic_code: str | None = None


class WarnOut(BaseModel):
    user_id: int
    warns: int


# ----------------------------------------------------------------- settings
class SettingItem(BaseModel):
    key: str
    value: Any


class SettingUpdate(BaseModel):
    key: str
    value: Any


class SettingsOut(BaseModel):
    items: dict[str, Any]


# ------------------------------------------------------------------- backup
class BackupVerifyIn(BaseModel):
    id: int


class BackupOut(BaseModel):
    status: str
    path: str | None = None
    size: int = 0
    checksum: str | None = None
    error: str | None = None


# -------------------------------------------------------------------- misc
class HealthOut(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    cache: str
    tables: int
    uptime_seconds: float


class WebhookIn(BaseModel):
    """Generic inbound webhook used by external integrations."""

    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class MessageOut(ORMModel):
    id: int
    topic_id: int
    sender_id: int
    content_type: str
    text: str | None = None
    caption: str | None = None
    has_media: bool
    created_at: datetime