"""One call budget for every copy on this computer (#8)."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from netlogger_mcp.limiter import MAX_BLOCK, SharedRateLimiter
from netlogger_mcp.netlogger import LIMITS


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def path(tmp_path) -> Path:
    return tmp_path / "limits.json"


def two(path: Path, clock: Clock) -> tuple[SharedRateLimiter, SharedRateLimiter]:
    """Two copies of the server, e.g. Claude Desktop and Claude Code."""
    return SharedRateLimiter(LIMITS, path, clock=clock), SharedRateLimiter(LIMITS, path, clock=clock)


class TestOneBudget:
    def test_two_copies_share_the_limit(self, path, clock):
        a, b = two(path, clock)
        assert a.try_acquire("GetCheckins") == 0
        assert b.try_acquire("GetCheckins") == 0
        assert a.try_acquire("GetCheckins") == 0
        assert b.try_acquire("GetCheckins") > 0  # the fourth call this minute, from either copy
        assert a.try_acquire("GetCheckins") > 0

    def test_window_rolls(self, path, clock):
        a, b = two(path, clock)
        assert a.try_acquire("GetActiveNets") == 0
        clock.now += 30
        assert b.try_acquire("GetActiveNets") == pytest.approx(30)
        clock.now += 30
        assert b.try_acquire("GetActiveNets") == 0

    def test_routines_are_separate(self, path, clock):
        a, b = two(path, clock)
        assert a.try_acquire("GetActiveNets") == 0
        assert b.try_acquire("GetPastNets") == 0

    def test_a_429_in_one_copy_stops_the_other(self, path, clock):
        a, b = two(path, clock)
        a.block_all(300)
        clock.now += 299
        for routine in LIMITS:
            assert b.try_acquire(routine) > 0
        clock.now += 1
        assert b.try_acquire("GetCheckins") == 0

    def test_budget_survives_a_restart(self, path, clock):
        a = SharedRateLimiter(LIMITS, path, clock=clock)
        assert a.try_acquire("GetActiveNets") == 0
        restarted = SharedRateLimiter(LIMITS, path, clock=clock)
        assert restarted.try_acquire("GetActiveNets") > 0

    def test_file_stays_small(self, path, clock):
        a = SharedRateLimiter(LIMITS, path, clock=clock)
        for _ in range(100):
            a.try_acquire("GetPastNetCheckins")
            clock.now += 7
        data = json.loads(path.read_text())
        assert len(data["calls"]["GetPastNetCheckins"]) <= 10


class TestNeverFailsOpen:
    @pytest.mark.parametrize("junk", ["", "not json", "[]", '{"calls": 5}', '{"calls": {"GetCheckins": ["x"]}, "blocked_until": {}}'])
    def test_unreadable_file_means_wait_a_window(self, path, clock, junk, caplog):
        path.write_text(junk)
        a = SharedRateLimiter(LIMITS, path, clock=clock)
        with caplog.at_level("WARNING", logger="netlogger_mcp"):
            assert a.try_acquire("GetCheckins") == pytest.approx(60)
        assert "unreadable" in caplog.text
        clock.now += 60
        assert a.try_acquire("GetCheckins") == 0

    def test_clock_going_back_counts_calls_as_now(self, path, clock):
        a = SharedRateLimiter(LIMITS, path, clock=clock)
        assert a.try_acquire("GetActiveNets") == 0
        clock.now -= 3600  # the clock jumped back an hour
        assert a.try_acquire("GetActiveNets") > 0
        clock.now += 60
        assert a.try_acquire("GetActiveNets") == 0

    def test_absurd_back_off_is_capped(self, path, clock):
        path.write_text(json.dumps({"calls": {}, "blocked_until": {"GetCheckins": clock.now + 10**9}}))
        a = SharedRateLimiter(LIMITS, path, clock=clock)
        assert a.try_acquire("GetCheckins") == pytest.approx(MAX_BLOCK)

    def test_unusable_file_falls_back_to_own_limits_after_a_window(self, tmp_path, caplog):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        a = SharedRateLimiter(LIMITS, blocker / "limits.json")  # its folder can't be created
        with caplog.at_level("WARNING", logger="netlogger_mcp"):
            assert a.try_acquire("GetCheckins") > 0  # a full window first: we can't see what was spent
        assert "can't share call limits" in caplog.text
        assert a.try_acquire("GetActiveNets") > 0


def _grab(path: str, start, out) -> None:
    limiter = SharedRateLimiter(LIMITS, path)
    start.wait()
    out.put(sum(1 for _ in range(5) if limiter.try_acquire("GetCheckins") == 0))


def test_real_processes_racing(tmp_path):
    """Six real processes grab GetCheckins slots at the same moment: exactly three get one."""
    ctx = multiprocessing.get_context("spawn")
    start, out = ctx.Event(), ctx.Queue()
    procs = [ctx.Process(target=_grab, args=(str(tmp_path / "limits.json"), start, out)) for _ in range(6)]
    for p in procs:
        p.start()
    start.set()
    granted = sum(out.get(timeout=60) for _ in procs)
    for p in procs:
        p.join(timeout=60)
    assert granted == LIMITS["GetCheckins"]


def _acquire_once(path: str, out) -> None:
    out.put(SharedRateLimiter(LIMITS, path).try_acquire("GetCheckins"))


def test_another_process_waits_for_the_lock(tmp_path):
    """Deterministic: while one process holds the lock, another can't read or spend the budget."""
    import queue

    from netlogger_mcp.limiter import _file_lock

    path = tmp_path / "limits.json"
    ctx = multiprocessing.get_context("spawn")
    out = ctx.Queue()
    with _file_lock(path.with_suffix(".lock")):
        p = ctx.Process(target=_acquire_once, args=(str(path), out))
        p.start()
        with pytest.raises(queue.Empty):
            out.get(timeout=3)  # blocked on our lock
    assert out.get(timeout=60) == 0  # released: it goes ahead
    p.join(timeout=60)
