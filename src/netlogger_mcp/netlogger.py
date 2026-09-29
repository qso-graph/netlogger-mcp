"""NetLogger source: the NetLogger XML Data Service, API 1.3.

A plain library. Programs can use it directly; the MCP server is a thin layer
over it. Everything it returns is a contract record (contract.py).

    from netlogger_mcp.netlogger import NetLoggerSource
    nl = NetLoggerSource(callsign="KI7MT", program_id="MyLogger", program_version="1.0")
    nl.active_nets(name_like="ARES")

Every request names the station using it (its callsign) and, if given, the
program (ADIF's PROGRAMID and PROGRAMVERSION), in the User-Agent, so NetLogger
can tell users and programs apart. There is no anonymous mode.
"""

from __future__ import annotations

import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring

from . import __version__
from .contract import BOOL_FIELDS, CHECKIN_FIELDS, INT_FIELDS, NET_FIELDS, TIME_FIELDS
from .limiter import Cache, RateLimiter, SharedCache, SharedRateLimiter
from .paths import cache_file, limits_file
from .radio import read_band_and_frequency

log = logging.getLogger("netlogger_mcp")

BASE = "https://www.netlogger.org/api/"
SOURCE = "netlogger"
REPO = "https://github.com/qso-graph/netlogger-mcp"

# NetLogger's published guidance, calls per minute (spec v1.2+). Never exceeded.
LIMITS = {
    "GetActiveNets": 1,
    "GetCheckins": 3,
    "GetPastNets": 1,
    "GetPastNetCheckins": 10,
}

# How long an answer is reused before asking again, in seconds.
TTL = {
    "GetActiveNets": 60.0,
    "GetCheckins": 20.0,
    "GetPastNets": 60.0,
    "GetPastNetCheckins": 3600.0,  # a closed net's list doesn't change
}

MIN_BACKOFF = 60.0  # after a 429
MAX_BACKOFF = 3600.0
PAST_DAYS_WITHOUT_FILTER = 7  # beyond this the spec requires a name filter
MAX_PAST_DAYS = 365
MAX_BODY = 5 * 1024 * 1024

_SERVER_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
_NET_ID_RE = re.compile(r"[0-9]{1,12}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# A sanity check, not ADIF validation: letters, digits and "/" (portable
# suffixes), with at least one letter and one digit.
_CALLSIGN_RE = re.compile(r"(?=.*[A-Z])(?=.*[0-9])[A-Z0-9/]{3,20}")

# fetch(url) -> (HTTP status, body, Retry-After header or None)
Fetch = Callable[[str], "tuple[int, bytes, str | None]"]


class NetLoggerError(Exception):
    """The request couldn't be answered. The message is safe to show a user."""


class RateLimited(NetLoggerError):
    def __init__(self, routine: str, retry_after: float) -> None:
        self.retry_after = max(1, round(retry_after))
        super().__init__(
            f"NetLogger allows {LIMITS[routine]} {routine} call(s) a minute; "
            f"try again in {self.retry_after} s"
        )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def normalize_callsign(value: str | None) -> str:
    """The station's callsign, upper-cased, or NetLoggerError."""
    value = (value or "").strip().upper()
    if not _CALLSIGN_RE.fullmatch(value):
        raise NetLoggerError(
            "a valid amateur radio callsign is required (e.g. KI7MT): NetLogger is told "
            "which station is asking"
        )
    return value


# An HTTP token (RFC 9110 tchar), so the program's name can lead the User-Agent.
_TOKEN_RE = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}")


def _program_token(program_id: str | None, program_version: str | None) -> str:
    """ADIF's PROGRAMID and PROGRAMVERSION as a User-Agent product, or ""."""
    if not program_id:
        if program_version:
            raise NetLoggerError("program_version needs program_id")
        return ""
    for what, value in (("program_id", program_id), ("program_version", program_version)):
        if value is not None and not _TOKEN_RE.fullmatch(value):
            raise NetLoggerError(
                f"{what} must be 1-64 characters without spaces or '/' "
                "(it leads the HTTP User-Agent)"
            )
    return f"{program_id}/{program_version} " if program_version else f"{program_id} "


def user_agent(callsign: str, program_id: str | None = None, program_version: str | None = None) -> str:
    """Program (ADIF PROGRAMID/PROGRAMVERSION), then this library, then the station."""
    return f"{_program_token(program_id, program_version)}netlogger-mcp/{__version__} ({callsign}; +{REPO})"


