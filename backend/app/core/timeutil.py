"""Timezone helpers.

SQLite hands back naive datetimes, PostgreSQL returns ``timestamptz``. Every
comparison in the codebase therefore goes through :func:`aware` first so the
same code behaves identically on both engines.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime (no-op for aware ones and ``None``)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_future(value: datetime | None) -> bool:
    """``True`` when the timestamp is still ahead of us (``None`` = no expiry)."""
    checked = aware(value)
    if checked is None:
        return True
    return checked > utcnow()


def is_past(value: datetime | None) -> bool:
    checked = aware(value)
    if checked is None:
        return False
    return checked <= utcnow()


def hours_since(value: datetime | None, now: datetime | None = None) -> float:
    start = aware(value)
    if start is None:
        return 0.0
    return ((now or utcnow()) - start).total_seconds() / 3600.0
