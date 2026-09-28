"""The records every tool returns, whatever the source.

Each source maps its own format onto these fields and nothing else, so a
field a source sends that isn't listed here (a street address, a ZIP code, an
IP address, or anything added later) can never reach a user.
schema/contract.schema.json is the published form.
"""

from __future__ import annotations

# contract field -> NetLogger element(s), first present wins
NET_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("NetName",),
    "current_name": ("AltNetName",),
    "frequency": ("Frequency",),
    "band": ("Band",),
    "mode": ("Mode",),
    "net_control": ("NetControl",),
    "logger": ("Logger",),
    "opened": ("Date",),
    "monitoring": ("SubscriberCount",),
    # past nets only
    "net_id": ("NetID",),
    "closed": ("ClosedAt",),
    "last_activity": ("LastActivity",),
    "aim": ("AIM",),
    "aim_update_ms": ("UpdateInterval",),
    "inactivity_timeout_minutes": ("InactivityTimer", "InactivitytTimer"),  # the spec spells it both ways
    "auto_closed": ("Assassinated",),
}

CHECKIN_FIELDS: dict[str, tuple[str, ...]] = {
    "serial": ("SerialNo",),
    "callsign": ("Callsign",),
    "first_name": ("FirstName",),
    "preferred_name": ("PreferredName",),
    "city": ("CityCountry",),
    "county": ("County",),
    "state": ("State",),
    "country": ("Country",),
    "dxcc": ("DXCC",),
    "grid": ("Grid",),
    "status": ("Status",),
    "remarks": ("Remarks",),
    "qsl_info": ("QSLInfo",),
    "member_id": ("MemberID",),
}

INT_FIELDS = {"monitoring", "net_id", "aim_update_ms", "inactivity_timeout_minutes", "serial", "dxcc"}
BOOL_FIELDS = {"aim", "auto_closed"}  # Y/N
TIME_FIELDS = {"opened", "closed", "last_activity"}

# Never returned by any tool. Listed so tests can prove it.
PRIVATE_SOURCE_FIELDS = ("Street", "Zip", "srcIP")
