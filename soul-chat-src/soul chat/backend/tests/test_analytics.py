"""TZ 21/23 — analytics and search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.enums import MessageContentType, TopicStatus
from app.models.message import Media, Message
from app.services.analytics_service import AnalyticsService
from tests.conftest import make_topic


async def _seed(session, owner, partner):
    topic = await make_topic(session, owner, code="A-0001")
    topic.partner_id = partner.id
    topic.status = TopicStatus.ACTIVE.value
    topic.closed_at = datetime.now(UTC)
    for index in range(5):
        session.add(Message(topic_id=topic.id, sender_id=owner.id, content_type="text",
                            text=f"salom {index}"))
    session.add(Message(topic_id=topic.id, sender_id=partner.id,
                        content_type=MessageContentType.PHOTO.value, has_media=True, file_id="f1"))
    session.add(Media(topic_id=topic.id, kind=MessageContentType.PHOTO.value, file_id="f1", file_size=2048))
    await session.flush()
    return topic


async def test_dashboard_counts(session, owner, partner):
    await _seed(session, owner, partner)
    stats = await AnalyticsService(session).dashboard()

    assert stats.total_topics == 1
    assert stats.total_messages == 6
    assert stats.total_media == 1
    assert stats.active_topics == 1
    assert stats.average_chat_length == 6.0
    assert stats.average_days >= 0.0


async def test_top_users_and_hours(session, owner, partner):
    await _seed(session, owner, partner)
    owner.messages_sent = 5
    partner.messages_sent = 1
    await session.flush()

    stats = await AnalyticsService(session).dashboard()
    assert stats.top_users[0]["tg_id"] == owner.tg_id
    assert stats.top_active_hours
    assert stats.top_media[0]["kind"] == MessageContentType.PHOTO.value


async def test_daily_series_fills_missing_days(session, owner, partner):
    await _seed(session, owner, partner)
    series = await AnalyticsService(session).daily_series(days=7)
    assert len(series) == 7
    assert sum(item["messages"] for item in series) == 6


async def test_weekly_and_monthly_buckets(session, owner, partner):
    await _seed(session, owner, partner)
    service = AnalyticsService(session)
    assert len(await service.weekly(4)) == 4
    assert len(await service.monthly(6)) == 6


async def test_snapshot_is_idempotent(session, owner, partner):
    from sqlalchemy import select

    from app.models.log import StatDaily

    await _seed(session, owner, partner)
    service = AnalyticsService(session)
    first = await service.snapshot()
    second = await service.snapshot()
    assert first.id == second.id
    rows = (await session.execute(select(StatDaily))).scalars().all()
    assert len(rows) == 1


async def test_search_by_code_username_and_text(session, owner, partner):
    await _seed(session, owner, partner)
    service = AnalyticsService(session)

    by_code = await service.search(code="a-0001")
    assert len(by_code["topics"]) == 1

    by_user = await service.search(username="akbar")
    assert len(by_user["users"]) == 1

    by_text = await service.search(query="salom")
    assert len(by_text["messages"]) == 5

    media_only = await service.search(media_only=True)
    assert len(media_only["messages"]) == 1


async def test_search_by_tg_id_and_date_range(session, owner, partner):
    await _seed(session, owner, partner)
    service = AnalyticsService(session)
    assert len((await service.search(tg_id=owner.tg_id))["users"]) == 1
    future = datetime.now(UTC) + timedelta(days=1)
    assert (await service.search(query="salom", since=future))["messages"] == []


# ---------------------------------------------------------------------------
# dialect aware SQL (the PostgreSQL paths that SQLite tests cannot reach)
# ---------------------------------------------------------------------------
def test_sql_hour_compiles_per_dialect_not_per_setting():
    """Regression: the hour used to be chosen from ``settings.is_sqlite``.

    The expression is built before it is bound to an engine, so a branch on the
    URL emitted ``strftime('%H', …)`` for PostgreSQL — a function PostgreSQL does
    not have. The decision must come from the compiling dialect.
    """
    from sqlalchemy.dialects import mysql, postgresql, sqlite

    from app.core.timeutil import sql_hour
    from app.models.message import Message

    pg = str(sql_hour(Message.created_at).compile(dialect=postgresql.dialect()))
    lite = str(sql_hour(Message.created_at).compile(dialect=sqlite.dialect()))

    assert "EXTRACT(HOUR FROM messages.created_at)" in pg
    assert "strftime" not in pg
    assert "strftime('%H', messages.created_at)" in lite
    assert "EXTRACT" not in lite
    # both sides must be integer so GROUP BY / ORDER BY behave the same
    assert pg.startswith("CAST(") and lite.startswith("CAST(")
    # the generic fallback also produces valid SQL rather than failing
    assert "EXTRACT" in str(sql_hour(Message.created_at).compile(dialect=mysql.dialect()))


def test_sql_hour_is_independent_of_the_configured_database(monkeypatch):
    """Patching DATABASE_URL must not change the generated SQL."""
    from sqlalchemy.dialects import postgresql

    from app.core.config import settings
    from app.core.timeutil import sql_hour
    from app.models.message import Message

    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///./x.db")
    while_sqlite = str(sql_hour(Message.created_at).compile(dialect=postgresql.dialect()))

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@h/db")
    while_postgres = str(sql_hour(Message.created_at).compile(dialect=postgresql.dialect()))

    assert while_sqlite == while_postgres
    assert "EXTRACT" in while_postgres


def test_hour_histogram_query_compiles_for_postgresql():
    """The whole aggregate, not just the fragment."""
    from sqlalchemy import func, select
    from sqlalchemy.dialects import postgresql

    from app.core.timeutil import sql_hour
    from app.models.message import Message

    hour = sql_hour(Message.created_at).label("hour")
    stmt = (
        select(hour, func.count().label("total"))
        .where(Message.created_at.is_not(None))
        .group_by(hour)
        .order_by(func.count().desc())
    )
    compiled = str(stmt.compile(dialect=postgresql.dialect()))

    assert "GROUP BY" in compiled
    assert "strftime" not in compiled


def test_partial_unique_index_compiles_with_where_for_postgresql():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex

    from app.models.message import Message

    index = next(i for i in Message.__table__.indexes if i.name == "ix_message_source")
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "UNIQUE" in ddl
    assert "WHERE source_message_id IS NOT NULL" in ddl


def test_row_lock_compiles_for_postgresql():
    """``invite_service.accept`` guards the single partner slot with this."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.models.topic import Topic

    compiled = str(
        select(Topic).where(Topic.id == 1).with_for_update().compile(dialect=postgresql.dialect())
    )
    assert compiled.rstrip().endswith("FOR UPDATE")