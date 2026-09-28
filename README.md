# netlogger-mcp

MCP server and Python library for amateur-radio net logging: which nets are on the air, who has
checked in, who's up now, and what past nets logged.

- **Read-only.** It never writes to a net.
- **One contract, more than one source.** Every answer uses the same net and check-in records
  ([`schema/contract.schema.json`](src/netlogger_mcp/schema/contract.schema.json)), whatever logging
  system is behind them. The first source is [NetLogger](https://www.netlogger.org)'s public XML Data
  Service (API 1.3). The next is the OM-Logger being built for OMISS.
- **A good neighbour.** NetLogger is a donation-funded service. This server never exceeds
  NetLogger's published call limits, caches every answer, and backs off when told to.
- **Private details stay out.** Street addresses, ZIP codes and IP addresses in NetLogger's data
  have no place in the contract, so they never reach an AI, a program or a user.

Status: in development (0.1.0, not yet on PyPI).

## Tools

| Tool | NetLogger call | Returns |
|---|---|---|
| `netlogger_active_nets` | `GetActiveNets` | nets on the air: server, name, frequency, band, mode, net control, logger, opened, monitoring count |
| `netlogger_checkins` | `GetCheckins` | a live net's check-ins, the count, and the **pointer** (the station up now) |
| `netlogger_past_nets` | `GetPastNets` | closed nets over the last N days, with the net IDs past check-ins need |
| `netlogger_past_checkins` | `GetPastNetCheckins` | a closed net's check-ins |
| `get_version_info` | none | server version, NetLogger API version, contract version |

These are all the calls NetLogger's API 1.3 documents. `GetPointer` is deprecated; the pointer comes
with `GetCheckins`, so it's never called.

## Call limits

| Call | NetLogger's limit | Answers reused for |
|---|---|---|
| `GetActiveNets` | 1 a minute | 60 s; the name filter is applied locally, so any number of filters cost one call |
| `GetCheckins` | 3 a minute | 20 s per net |
| `GetPastNets` | 1 a minute | 60 s per query |
| `GetPastNetCheckins` | 10 a minute | an hour (a closed net's list doesn't change) |

A limit is checked before a request is sent, never after. Over the limit, the answer comes from
cache with its age (`age_seconds`, `stale`), or the result says when to try again. A
`429 Too Many Requests` on any call stops **all** calls to NetLogger for at least a minute, longer
if NetLogger's `Retry-After` asks. NetLogger's anti-flooding is aimed at the client, and every call
reaches the same server. Past nets older than 7 days need a name filter (NetLogger's rule).

The limits are per process. Every tool call in one server shares them.

## Install

```bash
pip install netlogger-mcp   # once released
```

Claude Code / Claude Desktop:

```json
"netlogger": { "command": "netlogger-mcp" }
```

No API key or password is needed. **Your callsign is.**

## Your callsign

Every request tells NetLogger which station is asking, in the User-Agent:

```
netlogger-mcp/0.1.0 (KI7MT; +https://github.com/qso-graph/netlogger-mcp)
```

That way, NetLogger can tell users apart. Without it, every install would look like one client, and
one misbehaving install could get everyone blocked. There is no anonymous mode.

- **Nothing to configure.** On first use, the server says it needs your callsign, the AI asks you,
  and it's saved (`netlogger_set_callsign`). You're asked once.
- **Saved** in a small settings file: `~/.config/netlogger-mcp/settings.json` on Linux,
  `~/Library/Application Support/netlogger-mcp/` on macOS, `%APPDATA%\netlogger-mcp\` on Windows.
  A callsign is public, not a password.
- **Or set it** with `NETLOGGER_MCP_CALLSIGN=KI7MT`, which overrides the file.
- Changing the callsign never resets the call limits.

For testing without the network, set `NETLOGGER_MCP_MOCK=1` to answer from bundled synthetic samples.

## As a library

Programs that don't need an AI use the same code directly, with the same limits, cache and contract.
A library can't ask anyone anything, so it requires the callsign: the program passes in the signed-in
user's callsign, or the club's for a shared server.

```python
from netlogger_mcp.netlogger import NetLoggerSource

# callsign: required (no valid callsign: NetLoggerError, nothing sent).
# program_id / program_version: your app, as in ADIF's PROGRAMID and PROGRAMVERSION (optional).
nl = NetLoggerSource(callsign="KI7MT", program_id="OM-Logger", program_version="0.3")
# User-Agent: OM-Logger/0.3 netlogger-mcp/0.1.0 (KI7MT; +https://github.com/qso-graph/netlogger-mcp)
for net in nl.active_nets(name_like="OMISS")["nets"]:
    live = nl.checkins(net["server"], net["name"])
    print(net["name"], "up now:", live["pointer"])
```

Programs in other languages can run the server and call its tools over MCP (JSON-RPC on stdio or
HTTP).

## Terms and privacy

NetLogger's terms allow API use "in direct support of Radio Communications". This server is for that.
It sends a User-Agent naming this project and the station using it. Parsing follows the spec: no assumptions about node order
or count, unknown elements ignored, `<Warning>` messages logged for the developer. XML is parsed with
`defusedxml`.

## Development

```bash
pip install -e ".[test]"
pytest
```

Part of [qso-graph](https://github.com/qso-graph). Licensed GPL-3.0-or-later.
