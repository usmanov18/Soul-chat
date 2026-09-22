"""Celery entry point: ``celery -A celery_worker.celery_app worker -B``."""

from app.tasks import celery_app

__all__ = ["celery_app"]