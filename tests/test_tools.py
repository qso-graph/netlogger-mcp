"""The MCP tools, in mock mode (bundled synthetic samples, no network)."""

from __future__ import annotations

import os

os.environ["NETLOGGER_MCP_MOCK"] = "1"

import asyncio  # noqa: E402

from fastmcp import Client  # noqa: E402

from netlogger_mcp import server  # noqa: E402

TOOLS = {
    "get_version_info", "netlogger_active_nets", "netlogger_checkins",
    "netlogger_past_nets", "netlogger_past_checkins",
}


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
    assert r["contract_version"] == "0.1"


def test_active_nets_null_filter():
    """mcpo / Open WebUI send null for optional parameters."""
    r = call("netlogger_active_nets", {"name_like": None})
    assert r["total"] == 2


def test_checkins():
    r = call("netlogger_checkins", {"server_name": "NETLOGGER2", "net_name": "OMISS 80m SSB Net"})
    assert r["pointer"] == 2 and len(r["checkins"]) == 2


def test_past_nets_null_interval():
    r = call("netlogger_past_nets", {"interval_days": None, "name_like": None})
    assert r["interval_days"] == 7 and r["nets"][0]["net_id"] == 987654


def test_past_checkins():
    r = call("netlogger_past_checkins", {"server_name": "NETLOGGER2", "net_name": "OMISS 80m SSB Net", "net_id": "987654"})
    assert r["checkins"][0]["callsign"] == "KI7MT"


def test_bad_input_is_an_error_result_not_a_crash():
    r = call("netlogger_checkins", {"server_name": "bad name!", "net_name": "x"})
    assert "error" in r and "server_name" in r["error"]
