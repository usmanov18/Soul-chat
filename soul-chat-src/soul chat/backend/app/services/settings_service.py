"""Dynamic settings stored in the DB, with typed access (TZ 9, 28)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as env_settings
from app.enums import AuditAction, SettingType
from app.models.log import Setting
from app.models.user import User
from app.services.audit import AuditService

DEFAULTS: dict[str, tuple[str, Any]] = {
    "code.scheme": (SettingType.STRING.value, env_settings.default_code_scheme),
    "code.male_letters": (SettingType.STRING.value, env_settings.male_prefix_letters),
    "code.female_letters": (SettingType.STRING.value, env_settings.female_prefix_letters),
    "code.separator": (SettingType.STRING.value, env_settings.code_separator),
    "code.pad": (SettingType.INT.value, env_settings.code_zero_pad),
    "code.emoji": (SettingType.STRING.value, env_settings.code_emoji),
    "topic.max_per_user": (SettingType.INT.value, env_settings.max_topics_per_user),
    "topic.max_partner_topics": (SettingType.INT.value, env_settings.max_partner_topics),
    "topic.delete_pending_hours": (SettingType.INT.value, env_settings.delete_pending_hours),
    "channel.show_names": (SettingType.BOOL.value, env_settings.channel_show_names),
    "archive.include_media": (SettingType.BOOL.value, env_settings.archive_include_media),
    "archive.media_budget_mb": (
        SettingType.INT.value,
        env_settings.archive_media_budget_bytes // (1024 * 1024),
    ),
    "channel.show_gallery": (SettingType.BOOL.value, env_settings.channel_show_gallery),
    "channel.gallery_overlay": (SettingType.BOOL.value, env_settings.channel_gallery_overlay),
    "topic.reactions_enabled": (SettingType.BOOL.value, env_settings.reactions_enabled),
    "topic.forward_enabled": (SettingType.BOOL.value, env_settings.forward_enabled),
    "topic.copy_enabled": (SettingType.BOOL.value, env_settings.copy_enabled),
    "moderation.max_warns": (SettingType.INT.value, env_settings.max_warns),
    "moderation.risk_block": (SettingType.STRING.value, env_settings.ai_risk_block_threshold),
    "security.rate_limit": (SettingType.INT.value, env_settings.rate_limit_per_minute),
    "subscription.required": (SettingType.BOOL.value, env_settings.subscription_required),
    "ai.provider": (SettingType.STRING.value, env_settings.ai_provider),
}


# Operator-facing metadata. Most importantly it says which switches the code
# actually *enforces*, so the admin panel never presents a toggle as a guarantee
# when the Bot API cannot deliver one.
#
#   enforced  — the relay refuses the message outright
#   reactive  — the effect is applied after the fact (the API cannot forbid it
#               up front, so the bot undoes it)
#   advisory  — stored and shown, but not enforceable; documented as such
SETTINGS_META: dict[str, dict[str, str]] = {
    "topic.forward_enabled": {
        "label": "Ko'chirib yuborish (forward)",
        "enforcement": "enforced",
        "note": "O'chiq bo'lsa, boshqa chatdan ko'chirilgan xabar rad etiladi.",
    },
    "topic.reactions_enabled": {
        "label": "Reaksiyalar",
        "enforcement": "reactive",
        "note": (
            "Bot API topic miqyosida reaksiyani taqiqlay olmaydi — "
            "o'chiq bo'lsa bot ularni keyin o'chiradi."
        ),
    },
    "topic.copy_enabled": {
        "label": "Matnni ko'chirish (copy)",
        "enforcement": "advisory",
        "note": (
            "Faqat ma'lumot uchun: sessiz ko'chirilgan xabar qo'lda yozilgandan "
            "farq qilmaydi, shuning uchun uni texnik jihatdan rad etib bo'lmaydi."
        ),
    },
    "channel.show_names": {
        "label": "Kanlda ismlarni ko'rsatish",
        "enforcement": "enforced",
        "note": (
            "O'chiq bo'lsa kanal postlarida va rasm ustidagi kartada faqat kod "
            "chiqadi (TZ 10 anonimligi)."
        ),
    },
    "channel.show_gallery": {
        "label": "Kanalga galereya postlari",
        "enforcement": "enforced",
        "note": "O'chiq bo'lsa foto va videolar kanalga umuman chiqmaydi.",
    },
    "channel.gallery_overlay": {
        "label": "Rasm ustiga karta chizish",
        "enforcement": "enforced",
        "note": (
            "Kod, sana va joy rasmning pastki qismiga chiziladi (TZ 15). "
            "Rasmni o'qib bo'lmasa yoki juda kichik bo'lsa, oddiy foto yuboriladi."
        ),
    },
}


# Bumped on every write. SettingsService instances are created per request, so a
# per-instance cache would let one instance keep serving a value another
# instance had already changed; the generation number keeps them honest.
_generation = 0


def bump_generation() -> None:
    """Tell every cached SettingsService that stored values changed."""
    global _generation
    _generation += 1


def _as_bool(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self._bool_cache: dict[str, bool] = {}
        self._cache_generation = -1

    async def ensure_defaults(self) -> None:
        existing = {
            row.key for row in (await self.session.execute(select(Setting))).scalars().all()
        }
        for key, (value_type, value) in DEFAULTS.items():
            if key in existing:
                continue
            self.session.add(
                Setting(key=key, value=str(value), value_type=value_type,
                        description=f"default for {key}")
            )
        await self.session.flush()

    async def get(self, key: str, default: Any = None) -> Any:
        row = (await self.session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        if row is None:
            fallback = DEFAULTS.get(key)
            return fallback[1] if fallback else default
        return self._cast(row)

    async def get_bool(self, key: str, env_default: bool) -> bool:
        """An operator switch: the stored row wins, the environment is the default.

        Precedence is ``settings`` row -> ``DEFAULTS`` -> ``env_default``.
        Every service that renders something an operator can switch must go
        through here. Reading ``app.core.config`` directly was how
        ``channel.show_names`` became a dead control: the panel could toggle it,
        the row was stored, and the channel kept posting whatever the
        environment said. Results are cached until the next write.
        """
        global _generation
        if self._cache_generation != _generation:
            self._bool_cache.clear()
            self._cache_generation = _generation
        if key in self._bool_cache:
            return self._bool_cache[key]
        try:
            value = await self.get(key, None)
        except Exception:  # pragma: no cover - a missing table must not break posting
            value = None
        result = env_default if value is None else _as_bool(value, env_default)
        # Only cache keys that DEFAULTS knows about: for those the answer does
        # not depend on the caller's env_default, so caching is sound. An
        # unregistered key would otherwise pin whatever default came first.
        if key in DEFAULTS:
            self._bool_cache[key] = result
        return result

    def invalidate(self) -> None:
        self._bool_cache.clear()

    async def set(self, key: str, value: Any, actor: User | None = None) -> Setting:
        row = (await self.session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        value_type = DEFAULTS.get(key, (SettingType.STRING.value, None))[0]
        if row is None:
            row = Setting(key=key, value_type=value_type)
            self.session.add(row)
        if row.value_type == SettingType.JSON.value and not isinstance(value, str):
            row.value = json.dumps(value, ensure_ascii=False)
        elif row.value_type == SettingType.BOOL.value:
            row.value = str(bool(value)).lower()
        else:
            row.value = str(value)
        await self.audit.log(
            AuditAction.SETTINGS_CHANGE, actor=actor, entity_type="Setting",
            message=f"{key}={row.value}", source="panel" if actor else "system",
        )
        await self.session.flush()
        bump_generation()
        return row

    async def all(self) -> dict[str, Any]:
        await self.ensure_defaults()
        rows = (await self.session.execute(select(Setting))).scalars().all()
        return {row.key: self._cast(row) for row in rows}

    @staticmethod
    def _cast(row: Setting) -> Any:
        if row.value is None:
            return None
        if row.value_type == SettingType.INT.value:
            try:
                return int(row.value)
            except ValueError:
                return row.value
        if row.value_type == SettingType.BOOL.value:
            return row.value.lower() in {"1", "true", "yes", "on"}
        if row.value_type == SettingType.JSON.value:
            try:
                return json.loads(row.value)
            except json.JSONDecodeError:
                return row.value
        return row.value