#!/usr/bin/env python3
"""Turn real NetLogger API responses into fixtures that are safe to commit (#15).

Usage:
    python scripts/anonymize_samples.py RAW_DIR OUT_DIR

RAW_DIR holds one real response per routine (GetActiveNets.xml, GetCheckins.xml,
GetPastNets.xml, GetPastNetCheckins.xml), captured within NetLogger's published
rates. Raw captures never go in the repository.

Kept as NetLogger sent them: element names and order, value formats, status markers,
counts, serials, the pointer, net names (callsigns inside them replaced), states,
countries and DXCC codes. Replaced:

- every callsign (check-ins, net control, and inside any free-text net field: the
  logger, net names, even Frequency, where one was found typed) with
  a clearly fictional one in the N0CALL style, the same one each time it appears;
- names, cities and counties with made-up ones; remarks and QSL info with
  placeholder text;
- grid squares cut to 4 characters;
- Street and Zip with test values, srcIP with an address from 192.0.2.0/24
  (reserved for documentation, RFC 5737).

The past-nets list is cut to a representative slice: each distinct shape of
Frequency, Mode and Band once.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.etree.ElementTree import Element, fromstring, tostring

CALL = re.compile(r"\b[A-Z]{1,2}\d{1,2}[A-Z]{1,4}\b")
FIRST = ["Alan", "Betty", "Carl", "Dora", "Evan", "Faye", "Glen", "Hope", "Ivan", "June", "Kurt",
         "Lena", "Mark", "Nora", "Owen", "Pam", "Rex", "Sue", "Ted", "Uma", "Vic", "Wes"]
LAST = ["Adams", "Baker", "Clark", "Davis", "Evans", "Foster", "Grant", "Hayes", "Irwin", "Jones",
        "Keller", "Lewis", "Moore", "Nolan", "Owens", "Price", "Quinn", "Reed", "Stone", "Turner"]
TOWN = ["Springfield", "Riverton", "Fairview", "Lakeside", "Greenville", "Oakdale", "Milton",
        "Ashland", "Clayton", "Dayton", "Easton", "Franklin"]
ROUTINES = ("GetActiveNets", "GetCheckins", "GetPastNets", "GetPastNetCheckins")


class Scrubber:
    def __init__(self) -> None:
        self.calls: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.places: dict[str, str] = {}

    def call(self, c: str) -> str:
        if c not in self.calls:
            i = len(self.calls)
            self.calls[c] = f"{'NKW'[i // 10 % 3]}{i % 10}{('CALL', 'TEST', 'FAKE')[i // 30 % 3]}"
        return self.calls[c]

    def calls_in(self, text: str) -> str:
        return CALL.sub(lambda m: self.call(m.group(0)), text)

    def name(self, v: str) -> str:
        if v not in self.names:
            k, parts = len(self.names), v.split()
            first, last = FIRST[k % len(FIRST)], LAST[k * 7 % len(LAST)]
            self.names[v] = first if len(parts) == 1 else (
                f"{first} {chr(65 + k % 26)} {last}" if len(parts) >= 3 else f"{first} {last}")
        return self.names[v]

    def place(self, v: str) -> str:
        if v not in self.places:
            self.places[v] = TOWN[len(self.places) % len(TOWN)] + (" County" if len(v.split()) > 1 else "")
        return self.places[v]


def _set(el: Element, tag: str, fn) -> None:
    e = el.find(tag)
    if e is not None and e.text and e.text.strip():
        e.text = fn(e.text.strip())


def scrub(root: Element, s: Scrubber, routine: str) -> None:
    if routine == "GetPastNets":
        for server in root.iter("Server"):
            seen, nets = set(), list(server.iter("Net"))
            for n in nets:
                shape = tuple(re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "9", (n.findtext(t) or "").strip()))
                              for t in ("Frequency", "Mode", "Band"))
                if shape in seen or len(seen) >= 14:
                    server.remove(n)
                else:
                    seen.add(shape)
    for i, n in enumerate(root.iter("Net")):
        _set(n, "NetControl", s.call)
        for tag in ("NetName", "AltNetName", "Logger", "Frequency", "Mode", "Band"):  # free text: a callsign turns up anywhere
            _set(n, tag, s.calls_in)
        _set(n, "srcIP", lambda _ip, i=i: f"192.0.2.{i % 250 + 1}")
    for c in root.iter("Checkin"):
        _set(c, "Callsign", s.call)
        for tag in ("FirstName", "PreferredName"):
            _set(c, tag, s.name)
        for tag in ("CityCountry", "County"):
            _set(c, tag, s.place)
        _set(c, "Grid", lambda g: g[:4])
        _set(c, "Remarks", lambda r: "(remark text)" if r.startswith("(") else "remark text")
        _set(c, "QSLInfo", lambda _q: "QSL info text")
        _set(c, "Street", lambda _v: "1 Test Street")
        _set(c, "Zip", lambda _v: "00000")
    for cl in root.iter("CheckinList"):
        _set(cl, "NetName", s.calls_in)


def main(raw: Path, out: Path) -> None:
    s = Scrubber()
    out.mkdir(parents=True, exist_ok=True)
    for routine in ROUTINES:
        root = fromstring((raw / f"{routine}.xml").read_bytes())
        scrub(root, s, routine)
        (out / f"{routine}.xml").write_bytes(
            b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="utf-8") + b"\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
