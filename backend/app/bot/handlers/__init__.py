"""Aiogram router.

Thin adapter: parses the Telegram update, hands it to
:class:`app.services.bot_service.SoulChatBot` and renders the returned
:class:`BotReply`. No business rules live here.
"""

from __future__ import annotations

from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.logging import get_logger
from app.enums import EventKind, MessageContentType
from app.services.bot_service import BotReply, Button, SoulChatBot
from app.services.event_service import EventDraft
from app.services.relay import IncomingMessage
from app.services.telegram_gateway import AiogramGateway, TelegramGateway

logger = get_logger(__name__)

router = Router(name="soulchat")


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def _keyboard(reply: BotReply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button.text, callback_data=button.callback) for button in row]
            for row in reply.buttons
        ]
    )


async def _render(message: Message, reply: BotReply | None) -> None:
    if reply is None:
        return
    if reply.text:
        await message.answer(
            reply.text,
            reply_markup=_keyboard(reply),
            parse_mode=ParseMode.HTML if reply.parse_mode == "HTML" else None,
        )
    if reply.document:
        from aiogram.types import BufferedInputFile

        payload, filename = reply.document
        await message.answer_document(BufferedInputFile(payload, filename=filename))


def _bot(data: dict[str, Any]) -> SoulChatBot:
    bot: Bot = data["bot"]
    gateway: TelegramGateway = data.get("gateway") or AiogramGateway(bot)
    data["gateway"] = gateway
    return SoulChatBot(data["session"], gateway, bot_username=bot.username or "SoulChatBot")


def _content_type(message: Message) -> str:
    mapping = {
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
    return mapping.get(message.content_type or "", MessageContentType.TEXT.value)


def _incoming(message: Message) -> IncomingMessage:
    file_id = None
    for attr in ("photo", "video", "voice", "document", "audio", "animation", "sticker", "video_note"):
        value = getattr(message, attr, None)
        if value:
            file_id = value[-1].file_id if isinstance(value, list) else value.file_id
            break
    return IncomingMessage(
        user_id=message.from_user.id if message.from_user else 0,
        chat_id=message.chat.id,
        content_type=_content_type(message),
        text=message.text,
        caption=message.caption,
        file_id=file_id,
        tg_message_id=message.message_id,
        is_forward=bool(message.forward_origin),
        extra={"location": message.venue.address if message.venue else None},
    )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
@router.message(CommandStart(deep_link=True))
async def cmd_start(message: Message, command: CommandObject, **data: Any) -> None:
    service = _bot(data)
    user = message.from_user
    reply = await service.start(
        user.id if user else 0,
        payload=command.args or "",
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
        language_code=user.language_code if user else None,
    )
    await _render(message, reply)


@router.message(CommandStart())
async def cmd_start_plain(message: Message, **data: Any) -> None:
    service = _bot(data)
    user = message.from_user
    reply = await service.start(
        user.id if user else 0,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
        language_code=user.language_code if user else None,
    )
    await _render(message, reply)


@router.message(Command("new"))
async def cmd_new(message: Message, **data: Any) -> None:
    service = _bot(data)
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await _render(message, await service.new_topic(message.from_user.id))


@router.message(Command("invite"))
async def cmd_invite(message: Message, **data: Any) -> None:
    await _render(message, await _bot(data).invite(message.from_user.id))


@router.message(Command("close"))
async def cmd_close(message: Message, **data: Any) -> None:
    await _render(message, await _bot(data).close(message.from_user.id))


@router.message(Command("confirm"))
async def cmd_confirm(message: Message, command: CommandObject, **data: Any) -> None:
    code = (command.args or "").strip()
    if not code:
        await message.answer("Foydalanish: /confirm 123456")
        return
    await _render(message, await _bot(data).confirm(message.from_user.id, code))


@router.message(Command("restore"))
async def cmd_restore(message: Message, **data: Any) -> None:
    await _render(message, await _bot(data).restore(message.from_user.id))


@router.message(Command("archive"))
async def cmd_archive(message: Message, **data: Any) -> None:
    await message.answer("📦 Arxiv tayyorlanmoqda…")
    await _render(message, await _bot(data).archive(message.from_user.id))


@router.message(Command("status"))
async def cmd_status(message: Message, **data: Any) -> None:
    await _render(message, await _bot(data).status(message.from_user.id))


@router.message(Command("help"))
async def cmd_help(message: Message, **data: Any) -> None:
    await _render(message, await _bot(data).help(message.from_user.id))


@router.message(Command("event"))
async def cmd_event(message: Message, command: CommandObject, **data: Any) -> None:
    args = (command.args or "").strip()
    if not args:
        await message.answer("Foydalanish: /event <sarlavha> | 2026-12-31 19:00 | Toshkent")
        return
    parts = [part.strip() for part in args.split("|")]
    draft = EventDraft(kind=EventKind.DATE, title=parts[0])
    if len(parts) > 1 and parts[1]:
        from datetime import datetime

        try:
            draft.due_at = datetime.fromisoformat(parts[1])
            draft.remind_at = draft.due_at
        except ValueError:
            await message.answer("Sana formati: YYYY-MM-DD HH:MM")
            return
    if len(parts) > 2:
        draft.location = parts[2]
    await _render(message, await _bot(data).create_event(message.from_user.id, draft))


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, command: CommandObject, **data: Any) -> None:
    args = (command.args or "").strip()
    if not args:
        await message.answer("Foydalanish: /schedule 1,3,5 20:00 22:00")
        return
    try:
        days_raw, start, end = args.split()
        days = [int(d) for d in days_raw.split(",") if d.strip()]
    except ValueError:
        await message.answer("Format: /schedule 1,3,5 20:00 22:00 (kunlar 0=Yak … 6=Shan)")
        return
    await _render(message, await _bot(data).schedule(message.from_user.id, days, start, end))


