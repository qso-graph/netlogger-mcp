<!-- mcp-name: io.github.qso-graph/netlogger-mcp -->
# netlogger-mcp

[![PyPI](https://img.shields.io/pypi/v/netlogger-mcp?label=PyPI&color=blue)](https://pypi.org/project/netlogger-mcp/)
[![MCP Registry](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fregistry.modelcontextprotocol.io%2Fv0%2Fservers%3Fsearch%3Dio.github.qso-graph%2Fnetlogger-mcp%26version%3Dlatest&query=%24.servers%5B0%5D.server.version&label=MCP%20Registry&color=blue)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.qso-graph/netlogger-mcp&version=latest)

MCP server for [NetLogger](https://www.netlogger.org/): nets on the air now, live check-in lists and who's up, and past nets and their check-ins, through any MCP-compatible AI assistant.

Data from NetLogger's public XML Data Service (API 1.3). Part of the [qso-graph](https://qso-graph.io/) project. **No API key needed.** Your callsign is asked for once (see below).

## Install

```bash
pip install netlogger-mcp
```

## Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `netlogger_active_nets` | Nets on the air now: frequency, band, mode, net control, logger, monitoring count | name_like |
| `netlogger_checkins` | A live net's check-in list, plus the pointer (the station being worked now) | server_name, net_name |
| `netlogger_past_nets` | Closed nets over the last N days, with the net IDs past check-ins need | interval_days, name_like |
| `netlogger_past_checkins` | A closed net's check-in list | server_name, net_name, net_id |
| `netlogger_set_callsign` | Save your callsign (asked once, on first use) | callsign |
| `get_version_info` | Service version + upstream spec version (fleet identity attestation) | — |

## What is NetLogger?

NetLogger is the logging program many amateur-radio nets use: net control or a logger keeps the check-in list, and anyone can follow the net live. Its server publishes active nets, check-in lists and past nets through a public API.

## Your Callsign

Every request tells NetLogger which station is asking, so it can tell one user from another:

```
netlogger-mcp/0.1.0 (KI7MT; +https://github.com/qso-graph/netlogger-mcp)
```

On first use the assistant asks for your callsign and saves it. You're asked once. To set it yourself, use `NETLOGGER_MCP_CALLSIGN=KI7MT`.

It's saved in `settings.json`, in `~/.config/netlogger-mcp/` (Linux), `~/Library/Application Support/netlogger-mcp/` (macOS) or `%APPDATA%\netlogger-mcp\` (Windows).

## Good Neighbour Policy

NetLogger is a donation-funded service on one server, and it limits how often each call may be made. We keep to those limits:

| Measure | Detail |
|---------|--------|
| **NetLogger's call limits** | GetActiveNets 1/min, GetCheckins 3/min, GetPastNets 1/min, GetPastNetCheckins 10/min. Checked before a request is sent, never after. |
| **One budget per user** | Every copy you run (Claude Desktop, Claude Code, a script) shares one budget, through a locked file beside `settings.json`. |
| **Response caching** | Active nets 60 s, check-ins 20 s, past nets 60 s, past check-ins 1 hour. Filtering by name costs no extra calls. |
| **Stale answers over errors** | When a limit is reached, the last answer comes back with its age rather than a new request. |
| **429 back-off** | A "too many requests" on any call stops all calls for at least a minute, longer if NetLogger asks. |
| **Past-net windows** | More than 7 days of past nets needs a name filter, NetLogger's rule to protect its server. |
| **Request timeout** | 15-second timeout. |
| **User-Agent header** | Every request names this project and your callsign, so NetLogger's operators can see who is asking. |

## Privacy

NetLogger's check-in data includes street addresses and ZIP codes, and past nets include the IP address of whoever opened them. **None of these are ever returned.**

## Quick Start

### Configure your MCP client

netlogger-mcp works with any MCP-compatible client. Add the server config and restart. The tools appear automatically.

#### Claude Desktop

Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "netlogger": {
      "command": "netlogger-mcp"
    }
  }
}
```

#### Claude Code

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "netlogger": {
      "command": "netlogger-mcp"
    }
  }
}
```

#### ChatGPT Desktop

```json
{
  "mcpServers": {
    "netlogger": {
      "command": "netlogger-mcp"
    }
  }
}
```

#### Cursor

Add to `.cursor/mcp.json` (project-level) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "netlogger": {
      "command": "netlogger-mcp"
    }
  }
}
```

#### VS Code / GitHub Copilot

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "netlogger": {
      "command": "netlogger-mcp"
    }
  }
}
```

#### Gemini CLI

Add to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project):

```json
{
  "mcpServers": {
    "netlogger": {
      "command": "netlogger-mcp"
    }
  }
}
```

### Ask questions

> "What nets are on the air right now?"

> "Are any 80m nets running?"

> "Who's checked into the county ARES net, and who's up now?"

> "Which nets ran in the last three days?"

> "Show me the check-ins from last night's net."

## As a Python Library

The same code works without an AI, with the same limits and cache. A library can't ask for your callsign, so you pass it in:

```python
from netlogger_mcp.netlogger import NetLoggerSource

nl = NetLoggerSource(callsign="KI7MT")
for net in nl.active_nets()["nets"]:
    live = nl.checkins(net["server"], net["name"])
    print(net["name"], "up now:", live["pointer"])
```

Apps can also name themselves, using ADIF's `PROGRAMID` and `PROGRAMVERSION`: `NetLoggerSource(callsign="KI7MT", program_id="MyLogger", program_version="1.0")`.

## Testing Without Network

```bash
NETLOGGER_MCP_MOCK=1 netlogger-mcp
```

## MCP Inspector

```bash
netlogger-mcp --transport streamable-http --port 8014
```

## Development

```bash
git clone https://github.com/qso-graph/netlogger-mcp.git
cd netlogger-mcp
pip install -e ".[test]"
pytest
```

## License

GPL-3.0-or-later
