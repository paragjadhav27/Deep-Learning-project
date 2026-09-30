"""Rate limiting: in-memory for single-process dev, Redis for multi-replica deployments."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int = 60) -> int | None:
        """Record a hit. Return None if allowed, else seconds until the window resets."""
        ...


class InMemoryRateLimiter:
    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> int | None:
        now = self._now()
        with self._lock:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            if count >= limit:
                return max(1, math.ceil(window_seconds - (now - start)))
            self._windows[key] = (start, count + 1)
            if len(self._windows) > 50_000:  # bound memory under key churn
                cutoff = now - window_seconds
                self._windows = {k: v for k, v in self._windows.items() if v[0] >= cutoff}
            return None


class RedisRateLimiter:
    """Fixed-window limiter shared by every API replica."""

    def __init__(self, client: Any, now: Callable[[], float] = time.time) -> None:
        self._r = client
        self._now = now

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> int | None:
        now = self._now()
        window = int(now // window_seconds)
        redis_key = f"facelens:rl:{key}:{window}"
        pipe = self._r.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds + 1)
        count, _ = pipe.execute()
        if int(count) > limit:
            return max(1, math.ceil((window + 1) * window_seconds - now))
        return None
