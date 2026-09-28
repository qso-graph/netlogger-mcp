"""Call limits and caching, so the server never asks a source more than it allows."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

WINDOW = 60.0  # the limits are per minute


class RateLimiter:
    """A per-routine limit over a rolling window, plus back-off when the source says stop.

    ``try_acquire`` never sleeps: it takes a slot and returns 0, or returns the
    seconds until one frees. Callers answer from cache or report when to retry,
    rather than queueing calls up.
    """

    def __init__(
        self,
        limits: dict[str, int],
        window: float = WINDOW,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = dict(limits)
        self._window = window
        self._clock = clock
        self._calls: dict[str, deque[float]] = {k: deque() for k in limits}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def try_acquire(self, routine: str) -> float:
        """Take a slot for ``routine`` and return 0, or return the seconds to wait."""
        limit = self._limits[routine]  # an unknown routine is a bug, not a free pass
        with self._lock:
            now = self._clock()
            blocked = self._blocked_until.get(routine, 0.0)
            if now < blocked:
                return blocked - now
            calls = self._calls[routine]
            while calls and now - calls[0] >= self._window:
                calls.popleft()
            if len(calls) >= limit:
                return calls[0] + self._window - now
            calls.append(now)
            return 0.0

    def block_all(self, seconds: float) -> None:
        """Stop calling every routine for ``seconds`` (after a 429 on any of them)."""
        with self._lock:
            until = self._clock() + seconds
            for routine in self._limits:
                self._blocked_until[routine] = max(until, self._blocked_until.get(routine, 0.0))


class Cache:
    """Answers with their age. Entries outlive their TTL so a stale answer can
    stand in when the limit is reached or the source is down."""

    def __init__(self, max_entries: int = 256, clock: Callable[[], float] = time.monotonic) -> None:
        self._max = max_entries
        self._clock = clock
        self._data: dict[str, tuple[float, float, Any]] = {}  # key -> (stored, ttl, value)
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[Any, float, bool] | None:
        """Return (value, age in seconds, fresh), or None."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            stored, ttl, value = entry
            age = self._clock() - stored
            return value, age, age < ttl

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._data[key] = (self._clock(), ttl, value)
            while len(self._data) > self._max:
                del self._data[next(iter(self._data))]  # oldest first
