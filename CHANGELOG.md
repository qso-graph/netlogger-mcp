# Changelog

## 0.1.3 (2026-09-29)

From Patton's test on a live net (OMISS 40m, #19):

- **Empty slots aren't check-ins.** A list row with no callsign is left out of `checkins` and
  `checkin_count`, and its serial is listed in `empty_slots`. NetLogger's own count, which includes
  them, is kept as `source_checkin_count` when it differs.
- **`pointer_callsign`**: the station at the pointer, from the same answer. NetLogger renumbers
  serials as the logger edits the list, so a serial can't be matched across calls.

## 0.1.2 (2026-09-29)

From Patton's cold test of omiss-mcp 0.1.1 (#17):

- **Shared answers.** Every copy on the computer already shared the call budget; now it also shares
  the answers it fetched (`cache.json` beside `limits.json`, under the same kind of lock). A copy
  that has reached a limit gets the newest answer any copy fetched, with its real `age_seconds`,
  instead of an error. If the file can't be used, the copy keeps its own cache; the limits never
  depend on it.
- `as_of_utc` on every response, errors included.
- Active nets list every server NetLogger returned and its net count (`servers`), before any name
  filter, so an empty answer explains itself.
- Records contract 0.2.

## 0.1.1 (2026-09-28)

- README rewritten in the qso-graph layout, about NetLogger only: tools, callsign, Good Neighbour
  Policy, privacy, client setup and example questions.
- Tool descriptions, docstrings and keywords no longer name other projects.

### Added (CI hygiene)

- **MCP Registry sync** — `publish.yml` now publishes to the [Official MCP Registry](https://registry.modelcontextprotocol.io)
  after each PyPI publish, using GitHub OIDC for auth. Triggered on
  `v*` tag push; no manual steps. Pattern documented in
  [qso-graph/.github/TEMPLATES.md](https://github.com/qso-graph/.github/blob/main/TEMPLATES.md).
- **Registry version badge** in README — PyPI and Registry versions
  are visible side-by-side so any drift between publishing surfaces
  is immediately apparent.
- **Release gates** — the tag must match `pyproject.toml`, and a
  `verify` job fails the release unless PyPI and the MCP Registry
  both serve the new version.
- `server.json` (`io.github.qso-graph/netlogger-mcp`).

## 0.1.0 (2026-09-28)

- Tools for every documented NetLogger API 1.3 call: active nets, live check-ins with the pointer,
  past nets, past check-ins; plus `get_version_info`.
- Records follow a source-independent contract (`schema/contract.schema.json`, 0.1).
- NetLogger's call limits enforced before sending; answers cached; a 429 on any call stops all
  calls for the back-off.
- Every request names the station using it (callsign in the User-Agent); no anonymous mode. The MCP
  asks once on first use and saves it (`netlogger_set_callsign`); the library requires it.
- Apps built on the library name themselves with ADIF's PROGRAMID and PROGRAMVERSION, which lead
  the User-Agent (`MyLogger/1.0 netlogger-mcp/0.1.0 (KI7MT; +…)`).
- The call budget is shared by every copy for the user account (a locked state file), so two AI apps
  can't double the calls. It never fails open, and a copy that fell back rejoins once the file works.
- Street, ZIP and IP address never returned.
- `NetLoggerSource` usable as a plain Python library.