@router.message(Command("stats"))
async def cmd_stats(message: Message, **data: Any) -> None:
    await _render(message, await _bot(data).stats(message.from_user.id))


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject, **data: Any) -> None:
    await _render(message, await _bot(data).search(message.from_user.id, command.args or ""))


@router.message(Command("moderate"))
async def cmd_moderate(message: Message, command: CommandObject, **data: Any) -> None:
    parts = (command.args or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Foydalanish: /moderate <warn|mute|ban|freeze|restore> <user_id> [sabab]")
        return
    action, target = parts[0], parts[1]
    reason = parts[2] if len(parts) > 2 else ""
    await _render(
        message, await _bot(data).moderate(message.from_user.id, action, int(target), reason)
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, command: CommandObject, **data: Any) -> None:
    service = _bot(data)
    args = (command.args or "").strip()
    if not args:
        await _render(message, await service.settings_view(message.from_user.id))
        return
    key, _, value = args.partition("=")
    await _render(message, await service.set_setting(message.from_user.id, key.strip(), value.strip()))


# ---------------------------------------------------------------------------
# content
# ---------------------------------------------------------------------------
@router.message(F.chat.type == "private")
async def private_content(message: Message, **data: Any) -> None:
    service = _bot(data)
    await _render(message, await service.handle_private_message(_incoming(message)))


@router.message(F.chat.type.in_({"supergroup", "group"}))
async def group_content(message: Message, **data: Any) -> None:
    service = _bot(data)
    await service.handle_group_message(
        message.chat.id,
        message.message_id,
        message.from_user.id if message.from_user else 0,
        message.message_thread_id,
    )


@router.callback_query()
async def callbacks(callback: Any, **data: Any) -> None:
    """Inline button router (``new``, ``invite``, ``status`` …)."""
    service = _bot(data)
    payload: str = callback.data or ""
    user_id = callback.from_user.id
    if payload == "new":
        reply = await service.new_topic(user_id)
    elif payload == "invite":
        reply = await service.invite(user_id)
    elif payload == "status":
        reply = await service.status(user_id)
    elif payload == "close":
        reply = await service.close(user_id)
    elif payload == "restore":
        reply = await service.restore(user_id)
    elif payload == "archive":
        reply = await service.archive(user_id)
    elif payload == "help":
        reply = await service.help(user_id)
    else:
        reply = BotReply(f"Tugma: {payload}")
    await callback.message.answer(reply.text, reply_markup=_keyboard(reply),
                                  parse_mode=ParseMode.HTML if reply.parse_mode == "HTML" else None)
    await callback.answer()


class GatewayMiddleware(BaseMiddleware):
    """Injects the shared transport into every handler's data dict."""

    def __init__(self, gateway: TelegramGateway) -> None:
        self.gateway = gateway

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        data["gateway"] = self.gateway
        return await handler(event, data)


def register_middlewares(dispatcher: Any, gateway: TelegramGateway) -> None:
    from app.bot.middlewares import (
        DatabaseSessionMiddleware,
        SecurityMiddleware,
        SubscriptionMiddleware,
        ThrottleMiddleware,
    )

    dispatcher.update.outer_middleware(DatabaseSessionMiddleware())
    dispatcher.update.outer_middleware(GatewayMiddleware(gateway))
    dispatcher.message.middleware(ThrottleMiddleware())
    dispatcher.message.middleware(SecurityMiddleware())
    dispatcher.message.middleware(SubscriptionMiddleware())