def _server_name(value: str) -> str:
    value = (value or "").strip()
    if not _SERVER_RE.fullmatch(value):
        raise NetLoggerError("server_name must be 1-32 letters, digits, '-' or '_' (e.g. NETLOGGER)")
    return value


def _text(value: str | None, what: str, max_len: int, required: bool) -> str:
    value = (value or "").strip()
    if required and not value:
        raise NetLoggerError(f"{what} is required")
    if len(value) > max_len or _CONTROL_RE.search(value):
        raise NetLoggerError(f"{what} must be at most {max_len} printable characters")
    return value


def _net_id(value: str | int) -> str:
    value = str(value).strip()
    if not _NET_ID_RE.fullmatch(value):
        raise NetLoggerError("net_id must be a number (from netlogger_past_nets)")
    return value


# ---------------------------------------------------------------------------
# Parsing: no assumptions about node order or count; unknown nodes ignored
# ---------------------------------------------------------------------------


def _child_text(el: Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is None:
        return None
    return (child.text or "").strip()


def _response_code(el: Element | None) -> int | None:
    if el is None:
        return None
    text = _child_text(el, "ResponseCode")
    if not text:
        return None
    m = re.match(r"\s*(\d{3})", text)
    return int(m.group(1)) if m else None


def _time(value: str, utc: bool) -> str:
    # NetLogger sends "2016-01-06 01:51:22" in the header's TimeZone.
    if utc and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        return value.replace(" ", "T") + "Z"
    return value


def _record(el: Element, fields: dict[str, tuple[str, ...]], utc: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, tags in fields.items():
        value = None
        for tag in tags:
            value = _child_text(el, tag)
            if value is not None:
                break
        if value is None or value == "":
            continue
        if name in INT_FIELDS:
            try:
                out[name] = int(value)
            except ValueError:
                continue
        elif name in BOOL_FIELDS:
            if value.upper() in ("Y", "N"):
                out[name] = value.upper() == "Y"
        elif name in TIME_FIELDS:
            out[name] = _time(value, utc)
        else:
            out[name] = value
    return out


class Parsed:
    def __init__(self, root: Element) -> None:
        header = root.find("Header")
        self.time_zone = (_child_text(header, "TimeZone") if header is not None else None) or "UTC"
        self.utc = self.time_zone.upper() == "UTC"
        self.api_version = _child_text(header, "APIVersion") if header is not None else None
        self.warnings = [
            (w.text or "").strip() for w in (header.iter("Warning") if header is not None else [])
        ]
        self.error = _child_text(root, "Error")
        self.code = _response_code(root)
        self.server_list = root.find("ServerList")
        self.checkin_list = root.find("CheckinList")

    def status(self) -> int | None:
        for el in (self.server_list, self.checkin_list):
            code = _response_code(el)
            if code is not None:
                return code
        return self.code

    def nets(self) -> list[dict[str, Any]]:
        nets = []
        if self.server_list is None:
            return nets
        for server in self.server_list.iter("Server"):
            server_name = _child_text(server, "ServerName") or ""
            for net in server.iter("Net"):
                rec = {"source": SOURCE, "server": server_name}
                rec.update(_record(net, NET_FIELDS, self.utc))
                rec.update(read_band_and_frequency(rec.get("band"), rec.get("frequency")))
                nets.append(rec)
        return nets

    def checkins(self) -> dict[str, Any]:
        cl = self.checkin_list
        checkins, pending = [], []
        pointer = count = None
        if cl is not None:
            for c in cl.iter("Checkin"):
                rec = {"source": SOURCE}
                rec.update(_record(c, CHECKIN_FIELDS, self.utc))
                if rec.get("callsign"):
                    checkins.append(rec)
                elif "serial" in rec:
                    # A row net control has opened but not filled in yet (the
                    # callsign is typed after): a station being entered, not yet
                    # a check-in.
                    pending.append(rec["serial"])
            for tag in ("Pointer", "CheckinCount"):
                text = _child_text(cl, tag)
                try:
                    value = int(text) if text else None
                except ValueError:
                    value = None
                if tag == "Pointer":
                    pointer = value
                else:
                    count = value
        checkins.sort(key=lambda r: r.get("serial", 0))
        # Serials are renumbered as the logger edits the list, so the station at
        # the pointer is named here, from the same answer.
        at_pointer = next((c for c in checkins if pointer is not None and c.get("serial") == pointer), None)
        result = {
            "checkin_count": len(checkins),
            "pointer": pointer,
            "pointer_callsign": at_pointer["callsign"] if at_pointer else None,
            "pending_serials": sorted(pending),
            "checkins": checkins,
        }
        if count is not None and count != len(checkins):
            result["source_checkin_count"] = count  # NetLogger's own figure, pending rows included
        if not checkins and self.error:
            result["message"] = self.error  # e.g. no such net, or the net has closed
        return result


def parse(body: bytes) -> Parsed:
    try:
        root = fromstring(body)
    except Exception as e:  # malformed, or refused by defusedxml
        raise NetLoggerError("NetLogger returned a response that couldn't be read") from e
    if root.tag != "NetLoggerXML":
        raise NetLoggerError("NetLogger returned an unexpected response")
    parsed = Parsed(root)
    for w in parsed.warnings:
        if w:
            log.warning("NetLogger API warning: %s", w)  # for the developer, per the spec
    return parsed


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _urllib_fetch(agent: str) -> Fetch:
    def fetch(url: str) -> tuple[int, bytes, str | None]:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": agent})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read(MAX_BODY + 1), resp.headers.get("Retry-After")
        except urllib.error.HTTPError as e:
            return e.code, e.read(MAX_BODY + 1) if e.fp else b"", e.headers.get("Retry-After")
    return fetch


def as_of_utc() -> str:
    """The time of an answer (or an error), ISO 8601 UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _retry_after(header: str | None) -> float:
    try:
        seconds = float(header) if header else 0.0
    except ValueError:
        seconds = 0.0
    return min(max(seconds, MIN_BACKOFF), MAX_BACKOFF)


class NetLoggerSource:
    """Every documented NetLogger API 1.3 call, within NetLogger's limits.

    GetPointer is deprecated; the pointer comes back with GetCheckins, so it
    isn't called. One instance per process: the limits are shared by all its
    callers.
    """

    def __init__(
        self,
        callsign: str,
        program_id: str | None = None,
        program_version: str | None = None,
        fetch: Fetch | None = None,
        limiter: RateLimiter | SharedRateLimiter | None = None,
        cache: Cache | SharedCache | None = None,
    ) -> None:
        """``callsign``: the station using it (required). ``program_id`` and
        ``program_version``: the app built on this library, as in ADIF's
        PROGRAMID and PROGRAMVERSION (e.g. "MyLogger", "1.0"); optional."""
        self.callsign = normalize_callsign(callsign)
        self.user_agent = user_agent(self.callsign, program_id, program_version)
        self._fetch = fetch or _urllib_fetch(self.user_agent)
        # By default every copy on this computer shares one budget (one station).
        self._limiter = limiter or SharedRateLimiter(LIMITS, limits_file())
        # ... and their answers, so a copy that's out of budget can use another's.
        self._cache = cache or SharedCache(cache_file())
        self._inflight = threading.Lock()  # one request at a time

    def _call(self, routine: str, params: dict[str, str], cache_key: str) -> tuple[Parsed | Any, dict[str, Any]]:
        """Return (parsed or cached value, freshness info)."""
        hit = self._cache.get(cache_key)
        if hit is not None and hit[2]:
            return hit[0], {"cached": True, "age_seconds": round(hit[1]), "stale": False}

        with self._inflight:
            hit = self._cache.get(cache_key)  # another caller may have just fetched it
            if hit is not None and hit[2]:
                return hit[0], {"cached": True, "age_seconds": round(hit[1]), "stale": False}

            wait = self._limiter.try_acquire(routine)
            if wait > 0:
                return self._stale_or_raise(hit, RateLimited(routine, wait))

            url = BASE + routine + ".php" + ("?" + urllib.parse.urlencode(params) if params else "")
            try:
                status, body, retry_after = self._fetch(url)
            except (OSError, ValueError) as e:
                log.warning("NetLogger %s failed: %s", routine, e)
                return self._stale_or_raise(hit, NetLoggerError("NetLogger couldn't be reached"))

            # NetLogger's 429 is anti-flooding aimed at the client, and every routine
            # hits the same server, so a 429 on one stops them all.
            if status == 429:
                self._limiter.block_all(_retry_after(retry_after))
                return self._stale_or_raise(hit, RateLimited(routine, _retry_after(retry_after)))
            if len(body) > MAX_BODY:
                return self._stale_or_raise(hit, NetLoggerError("NetLogger's response was too large"))
            if status != 200 and not body:
                return self._stale_or_raise(hit, NetLoggerError(f"NetLogger answered HTTP {status}"))

            try:
                parsed = parse(body)
            except NetLoggerError as e:
                return self._stale_or_raise(hit, e)
            code = parsed.status()
            if code == 429:
                self._limiter.block_all(MIN_BACKOFF)
                return self._stale_or_raise(hit, RateLimited(routine, MIN_BACKOFF))
            if code is not None and code >= 500:
                return self._stale_or_raise(hit, NetLoggerError(f"NetLogger reported an error ({code})"))
            if code in (400, 401, 403):
                raise NetLoggerError(f"NetLogger refused the request ({code})")
            return parsed, {"cached": False, "age_seconds": 0, "stale": False}

    @staticmethod
    def _stale_or_raise(hit: tuple[Any, float, bool] | None, error: NetLoggerError) -> tuple[Any, dict[str, Any]]:
        if hit is None:
            raise error
        return hit[0], {"cached": True, "age_seconds": round(hit[1]), "stale": True, "note": str(error)}

    def _fetch_cached(self, routine: str, params: dict[str, str], key: str, build: Callable[[Parsed], Any]) -> tuple[Any, dict[str, Any]]:
        value, info = self._call(routine, params, key)
        if isinstance(value, Parsed):
            value = build(value)
            self._cache.set(key, value, TTL[routine])
        return value, {"as_of_utc": as_of_utc(), **info}

    # ------------------------------------------------------------------
    # The four documented calls
    # ------------------------------------------------------------------

    def active_nets(self, name_like: str | None = None) -> dict[str, Any]:
        """Nets on the air now. The filter is applied here, not by NetLogger, so
        any number of filters cost one GetActiveNets call a minute."""
        name_like = _text(name_like, "name_like", 64, required=False)
        nets, info = self._fetch_cached("GetActiveNets", {}, "active", lambda p: p.nets())
        # Every server NetLogger listed, before the filter, so an empty answer explains itself.
        counts: dict[str, int] = {}
        for n in nets:
            counts[n.get("server", "")] = counts.get(n.get("server", ""), 0) + 1
        servers = [{"server": s, "nets": c} for s, c in sorted(counts.items())]
        if name_like:
            needle = name_like.casefold()
            nets = [
                n for n in nets
                if needle in n.get("name", "").casefold() or needle in n.get("current_name", "").casefold()
            ]
        return {"source": SOURCE, "total": len(nets), "nets": nets, "servers": servers, **info}

    def checkins(self, server_name: str, net_name: str) -> dict[str, Any]:
        """A live net's check-in list, with the pointer (the station up now)."""
        server = _server_name(server_name)
        net = _text(net_name, "net_name", 128, required=True)
        result, info = self._fetch_cached(
            "GetCheckins", {"ServerName": server, "NetName": net},
            f"checkins:{server}:{net}", lambda p: p.checkins(),
        )
        return {"source": SOURCE, "server": server, "net": net, **result, **info}

    def past_nets(self, interval_days: int = PAST_DAYS_WITHOUT_FILTER, name_like: str | None = None) -> dict[str, Any]:
        """Closed nets over the last ``interval_days``, with the net IDs past check-ins need."""
        try:
            days = int(interval_days)
        except (TypeError, ValueError):
            raise NetLoggerError("interval_days must be a whole number of days") from None
        if not 1 <= days <= MAX_PAST_DAYS:
            raise NetLoggerError(f"interval_days must be 1-{MAX_PAST_DAYS}")
        name_like = _text(name_like, "name_like", 64, required=False)
        if days > PAST_DAYS_WITHOUT_FILTER and not name_like:
            raise NetLoggerError(
                f"more than {PAST_DAYS_WITHOUT_FILTER} days needs name_like "
                "(NetLogger's rule, to protect its server)"
            )
        params = {"Interval": str(days)}
        if name_like:
            params["NetNameLike"] = name_like
        nets, info = self._fetch_cached(
            "GetPastNets", params, f"past:{days}:{name_like.casefold()}", lambda p: p.nets(),
        )
        return {"source": SOURCE, "interval_days": days, "total": len(nets), "nets": nets, **info}

    def past_checkins(self, server_name: str, net_name: str, net_id: str | int) -> dict[str, Any]:
        """A closed net's check-in list."""
        server = _server_name(server_name)
        net = _text(net_name, "net_name", 128, required=True)
        nid = _net_id(net_id)
        result, info = self._fetch_cached(
            "GetPastNetCheckins", {"ServerName": server, "NetName": net, "NetID": nid},
            f"pastcheckins:{server}:{net}:{nid}", lambda p: p.checkins(),
        )
        return {"source": SOURCE, "server": server, "net": net, "net_id": int(nid), **result, **info}
