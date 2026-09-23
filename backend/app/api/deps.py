"""Shared FastAPI dependencies: DB session, current user, role guards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.logging import get_logger
from app.core.security import constant_time_equals, decode_token, hash_api_key
from app.core.timeutil import is_future
from app.enums import Role
from app.models.security import ApiKey
from app.models.user import User

logger = get_logger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

STAFF = {Role.MODERATOR.value, Role.ADMIN.value, Role.SUPER_ADMIN.value}
ADMINS = {Role.ADMIN.value, Role.SUPER_ADMIN.value}


async def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> User:
    """JWT bearer or API key."""
    if x_api_key:
        user = await _user_from_api_key(session, x_api_key)
        if user:
            return user
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")

    user = await session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    if user.is_banned and user.role not in STAFF:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is banned")
    return user


async def _user_from_api_key(session: AsyncSession, raw: str) -> User | None:
    key_hash = hash_api_key(raw)
    row = (await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))).scalar_one_or_none()
    if row is None or not row.active:
        return None
    if row.expires_at is not None and not is_future(row.expires_at):
        return None
    row.last_used_at = datetime.now(UTC)
    if not row.owner_id:
        return None
    return await session.get(User, row.owner_id)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    """Dependency factory enforcing a minimum role set."""

    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return checker


StaffUser = Annotated[User, Depends(require_role(*STAFF))]
AdminUser = Annotated[User, Depends(require_role(*ADMINS))]


async def optional_current_user(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> User | None:
    try:
        return await get_current_user(session, authorization, None)
    except HTTPException:
        return None


def client_ip(request: Any) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def check_secret(provided: str, expected: str) -> bool:
    return constant_time_equals(provided, expected)