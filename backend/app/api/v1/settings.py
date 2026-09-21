"""Dynamic settings endpoints (TZ 28)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AdminUser, SessionDep
from app.api.schemas import SettingUpdate
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def get_settings(session: SessionDep, user: AdminUser) -> dict:
    return {"items": await SettingsService(session).all()}


@router.put("")
async def update_setting(payload: SettingUpdate, session: SessionDep, user: AdminUser) -> dict:
    row = await SettingsService(session).set(payload.key, payload.value, user)
    return {"key": row.key, "value": row.value, "type": row.value_type}


@router.post("/reset")
async def reset(session: SessionDep, user: AdminUser) -> dict:
    service = SettingsService(session)
    await service.ensure_defaults()
    return {"items": await service.all()}
