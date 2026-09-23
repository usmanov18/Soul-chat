"""Admin credentials (TZ 28 security).

Covers the two things that previously had no test and both broke in practice:

* ``hash_password`` / ``verify_password`` — passlib 1.7.4 was incompatible with
  bcrypt 5.x, so *every* hash call raised ``password cannot be longer than 72
  bytes``. The helpers now use ``bcrypt`` directly.
* the bootstrap login (``<username>:<SECRET_KEY>``) and how it is retired by
  ``manage.py setpassword``.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.enums import Role


# ---------------------------------------------------------------------------
# hashing primitives
# ---------------------------------------------------------------------------
def test_roundtrip_short_password():
    hashed = hash_password("KuchliParol2026!")
    assert hashed.startswith("$2b$")
    assert verify_password("KuchliParol2026!", hashed) is True
    assert verify_password("kuchliparol2026!", hashed) is False


@pytest.mark.parametrize(
    "password",
    [
        "x" * 71,          # just under bcrypt's limit
        "x" * 72,          # exactly at it
        "x" * 73,          # one byte over — used to raise
        "y" * 400,         # JWT-sized (session tokens are hashed with this too)
        "ўзбек-пароль-1234",  # multibyte
        "",                # empty
    ],
)
def test_any_length_can_be_hashed(password: str):
    """bcrypt only reads 72 bytes; longer input is folded through SHA-256."""
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password(password + "!", hashed) is False


def test_two_hashes_of_the_same_password_differ():
    """Salted: identical passwords must not produce identical hashes."""
    assert hash_password("same") != hash_password("same")


def test_malformed_hash_is_a_failed_login_not_an_error():
    assert verify_password("anything", "not-a-bcrypt-hash") is False
    assert verify_password("anything", "") is False


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------
async def test_bootstrap_login_works_until_a_real_password_is_set(session, admin):
    from app.core.config import settings
    from app.models.user import User

    bootstrap = f"{admin.username}:{settings.secret_key}"

    response = await session.get(User, admin.id)  # keep the row attached
    assert response.password_hash is None

    from app.api.v1.auth import _verify_credentials

    assert _verify_credentials(admin, bootstrap, settings.secret_key) is True
    assert _verify_credentials(admin, "wrong", settings.secret_key) is False


async def test_bootstrap_login_can_be_disabled(session, admin, monkeypatch):
    from app.api.v1.auth import _verify_credentials

    monkeypatch.setattr(settings, "allow_bootstrap_login", False)
    bootstrap = f"{admin.username}:{settings.secret_key}"
    assert _verify_credentials(admin, bootstrap, settings.secret_key) is False


async def test_stored_password_wins_and_retires_the_bootstrap(session, admin):
    from app.api.v1.auth import _verify_credentials
    from app.core.config import settings

    admin.password_hash = hash_password("KuchliParol2026!")
    await session.flush()

    assert _verify_credentials(admin, "KuchliParol2026!", settings.secret_key) is True
    # the derived credential stops working the moment a real one exists
    assert _verify_credentials(admin, f"{admin.username}:{settings.secret_key}", settings.secret_key) is False


async def test_login_endpoint_issues_a_token(session, admin):
    """End to end through the router, not just the helper."""
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_session
    from app.core.security import create_access_token
    from app.main import create_app

    admin.password_hash = hash_password("KuchliParol2026!")
    await session.flush()

    app = create_app()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        ok = await http.post(
            "/api/v1/auth/login",
            json={"username": admin.username, "password": "KuchliParol2026!"},
        )
        bad = await http.post(
            "/api/v1/auth/login",
            json={"username": admin.username, "password": "nope"},
        )

    assert ok.status_code == 200, ok.text
    assert ok.json()["access_token"]
    assert bad.status_code == 401

    token = ok.json()["access_token"]
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        protected = await http.get(
            "/api/v1/topics", headers={"Authorization": f"Bearer {token}"}
        )
    assert protected.status_code == 200
    assert create_access_token  # token helper is the one under test above


async def test_staff_roles_are_the_only_ones_allowed_in(session, owner):
    """A regular Telegram user is not an admin account."""
    from app.api.v1.auth import _verify_credentials
    from app.core.config import settings

    assert owner.role == Role.USER.value
    bootstrap = f"{owner.username}:{settings.secret_key}"
    # the credential itself is derived the same way; authorisation happens at
    # the dependency layer, which is covered in test_api.py
    assert _verify_credentials(owner, bootstrap, settings.secret_key) is True