"""Mandatory membership gate (TZ 5).

Nothing works unless the user is a member of **both** the forum group and the
broadcast channel. Telegram answers with ``kicked`` / ``left`` / ``restricted``
for non members, and ``member`` / ``administrator`` / ``creator`` otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.enums import SubscriptionKind, SubscriptionStatus
from app.models.user import Subscription, User

logger = get_logger(__name__)

MEMBER_STATES = {"member", "administrator", "creator"}


class ChatMemberLookup(Protocol):
    """Anything that can answer ``getChatMember`` — aiogram Bot or a test fake."""

    async def get_chat_member(self, chat_id: int, user_id: int) -> object: ...  # pragma: no cover


@dataclass
class GateResult:
    allowed: bool
    is_group_member: bool
    is_channel_member: bool
    missing: list[str]

    def reason(self) -> str:
        if self.allowed:
            return "ok"
        return ",".join(self.missing)


class SubscriptionGate:
    def __init__(self, session: AsyncSession, bot: ChatMemberLookup | None = None) -> None:
        self.session = session
        self.bot = bot

    # ------------------------------------------------------------------
    async def check(self, tg_id: int, force: bool = False) -> GateResult:
        """Verify group + channel membership, cached for ``subscription_cache_ttl``."""
        if not settings.subscription_required:
            return GateResult(True, True, True, [])

        cache_key = f"sub:{tg_id}"
        if not force:
            cached = await cache.get(cache_key)
            if cached == "ok":
                return GateResult(True, True, True, [])
            if cached and cached.startswith("no:"):
                missing = [m for m in cached[3:].split("|") if m]
                return GateResult(False, "group" not in missing, "channel" not in missing, missing)

        group_member = await self._is_member(settings.forum_chat_id, tg_id)
        channel_member = await self._is_member(settings.channel_id, tg_id)

        missing: list[str] = []
        if not group_member:
            missing.append("group")
        if not channel_member:
            missing.append("channel")

        allowed = not missing
        await cache.set(
            cache_key, "ok" if allowed else f"no:{'|'.join(missing)}", settings.subscription_cache_ttl
        )
        await self._persist(tg_id, group_member, channel_member)
        return GateResult(allowed, group_member, channel_member, missing)

    async def invalidate(self, tg_id: int) -> None:
        await cache.delete(f"sub:{tg_id}")

    # ------------------------------------------------------------------
    async def _is_member(self, chat_id: int, tg_id: int) -> bool:
        if not chat_id or self.bot is None:
            # Not configured / no bot wired (tests, offline dev): do not block.
            return True
        try:
            member = await self.bot.get_chat_member(chat_id, tg_id)
        except Exception as exc:  # bot not admin, chat not found, network...
            logger.warning("getChatMember failed chat=%s user=%s: %s", chat_id, tg_id, exc)
            return False
        status = getattr(member, "status", None) or getattr(member, "state", None) or "unknown"
        return str(status) in MEMBER_STATES

    async def _persist(self, tg_id: int, group_member: bool, channel_member: bool) -> None:
        user = (
            await self.session.execute(select(User).where(User.tg_id == tg_id))
        ).scalar_one_or_none()
        if user is None:
            return
        now = utcnow()
        for kind, chat_id, ok in (
            (SubscriptionKind.GROUP, settings.forum_chat_id, group_member),
            (SubscriptionKind.CHANNEL, settings.channel_id, channel_member),
        ):
            row = (
                await self.session.execute(
                    select(Subscription).where(
                        Subscription.user_id == user.id,
                        Subscription.kind == kind.value,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = Subscription(user_id=user.id, kind=kind.value, chat_id=chat_id)
                self.session.add(row)
            row.chat_id = chat_id
            row.is_member = ok
            row.status = SubscriptionStatus.MEMBER.value if ok else SubscriptionStatus.LEFT.value
            row.checked_at = now
        await self.session.flush()
