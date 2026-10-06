"""The parser against real NetLogger responses (#15).

The bundled samples (``netlogger_mcp/samples``) are one real response per routine,
captured on 2026-10-06 within NetLogger's published rates and anonymized by
``scripts/anonymize_samples.py``: callsigns, names, places and remarks replaced,
grids cut to 4 characters, Street, Zip and srcIP set to test values. Structure,
element order, value formats and status markers are NetLogger's own.

The spec-shaped fixtures in tests/fixtures/spec cover what these didn't show.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from netlogger_mcp.limiter import Cache, RateLimiter
from netlogger_mcp.netlogger import LIMITS, NetLoggerSource, parse

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "src/netlogger_mcp/schema/contract.schema.json").read_text()
)


def real(routine: str) -> bytes:
    return files("netlogger_mcp.samples").joinpath(f"{routine}.xml").read_bytes()


def validate(instance: dict, definition: str) -> None:
    jsonschema.validate(instance, {**SCHEMA, "$ref": f"#/$defs/{definition}"})


@pytest.fixture
def nl() -> NetLoggerSource:
    def fetch(url: str):
        return 200, real(url.split("/api/")[1].split(".php")[0]), None
    return NetLoggerSource("N0CALL", fetch=fetch, limiter=RateLimiter(LIMITS, clock=lambda: 0.0),
                           cache=Cache(clock=lambda: 0.0))


class TestRealResponses:
    def test_active_nets_fit_the_contract(self, nl):
        r = nl.active_nets()
        validate(r, "net_list")
        assert r["total"] == 7
        assert all(n["opened"].endswith("Z") for n in r["nets"])  # "YYYY-MM-DD hh:mm:ss" read as UTC

    def test_free_text_frequency_is_kept_but_not_read(self, nl):
        alaska = next(n for n in nl.active_nets()["nets"] if n["name"] == "Alaska morning net")
        assert alaska["frequency"] == "all" and "frequency_mhz" not in alaska
        assert alaska["band_adif"] == "2m"  # the logger's band, an ADIF band name

    def test_empty_net_control_is_omitted(self, nl):
        ohana = next(n for n in nl.active_nets()["nets"] if n["name"].startswith("Ohana Net"))
        assert "net_control" not in ohana

    def test_checkins_fit_the_contract(self, nl):
        r = nl.checkins("NETLOGGER", "Alaska morning net")
        validate(r, "checkin_list")
        assert r["checkin_count"] == 10 and r["pending_serials"] == [20] and r["source_checkin_count"] == 11
        assert r["pointer"] == 5 and r["pointer_callsign"] == "K2CALL"
        # Role markers as NetLogger sends them, combined ones included.
        assert [c["status"] for c in r["checkins"] if "status" in c] == ["(nc),(log)", "(m)", "(c/o)"]

    def test_empty_member_id_is_omitted(self, nl):
        """On a net that isn't a club's, MemberID is present but empty."""
        assert all("member_id" not in c for c in nl.checkins("NETLOGGER", "Alaska morning net")["checkins"])

    def test_past_nets_fit_the_contract(self, nl):
        r = nl.past_nets(1)
        validate(r, "net_list")
        net = r["nets"][0]
        assert net["net_id"] == 440529 and net["closed"] == "2026-10-06T17:05:22Z"
        assert net["inactivity_timeout_minutes"] == 30  # the server spells it InactivityTimer
        assert net["aim"] is True and net["auto_closed"] is False

    def test_unreadable_frequencies_stay_unread(self, nl):
        unread = sorted(n["frequency"] for n in nl.past_nets(1)["nets"] if "frequency_mhz" not in n)
        # As loggers typed them: a doubled decimal point, a reflector, a stray space, a callsign.
        assert "7.185.5" in unread and "REF 35C" in unread and "14. 290" in unread and "14.332.00" in unread

    def test_past_checkins_fit_the_contract(self, nl):
        r = nl.past_checkins("NETLOGGER", "Pacific RV Service Net", "440529")
        validate(r, "checkin_list")
        assert r["checkin_count"] == 20 and r["checkins"][0]["callsign"] == "K8CALL"
        # A closed net's pointer can sit past the last row.
        assert r["pointer"] == 21 and r["pointer_callsign"] is None

    def test_no_street_zip_or_ip_in_any_answer(self, nl):
        out = json.dumps([
            nl.active_nets(), nl.checkins("NETLOGGER", "Alaska morning net"),
            nl.past_nets(1), nl.past_checkins("NETLOGGER", "Pacific RV Service Net", "440529"),
        ])
        for private in ("1 Test Street", "00000", "192.0.2."):
            assert private not in out

    def test_no_warning_in_real_headers(self):
        """The spec describes <Warning>; none came back. tests/fixtures/spec covers it."""
        for routine in ("GetActiveNets", "GetCheckins", "GetPastNets", "GetPastNetCheckins"):
            assert parse(real(routine)).warnings == []
