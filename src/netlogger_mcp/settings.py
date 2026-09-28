"""The MCP server's one setting: the callsign of the station using it.

A callsign is public, not a credential, so it lives in a small settings file
in the user's config folder. NETLOGGER_MCP_CALLSIGN overrides the file.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .netlogger import normalize_callsign

ENV_CALLSIGN = "NETLOGGER_MCP_CALLSIGN"
ENV_CONFIG_DIR = "NETLOGGER_MCP_CONFIG_DIR"


def config_dir() -> Path:
    if os.getenv(ENV_CONFIG_DIR):
        return Path(os.environ[ENV_CONFIG_DIR])
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "netlogger-mcp"


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
