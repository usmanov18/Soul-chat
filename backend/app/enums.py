"""Domain enumerations.

Kept in one module so the bot, the REST API, celery tasks and the admin panel
all agree on the exact string values that end up in the database.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    PARTNER = "partner"
    MODERATOR = "moderator"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class TopicStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    FROZEN = "frozen"          # moderator freeze
    BLOCKED = "blocked"        # both users closed it
    DELETE_PENDING = "delete_pending"  # 96h countdown
    ARCHIVED = "archived"
    DELETED = "deleted"


class ParticipantRole(StrEnum):
    OWNER = "owner"
    PARTNER = "partner"


class ParticipantStatus(StrEnum):
    INVITED = "invited"
    PENDING = "pending"
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"


class InviteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class MessageContentType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    LOCATION = "location"
    VENUE = "venue"
    AUDIO = "audio"
    VIDEO_NOTE = "video_note"
    ANIMATION = "animation"
    CONTACT = "contact"
    POLL = "poll"
    SYSTEM = "system"


class MediaKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    ANIMATION = "animation"
    AUDIO = "audio"
    VIDEO_NOTE = "video_note"


class EventKind(StrEnum):
    DATE = "date"
    REMINDER = "reminder"
    PHOTO = "photo"
    VIDEO = "video"
    LOCATION = "location"
    CHECKLIST = "checklist"
    DEADLINE = "deadline"


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    NOTIFIED = "notified"
    DONE = "done"
    CANCELLED = "cancelled"


class ChannelPostType(StrEnum):
    NEW_TOPIC = "new_topic"
    GALLERY = "gallery"
    SYSTEM = "system"


class CloseCodeStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"


class RestoreStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class NotificationKind(StrEnum):
    TOPIC_CREATED = "topic_created"
    PARTNER_JOINED = "partner_joined"
    PARTNER_LEFT = "partner_left"
    REMINDER = "reminder"
    DELETE_PENDING = "delete_pending"
    RESTORED = "restored"
    ARCHIVED = "archived"
    BIRTHDAY = "birthday"
    SYSTEM_NEWS = "system_news"
    WARNING = "warning"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class AuditAction(StrEnum):
    TOPIC_CREATE = "topic.create"
    TOPIC_CLOSE = "topic.close"
    TOPIC_RESTORE = "topic.restore"
    TOPIC_ARCHIVE = "topic.archive"
    TOPIC_DELETE = "topic.delete"
    TOPIC_BLOCK = "topic.block"
    TOPIC_FREEZE = "topic.freeze"
    TOPIC_UNFREEZE = "topic.unfreeze"
    PARTNER_INVITE = "partner.invite"
    PARTNER_ACCEPT = "partner.accept"
    PARTNER_LEAVE = "partner.leave"
    MESSAGE_RELAY = "message.relay"
    MESSAGE_DELETE = "message.delete"
    MEDIA_PUBLISH = "media.publish"
    EVENT_CREATE = "event.create"
    WARN_ISSUED = "moderation.warn"
    USER_BAN = "moderation.ban"
    USER_UNBAN = "moderation.unban"
    USER_UNMUTE = "moderation.unmute"
    USER_MUTE = "moderation.mute"
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    SETTINGS_CHANGE = "settings.change"
    EXPORT = "export.download"
    BACKUP = "system.backup"


class BackupStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ModerationAction(StrEnum):
    ALLOW = "allow"
    FLAG = "flag"
    REVIEW = "review"
    DELETE = "delete"
    BLOCK = "block"


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    UNSPECIFIED = "unspecified"


class SubscriptionKind(StrEnum):
    GROUP = "group"
    CHANNEL = "channel"


class SubscriptionStatus(StrEnum):
    MEMBER = "member"
    LEFT = "left"
    BANNED = "banned"
    UNKNOWN = "unknown"


class CodeScheme(StrEnum):
    SEQUENTIAL = "sequential"
    GENDER = "gender"
    RANDOM = "random"


class SettingType(StrEnum):
    STRING = "string"
    INT = "int"
    BOOL = "bool"
    JSON = "json"


class TopicStatusFlow:
    """Legal transitions for ``Topic.status``.

    Enforced by :meth:`app.services.topic_service.TopicService.transition`.
    """

    ALLOWED: dict[TopicStatus, set[TopicStatus]] = {
        TopicStatus.DRAFT: {TopicStatus.ACTIVE, TopicStatus.DELETED},
        TopicStatus.ACTIVE: {
            TopicStatus.FROZEN,
            TopicStatus.BLOCKED,
            TopicStatus.DELETE_PENDING,
            TopicStatus.ARCHIVED,
        },
        TopicStatus.FROZEN: {TopicStatus.ACTIVE, TopicStatus.DELETE_PENDING, TopicStatus.ARCHIVED},
        TopicStatus.BLOCKED: {TopicStatus.DELETE_PENDING, TopicStatus.ACTIVE},
        TopicStatus.DELETE_PENDING: {TopicStatus.ACTIVE, TopicStatus.ARCHIVED, TopicStatus.DELETED},
        TopicStatus.ARCHIVED: {TopicStatus.ACTIVE, TopicStatus.DELETED},
        TopicStatus.DELETED: set(),
    }

    @classmethod
    def can(cls, current: TopicStatus | str, target: TopicStatus | str) -> bool:
        current = TopicStatus(current)
        target = TopicStatus(target)
        return target in cls.ALLOWED.get(current, set())