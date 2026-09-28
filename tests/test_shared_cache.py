"""Answers shared by every copy on this computer, beside the shared budget (#17)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netlogger_mcp.limiter import SharedCache, SharedRateLimiter
from netlogger_mcp.netlogger import LIMITS, NetLoggerSource

from test_netlogger import FakeNetLogger


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def copy(tmp_path: Path, clock: Clock, fake: FakeNetLogger) -> NetLoggerSource:
    """One server process: its own source, the shared limits and answers."""
    return NetLoggerSource(
        "N0CALL", fetch=fake,
        limiter=SharedRateLimiter(LIMITS, tmp_path / "limits.json", clock=clock),
        cache=SharedCache(tmp_path / "cache.json", clock=clock),
    )


def test_a_copy_out_of_budget_gets_the_other_copys_answer(tmp_path, clock):
    """Watson's case: netlogger-mcp fetched active nets; omiss-mcp, a moment later,
    is out of budget. It gets that answer, with its real age, and no request."""
    fake_a, fake_b = FakeNetLogger(), FakeNetLogger()
    a, b = copy(tmp_path, clock, fake_a), copy(tmp_path, clock, fake_b)
    first = a.active_nets()
    clock.now += 49
    second = b.active_nets(name_like="OMISS")
    assert "error" not in second
    assert second["cached"] is True and second["age_seconds"] == 49
    assert second["stale"] is False  # active nets are fresh for 60 s
    assert fake_b.urls == []
    assert first["total"] >= second["total"]


def test_after_the_ttl_the_shared_answer_is_marked_stale(tmp_path, clock):
    a, b = copy(tmp_path, clock, FakeNetLogger()), copy(tmp_path, clock, FakeNetLogger())
    a.active_nets()
    clock.now += 61  # a fresh fetch is allowed again; b makes one
    fake_b = b._fetch
    r = b.active_nets()
    assert r["cached"] is False and len(fake_b.urls) == 1


def test_newest_answer_wins(tmp_path, clock):
    c1, c2 = SharedCache(tmp_path / "cache.json", clock=clock), SharedCache(tmp_path / "cache.json", clock=clock)
    c1.set("k", "old", 60)
    clock.now += 10
    c2.set("k", "new", 60)
    value, age, fresh = c1.get("k")
    assert value == "new" and age == 0 and fresh


def test_a_corrupt_file_is_ignored(tmp_path, clock):
    path = tmp_path / "cache.json"
    path.write_text("{not json")
    c = SharedCache(path, clock=clock)
    assert c.get("k") is None
    c.set("k", [1, 2], 60)
    assert c.get("k")[0] == [1, 2]


def test_an_unusable_file_falls_back_to_this_process(tmp_path, clock):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    c = SharedCache(blocker / "cache.json", clock=clock)  # its folder can't exist
    c.set("k", "mine", 60)
    assert c.get("k")[0] == "mine"


def test_the_file_stays_bounded(tmp_path, clock):
    c = SharedCache(tmp_path / "cache.json", max_entries=3, clock=clock)
    for i in range(10):
        c.set(f"k{i}", i, 60)
    assert list(json.loads((tmp_path / "cache.json").read_text())) == ["k7", "k8", "k9"]


def test_every_answer_has_as_of_and_active_nets_lists_servers(tmp_path, clock):
    r = copy(tmp_path, clock, FakeNetLogger()).active_nets(name_like="no such net")
    assert r["total"] == 0 and r["as_of_utc"].endswith("Z")
    assert r["servers"] and all(s["nets"] > 0 for s in r["servers"])  # what NetLogger listed, before the filter
