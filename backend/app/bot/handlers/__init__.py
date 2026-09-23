"""Aiogram router.

Thin adapter: parses the Telegram update, hands it to
:class:`app.services.bot_service.SoulChatBot` and renders the returned
:class:`BotReply`. No business rules live here — the parsing helpers are in
:mod:`app.bot.adapter` so they can be unit tested without aiogram I/O.
"""

from __future__ import annotations

from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, Message

from app.bot.adapter import (
    command_arg,
    content_type_of,
    deep_link_payload,
    event_args,
    extract_file,
    keyboard_of,
    media_dimensions,
    moderate_args,
    schedule_args,
)
from app.core.logging import get_logger
from app.enums import EventKind, MessageContentType
from app.services.bot_service import BotReply, SoulChatBot
from app.services.event_service import EventDraft
from app.services.relay import IncomingMessage
from app.services.telegram_gateway import AiogramGateway, TelegramGateway

logger = get_logger(__name__)

router = Router(name="soulchat")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
async def _render(message: Message, reply: BotReply | None) -> None:
    if reply is None:
        return
    if reply.text:
        await message.answer(
            reply.text,
            reply_markup=keyboard_of(reply),
            parse_mode=ParseMode.HTML if reply.parse_mode == "HTML" else None,
        )
    if reply.document:
        payload, filename = reply.document
        await message.answer_document(BufferedInputFile(payload, filename=filename))


def _service(data: dict[str, Any]) -> SoulChatBot:
    bot: Bot = data["bot"]
    gateway: TelegramGateway = data.get("gateway") or AiogramGateway(bot)
    data["gateway"] = gateway
    return SoulChatBot(data["session"], gateway, bot_username=bot.username or "SoulChatBot")


def _incoming(message: Message) -> IncomingMessage:
    file_id, unique_id, size = extract_file(message)
    width, height, duration, mime = media_dimensions(message)
    location = getattr(message, "location", None)
    venue = getattr(message, "venue", None)
    return IncomingMessage(
        user_id=message.from_user.id if message.from_user else 0,
        chat_id=message.chat.id,
        content_type=content_type_of(message),
        text=message.text,
        caption=message.caption,
        file_id=file_id,
        unique_file_id=unique_id,
        file_size=size,
        width=width,
        height=height,
        duration=duration,
        mime_type=mime,
        latitude=getattr(location, "latitude", None) or getattr(venue, "latitude", None)
        if location or venue
        else None,
        longitude=getattr(location, "longitude", None) or getattr(venue, "longitude", None)
        if location or venue
        else None,
        tg_message_id=message.message_id,
        is_forward=bool(message.forward_origin),
        extra={"location": venue.address if venue else None},
    )


def _profile(message: Message) -> dict[str, Any]:
    user = message.from_user
    if user is None:
        return {}
    return {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "language_code": user.language_code,
    }


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
@router.message(CommandStart(deep_link=True))
async def cmd_start(message: Message, command: CommandObject, **data: Any) -> None:
    reply = await _service(data).start(
        message.from_user.id, payload=deep_link_payload(command.args), **_profile(message)
    )
    await _render(message, reply)


@router.message(CommandStart())
async def cmd_start_plain(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).start(message.from_user.id, **_profile(message)))


@router.message(Command("new"))
async def cmd_new(message: Message, **data: Any) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await _render(message, await _service(data).new_topic(message.from_user.id))


@router.message(Command("invite"))
async def cmd_invite(message: Message, **data: Any) -> None:
    # D6: the QR rides along when qrcode is installed; the link is the fallback
    await _render(message, await _service(data).invite_qr(message.from_user.id))


@router.message(Command("close"))
async def cmd_close(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).close(message.from_user.id))


@router.message(Command("confirm"))
async def cmd_confirm(message: Message, command: CommandObject, **data: Any) -> None:
    code = command_arg(command.args)
    if not code:
        await message.answer("Foydalanish: /confirm 123456")
        return
    await _render(message, await _service(data).confirm(message.from_user.id, code))


@router.message(Command("restore"))
async def cmd_restore(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).restore(message.from_user.id))


@router.message(Command("undo"))
async def cmd_undo(message: Message, **data: Any) -> None:
    """Delete the last message this user had relayed into their topic."""
    await _render(message, await _service(data).undo_last(message.from_user.id))


@router.message(Command("archive"))
async def cmd_archive(message: Message, **data: Any) -> None:
    await message.answer("📦 Arxiv tayyorlanmoqda…")
    await _render(message, await _service(data).archive(message.from_user.id))


@router.message(Command("status"))
async def cmd_status(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).status(message.from_user.id))


@router.message(Command("help"))
async def cmd_help(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).help(message.from_user.id))


