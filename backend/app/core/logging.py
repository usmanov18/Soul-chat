"""Structured logging + optional Sentry wiring."""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = logging.DEBUG if settings.debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("aiogram", "httpx", "sqlalchemy.engine", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    try:  # pragma: no cover - optional dependency
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            release=settings.app_version,
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.1,
        )
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).warning("sentry_sdk not installed, skipping")


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)