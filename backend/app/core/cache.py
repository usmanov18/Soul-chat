"""Cache + rate-limit primitives.

Redis is used in production.  When Redis is unavailable (local development,
unit tests, CI) everything transparently falls back to an in-process store with
the same semantics, so the bot keeps working instead of crashing.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from app.core.config import settings

try:  # pragma: no cover - optional dependency wiring
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]


class MemoryStore:
    """Tiny TTL aware dict used as the Redis fallback."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._counters: dict[str, deque[float]] = defaultdict(deque)

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._data[key] = (value, time.time() + ttl if ttl else None)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        current = await self.get(key)
        current = int(current or 0) + 1
        await self.set(key, current, ttl)
        return current

    async def hit_window(self, key: str, window: int, limit: int) -> tuple[bool, int]:
        """Sliding window counter. Returns ``(allowed, hits_in_window)``."""
        now = time.time()
        bucket = self._counters[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        bucket.append(now)
        return len(bucket) <= limit, len(bucket)


class RedisStore:
    def __init__(self, client: Any) -> None:
        self._r = client

    async def get(self, key: str) -> Any | None:
        value = await self._r.get(key)
        if isinstance(value, bytes):
            return value.decode()
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if ttl:
            await self._r.set(key, value, ex=ttl)
        else:
            await self._r.set(key, value)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        value = await self._r.incr(key)
        if ttl and value == 1:
            await self._r.expire(key, ttl)
        return int(value)

    async def hit_window(self, key: str, window: int, limit: int) -> tuple[bool, int]:
        now = time.time()
        pipe = self._r.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {f"{now}:{id(pipe)}": now})
        pipe.zcard(key)
        pipe.expire(key, window + 1)
        _, _, count, _ = await pipe.execute()
        return int(count) <= limit, int(count)


class Cache:
    """Facade that hides whether we are talking to Redis or memory."""

    def __init__(self) -> None:
        self._memory = MemoryStore()
        self._redis: RedisStore | None = None
        self._client: Any = None

    async def connect(self) -> bool:
        if not settings.redis_enabled or aioredis is None:
            return False
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
        except Exception:
            self._redis = None
            return False
        self._client = client
        self._redis = RedisStore(client)
        return True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._redis = None

    @property
    def backend(self) -> str:
        return "redis" if self._redis else "memory"

    def _store(self) -> Any:
        return self._redis or self._memory

    async def get(self, key: str) -> Any | None:
        return await self._store().get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._store().set(key, value, ttl)

    async def delete(self, key: str) -> None:
        await self._store().delete(key)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        return await self._store().incr(key, ttl)

    async def hit_window(self, key: str, window: int, limit: int) -> tuple[bool, int]:
        return await self._store().hit_window(key, window, limit)

    async def reset(self) -> None:
        """Drop every key (used by the test suite)."""
        if self._redis is not None:  # pragma: no cover - requires a live redis
            await self._client.flushdb()
        self._memory._data.clear()
        self._memory._counters.clear()


cache = Cache()