@router.message(Command("event"))
async def cmd_event(message: Message, command: CommandObject, **data: Any) -> None:
    parsed = event_args(command.args)
    if parsed is None:
        await message.answer("Foydalanish: /event <sarlavha> | 2026-12-31 19:00 | Toshkent")
        return
    title, when, where = parsed
    draft = EventDraft(kind=EventKind.DATE, title=title, location=where)
    if when:
        from datetime import datetime

        try:
            draft.due_at = datetime.fromisoformat(when)
            draft.remind_at = draft.due_at
        except ValueError:
            await message.answer("Sana formati: YYYY-MM-DD HH:MM")
            return
    await _render(message, await _service(data).create_event(message.from_user.id, draft))


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, command: CommandObject, **data: Any) -> None:
    parsed = schedule_args(command.args)
    if parsed is None:
        await message.answer("Format: /schedule 1,3,5 20:00 22:00 (kunlar 0=Yak … 6=Shan)")
        return
    days, start, end = parsed
    await _render(message, await _service(data).schedule(message.from_user.id, days, start, end))


@router.message(Command("stats"))
async def cmd_stats(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).stats(message.from_user.id))


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject, **data: Any) -> None:
    await _render(message, await _service(data).search(message.from_user.id, command.args or ""))


@router.message(Command("moderate"))
async def cmd_moderate(message: Message, command: CommandObject, **data: Any) -> None:
    parsed = moderate_args(command.args)
    if parsed is None:
        await message.answer("Foydalanish: /moderate <warn|mute|ban|freeze|restore> <user_id> [sabab]")
        return
    action, target, reason = parsed
    await _render(message, await _service(data).moderate(message.from_user.id, action, target, reason))


@router.message(Command("timer"))
async def cmd_timer(message: Message, command: CommandObject, **data: Any) -> None:
    await _render(message, await _service(data).timer(message.from_user.id, command_arg(command.args) or ""))


@router.message(Command("appeal"))
async def cmd_appeal(message: Message, command: CommandObject, **data: Any) -> None:
    await _render(message, await _service(data).appeal(message.from_user.id, command_arg(command.args) or ""))


@router.message(Command("summary"))
async def cmd_summary(message: Message, **data: Any) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await _render(message, await _service(data).summary(message.from_user.id))


@router.message(Command("timeline"))
async def cmd_timeline(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).timeline(message.from_user.id))


@router.message(Command("suggest"))
async def cmd_suggest(message: Message, **data: Any) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await _render(message, await _service(data).suggest(message.from_user.id))


@router.message(Command("remember"))
async def cmd_remember(message: Message, command: CommandObject, **data: Any) -> None:
    await _render(message, await _service(data).remember(message.from_user.id, command_arg(command.args) or ""))


@router.message(Command("memory"))
async def cmd_memory(message: Message, **data: Any) -> None:
    await _render(message, await _service(data).memory(message.from_user.id))


@router.message(Command("forget"))
async def cmd_forget(message: Message, command: CommandObject, **data: Any) -> None:
    args = command_arg(command.args)
    await _render(
        message,
        await _service(data).forget(message.from_user.id, int(args) if args and args.isdigit() else 0),
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, command: CommandObject, **data: Any) -> None:
    service = _service(data)
    args = command_arg(command.args)
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
    await _render(message, await _service(data).handle_private_message(_incoming(message)))


@router.edited_message(F.chat.type == "private")
async def private_edited(message: Message, **data: Any) -> None:
    """An edit in the DM is mirrored onto the topic copy."""
    await _render(message, await _service(data).handle_private_edit(_incoming(message)))


@router.message(F.chat.type.in_({"supergroup", "group"}))
async def group_content(message: Message, **data: Any) -> None:
    await _service(data).handle_group_message(
        message.chat.id,
        message.message_id,
        message.from_user.id if message.from_user else 0,
        message.message_thread_id,
    )


@router.callback_query()
async def callbacks(callback: Any, **data: Any) -> None:
    """Inline button router (``new``, ``invite``, ``status`` …)."""
    service = _service(data)
    payload: str = callback.data or ""
    user_id = callback.from_user.id
    handlers = {
        "new": service.new_topic,
        "invite": service.invite,
        "status": service.status,
        "close": service.close,
        "restore": service.restore,
        "archive": service.archive,
        "help": service.help,
    }
    handler = handlers.get(payload)
    reply = await handler(user_id) if handler else BotReply(f"Tugma: {payload}")
    await callback.message.answer(
        reply.text,
        reply_markup=keyboard_of(reply),
        parse_mode=ParseMode.HTML if reply.parse_mode == "HTML" else None,
    )
    await callback.answer()


# ---------------------------------------------------------------------------
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


__all__ = ["router", "register_middlewares", "GatewayMiddleware", "MessageContentType"]