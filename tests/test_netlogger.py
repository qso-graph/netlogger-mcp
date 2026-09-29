"""NetLogger source: parsing, privacy, validation, and the call limits.

No network: every test injects a fake fetch and a fake clock.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from netlogger_mcp.limiter import Cache, RateLimiter
from netlogger_mcp.netlogger import (
    LIMITS,
    NetLoggerError,
    NetLoggerSource,
    RateLimited,
    parse,
)

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "src/netlogger_mcp/schema/contract.schema.json").read_text()
)


def sample(routine: str) -> bytes:
    return files("netlogger_mcp.samples").joinpath(f"{routine}.xml").read_bytes()


def validate(instance: dict, definition: str) -> None:
    jsonschema.validate(instance, {**SCHEMA, "$ref": f"#/$defs/{definition}"})


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeNetLogger:
    """Answers from the samples and records every URL asked for."""

    def __init__(self, status: int = 200, body: bytes | None = None, retry_after: str | None = None) -> None:
        self.urls: list[str] = []
        self.status = status
        self.body = body
        self.retry_after = retry_after

    def __call__(self, url: str) -> tuple[int, bytes, str | None]:
        self.urls.append(url)
        routine = url.split("/api/")[1].split(".php")[0]
        return self.status, self.body if self.body is not None else sample(routine), self.retry_after


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def fake() -> FakeNetLogger:
    return FakeNetLogger()


@pytest.fixture
def nl(fake: FakeNetLogger, clock: Clock) -> NetLoggerSource:
    return NetLoggerSource("N0CALL", fetch=fake, limiter=RateLimiter(LIMITS, clock=clock), cache=Cache(clock=clock))


# ---------------------------------------------------------------------------
# Every documented call, mapped onto the contract
# ---------------------------------------------------------------------------


class TestCalls:
    def test_active_nets(self, nl, fake):
        r = nl.active_nets()
        validate(r, "net_list")
        assert r["total"] == 2
        omiss = next(n for n in r["nets"] if n["server"] == "NETLOGGER2")
        assert omiss == {
            "source": "netlogger", "server": "NETLOGGER2", "name": "OMISS 80m SSB Net",
            "current_name": "OMISS 80m SSB Net", "frequency": "3.825", "band": "80m", "mode": "SSB",
            "net_control": "KI7MT", "logger": "KI7MT - v3.1.7", "opened": "2026-09-28T01:15:00Z",
            "monitoring": 21, "frequency_mhz": 3.825, "band_adif": "80m",
        }
        assert fake.urls == ["https://www.netlogger.org/api/GetActiveNets.php"]

    def test_checkins_with_pointer(self, nl, fake):
        r = nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        validate(r, "checkin_list")
        assert r["pointer"] == 2 and r["checkin_count"] == 2
        assert [c["serial"] for c in r["checkins"]] == [1, 2]  # list order, whatever the XML order
        assert r["checkins"][0]["member_id"] == "7212"
        assert "status" not in r["checkins"][0]  # a blank status is omitted
        assert fake.urls == [
            "https://www.netlogger.org/api/GetCheckins.php?ServerName=NETLOGGER2&NetName=OMISS+80m+SSB+Net"
        ]

    def test_past_nets(self, nl, fake):
        r = nl.past_nets(3, "OMISS")
        validate(r, "net_list")
        net = r["nets"][0]
        assert net["net_id"] == 987654 and net["aim"] is True and net["auto_closed"] is False
        assert net["inactivity_timeout_minutes"] == 30  # the spec's "InactivitytTimer" spelling
        assert net["closed"] == "2026-09-27T03:12:00Z"
        assert fake.urls == ["https://www.netlogger.org/api/GetPastNets.php?Interval=3&NetNameLike=OMISS"]

    def test_past_checkins(self, nl, fake):
        r = nl.past_checkins("NETLOGGER2", "OMISS 80m SSB Net", "987654")
        validate(r, "checkin_list")
        assert r["net_id"] == 987654 and r["checkins"][0]["status"] == "(c/o)"
        assert fake.urls[0].endswith("GetPastNetCheckins.php?ServerName=NETLOGGER2&NetName=OMISS+80m+SSB+Net&NetID=987654")

    def test_get_pointer_never_called(self, nl, fake):
        nl.active_nets(); nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        nl.past_nets(); nl.past_checkins("NETLOGGER2", "x", 1)
        assert not any("GetPointer" in u for u in fake.urls)


# ---------------------------------------------------------------------------
# Privacy: street, ZIP and IP never leave
# ---------------------------------------------------------------------------


class TestPrivacy:
    def test_no_private_values_anywhere(self, nl):
        out = json.dumps([
            nl.active_nets(),
            nl.checkins("NETLOGGER2", "OMISS 80m SSB Net"),
            nl.past_nets(),
            nl.past_checkins("NETLOGGER2", "OMISS 80m SSB Net", 987654),
        ])
        for private in ("123 Example Street", "456 Sample Road", "99999", "88888", "192.0.2.10"):
            assert private not in out

    def test_unknown_elements_dropped(self, nl):
        assert "SomeFutureElement" not in json.dumps(nl.active_nets())
        assert "ignored" not in json.dumps(nl.active_nets())


# ---------------------------------------------------------------------------
# Parsing as the spec requires
# ---------------------------------------------------------------------------


class TestParsing:
    def test_error_node_gives_empty_list_and_message(self, clock):
        body = (b"<NetLoggerXML><Header><TimeZone>UTC</TimeZone></Header>"
                b"<Error>Not a Valid ServerName or NetName</Error><ResponseCode>404 Not Found</ResponseCode>"
                b"</NetLoggerXML>")
        nl = NetLoggerSource("N0CALL", fetch=FakeNetLogger(body=body), limiter=RateLimiter(LIMITS, clock=clock), cache=Cache(clock=clock))
        r = nl.checkins("NETLOGGER", "no such net")
        assert r["checkins"] == [] and r["checkin_count"] == 0
        assert r["message"] == "Not a Valid ServerName or NetName"

    def test_warning_logged_not_returned(self, nl, caplog):
        with caplog.at_level("WARNING", logger="netlogger_mcp"):
            r = nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        assert "Sample warning for the developer" in caplog.text
        assert "Sample warning" not in json.dumps(r)

    def test_entity_expansion_refused(self):
        bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
                b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><NetLoggerXML>&b;</NetLoggerXML>')
        with pytest.raises(NetLoggerError):
            parse(bomb)

    def test_not_netlogger_xml(self):
        with pytest.raises(NetLoggerError):
            parse(b"<html><body>maintenance</body></html>")

    def test_non_utc_times_left_as_sent(self):
        p = parse(sample("GetActiveNets").replace(b"<TimeZone>UTC</TimeZone>", b"<TimeZone>CST</TimeZone>"))
        assert p.nets()[0]["opened"] == "2026-09-28 01:00:00"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.parametrize("server", ["", "NET LOGGER", "a" * 33, "../x", "NET\nLOGGER"])
    def test_bad_server_name(self, nl, server):
        with pytest.raises(NetLoggerError):
            nl.checkins(server, "Net")

    @pytest.mark.parametrize("net", ["", "a" * 129, "bad\x00name", "bad\nname"])
    def test_bad_net_name(self, nl, net):
        with pytest.raises(NetLoggerError):
            nl.checkins("NETLOGGER", net)

    @pytest.mark.parametrize("net_id", ["", "12a", "-1", "1" * 13])
    def test_bad_net_id(self, nl, net_id):
        with pytest.raises(NetLoggerError):
            nl.past_checkins("NETLOGGER", "Net", net_id)

    def test_url_encoding(self, nl, fake):
        nl.checkins("NETLOGGER", "A&B=C Net")
        assert fake.urls[0].endswith("NetName=A%26B%3DC+Net")

    @pytest.mark.parametrize("days", [0, 366, "x"])
    def test_bad_interval(self, nl, days):
        with pytest.raises(NetLoggerError):
            nl.past_nets(days, "OMISS")

    def test_over_seven_days_needs_filter(self, nl, fake):
        with pytest.raises(NetLoggerError, match="name_like"):
            nl.past_nets(8)
        assert fake.urls == []
        nl.past_nets(30, "OMISS")
        assert len(fake.urls) == 1


# ---------------------------------------------------------------------------
# The call limits: never exceeded
# ---------------------------------------------------------------------------


class TestLimits:
    def test_limits_are_netloggers(self):
        assert LIMITS == {"GetActiveNets": 1, "GetCheckins": 3, "GetPastNets": 1, "GetPastNetCheckins": 10}

    def test_active_nets_one_call_a_minute_for_any_filters(self, nl, fake, clock):
        nl.active_nets(); nl.active_nets("OMISS"); nl.active_nets("ARES")
        clock.now += 59
        nl.active_nets("omiss")
        assert len(fake.urls) == 1
        clock.now += 1
        assert nl.active_nets("omiss")["total"] == 1
        assert len(fake.urls) == 2

    def test_filter_matches_either_name_ignoring_case(self, nl):
        assert [n["name"] for n in nl.active_nets("omiss")["nets"]] == ["OMISS 80m SSB Net"]

    def test_checkins_three_a_minute(self, nl, fake, clock):
        for i in range(3):
            nl.checkins("NETLOGGER", f"Net {i}")
        with pytest.raises(RateLimited) as e:
            nl.checkins("NETLOGGER", "Net 3")
        assert len(fake.urls) == 3
        assert 1 <= e.value.retry_after <= 60
        clock.now += 60
        nl.checkins("NETLOGGER", "Net 3")
        assert len(fake.urls) == 4

    def test_past_checkins_ten_a_minute(self, nl, fake):
        for i in range(10):
            nl.past_checkins("NETLOGGER", "Net", i)
        with pytest.raises(RateLimited):
            nl.past_checkins("NETLOGGER", "Net", 10)
        assert len(fake.urls) == 10

    def test_worst_case_hammering_stays_within_limits(self, nl, fake, clock):
        """Call every tool every second for ten minutes; count calls per rolling minute."""
        sent: list[tuple[float, str]] = []
        for second in range(600):
            clock.now = 1000.0 + second
            for fn, args in [
                (nl.active_nets, ()), (nl.checkins, ("NETLOGGER", f"Net {second % 7}")),
                (nl.past_nets, (second % 7 + 1,)), (nl.past_checkins, ("NETLOGGER", "Net", second)),
            ]:
                before = len(fake.urls)
                try:
                    fn(*args)
                except RateLimited:
                    pass
                if len(fake.urls) > before:
                    sent.append((clock.now, fake.urls[-1].split("/api/")[1].split(".php")[0]))
        for t, _ in sent:
            for routine, limit in LIMITS.items():
                in_window = [s for s in sent if s[1] == routine and t <= s[0] < t + 60]
                assert len(in_window) <= limit, (routine, t, len(in_window))

    def test_over_limit_answers_from_stale_cache(self, nl, fake, clock):
        nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        nl.checkins("NETLOGGER", "A"); nl.checkins("NETLOGGER", "B")
        clock.now += 30  # the OMISS entry is past its 20 s reuse time, the limit is still spent
        r = nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        assert r["stale"] is True and r["cached"] is True and r["age_seconds"] == 30
        assert "try again" in r["note"]
        assert len(fake.urls) == 3

    def test_fresh_cache_reused(self, nl, fake, clock):
        nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        clock.now += 10
        r = nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        assert r["cached"] is True and r["stale"] is False and r["age_seconds"] == 10
        assert len(fake.urls) == 1


class TestTooManyRequests:
    def test_http_429_backs_off_a_minute(self, clock):
        fake = FakeNetLogger(status=429, body=b"")
        nl = NetLoggerSource("N0CALL", fetch=fake, limiter=RateLimiter(LIMITS, clock=clock), cache=Cache(clock=clock))
        with pytest.raises(RateLimited):
            nl.past_checkins("NETLOGGER", "Net", 1)
        fake.status, fake.body = 200, None
        for _ in range(5):
            clock.now += 10
            with pytest.raises(RateLimited):
                nl.past_checkins("NETLOGGER", "Net", 2)
        assert len(fake.urls) == 1  # nothing sent during the back-off
        clock.now += 10
        nl.past_checkins("NETLOGGER", "Net", 2)
        assert len(fake.urls) == 2

    def test_429_on_one_routine_stops_them_all(self, clock):
        fake = FakeNetLogger(status=429, body=b"")
        nl = NetLoggerSource("N0CALL", fetch=fake, limiter=RateLimiter(LIMITS, clock=clock), cache=Cache(clock=clock))
        with pytest.raises(RateLimited):
            nl.checkins("NETLOGGER", "Net")
        fake.status, fake.body = 200, None
        clock.now += 30
        for fn, args in [(nl.active_nets, ()), (nl.past_nets, ()), (nl.past_checkins, ("NETLOGGER", "Net", 1)),
                         (nl.checkins, ("NETLOGGER", "Other"))]:
            with pytest.raises(RateLimited):
                fn(*args)
        assert len(fake.urls) == 1
        clock.now += 30
        nl.active_nets()
        assert len(fake.urls) == 2

    def test_429_elsewhere_still_answers_from_cache(self, nl, fake, clock):
        nl.active_nets()
        clock.now += 50
        fake.status, fake.body = 429, b""
        with pytest.raises(RateLimited):
            nl.checkins("NETLOGGER", "Net")  # blocks everything until +110
        clock.now += 30  # active nets are 80 s old, past their reuse time, but NetLogger said stop
        fake.status, fake.body = 200, None
        r = nl.active_nets()
        assert r["stale"] is True and r["total"] == 2

    def test_retry_after_honoured(self, clock):
        fake = FakeNetLogger(status=429, body=b"", retry_after="300")
        nl = NetLoggerSource("N0CALL", fetch=fake, limiter=RateLimiter(LIMITS, clock=clock), cache=Cache(clock=clock))
        with pytest.raises(RateLimited) as e:
            nl.past_checkins("NETLOGGER", "Net", 1)
        assert e.value.retry_after == 300
        clock.now += 299
        fake.status = 200
        with pytest.raises(RateLimited):
            nl.past_checkins("NETLOGGER", "Net", 1)
        assert len(fake.urls) == 1

    def test_response_code_429_in_xml(self, clock):
        body = (b"<NetLoggerXML><Header/><Error>Too many requests</Error>"
                b"<ResponseCode>429 Too Many Requests</ResponseCode></NetLoggerXML>")
        fake = FakeNetLogger(body=body)
        nl = NetLoggerSource("N0CALL", fetch=fake, limiter=RateLimiter(LIMITS, clock=clock), cache=Cache(clock=clock))
        with pytest.raises(RateLimited):
            nl.checkins("NETLOGGER", "Net")
        clock.now += 30
        with pytest.raises(RateLimited):
            nl.checkins("NETLOGGER", "Other")
        assert len(fake.urls) == 1

    def test_unreachable_serves_stale(self, nl, fake, clock):
        nl.active_nets()
        clock.now += 120

        def down(url):
            raise OSError("connection refused")
        nl._fetch = down
        r = nl.active_nets()
        assert r["stale"] is True and r["total"] == 2 and "couldn't be reached" in r["note"]


# ---------------------------------------------------------------------------
# Every request names the station: no anonymous mode
# ---------------------------------------------------------------------------


class TestCallsign:
    @pytest.mark.parametrize("bad", [None, "", "   ", "KI", "NOCALL", "1234", "KI7MT!", "KI 7MT", "A" * 21])
    def test_required_and_checked(self, bad):
        with pytest.raises(NetLoggerError, match="callsign"):
            NetLoggerSource(bad)

    @pytest.mark.parametrize("given,saved", [("ki7mt", "KI7MT"), (" KI7MT ", "KI7MT"), ("ki7mt/p", "KI7MT/P"), ("VE3/KI7MT", "VE3/KI7MT")])
    def test_normalized(self, given, saved):
        assert NetLoggerSource(given, fetch=FakeNetLogger()).callsign == saved

    def test_user_agent_names_the_station(self):
        nl = NetLoggerSource("ki7mt", fetch=FakeNetLogger())
        assert nl.user_agent.startswith("netlogger-mcp/")
        assert "(KI7MT; +https://github.com/qso-graph/netlogger-mcp)" in nl.user_agent

    def test_real_requests_carry_it(self, monkeypatch):
        seen = {}

        class Resp:
            status = 200
            headers = {}

            def read(self, n):
                return sample("GetActiveNets")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout):
            seen["ua"] = req.get_header("User-agent")
            seen["url"] = req.full_url
            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        NetLoggerSource("KI7MT").active_nets()
        assert "(KI7MT; " in seen["ua"]
        assert seen["url"].startswith("https://")


class TestProgramId:
    """ADIF's PROGRAMID and PROGRAMVERSION name the app built on the library."""

    def test_program_leads_the_user_agent(self):
        nl = NetLoggerSource("KI7MT", program_id="OM-Logger", program_version="0.3", fetch=FakeNetLogger())
        assert nl.user_agent.startswith("OM-Logger/0.3 netlogger-mcp/")
        assert nl.user_agent.endswith("(KI7MT; +https://github.com/qso-graph/netlogger-mcp)")

    def test_program_without_version(self):
        nl = NetLoggerSource("KI7MT", program_id="OM-Logger", fetch=FakeNetLogger())
        assert nl.user_agent.startswith("OM-Logger netlogger-mcp/")

    def test_optional(self):
        assert NetLoggerSource("KI7MT", fetch=FakeNetLogger()).user_agent.startswith("netlogger-mcp/")

    @pytest.mark.parametrize("program_id,version", [
        ("OM Logger", None), ("OM/Logger", None), ("OM-Logger", "0.3 beta"), ("", "0.3"), ("a" * 65, None),
        ("OM-Logger\r\nX-Injected: 1", None),
    ])
    def test_rejected(self, program_id, version):
        with pytest.raises(NetLoggerError, match="program"):
            NetLoggerSource("KI7MT", program_id=program_id, program_version=version)


