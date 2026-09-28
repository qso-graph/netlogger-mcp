"""netlogger-mcp: nets on the air, check-ins, and past nets. Read-only."""

from __future__ import annotations

import os
import sys
import urllib.parse
from importlib.resources import files
from typing import Any

from fastmcp import FastMCP

from . import __contract_version__, __spec_version__, __version__
from . import settings
from .limiter import Cache, RateLimiter
from .netlogger import LIMITS, NetLoggerError, NetLoggerSource

mcp = FastMCP(
    "netlogger-mcp",
    version=__version__,
    instructions=(
        "Amateur-radio nets: which nets are on the air, who has checked in and who is up "
        "now (the pointer), and past nets and their check-ins. Read-only. Data comes from "
        "NetLogger, which limits how often it may be asked, so answers may come from a "
        "short cache (see age_seconds). Start with netlogger_active_nets or "
        "netlogger_past_nets to get the server and net names the other tools need. "
        "Every request tells NetLogger which station is asking, so the user's callsign "
        "is needed once: if a tool says so, ask the user for their callsign and call "
        "netlogger_set_callsign."
    ),
)


def _mock_fetch(url: str) -> tuple[int, bytes, str | None]:
    """NETLOGGER_MCP_MOCK=1: answer from the bundled synthetic samples, never the network."""
    routine = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1].removesuffix(".php")
    return 200, files("netlogger_mcp.samples").joinpath(f"{routine}.xml").read_bytes(), None


_source: NetLoggerSource | None = None
# Owned by the process, not the source: changing the callsign rebuilds the
# source but must never reset the call limits.
_limiter = RateLimiter(LIMITS)
_cache = Cache()


class NeedsCallsign(Exception):
    pass


NEEDS_CALLSIGN = {
    "error": "netlogger-mcp needs the user's callsign before it can ask NetLogger. "
             "Every request tells NetLogger which station is asking.",
    "needs_callsign": True,
    "next_step": "Ask the user for their amateur radio callsign, then call "
                 "netlogger_set_callsign with it. It is asked only once.",
}


def _get_source() -> NetLoggerSource:
    """One source per process, so the call limits cover every tool call."""
    global _source
    if _source is None:
        callsign = settings.load_callsign()
        if callsign is None:
            raise NeedsCallsign
        _source = NetLoggerSource(
            callsign, fetch=_mock_fetch if os.getenv("NETLOGGER_MCP_MOCK") == "1" else None,
            limiter=_limiter, cache=_cache,
        )
    return _source


def _run(method: str, *args) -> dict[str, Any]:
    try:
        return getattr(_get_source(), method)(*args)
    except NeedsCallsign:
        return dict(NEEDS_CALLSIGN)
    except NetLoggerError as e:
        return {"error": str(e)}
    except Exception:
        return {"error": "netlogger-mcp hit an unexpected problem"}


def _version_info_payload() -> dict[str, Any]:
    return {
        "service_name": "netlogger-mcp",
        "service_version": __version__,
        "spec_version": __spec_version__,
        "contract_version": __contract_version__,
    }


@mcp.tool()
def get_version_info() -> dict[str, Any]:
    """Get netlogger-mcp's version, the NetLogger API version it is built for, and
    the version of the records it returns.

    Returns:
        service_name, service_version (PyPI), spec_version (NetLogger API), contract_version.
    """
    return _version_info_payload()


@mcp.tool()
def netlogger_set_callsign(callsign: str) -> dict[str, Any]:
    """Save the user's amateur radio callsign. Needed once, before the first lookup.

    NetLogger is told which station is asking, in every request, so it can tell
    one user from another. Ask the user for their own callsign; don't guess it.

    Args:
        callsign: The user's callsign (e.g. KI7MT).

    Returns:
        The saved callsign.
    """
    global _source
    try:
        saved = settings.save_callsign(callsign)
    except NetLoggerError as e:
        return {"error": str(e)}
    except OSError:
        return {"error": "the callsign couldn't be saved to the settings file"}
    _source = None  # the next call identifies as the new callsign
    return {"callsign": saved, "saved": True}


@mcp.tool()
def netlogger_active_nets(name_like: str | None = "") -> dict[str, Any]:
    """List nets on the air now.

    Args:
        name_like: Only nets whose name contains this text, ignoring case (e.g. OMISS). Empty for all.

    Returns:
        Nets with server, name, frequency, band, mode, net control, logger, when
        opened, and how many are monitoring. Use server and name with netlogger_checkins.
    """
    return _run("active_nets", name_like or "")


@mcp.tool()
def netlogger_checkins(server_name: str, net_name: str) -> dict[str, Any]:
    """Get a live net's check-in list, and the pointer: the serial number of the
    station net control is working now.

    Args:
        server_name: The net's server, from netlogger_active_nets (e.g. NETLOGGER2).
        net_name: The net's name, from netlogger_active_nets.

    Returns:
        Check-ins in list order with callsign, name, location, grid, status and
        remarks; the check-in count; and the pointer.
    """
    return _run("checkins", server_name, net_name)


@mcp.tool()
def netlogger_past_nets(interval_days: int | None = 7, name_like: str | None = "") -> dict[str, Any]:
    """List closed nets over the last few days, with the net IDs netlogger_past_checkins needs.

    Args:
        interval_days: How many days back (default 7). Over 7 needs name_like (NetLogger's rule).
        name_like: Only nets whose name contains this text (e.g. OMISS).

    Returns:
        Past nets with server, name, net ID, frequency, band, mode, net control,
        opened and closed times.
    """
    return _run("past_nets", interval_days if interval_days is not None else 7, name_like or "")


@mcp.tool()
def netlogger_past_checkins(server_name: str, net_name: str, net_id: str) -> dict[str, Any]:
    """Get a closed net's check-in list.

    Args:
        server_name: The net's server, from netlogger_past_nets.
        net_name: The net's name, from netlogger_past_nets.
        net_id: The net ID, from netlogger_past_nets.

    Returns:
        The net's check-ins with callsign, name, location, grid, status and remarks.
    """
    return _run("past_checkins", server_name, net_name, net_id)


def main() -> None:
    """Run the netlogger-mcp server."""
    transport = "stdio"
    port = 8014
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--transport" and i < len(sys.argv) - 1:
            transport = sys.argv[i + 1]
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    if transport == "streamable-http":
        mcp.run(transport=transport, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
