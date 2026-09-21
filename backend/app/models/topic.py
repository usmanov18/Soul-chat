"""Topic, participants, invites, close codes and restore requests."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.enums import (
    CloseCodeStatus,
    InviteStatus,
    ParticipantRole,
    ParticipantStatus,
    RestoreStatus,
    TopicStatus,
)
from app.models.base import TimestampMixin


class CodePrefix(TimestampMixin, Base):
    """Configurable code scheme.

    ``letters='ABC'`` + ``gender='male'`` means male users get A###, B###, C###
    round-robin. ``mode='sequential'`` ignores gender entirely.
    """

    __tablename__ = "code_prefixes"
    __table_args__ = (UniqueConstraint("letters", "gender", name="uq_code_prefix_gender"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    letters: Mapped[str] = mapped_column(String(26), default="A")
    gender: Mapped[str | None] = mapped_column(String(16))  # male/female/None
    mode: Mapped[str] = mapped_column(String(16), default="sequential")
    separator: Mapped[str] = mapped_column(String(4), default="-")
    pad: Mapped[int] = mapped_column(Integer, default=4)
    emoji: Mapped[str] = mapped_column(String(8), default="")
    counter: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    def letter_for(self, sequence: int) -> str:
        letters = self.letters or "A"
        return letters[sequence % len(letters)]


class Topic(TimestampMixin, Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)  # == code, never a real name
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    message_thread_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Denormalised Telegram ids: the hot path of the relay answers
    # "may this update writer?" straight off the topic row, no join needed.
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    partner_tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=TopicStatus.ACTIVE.value, index=True
    )
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    reactions_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    forward_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    copy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    icon_color: Mapped[int] = mapped_column(Integer, default=0x6FB9F0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    media_count: Mapped[int] = mapped_column(Integer, default=0)
    first_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delete_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_count: Mapped[int] = mapped_column(Integer, default=0)
    close_code: Mapped[str | None] = mapped_column(String(16))
    channel_post_id: Mapped[int | None] = mapped_column(BigInteger)
    schedule_days: Mapped[str | None] = mapped_column(String(32))  # CSV "1,2,3"
    schedule_window_start: Mapped[str | None] = mapped_column(String(5))  # "20:00"
    schedule_window_end: Mapped[str | None] = mapped_column(String(5))  # "22:00"
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
    emotion: Mapped[str | None] = mapped_column(String(32))
    risk_score: Mapped[int] = mapped_column(Integer, default=0)

    participants: Mapped[list[TopicParticipant]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )
    messages: Mapped[list[Message]] = relationship(  # noqa: F821
        back_populates="topic", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship(  # noqa: F821
        back_populates="topic", cascade="all, delete-orphan"
    )

    @property
    def writer_ids(self) -> list[int]:
        """Telegram ids allowed to write in this topic — exactly two at most."""
        writers = [self.owner_tg_id] if self.owner_tg_id else []
        if self.partner_tg_id:
            writers.append(self.partner_tg_id)
        return writers

    @property
    def is_writable(self) -> bool:
        return self.status in {TopicStatus.ACTIVE.value} and not self.is_closed


class TopicParticipant(TimestampMixin, Base):
    __tablename__ = "topic_participants"
    __table_args__ = (
        UniqueConstraint("topic_id", "user_id", name="uq_participant_topic_user"),
        Index("ix_participant_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default=ParticipantRole.OWNER.value)
    status: Mapped[str] = mapped_column(String(16), default=ParticipantStatus.ACTIVE.value)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    messages_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    topic: Mapped[Topic] = relationship(back_populates="participants")


class Invite(TimestampMixin, Base):
    """Partner invitation link (``t.me/<bot>?start=inv_<token>``)."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default=InviteStatus.PENDING.value)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CloseCode(TimestampMixin, Base):
    """Two sided confirmation code for closing a chat (TZ 17)."""

    __tablename__ = "close_codes"
    __table_args__ = (Index("ix_close_code_topic_active", "topic_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    partner_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default=CloseCodeStatus.PENDING.value)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RestoreRequest(TimestampMixin, Base):
    __tablename__ = "restore_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=RestoreStatus.REQUESTED.value)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
