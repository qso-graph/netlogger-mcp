"""The MCP tools, in mock mode (bundled real responses, anonymized; no network)."""

from __future__ import annotations

import os

os.environ["NETLOGGER_MCP_MOCK"] = "1"
os.environ.pop("NETLOGGER_MCP_CALLSIGN", None)

import asyncio  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402
from fastmcp import Client  # noqa: E402

from netlogger_mcp import server  # noqa: E402

TOOLS = {
    "get_version_info", "netlogger_set_callsign", "netlogger_active_nets",
    "netlogger_checkins", "netlogger_past_nets", "netlogger_past_checkins",
}


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    """Each test starts with no saved callsign, in its own settings folder."""
    monkeypatch.setenv("NETLOGGER_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("NETLOGGER_MCP_CALLSIGN", raising=False)
    server._source = None
    server._limiter = None
    server._cache = None
    yield tmp_path
    server._source = None
    server._limiter = None


@pytest.fixture
def with_callsign(config):
    call("netlogger_set_callsign", {"callsign": "KI7MT"})


def call(name: str, args: dict | None = None) -> dict:
    async def go():
        async with Client(server.mcp) as c:
            return (await c.call_tool(name, args or {})).data
    return asyncio.run(go())


def test_tool_list():
    async def go():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}
    assert asyncio.run(go()) == TOOLS


def test_version_info():
    r = call("get_version_info")
    assert r["service_name"] == "netlogger-mcp"
    assert r["spec_version"] == "netlogger-xml-api-1.3"
    assert r["contract_version"] == "0.4"


# First use: ask once, remember


def test_first_use_asks_for_the_callsign():
    r = call("netlogger_active_nets")
    assert r["needs_callsign"] is True
    assert "netlogger_set_callsign" in r["next_step"]


def test_set_callsign_is_saved_and_used(config):
    assert call("netlogger_set_callsign", {"callsign": "ki7mt"}) == {"callsign": "KI7MT", "saved": True}
    assert json.loads((config / "settings.json").read_text()) == {"callsign": "KI7MT"}
    assert call("netlogger_active_nets")["total"] == 7
    assert server._source.callsign == "KI7MT"


def test_remembered_across_restarts(config):
    call("netlogger_set_callsign", {"callsign": "KI7MT"})
    server._source = None  # as if the server restarted
    assert call("netlogger_active_nets")["total"] == 7


def test_bad_callsign_refused_and_not_saved(config):
    r = call("netlogger_set_callsign", {"callsign": "not a call"})
    assert "error" in r
    assert not (config / "settings.json").exists()


def test_environment_overrides_the_file(monkeypatch):
    monkeypatch.setenv("NETLOGGER_MCP_CALLSIGN", "N0CALL")
    call("netlogger_active_nets")
    assert server._source.callsign == "N0CALL"


def test_changing_callsign_keeps_the_limits(with_callsign):
    """A new callsign must not buy a fresh set of calls."""
    call("netlogger_checkins", {"server_name": "NETLOGGER", "net_name": "A"})
    limiter = server._get_limiter()
    call("netlogger_set_callsign", {"callsign": "N0CALL"})
    call("netlogger_checkins", {"server_name": "NETLOGGER", "net_name": "B"})
    assert server._get_limiter() is limiter and server._source._limiter is limiter


def test_mock_mode_never_spends_the_shared_budget(with_callsign, config):
    call("netlogger_active_nets")
    assert type(server._get_limiter()).__name__ == "RateLimiter"
    assert not list(config.rglob("limits.json"))


def test_real_mode_shares_the_budget(with_callsign, monkeypatch):
    monkeypatch.setenv("NETLOGGER_MCP_MOCK", "0")
    server._source = server._limiter = None
    assert type(server._get_limiter()).__name__ == "SharedRateLimiter"


# The tools


def test_active_nets_null_filter(with_callsign):
    """mcpo / Open WebUI send null for optional parameters."""
    assert call("netlogger_active_nets", {"name_like": None})["total"] == 7


def test_checkins(with_callsign):
    r = call("netlogger_checkins", {"server_name": "NETLOGGER", "net_name": "Alaska morning net"})
    assert r["pointer"] == 5 and len(r["checkins"]) == 10


def test_past_nets_null_interval(with_callsign):
    r = call("netlogger_past_nets", {"interval_days": None, "name_like": None})
    assert r["interval_days"] == 7 and r["nets"][0]["net_id"] == 440529


def test_past_checkins(with_callsign):
    r = call("netlogger_past_checkins", {"server_name": "NETLOGGER", "net_name": "Pacific RV Service Net", "net_id": "440529"})
    assert r["checkins"][0]["callsign"] == "K8CALL"


def test_bad_input_is_an_error_result_not_a_crash(with_callsign):
    r = call("netlogger_checkins", {"server_name": "bad name!", "net_name": "x"})
    assert "error" in r and "server_name" in r["error"]


def test_help_and_version_exit_without_serving(capsys, monkeypatch):
    for arg, expect in (("--help", "usage: netlogger-mcp"), ("-h", "usage: netlogger-mcp"), ("--version", "netlogger-mcp ")):
        monkeypatch.setattr("sys.argv", ["netlogger-mcp", arg])
        server.main()  # returns instead of serving
        assert expect in capsys.readouterr().out
