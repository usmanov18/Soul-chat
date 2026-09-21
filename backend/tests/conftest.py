"""Shared fixtures.

Every test runs against a fresh in-memory SQLite database and the
:class:`FakeGateway`, so the whole platform — bot commands, lifecycle state
machine, REST API — is exercised without Telegram, Redis or Postgres.
"""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.cache import cache
from app.core.db import Base, get_session
from app.enums import Gender, Role
from app.models.topic import Topic
from app.models.user import User
from app.services.telegram_gateway import FakeGateway


def pytest_configure(config: pytest.Config) -> None:
    """Keep aiosqlite / SQLAlchemy echo out of the test output."""
    logging.getLogger("aiosqlite").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture(autouse=True)
async def clean_cache():
    await cache.reset()
    yield
    await cache.reset()


@pytest.fixture
def gateway() -> FakeGateway:
    fake = FakeGateway()
    fake.set_member(-100123, 111, "member")
    return fake


# ------------------------------------------------------------------- helpers
@pytest_asyncio.fixture
async def owner(session) -> User:
    user = User(
        tg_id=111, username="akbar", first_name="Akbar", last_name="Karimov",
        gender=Gender.MALE.value, role=Role.USER.value,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def partner(session) -> User:
    user = User(
        tg_id=222, username="salima", first_name="Salima", last_name="Yusupova",
        gender=Gender.FEMALE.value, role=Role.USER.value,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def outsider(session) -> User:
    user = User(tg_id=333, username="begona", first_name="Begona", gender=Gender.MALE.value)
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def moderator(session) -> User:
    user = User(tg_id=900, username="mod", first_name="Moder", role=Role.MODERATOR.value)
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def admin(session) -> User:
    user = User(tg_id=901, username="admin", first_name="Admin", role=Role.ADMIN.value)
    session.add(user)
    await session.flush()
    return user


async def make_topic(session, owner: User, code: str = "A-0001", thread_id: int = 1000) -> Topic:
    from app.enums import ParticipantRole, ParticipantStatus, TopicStatus
    from app.models.topic import TopicParticipant

    topic = Topic(
        code=code, title=code, chat_id=-100123, message_thread_id=thread_id,
        owner_id=owner.id, owner_tg_id=owner.tg_id, status=TopicStatus.ACTIVE.value,
    )
    session.add(topic)
    await session.flush()
    session.add(
        TopicParticipant(
            topic_id=topic.id, user_id=owner.id, role=ParticipantRole.OWNER.value,
            status=ParticipantStatus.ACTIVE.value,
        )
    )
    await session.flush()
    return topic


# ------------------------------------------------------------------- api app
@pytest_asyncio.fixture
async def client(session, admin, monkeypatch):
    from app.core.security import create_access_token
    from app.main import create_app

    app = create_app()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        http.headers["Authorization"] = f"Bearer {create_access_token(admin.id, {'role': admin.role})}"
        yield http