# ---------------------------------------------------------------------------
# Empty slots and the pointer (#19): from a live OMISS net, 2026-09-29
# ---------------------------------------------------------------------------

def _live_list(pointer: int, rows: list[tuple[int, str | None]], count: int) -> bytes:
    checkins = "".join(
        f"<Checkin><SerialNo>{s}</SerialNo>" + (f"<Callsign>{c}</Callsign>" if c else "<Callsign/>") + "</Checkin>"
        for s, c in rows
    )
    return (
        "<NetLoggerXML><Header><TimeZone>UTC</TimeZone></Header><CheckinList>"
        f"<ResponseCode>200 OK</ResponseCode><CheckinCount>{count}</CheckinCount><Pointer>{pointer}</Pointer>"
        f"{checkins}</CheckinList></NetLoggerXML>"
    ).encode()


class TestEmptySlotsAndPointer:
    def test_empty_slots_are_not_checkins(self, clock):
        body = _live_list(3, [(1, "KC9RRN"), (2, "W7RSO"), (3, "KG5JIM"), (21, None), (24, "W2EUA"), (25, None)], 6)
        nl = NetLoggerSource("N0CALL", fetch=FakeNetLogger(body=body), limiter=RateLimiter(LIMITS, clock=clock),
                             cache=Cache(clock=clock))
        r = nl.checkins("NETLOGGER2", "OMISS 40m SSB Net")
        assert [c["callsign"] for c in r["checkins"]] == ["KC9RRN", "W7RSO", "KG5JIM", "W2EUA"]
        assert r["checkin_count"] == 4
        assert r["empty_slots"] == [21, 25]
        assert r["source_checkin_count"] == 6  # NetLogger's own figure, kept for reference
        assert r["pointer"] == 3 and r["pointer_callsign"] == "KG5JIM"

    def test_pointer_on_an_empty_slot_names_no_one(self, clock):
        body = _live_list(21, [(1, "KC9RRN"), (21, None)], 2)
        nl = NetLoggerSource("N0CALL", fetch=FakeNetLogger(body=body), limiter=RateLimiter(LIMITS, clock=clock),
                             cache=Cache(clock=clock))
        r = nl.checkins("NETLOGGER2", "OMISS 40m SSB Net")
        assert r["pointer"] == 21 and r["pointer_callsign"] is None

    def test_clean_list_has_no_extra_fields(self, nl):
        r = nl.checkins("NETLOGGER2", "OMISS 80m SSB Net")
        assert r["empty_slots"] == [] and "source_checkin_count" not in r
        assert r["pointer_callsign"] == "N0CALL"
