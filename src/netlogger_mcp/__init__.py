"""MCP server for net logging: live and past nets and check-ins."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Final

try:
    _pkg_version = version("netlogger-mcp")
except PackageNotFoundError:  # local dev / editable installs without dist metadata
    _pkg_version = "0.0.0-dev"

__version__: Final[str] = _pkg_version

# The NetLogger API this server is built against: "The NetLogger XML Data
# Service Interface Specification" v1.3 (K0JDD, 2023-12-01).
__spec_version__: Final[str] = "netlogger-xml-api-1.3"

# Version of the records the tools return (schema/contract.schema.json).
# Every source (NetLogger now, the OM-Logger next) maps onto this.
__contract_version__: Final[str] = "0.1"
