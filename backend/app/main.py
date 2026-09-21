"""FastAPI application factory (TZ 30).

Run with::

    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import analytics, auth, moderation, system, topics, users
from app.api.v1 import settings as settings_router
from app.core.cache import cache
from app.core.config import settings
from app.core.db import create_all, engine
from app.core.logging import get_logger, init_sentry, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment != "production":
        await create_all()
    connected = await cache.connect()
    logger.info("cache backend: %s", cache.backend if connected else "memory")
    init_sentry()
    app.state.started_at = time.time()
    try:
        yield
    finally:
        await cache.close()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "SoulChat AI — Telegram private topic manager. "
            "Two-person private topics inside one public forum supergroup, "
            "fully managed through a bot, with an admin REST API."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_process_time(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        response.headers["X-Process-Time-Ms"] = f"{(time.time() - start) * 1000:.2f}"
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(topics.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(moderation.router, prefix=prefix)
    app.include_router(settings_router.router, prefix=prefix)
    app.include_router(system.router, prefix=prefix)

    @app.get("/", tags=["system"])
    async def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api": prefix,
            "health": f"{prefix}/health",
            "metrics": f"{prefix}/metrics",
        }

    return app


app = create_app()
