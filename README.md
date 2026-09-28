# netlogger-mcp

MCP server for amateur-radio net logging: which nets are on the air, who has checked in, who's up
now, and what past nets logged.

- **Read-only.** It never writes to a net.
- **One contract, more than one source.** Tools return the same net and check-in records whatever
  logging system is behind them. The first source is [NetLogger](https://www.netlogger.org)'s public
  XML Data Service. The next is the OM-Logger being built for OMISS.
- **A good neighbour.** NetLogger is a donation-funded service. This server keeps to NetLogger's
  published call limits, caches every answer, and backs off when asked.
- **Private details stay out.** Street addresses, ZIP codes and IP addresses in NetLogger's data are
  dropped before anything reaches an AI or a user.

Status: in development. See the issues for the plan.

Part of [qso-graph](https://github.com/qso-graph). Licensed GPL-3.0-or-later.
