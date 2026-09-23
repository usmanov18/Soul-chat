"""Per-IP sliding-window rate limit for the REST API (TZ 30).

The bot path already had ``rate_limit_per_minute`` (SecurityService); the API
did not — an operator's panel or a leaked key could hammer the backend freely.
This middleware reuses the same ``cache`` infrastructure (Redis in production,
memory fallback in tests) so limits are global across workers, not per-process.

``/health`` is exempt: uptime monitors poll it more often than any operator.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.cache import cache
from app.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, window: int = 60) -> None:
        super().__init__(app)
        self.window = window

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        prefix = settings.api_prefix
        if not request.url.path.startswith(prefix) or request.url.path.endswith("/health"):
            return await call_next(request)

        limit = settings.api_rate_limit_per_minute
        if limit <= 0:  # disabled explicitly
            return await call_next(request)

        forwarded = request.headers.get("x-forwarded-for")
        ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
        ok, count = await cache.hit_window(f"api_rl:{ip}", self.window, limit)
        if not ok:
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(self.window)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response
