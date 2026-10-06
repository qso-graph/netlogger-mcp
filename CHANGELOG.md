# Changelog

## [Unreleased]

- PyPI: the Documentation link goes to this package's own page, https://qso-graph.io/servers/netlogger-mcp/ (qso-graph/.github#15).
- CI: the release flow (qso-graph/.github TEMPLATES.md). Work lands on `develop`; a release is a
  PR from `develop` into `main`, and merging it publishes to PyPI and the MCP Registry, verifies both
  and tags the release. CI runs on `develop` too, and PRs into `main` must come from `develop` or a
  `security/` branch.

## 0.1.7 (2026-10-06)

- `scripts/anonymize_samples.py` now also finds callsigns that begin with a digit (`4X4ABC`,
  `2E0ABC`, `3D2AB`, `9A1AA`) or are in lower case, in free-text fields, while leaving a D-STAR
  reflector's `35C`, grid squares, frequencies and `C4FM` alone (#29). Test-tooling only: the
  published package is unchanged, and today's samples regenerate identically.

## 0.1.6 (2026-10-06)

- **Tested against real NetLogger responses** (#15). The bundled samples (mock mode) are now one
  real response per routine, captured within NetLogger's published rates and anonymized by
  `scripts/anonymize_samples.py`: callsigns, names, places and remarks replaced (callsigns with
  N0CALL-style ones), grids cut to 4 characters, street, ZIP and source IP set to test values. The
  earlier synthetic samples move to `tests/fixtures/spec/`, kept for what the real responses didn't
  show (a `<Warning>`, a non-UTC time zone, an unknown element, club member IDs).
- **The parser held up**: no behaviour change was needed. What the real responses showed, now
  pinned by `tests/test_real_responses.py`:
  - the server sends `InactivityTimer` (the spec also spells it `InactivitytTimer`; both are read);
  - past nets list their elements in a different order from the spec (order doesn't matter here);
  - no `<Warning>` in any header;
  - `MemberID` is present but empty on nets that aren't a club's;
  - role markers as sent: `(nc),(log)`, `(m)`, `(c/o)`;
  - free-text frequencies (`all`, `REF 35C`, `7.185.5`, `14. 290`, even a callsign) are kept as sent
    and not read as a frequency;
  - an empty net control, and a closed net's pointer one past its last row.

## 0.1.5 (2026-10-06)

- **Note rows aren't pending rows** (#24). A row with no callsign but text in its member ID or
  remarks is the logger's own note (`# # NET START: 01:00`, `# # FREQUENCY: 7.192`), not a station
  being entered. Notes are returned in `log_notes`, without the leading `# #`, as omiss-mcp already
  does for the omiss.net archive (contract 0.4). Only rows with nothing at all stay in
  `pending_serials`. Neither is counted as a check-in. Found by comparing a live OMISS 40m net with
  its published report.
- **Tool descriptions** (#23): `netlogger_active_nets` says that `total` counts the nets returned
  after `name_like` while `servers` counts every net listed, and states the band rule (a readable
  frequency decides `band_adif`; otherwise the logger's band counts only if it is an ADIF band name,
  so a DMR net has none). `netlogger_checkins` explains `log_notes` and `pending_serials`.

## 0.1.4 (2026-09-29)

From Patton's live run of 0.1.3:

- **Renamed `empty_slots` to `pending_serials`** (contract 0.3). Watson watched the NetLogger program
  during the net: those rows are ones net control has opened and not filled in yet (the callsign is
  typed after), so they're stations being entered, not empty. Always present, `[]` when there are
  none; still not counted as check-ins. Call again to see them filled in.
- Nets gain read values beside NetLogger's free text, each only when it can be read reliably
  (#16): `frequency_mhz`, `band_adif` (ADIF 3.1.7's Band enumeration, shipped unchanged in
  `adif_band.json`), `tone_hz` and `talkgroup`. A readable frequency decides the band, so a GMRS
  net labelled "70cm" gets no amateur band, and "DMR" (a mode) is never a band. The raw `band` and
  `frequency` are unchanged.
- `--help` and `--version` print and exit (the server used to start and wait for a client).
- README: an answer was fetched at `as_of_utc` minus `age_seconds`.

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
