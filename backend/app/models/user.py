"""User centric tables: accounts, roles, subscriptions, bans and warns."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.enums import Role, SubscriptionKind, SubscriptionStatus
from app.models.base import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str] = mapped_column(String(8), default="uz")
    gender: Mapped[str] = mapped_column(String(16), default="unspecified")
    role: Mapped[str] = mapped_column(String(20), default=Role.USER.value, index=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ban_reason: Mapped[str | None] = mapped_column(Text)
    ban_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    mute_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warns: Mapped[int] = mapped_column(Integer, default=0)
    risk_score: Mapped[float] = mapped_column(Integer, default=0)
    birthday: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent")
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL", use_alter=True, name="fk_user_last_topic")
    )
    topics_created: Mapped[int] = mapped_column(Integer, default=0)
    messages_sent: Mapped[int] = mapped_column(Integer, default=0)
    premium: Mapped[bool] = mapped_column(Boolean, default=False)

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="user")
    warns_log: Mapped[list[Warn]] = relationship(
        back_populates="user", foreign_keys="Warn.user_id"
    )

    @property
    def full_name(self) -> str:
        name = " ".join(part for part in (self.first_name, self.last_name) if part).strip()
        return name or self.username or f"id{self.tg_id}"


class Subscription(TimestampMixin, Base):
    """Mandatory membership check: forum group + broadcast channel."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscription_user_kind", "user_id", "kind", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default=SubscriptionKind.GROUP.value)
    chat_id: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default=SubscriptionStatus.UNKNOWN.value)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_member: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="subscriptions")


class Warn(TimestampMixin, Base):
    __tablename__ = "warns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    moderator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(
        back_populates="warns_log", foreign_keys="Warn.user_id"
    )


class Blacklist(TimestampMixin, Base):
    """Global blacklist / whitelist used by the security layer."""

    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="black")  # black | white
    reason: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
