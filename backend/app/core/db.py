"""Async SQLAlchemy engine / session plumbing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        # aiosqlite runs on a single connection; StaticPool keeps temp/test
        # databases alive for the lifetime of the engine.
        return {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    return {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow}


engine: AsyncEngine = create_async_engine(
    settings.database_url, echo=settings.db_echo, future=True, **_engine_kwargs(settings.database_url)
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for background tasks / celery / bot handlers."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create every table (used by tests and by ``manage.py initdb``)."""
    from app import models  # noqa: F401  (registers the mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all() -> None:
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def table_names() -> list[str]:
    from app import models  # noqa: F401

    return sorted(Base.metadata.tables.keys())
