"""Reading NetLogger's free-text band and frequency (#16). Values from real nets."""

from __future__ import annotations

import pytest

from netlogger_mcp.radio import adif_band, frequency_mhz, read_band_and_frequency


@pytest.mark.parametrize("text,mhz", [
    ("7.272", 7.272), ("7.192", 7.192), ("3918 KHz", 3.918), ("7033", 7.033),
    ("14290000", 14.29), ("147.030 91.5", 147.03), ("1296", 1296.0), ("50", 50.0),
    ("462.675", 462.675), ("3.825 MHz", 3.825),
])
def test_frequencies(text, mhz):
    assert frequency_mhz(text) == mhz


# "146520" fits two ADIF bands (146.52 MHz on 2m, 146,520 MHz on 2mm), so it's left unread.
@pytest.mark.parametrize("text", ["TG 3141", "", "7.2 or 3.8", "Echolink", "0", "12345", "146520"])
def test_unreadable_frequencies(text):
    assert frequency_mhz(text) is None


def test_bands_are_adifs():
    assert adif_band(7.192) == "40m" and adif_band(3.918) == "80m" and adif_band(147.03) == "2m"
    assert adif_band(462.675) is None  # GMRS: not an amateur band


@pytest.mark.parametrize("band,freq,expected", [
    ("40M", "7.192", {"frequency_mhz": 7.192, "band_adif": "40m"}),
    ("75M", "3918 KHz", {"frequency_mhz": 3.918, "band_adif": "80m"}),  # the frequency decides
    ("70cm", "462.675", {"frequency_mhz": 462.675}),  # GMRS labelled 70cm: no amateur band
    ("2m", "147.030 91.5", {"frequency_mhz": 147.03, "band_adif": "2m", "tone_hz": 91.5}),
    ("DMR", "TG 3141", {"talkgroup": 3141}),  # a mode, not a band
    ("40M", "", {"band_adif": "40m"}),  # no frequency: an ADIF band name is kept
    ("75M", "", {}),  # not an ADIF band name, and nothing to read it from
])
def test_read_band_and_frequency(band, freq, expected):
    assert read_band_and_frequency(band, freq) == expected
