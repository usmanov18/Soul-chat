"""Timezone helpers.

SQLite hands back naive datetimes, PostgreSQL returns ``timestamptz``. Every
comparison in the codebase therefore goes through :func:`aware` first so the
same code behaves identically on both engines.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Integer
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement


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


# ---------------------------------------------------------------------------
# dialect aware SQL fragments
# ---------------------------------------------------------------------------
class sql_hour(FunctionElement[Any]):
    """``HOUR(column)`` compiled per dialect.

    Why this is a SQL construct and not an ``if settings.is_sqlite`` branch:
    the decision has to be made from the *dialect the statement is compiled
    against*, not from a global setting. A branch on ``DATABASE_URL`` silently
    emitted ``strftime('%H', …)`` for PostgreSQL — where that function does not
    exist — because the expression is built before it is bound to an engine, so
    anything that patched the URL (tests, a future CLI that connects to both)
    produced SQL for the wrong database.

    ``strftime('%H', …)`` yields text on SQLite and ``EXTRACT`` yields numeric on
    PostgreSQL, hence the casts that make both sides integer.
    """

    type = Integer()
    name = "sql_hour"
    inherit_cache = True


@compiles(sql_hour)
def _compile_sql_hour_default(element: sql_hour, compiler: Any, **kw: Any) -> str:
    # generic fallback: ANSI EXTRACT works on PostgreSQL, MySQL, Oracle
    (column,) = element.clauses
    return f"CAST(EXTRACT(HOUR FROM {compiler.process(column, **kw)}) AS INTEGER)"


@compiles(sql_hour, "sqlite")
def _compile_sql_hour_sqlite(element: sql_hour, compiler: Any, **kw: Any) -> str:
    (column,) = element.clauses
    return f"CAST(strftime('%H', {compiler.process(column, **kw)}) AS INTEGER)"


@compiles(sql_hour, "postgresql")
def _compile_sql_hour_postgresql(element: sql_hour, compiler: Any, **kw: Any) -> str:
    (column,) = element.clauses
    return f"CAST(EXTRACT(HOUR FROM {compiler.process(column, **kw)}) AS INTEGER)"