"""Where netlogger-mcp keeps its files on this computer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

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


def limits_file() -> Path:
    """The call budget every copy on this computer shares."""
    return config_dir() / "limits.json"
