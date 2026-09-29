"""Reading NetLogger's free-text band and frequency, without guessing.

NetLogger's Band and Frequency are whatever the logger typed: "40m", "40M",
"75M", "DMR", "7033", "3918 KHz", "7.272", "147.030 91.5", "TG 3141". The raw
values are always returned as typed. These helpers add read values only when
the text can be read reliably, and leave them out otherwise.

Band limits are ADIF's (adif_band.json: the ADIF 3.1.7 Band enumeration,
unchanged), never a table of our own.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

_BANDS: list[tuple[str, float, float]] = [
    (b["band"], float(b["lower_mhz"]), float(b["upper_mhz"]))
    for b in json.loads(files("netlogger_mcp").joinpath("adif_band.json").read_text(encoding="utf-8"))["bands"]
]
_BAND_NAMES = {name.casefold(): name for name, _, _ in _BANDS}

_NUM = r"(\d+(?:\.\d+)?|\.\d+)"
# A single frequency with an optional unit, then optionally a CTCSS/DCS tone in Hz.
_FREQ_RE = re.compile(rf"^{_NUM}\s*(mhz|khz|hz)?(?:\s+{_NUM}\s*(?:hz)?)?$", re.I)
_TALKGROUP_RE = re.compile(r"^TG\s*#?\s*(\d{1,9})$", re.I)


def frequency_mhz(text: str | None) -> float | None:
    """'7.272' -> 7.272; '3918 KHz' -> 3.918; '147.030 91.5' -> 147.03;
    '7033' -> 7.033; '1296' -> 1296.0; '14290000' -> 14.29. None if unreadable.

    A unit is taken as given. With no unit, the number could be MHz, kHz or Hz:
    the one reading that falls inside an ADIF band is used. If none does, a
    decimal number under 1000 is taken as MHz (e.g. GMRS 462.675); otherwise,
    and whenever more than one reading fits, it's left unread.
    """
    m = _FREQ_RE.match((text or "").strip())
    if not m:
        return None
    raw, unit = m.group(1), (m.group(2) or "").casefold()
    value = float(raw)
    if unit:
        mhz = value / {"mhz": 1, "khz": 1000, "hz": 1_000_000}[unit]
    else:
        fits = {round(value / d, 6) for d in (1, 1000, 1_000_000) if adif_band(value / d)}
        if len(fits) == 1:
            mhz = fits.pop()
        elif not fits and "." in raw and value < 1000:
            mhz = value
        else:
            return None
    return round(mhz, 6) if 0.1 <= mhz <= 7_500_000 else None


def tone_hz(text: str | None) -> float | None:
    """The tone after a frequency ('147.030 91.5' -> 91.5), or None."""
    m = _FREQ_RE.match((text or "").strip())
    return float(m.group(3)) if m and m.group(3) else None


def talkgroup(text: str | None) -> int | None:
    """'TG 3141' -> 3141, or None."""
    m = _TALKGROUP_RE.match((text or "").strip())
    return int(m.group(1)) if m else None


def adif_band(mhz: float | None) -> str | None:
    """The ADIF band containing the frequency, or None (e.g. GMRS, 462.675 MHz)."""
    if mhz is None:
        return None
    for name, low, high in _BANDS:
        if low <= mhz <= high:
            return name
    return None


def read_band_and_frequency(band: str | None, frequency: str | None) -> dict[str, Any]:
    """The read fields for a net: frequency_mhz, band_adif, tone_hz, talkgroup,
    each only when readable. A readable frequency decides the band; otherwise
    the logger's band counts only if it is an ADIF band name (any case)."""
    out: dict[str, Any] = {}
    mhz = frequency_mhz(frequency)
    if mhz is not None:
        out["frequency_mhz"] = mhz
        if (band_name := adif_band(mhz)) is not None:
            out["band_adif"] = band_name
        if (tone := tone_hz(frequency)) is not None:
            out["tone_hz"] = tone
    else:
        if (tg := talkgroup(frequency)) is not None:
            out["talkgroup"] = tg
        if band and band.strip().casefold() in _BAND_NAMES:
            out["band_adif"] = _BAND_NAMES[band.strip().casefold()]
    return out
