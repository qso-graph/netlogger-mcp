# Changelog

## 0.1.0 (unreleased)

- Tools for every documented NetLogger API 1.3 call: active nets, live check-ins with the pointer,
  past nets, past check-ins; plus `get_version_info`.
- Records follow a source-independent contract (`schema/contract.schema.json`, 0.1).
- NetLogger's call limits enforced before sending; answers cached; a 429 on any call stops all
  calls for the back-off.
- Every request names the station using it (callsign in the User-Agent); no anonymous mode. The MCP
  asks once on first use and saves it (`netlogger_set_callsign`); the library requires it.
- Apps built on the library name themselves with ADIF's PROGRAMID and PROGRAMVERSION, which lead
  the User-Agent (`OM-Logger/0.3 netlogger-mcp/0.1.0 (KI7MT; +…)`).
- Street, ZIP and IP address never returned.
- `NetLoggerSource` usable as a plain Python library.
