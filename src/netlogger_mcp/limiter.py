"""Call limits and caching, so the server never asks a source more than it allows."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl

log = logging.getLogger("netlogger_mcp")

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

    def snapshot(self) -> tuple[dict[str, list[float]], dict[str, float]]:
        """(calls per routine, blocked-until per routine), on this limiter's clock."""
        with self._lock:
            return {k: list(v) for k, v in self._calls.items() if v}, dict(self._blocked_until)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """An exclusive lock between processes, on the lock file at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # retries for about 10 s, then OSError
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


MAX_BLOCK = 3600.0 + WINDOW  # no back-off in the file is trusted beyond this


class SharedRateLimiter:
    """The same limits, shared by every process the user runs.

    Two AI apps each run their own copy of the server, and every request
    carries the same callsign, so to NetLogger they're one station. The budget
    lives in a state file in the user's config folder, read and updated under a
    lock the operating system enforces between processes. (Another account on
    the same computer has its own folder, and its own callsign.)

    Uses the wall clock, since processes share no other. A call stamped in the
    future (the clock went back) counts as now, which keeps it in the window
    longer, never shorter.

    Never fails open: if the file can't be used, this process keeps to the
    limits on its own, starting with a full window's back-off, and logs why.
    It tries the file again once a window has passed and, when that works,
    rejoins the shared budget, bringing the calls it made on its own. A
    long-running server isn't stranded on a private budget by one glitch.
    """

    def __init__(
        self,
        limits: dict[str, int],
        path: Path | str,
        window: float = WINDOW,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._limits = dict(limits)
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(".lock")
        self._window = window
        self._clock = clock
        self._thread_lock = threading.Lock()
        # Same clock as the file, so calls made on our own can be carried back in.
        self._fallback = RateLimiter(limits, window, clock)
        self._fell_back_at: float | None = None  # when the file last failed

    def _empty(self) -> dict[str, dict]:
        return {"calls": {}, "blocked_until": {}}

    def _read(self, now: float) -> dict[str, dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except ValueError:
            data = None
        ok = (
            isinstance(data, dict)
            and isinstance(data.get("calls"), dict)
            and isinstance(data.get("blocked_until"), dict)
            and all(isinstance(v, list) and all(isinstance(t, (int, float)) for t in v)
                    for v in data["calls"].values())
            and all(isinstance(v, (int, float)) for v in data["blocked_until"].values())
        )
        if not ok:
            # We can't tell what was spent, so assume everything was.
            log.warning("call-limit file %s was unreadable; waiting a full window", self._path)
            return {"calls": {}, "blocked_until": {r: now + self._window for r in self._limits}}
        return data

    def _write(self, data: dict[str, dict]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self._path)

    def _prune(self, data: dict[str, dict], now: float) -> None:
        for routine in list(data["calls"]):
            kept = [min(t, now) for t in data["calls"][routine] if now - min(t, now) < self._window]
            if kept:
                data["calls"][routine] = kept
            else:
                del data["calls"][routine]
        for routine in list(data["blocked_until"]):
            until = min(data["blocked_until"][routine], now + MAX_BLOCK)
            if until > now:
                data["blocked_until"][routine] = until
            else:
                del data["blocked_until"][routine]

    def _fall_back(self, error: OSError) -> None:
        if self._fell_back_at is None:
            log.warning(
                "can't share call limits through %s (%s); this process keeps to them on "
                "its own, starting with a full window's back-off, and will try again",
                self._path, error,
            )
            self._fallback.block_all(self._window)
        self._fell_back_at = self._clock()

    def _on_own(self) -> bool:
        """True while this process should stay on its own budget."""
        return self._fell_back_at is not None and self._clock() - self._fell_back_at < self._window

    def _carry_back(self, data: dict[str, dict]) -> None:
        """Rejoining: add the calls and back-offs this process made on its own."""
        calls, blocked = self._fallback.snapshot()
        for routine, stamps in calls.items():
            data["calls"][routine] = data["calls"].get(routine, []) + stamps
        for routine, until in blocked.items():
            data["blocked_until"][routine] = max(until, data["blocked_until"].get(routine, 0.0))

    def _rejoined(self) -> None:
        if self._fell_back_at is not None:
            log.warning("call limits are shared through %s again", self._path)
            self._fell_back_at = None
            self._fallback = RateLimiter(self._limits, self._window, self._clock)

    def try_acquire(self, routine: str) -> float:
        """Take a slot for ``routine`` and return 0, or return the seconds to wait."""
        limit = self._limits[routine]
        if self._on_own():
            return self._fallback.try_acquire(routine)
        try:
            with self._thread_lock, _file_lock(self._lock_path):
                now = self._clock()
                data = self._read(now)
                if self._fell_back_at is not None:
                    self._carry_back(data)
                self._prune(data, now)
                wait = 0.0
                blocked = data["blocked_until"].get(routine, 0.0)
                calls = data["calls"].get(routine, [])
                if now < blocked:
                    wait = blocked - now
                elif len(calls) >= limit:
                    wait = min(calls) + self._window - now
                else:
                    data["calls"][routine] = calls + [now]
                self._write(data)
            self._rejoined()
            return wait
        except OSError as e:
            self._fall_back(e)
            return self._fallback.try_acquire(routine)

    def block_all(self, seconds: float) -> None:
        """Stop every process sharing the budget calling any routine for ``seconds``."""
        self._fallback.block_all(seconds)
        if self._on_own():
            return
        try:
            with self._thread_lock, _file_lock(self._lock_path):
                now = self._clock()
                data = self._read(now)
                if self._fell_back_at is not None:
                    self._carry_back(data)
                self._prune(data, now)
                for routine in self._limits:
                    data["blocked_until"][routine] = max(now + seconds, data["blocked_until"].get(routine, 0.0))
                self._write(data)
            self._rejoined()
        except OSError as e:
            self._fall_back(e)


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
