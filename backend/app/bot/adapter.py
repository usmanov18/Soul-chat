"""Pure translation between Telegram updates and service-layer objects.

Everything in this module is a plain function with no I/O, which is what makes
the bot adapter testable: the handlers only wire aiogram to these helpers and
to :class:`app.services.bot_service.SoulChatBot`.
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.enums import MessageContentType
from app.services.bot_service import BotReply

_CONTENT_TYPES: dict[str, str] = {
    "photo": MessageContentType.PHOTO.value,
    "video": MessageContentType.VIDEO.value,
    "voice": MessageContentType.VOICE.value,
    "document": MessageContentType.DOCUMENT.value,
    "audio": MessageContentType.AUDIO.value,
    "animation": MessageContentType.ANIMATION.value,
    "sticker": MessageContentType.STICKER.value,
    "video_note": MessageContentType.VIDEO_NOTE.value,
    "location": MessageContentType.LOCATION.value,
    "venue": MessageContentType.VENUE.value,
}

# attributes holding the file id, in the order aiogram exposes them
_FILE_ATTRS = (
    "photo",
    "video",
    "voice",
    "document",
    "audio",
    "animation",
    "sticker",
    "video_note",
)


def content_type_of(message: Any) -> str:
    """Map aiogram's ``content_type`` onto our enum."""
    return _CONTENT_TYPES.get(getattr(message, "content_type", "") or "", MessageContentType.TEXT.value)


def extract_file(message: Any) -> tuple[str | None, str | None, int]:
    """Return ``(file_id, unique_file_id, file_size)`` for a media message.

    Photos arrive as a list of sizes — the largest one is the one to store.
    """
    for attr in _FILE_ATTRS:
        value = getattr(message, attr, None)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = max(value, key=lambda item: getattr(item, "file_size", 0) or 0)
        return (
            getattr(value, "file_id", None),
            getattr(value, "file_unique_id", None),
            int(getattr(value, "file_size", 0) or 0),
        )
    return None, None, 0


def media_dimensions(message: Any) -> tuple[int | None, int | None, int | None, str | None]:
    """``(width, height, duration, mime_type)`` when the payload carries them."""
    for attr in _FILE_ATTRS:
        value = getattr(message, attr, None)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = max(value, key=lambda item: getattr(item, "file_size", 0) or 0)
        return (
            getattr(value, "width", None),
            getattr(value, "height", None),
            getattr(value, "duration", None),
            getattr(value, "mime_type", None),
        )
    return None, None, None, None


def keyboard_of(reply: BotReply) -> InlineKeyboardMarkup | None:
    """Render a :class:`BotReply`'s button rows as an inline keyboard."""
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button.text, callback_data=button.callback) for button in row]
            for row in reply.buttons
        ]
    )


def deep_link_payload(args: str | None) -> str:
    """``/start inv_ABC`` -> ``inv_ABC`` (empty string when absent)."""
    return (args or "").strip()


def command_arg(args: str | None) -> str:
    return (args or "").strip()


def schedule_args(args: str | None) -> tuple[list[int], str, str] | None:
    """Parse ``1,3,5 20:00 22:00``; ``None`` when the shape is wrong."""
    parts = (args or "").split()
    if len(parts) != 3:
        return None
    days_raw, start, end = parts
    try:
        days = [int(day) for day in days_raw.split(",") if day.strip()]
    except ValueError:
        return None
    return days, start, end


def event_args(args: str | None) -> tuple[str, str | None, str | None] | None:
    """Parse ``<sarlavha> | 2026-12-31 19:00 | Toshkent``."""
    raw = (args or "").strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split("|")]
    title = parts[0]
    when = parts[1] if len(parts) > 1 and parts[1] else None
    where = parts[2] if len(parts) > 2 and parts[2] else None
    return title, when, where


def moderate_args(args: str | None) -> tuple[str, int, str] | None:
    """Parse ``<action> <user_id> [reason]``."""
    parts = (args or "").split(maxsplit=2)
    if len(parts) < 2:
        return None
    try:
        target = int(parts[1])
    except ValueError:
        return None
    return parts[0], target, parts[2] if len(parts) > 2 else ""