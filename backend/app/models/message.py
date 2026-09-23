"""Messages, media, events and channel posts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.enums import (
    ChannelPostType,
    EventKind,
    EventStatus,
    MediaKind,
    MessageContentType,
)
from app.models.base import TimestampMixin


class Message(TimestampMixin, Base):
    """Every relayed message. This is the archive source of truth (TZ 20)."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_message_topic_thread", "topic_id", "tg_message_id"),
        Index("ix_message_topic_created", "topic_id", "created_at"),
        # Telegram retries updates on network hiccups; the source DM id is what
        # makes a relay idempotent (one DM message -> one topic message).
        # Partial: only relayed DM copies carry a source id. Without the WHERE
        # clause two group messages (source NULL) would violate the constraint.
        Index(
            "ix_message_source",
            "topic_id",
            "sender_id",
            "source_message_id",
            unique=True,
            postgresql_where=text("source_message_id IS NOT NULL"),
            sqlite_where=text("source_message_id IS NOT NULL"),
            mssql_where=text("source_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    # id of the *incoming* DM/inline message this row was relayed from
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    thread_id: Mapped[int | None] = mapped_column(BigInteger)
    # Internal users.id; kept as a plain column so an archive row never
    # depends on the account still existing.
    sender_id: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    content_type: Mapped[str] = mapped_column(
        String(20), default=MessageContentType.TEXT.value, index=True
    )
    text: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(String(255), index=True)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger)
    forwarded: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    moderation_action: Mapped[str] = mapped_column(String(16), default="allow")
    relayed: Mapped[bool] = mapped_column(Boolean, default=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    # D1: /timer sets this; the beat sweep deletes the topic copy when it passes
    self_destruct_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    topic: Mapped[Topic] = relationship(back_populates="messages")  # noqa: F821
    media: Mapped[list[Media]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class Media(TimestampMixin, Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default=MediaKind.PHOTO.value, index=True)
    file_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    unique_file_id: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(String(64))
    caption: Mapped[str | None] = mapped_column(Text)
    thumb_path: Mapped[str | None] = mapped_column(String(512))
    storage_path: Mapped[str | None] = mapped_column(String(512))
    published_to_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    channel_post_id: Mapped[int | None] = mapped_column(BigInteger)
    nsfw: Mapped[bool] = mapped_column(Boolean, default=False)
    nsfw_score: Mapped[int] = mapped_column(Integer, default=0)

    message: Mapped[Message | None] = relationship(back_populates="media")


class Event(TimestampMixin, Base):
    """In-topic events: date, reminder, checklist, deadline, ... (TZ 13)."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_event_due_status", "due_at", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), default=EventKind.DATE.value, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    location: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    media_file_id: Mapped[str | None] = mapped_column(String(255))
    checklist: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=EventStatus.SCHEDULED.value)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    topic: Mapped[Topic] = relationship(back_populates="events")  # noqa: F821


class Memory(TimestampMixin, Base):
    """A fact the couple saved on purpose via /remember (TZ 27)."""

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memory_topic", "topic_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)

    topic: Mapped[Topic] = relationship()  # noqa: F821


class ChannelPost(TimestampMixin, Base):
    __tablename__ = "channel_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), default=ChannelPostType.NEW_TOPIC.value)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text)
    media_file_ids: Mapped[list | None] = mapped_column(JSON)
    template: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_reason: Mapped[str | None] = mapped_column(Text)