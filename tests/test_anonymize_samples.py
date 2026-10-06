"""scripts/anonymize_samples.py finds every callsign in free text, and nothing else (#29)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "anonymize_samples", Path(__file__).parent.parent / "scripts" / "anonymize_samples.py"
)
anonymize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anonymize)


@pytest.mark.parametrize("call", ["W1AW", "KK4XA", "9A1AA", "4X4ABC", "2E0ABC", "3D2AB", "A61AB", "kk4xa"])
def test_callsigns_in_free_text_are_replaced(call):
    out = anonymize.Scrubber().calls_in(f"{call} Morning Net")
    assert call not in out and out.endswith(" Morning Net")


@pytest.mark.parametrize("text", ["REF 35C", "Tue DRE Net 35C w Duff", "EL29", "14.340", "7.185.5", "C4FM", "2m", "40m SSB"])
def test_things_that_are_not_callsigns_are_kept(text):
    assert anonymize.Scrubber().calls_in(text) == text
