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
    "topic.delete_pending_hours": (SettingType.INT.value, env_settings.delete_pending_hours),
    "topic.reactions_enabled": (SettingType.BOOL.value, env_settings.reactions_enabled),
    "topic.forward_enabled": (SettingType.BOOL.value, env_settings.forward_enabled),
    "topic.copy_enabled": (SettingType.BOOL.value, env_settings.copy_enabled),
    "moderation.max_warns": (SettingType.INT.value, env_settings.max_warns),
    "moderation.risk_block": (SettingType.STRING.value, env_settings.ai_risk_block_threshold),
    "security.rate_limit": (SettingType.INT.value, env_settings.rate_limit_per_minute),
    "subscription.required": (SettingType.BOOL.value, env_settings.subscription_required),
    "ai.provider": (SettingType.STRING.value, env_settings.ai_provider),
}


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

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
