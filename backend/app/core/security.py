"""Password hashing, JWT issuing/verification and random code helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

_CODE_ALPHABET = string.digits

# bcrypt only ever reads the first 72 bytes of the secret. passlib used to
# truncate silently; the `bcrypt` package raises instead, so the input is
# folded through SHA-256 first. That keeps any length safe (JWTs are hashed
# with this helper too) and makes the limit explicit rather than surprising.
_BCRYPT_MAX_BYTES = 72


def _secret(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) <= _BCRYPT_MAX_BYTES:
        return raw
    digest = hashlib.sha256(raw).hexdigest().encode("ascii")  # 64 bytes, ASCII safe
    return digest


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_secret(password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_secret(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        # malformed/foreign hash format: treat as a failed login, never a 500
        return False


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str | int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.refresh_token_ttl_days)).timestamp()),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Return the decoded payload or raise ``jwt.PyJWTError``."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def random_numeric_code(length: int | None = None) -> str:
    """Closes-chats confirmation code, e.g. ``948213``."""
    length = length or settings.close_code_length
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())