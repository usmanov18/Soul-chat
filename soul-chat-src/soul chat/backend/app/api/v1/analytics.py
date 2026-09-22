"""Analytics + search endpoints (TZ 21, 23)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, StaffUser
from app.api.schemas import DashboardOut, SearchRequest
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    session: SessionDep, user: StaffUser, days: int = Query(default=30, le=365)
) -> DashboardOut:
    service = AnalyticsService(session)
    stats = await service.dashboard()
    return DashboardOut(
        stats=stats.to_dict(),
        daily=await service.daily_series(days),
        weekly=await service.weekly(),
        monthly=await service.monthly(),
    )


@router.get("/daily")
async def daily(session: SessionDep, user: StaffUser, days: int = Query(default=30, le=365)) -> list[dict]:
    return await AnalyticsService(session).daily_series(days)


@router.get("/weekly")
async def weekly(session: SessionDep, user: StaffUser) -> list[dict]:
    return await AnalyticsService(session).weekly()


@router.get("/monthly")
async def monthly(session: SessionDep, user: StaffUser) -> list[dict]:
    return await AnalyticsService(session).monthly()


@router.post("/search")
async def search(payload: SearchRequest, session: SessionDep, user: StaffUser) -> dict:
    return await AnalyticsService(session).search(
        query=payload.query,
        code=payload.code,
        username=payload.username,
        tg_id=payload.tg_id,
        since=payload.since,
        until=payload.until,
        media_only=payload.media_only,
        limit=payload.limit,
    )


@router.get("/top-users")
async def top_users(session: SessionDep, user: StaffUser) -> list[dict]:
    return (await AnalyticsService(session).dashboard()).top_users


@router.get("/top-hours")
async def top_hours(session: SessionDep, user: StaffUser) -> list[dict]:
    return (await AnalyticsService(session).dashboard()).top_active_hours


@router.post("/snapshot")
async def snapshot(session: SessionDep, user: StaffUser) -> dict:
    row = await AnalyticsService(session).snapshot()
    return {"day": row.day.isoformat(), "messages": row.messages, "new_topics": row.new_topics}