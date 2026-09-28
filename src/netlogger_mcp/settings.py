"""The MCP server's one setting: the callsign of the station using it.

A callsign is public, not a credential, so it lives in a small settings file
in the user's config folder. NETLOGGER_MCP_CALLSIGN overrides the file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .netlogger import normalize_callsign
from .paths import config_dir

ENV_CALLSIGN = "NETLOGGER_MCP_CALLSIGN"


def settings_file() -> Path:
    return config_dir() / "settings.json"


def load_callsign() -> str | None:
    """The saved callsign, or None if it hasn't been set (or isn't valid)."""
    value = os.getenv(ENV_CALLSIGN)
    if not value:
        try:
            value = json.loads(settings_file().read_text(encoding="utf-8")).get("callsign")
        except (OSError, ValueError, AttributeError):
            return None
    try:
        return normalize_callsign(value)
    except Exception:
        return None


def save_callsign(value: str) -> str:
    """Validate and save the callsign; return it normalized."""
    callsign = normalize_callsign(value)
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"callsign": callsign}) + "\n", encoding="utf-8")
    return callsign
