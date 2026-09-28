"""Security test suite — qso-graph MCP Security Framework v1.0.

These tests enforce the 10 non-negotiable security guarantees.
See: https://qso-graph.io/security/
"""

import re
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src"


def _py_files():
    """Yield all .py files under src/."""
    yield from SRC_DIR.rglob("*.py")


def test_no_print_credentials():
    """Guarantee #1: Credentials never in logs (print statements)."""
    forbidden = re.compile(
        r'print\s*\(.*(?:password|api_key|creds|secret|token).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Credential print in {py_file.name}: {matches}"


def test_no_logging_credentials():
    """Guarantee #1: Credentials never in logs (logging statements)."""
    forbidden = re.compile(
        r'logging\..*\(.*(?:password|api_key|creds|secret|token).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Credential logging in {py_file.name}: {matches}"


def test_no_subprocess():
    """Guarantee #5: No command injection surface."""
    forbidden = re.compile(r'subprocess\.|os\.system|shell\s*=\s*True')
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Shell execution in {py_file.name}: {matches}"


def test_all_urls_https():
    """Guarantee #7: HTTPS only for external calls."""
    http_url = re.compile(r'http://(?!localhost|127\.0\.0\.1|::1)')
    for py_file in _py_files():
        content = py_file.read_text()
        matches = http_url.findall(content)
        assert not matches, f"Non-HTTPS URL in {py_file.name}: {matches}"


def test_error_messages_safe():
    """Guarantee #3/#10: Credentials never in error messages."""
    dangerous = re.compile(
        r'raise\s+\w+\([^)]*(?:password|api_key|creds|secret).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = dangerous.findall(content)
        assert not matches, f"Credential in exception in {py_file.name}: {matches}"


def test_no_eval_exec():
    """Guarantee #5: No code injection surface."""
    for py_file in _py_files():
        content = py_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if re.search(r'\b(?:eval|exec)\s*\(', stripped):
                assert False, f"eval/exec in {py_file.name}:{i}: {stripped.strip()}"


def test_xml_parsed_with_defusedxml():
    """XML from the network is parsed only through defusedxml."""
    for py_file in _py_files():
        content = py_file.read_text()
        assert not re.search(r'^\s*(?:from|import)\s+xml\.(?:etree|dom|sax)(?!\.ElementTree import Element\b)',
                             content, re.MULTILINE), f"stdlib XML parser imported in {py_file.name}"
        assert "lxml" not in content, f"lxml in {py_file.name}"


def test_private_fields_not_in_contract():
    """Street, ZIP and srcIP have no field in the contract, so they can't be returned."""
    import json
    from netlogger_mcp.contract import CHECKIN_FIELDS, NET_FIELDS, PRIVATE_SOURCE_FIELDS

    mapped = {tag for tags in (*NET_FIELDS.values(), *CHECKIN_FIELDS.values()) for tag in tags}
    assert not mapped & set(PRIVATE_SOURCE_FIELDS)
    schema = json.loads((SRC_DIR / "netlogger_mcp/schema/contract.schema.json").read_text())
    for name in ("net", "checkin"):
        props = set(schema["$defs"][name]["properties"])
        assert not {"street", "zip", "src_ip", "srcIP", "Street", "Zip"} & props
        assert schema["$defs"][name]["additionalProperties"] is False
