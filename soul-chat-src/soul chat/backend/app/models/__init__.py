"""Model registry.

Importing this package registers every mapper on
:data:`app.core.db.Base.metadata`.
"""

from __future__ import annotations

from app.models.log import AuditLog, Notification, Setting, StatDaily
from app.models.message import ChannelPost, Event, Media, Message
from app.models.security import (
    ApiKey,
    Archive,
    BackupHistory,
    CaptchaChallenge,
    Session,
    SpamEvent,
)
from app.models.topic import (
    CloseCode,
    CodePrefix,
    Invite,
    RestoreRequest,
    Topic,
    TopicParticipant,
)
from app.models.user import Blacklist, Subscription, User, Warn

__all__ = [
    "ApiKey",
    "Archive",
    "AuditLog",
    "BackupHistory",
    "Blacklist",
    "CaptchaChallenge",
    "ChannelPost",
    "CloseCode",
    "CodePrefix",
    "Event",
    "Invite",
    "Media",
    "Message",
    "Notification",
    "RestoreRequest",
    "Session",
    "Setting",
    "SpamEvent",
    "StatDaily",
    "Subscription",
    "Topic",
    "TopicParticipant",
    "User",
    "Warn",
]