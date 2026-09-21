"""Authentication endpoints (TZ 30)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, SessionDep, client_ip
from app.api.schemas import LoginRequest, RefreshRequest, TokenPair
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.enums import AuditAction, Role
from app.models.security import Session
from app.models.user import User
from app.services.audit import AuditService

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request, session: SessionDep) -> TokenPair:
    """Staff login. ``username`` is the Telegram username of a moderator/admin."""
    from sqlalchemy import select

    user = (
        await session.execute(select(User).where(User.username == payload.username.lstrip("@")))
    ).scalar_one_or_none()

    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user.role not in {Role.MODERATOR.value, Role.ADMIN.value, Role.SUPER_ADMIN.value}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a staff account")

    secret = settings.secret_key
    if not verify_password(payload.password, _bootstrap_hash(user, secret)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    access = create_access_token(user.id, {"role": user.role, "tg_id": user.tg_id})
    refresh = create_refresh_token(user.id)
    session.add(
        Session(
            user_id=user.id,
            token_hash=hash_password(access)[:60],
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            expires_at=_ttl(),
        )
    )
    await AuditService(session).log(
        AuditAction.LOGIN, actor=user, ip_address=client_ip(request), source="api"
    )
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenPair:
    import jwt as pyjwt

    try:
        data = decode_token(payload.refresh_token)
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid refresh token: {exc}") from exc
    if data.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = await session.get(User, int(data["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return TokenPair(
        access_token=create_access_token(user.id, {"role": user.role}),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return {
        "id": user.id,
        "tg_id": user.tg_id,
        "username": user.username,
        "name": user.full_name,
        "role": user.role,
        "premium": user.premium,
    }


def _bootstrap_hash(user: User, secret: str) -> str:
    """Staff password = ``<username>:<secret_key>`` until a real credential store exists."""
    return hash_password(f"{user.username}:{secret}")


def _ttl():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(minutes=settings.access_token_ttl_minutes)
