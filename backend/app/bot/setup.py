"""Bot bootstrap: aiogram Dispatcher, webhook or polling."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_dispatcher(bot: Bot) -> Dispatcher:
    from app.bot.handlers import register_middlewares, router
    from app.services.telegram_gateway import AiogramGateway

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    register_middlewares(dispatcher, AiogramGateway(bot))
    return dispatcher


def build_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def set_commands(bot: Bot) -> None:
    from aiogram.types import BotCommand

    await bot.set_my_commands(
        [
            BotCommand(command="new", description="Yangi suhbat yaratish"),
            BotCommand(command="invite", description="Sherik taklif qilish"),
            BotCommand(command="status", description="Suhbat holati"),
            BotCommand(command="close", description="Suhbatni yopish"),
            BotCommand(command="restore", description="Suhbatni tiklash"),
            BotCommand(command="archive", description="Arxivni yuklab olish"),
            BotCommand(command="event", description="Hodisa yaratish"),
            BotCommand(command="schedule", description="Yozish vaqtini belgilash"),
            BotCommand(command="help", description="Qo'llanma"),
        ]
    )


async def run_polling() -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set")
    bot = build_bot()
    dispatcher = build_dispatcher(bot)
    await set_commands(bot)
    logger.info("starting polling for @%s", (await bot.get_me()).username)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


async def run_webhook() -> None:  # pragma: no cover - requires a public endpoint
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web

    bot = build_bot()
    dispatcher = build_dispatcher(bot)
    await set_commands(bot)
    await bot.set_webhook(
        url=f"{settings.bot_webhook_url}/webhook",
        secret_token=settings.bot_webhook_secret,
        drop_pending_updates=True,
    )
    app = web.Application()
    SimpleRequestHandler(dispatcher=dispatcher, bot=bot, secret_token=settings.bot_webhook_secret).register(
        app, path="/webhook"
    )
    setup_application(app, dispatcher, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()
    await asyncio.Event().wait()