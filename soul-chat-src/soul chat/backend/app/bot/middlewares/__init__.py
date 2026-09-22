"""Aiogram middlewares: DB session, user resolution, subscription gate, throttle."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from aiogram.types import User as TgUser

from app.core.cache import cache
from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.services.security_service import SecurityService
from app.services.subscription_gate import SubscriptionGate

logger = get_logger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class DatabaseSessionMiddleware(BaseMiddleware):
    """One transactional session per update."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with session_scope() as session:
            data["session"] = session
            return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """Per user rate limit shared with the REST API through the same cache."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: TgUser | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        allowed, hits = await cache.hit_window(
            f"tg:{user.id}", window=60, limit=settings.rate_limit_per_minute
        )
        if not allowed:
            if isinstance(event, Message):
                await event.answer("⏳ Juda tez-buyruq bermoqdasiz. Biroz kuting.")
            return None
        data["throttle_hits"] = hits
        return await handler(event, data)


class SecurityMiddleware(BaseMiddleware):
    """Hard stop for blacklisted users before any handler runs."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: TgUser | None = data.get("event_from_user")
        session = data.get("session")
        if user is None or session is None:
            return await handler(event, data)

        security = SecurityService(session)
        if await security.is_blocked(user.id):
            if isinstance(event, Message):
                await event.answer("⛔ Siz qora ro'yxatdasiz.")
            return None
        if await security.is_whitelisted(user.id):
            data["whitelisted"] = True
        return await handler(event, data)


class SubscriptionMiddleware(BaseMiddleware):
    """TZ 5 — group + channel membership is mandatory for every function."""

    def __init__(self, skip_commands: tuple[str, ...] = ("/start", "/help")) -> None:
        self.skip_commands = skip_commands

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not settings.subscription_required:
            return await handler(event, data)
        user: TgUser | None = data.get("event_from_user")
        session = data.get("session")
        if user is None or session is None or not isinstance(event, Message):
            return await handler(event, data)
        if event.text and event.text.split()[0] in self.skip_commands:
            return await handler(event, data)
        if event.chat and event.chat.type != "private":
            return await handler(event, data)

        gateway = data.get("gateway")
        gate = SubscriptionGate(session, gateway)
        result = await gate.check(user.id)
        if not result.allowed:
            missing = []
            if "group" in result.missing:
                missing.append("guruhga a'zo bo'ling")
            if "channel" in result.missing:
                missing.append("kanalga obuna bo'ling")
            await event.answer(
                "🔒 Bot funksiyalari faqat obunachilar uchun:\n  • " + "\n  • ".join(missing)
            )
            return None
        data["subscription"] = result
        return await handler(event, data)