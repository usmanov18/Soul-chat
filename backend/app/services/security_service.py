"""Security layer: flood control, captcha, blacklist, abuse scoring (TZ 26)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.enums import AuditAction, ModerationAction
from app.models.security import CaptchaChallenge, SpamEvent
from app.models.topic import Topic
from app.models.user import Blacklist, User
from app.services.audit import AuditService

logger = get_logger(__name__)

URL_RE = re.compile(r"https?://\S+|t\.me/\S+", re.I)
REPEAT_RE = re.compile(r"(.)\1{9,}")


class FloodLevel(StrEnum):
    OK = "ok"
    THROTTLE = "throttle"
    CAPTCHA = "captcha"
    MUTE = "mute"


@dataclass
class FloodVerdict:
    level: FloodLevel
    hits: int
    retry_after: int = 0
    captcha_id: int | None = None

    @property
    def blocked(self) -> bool:
        return self.level in {FloodLevel.CAPTCHA, FloodLevel.MUTE}


class SecurityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ------------------------------------------------------------- flood
    async def register_hit(self, tg_id: int) -> FloodVerdict:
        """Sliding-window flood control over the last ``flood_window_seconds``."""
        allowed, hits = await cache.hit_window(
            f"flood:{tg_id}", settings.flood_window_seconds, settings.flood_threshold
        )
        if allowed:
            return FloodVerdict(FloodLevel.OK, hits)

        violations = int(await cache.incr(f"floodv:{tg_id}", ttl=3600) or 1)
        if violations >= settings.captcha_after_violations:
            challenge = await self.issue_captcha(tg_id)
            await self.record(
                tg_id, "flood", score=min(100, hits * 5), action=ModerationAction.BLOCK.value,
                detail={"hits": hits, "violations": violations},
            )
            return FloodVerdict(FloodLevel.CAPTCHA, hits, retry_after=300, captcha_id=challenge.id)

        await self.record(tg_id, "flood", score=min(100, hits * 5), action=ModerationAction.FLAG.value,
                          detail={"hits": hits})
        return FloodVerdict(FloodLevel.THROTTLE, hits, retry_after=settings.flood_window_seconds)

    # ----------------------------------------------------------- captcha
    async def issue_captcha(self, tg_id: int, kind: str = "math") -> CaptchaChallenge:
        import secrets

        a, b = secrets.randbelow(9) + 2, secrets.randbelow(9) + 2
        challenge = CaptchaChallenge(
            user_id=await self._user_id(tg_id),
            kind=kind,
            challenge=f"{a} + {b} = ?",
            answer=str(a + b),
            expires_at=utcnow() + timedelta(minutes=5),
        )
        self.session.add(challenge)
        await self.session.flush()
        return challenge

    async def solve_captcha(self, tg_id: int, answer: str) -> bool:
        user_id = await self._user_id(tg_id)
        row = (
            await self.session.execute(
                select(CaptchaChallenge)
                .where(CaptchaChallenge.user_id == user_id, CaptchaChallenge.solved.is_(False))
                .order_by(CaptchaChallenge.id.desc())
            )
        ).scalars().first()
        if row is None:
            return True
        row.attempts += 1
        if str(answer).strip() == row.answer:
            row.solved = True
            row.solved_at = utcnow()
            await cache.delete(f"floodv:{tg_id}")
            await self.session.flush()
            return True
        if row.attempts >= 3:
            await self.mute(tg_id, minutes=30, reason="captcha failed 3 times")
        await self.session.flush()
        return False

    # ------------------------------------------------------- black/white
    async def is_blocked(self, tg_id: int) -> bool:
        row = (
            await self.session.execute(
                select(Blacklist).where(
                    Blacklist.tg_id == tg_id, Blacklist.kind == "black"
                )
            )
        ).scalars().first()
        if row is None:
            return False
        from app.core.timeutil import is_future

        return is_future(row.expires_at)

    async def is_whitelisted(self, tg_id: int) -> bool:
        return (
            await self.session.execute(
                select(Blacklist).where(Blacklist.tg_id == tg_id, Blacklist.kind == "white")
            )
        ).scalars().first() is not None

    # ------------------------------------------------------------ muting
    async def mute(self, tg_id: int, minutes: int = 30, reason: str = "") -> User | None:
        user = (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user is None:
            return None
        user.is_muted = True
        user.mute_until = utcnow() + timedelta(minutes=minutes)
        await self.audit.log(
            AuditAction.USER_MUTE, actor=user, message=f"muted {minutes}m: {reason}", source="system"
        )
        return user

    async def ban(self, tg_id: int, actor: User | None = None, reason: str = "") -> User | None:
        user = (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user is None:
            return None
        user.is_banned = True
        user.ban_reason = reason
        self.session.add(Blacklist(tg_id=tg_id, kind="black", reason=reason,
                                   created_by=actor.id if actor else None))
        await self.audit.log(AuditAction.USER_BAN, actor=actor, message=f"ban {tg_id}: {reason}")
        return user

    async def warn(self, tg_id: int, actor: User | None, reason: str, topic: Topic | None = None) -> tuple[User | None, int]:
        from app.models.user import Warn

        user = (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user is None:
            return None, 0
        user.warns = (user.warns or 0) + 1
        self.session.add(
            Warn(
                user_id=user.id,
                topic_id=topic.id if topic else None,
                moderator_id=actor.id if actor else None,
                reason=reason,
            )
        )
        await self.audit.log(AuditAction.WARN_ISSUED, actor=actor, topic=topic, message=reason)
        if user.warns >= settings.max_warns:
            await self.ban(tg_id, actor, reason=f"{settings.max_warns} warnings")
        return user, user.warns

    # ------------------------------------------------------- heuristics
    @staticmethod
    def looks_like_spam(text: str) -> int:
        """Cheap pre-filter, 0-100. The AI moderator refines this."""
        score = 0
        if not text:
            return 0
        if len(URL_RE.findall(text)) >= 3:
            score += 45
        if REPEAT_RE.search(text):
            score += 25
        if text.upper() == text and len(text) > 25:
            score += 15
        if len(set(text.lower().split())) <= 2 and len(text.split()) >= 6:
            score += 25
        return min(100, score)

    async def record(
        self,
        tg_id: int,
        kind: str,
        *,
        score: int,
        action: str,
        detail: dict | None = None,
        topic_id: int | None = None,
        excerpt: str | None = None,
    ) -> SpamEvent:
        row = SpamEvent(
            user_id=await self._user_id(tg_id),
            topic_id=topic_id,
            kind=kind,
            score=score,
            action=action,
            detail=detail,
            text_excerpt=(excerpt or "")[:300] or None,
        )
        self.session.add(row)
        user = (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user is not None:
            user.risk_score = min(100, (user.risk_score or 0) + max(0, score // 10))
        await self.session.flush()
        return row

    async def _user_id(self, tg_id: int) -> int:
        user = (await self.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        return user.id if user else 0
