# Changelog

## Unreleased

**Upgrading:** a tool that fails now returns `isError: true` instead of a successful result whose
payload carried an `error` key. Anything reading `result["error"]` should read the error flag.

**The one that will be noticed:** needing a callsign used to be a *successful* result carrying
`needs_callsign: true` and a `next_step`. It is now a flagged error whose message is the whole of
that instruction. A caller that read `needs_callsign` should instead read the error flag; the text
still says exactly what to do and names `netlogger_set_callsign`.

- **Tool errors are flagged `isError`** (#46). Five error returns in `src/` arrived on the wire as
  successful results, so a client could not tell "the tool answered" from "the tool refused". The
  specification says of `CallToolResult.isError` that otherwise "the LLM would not be able to see
  that an error occurred and self-correct" — we were relying on the model reading the word *error*
  in prose where the protocol has a flag. They now raise `ToolError`, which FastMCP flags with the
  message intact.
- The catch-all branch deliberately does **not** pass `str(e)` through. It exists for what was not
  foreseen, and an unforeseen exception's text is not known to be safe to show; the three branches
  above it carry the messages that were written to be read.
- **Every tool declares all four annotation hints** (#46). Omitting them is not neutral: the
  defaults advertise a tool as `destructiveHint: true`, `idempotentHint: false` and
  `openWorldHint: true`, and the specification tells a client it may keep a human in the loop for
  an operation like that. So six read-only-looking tools were published as potentially destructive.
- **`netlogger_set_callsign` is `readOnlyHint: false`, and that is the point.** Issue #46 says
  "every tool in this repo is read-only" and that is not so — this one writes the operator's
  callsign to a settings file. It is the first tool in this fleet sweep that is not read-only, and
  copying the block the other nine servers use would have published a plain untruth about it. It is
  `destructiveHint: false` (it replaces one value the operator set themselves, and loses nothing
  else) and `idempotentHint: true` (saving the same callsign twice leaves the same state), so a
  client may safely retry it. `openWorldHint: false`: it writes locally and tells NetLogger nothing
  until the next lookup.
- `get_version_info` is `openWorldHint: false` — it reports versions carried in the wheel and opens
  no connection. The four NetLogger lookups are `true`.
- **`tests/test_mcp_conformance.py` asserts all of it**, through a real `fastmcp.Client` where the
  claim is about the wire. Each check was falsified once — the check removed, the suite watched to
  fail — including the two that matter most here: a `netlogger_set_callsign` that claims to be
  read-only, and a refusal that keeps the flag but loses the instruction. `get_version_info` drifted
  across this fleet precisely because it was a convention nobody asserted.
- Two controls back the write hints with behaviour rather than trust: the tool really does write a
  settings file, and a **refused** callsign leaves no file behind.
- `as_of_utc` was on the error payloads as well as the successful ones. It is unchanged for a
  successful answer, which gets it from the source layer, and a test says so.
- **`certifi` is carried, and the fetch verifies against it** (#44, qso-graph-devel#73). The one
  `urlopen` in `netlogger.py` passed no context, so it trusted whichever root store the running
  Python was built against. On macOS that is `/etc/ssl/cert.pem`, a deliberately *reduced*
  OpenSSL-compatibility file: current, not stale, but it omits roots the OS itself trusts, so a
  certificate chaining to one of them fails for Python while `curl` to the same URL succeeds.
- **Measured, not assumed:** `www.netlogger.org` chains through Let's Encrypt's `YR1` to ISRG
  `Root YR`, and verifies against Apple's file and against `certifi` alike today. So this was
  latent rather than an outage. What it buys is that the root set is now a dependency this project
  updates, rather than a file the operating system hands us — and the same one `requests` and
  `httpx` would have used had this fleet not been written against stdlib `urllib`.
- `certifi` holds *fewer* roots than Apple's file (121 against 128), so the point is not a bigger
  set. It is the right set, chosen by Mozilla's root program.
- This server holds no credential — a callsign is public — so a trust failure costs an answer
  rather than a secret. But it would cost it invisibly: the user is told only that NetLogger
  couldn't be reached, with nothing pointing at trust. Verification is never disabled;
  `ssl.CERT_NONE` would make a call "work" by accepting any certificate from anyone, which is a
  worse defect than this one and a silent one.
- **`certifi` is declared in `[project] dependencies`, and a test says so.** Measured: it is *not*
  a transitive dependency of `fastmcp>=4.0,<5` + `defusedxml` — that pair resolves 85 packages and
  `certifi` is not among them. An undeclared import here would be an ImportError at startup for
  anyone who ran `pip install netlogger-mcp`, so this is a hard failure rather than a latent one.
- Four static checks in `tests/test_security.py` (verification never disabled, the root set carried
  not borrowed, `certifi` declared, every outbound call verifying) and one behavioural check in
  `tests/test_netlogger.py` that watches the context arrive at `urlopen` and asks what it will do.
  The behavioural one exists because a grep cannot tell a verifying context from one built with
  verification switched off — falsified exactly that way, and it caught it.
- `test_every_outbound_call_verifies` scans the whole package line by line, not one file: there is
  one fetch here today, and a check written against the file you happen to be editing is a check
  that misses the second one. Falsified by adding a second fetch path with no context.

## 0.1.10 (2026-10-11)

- **ruff and mypy run in CI** (qso-graph-devel#66), as a job the `ci-all-green` gate requires.
  Settings follow `adif-mcp`, the reference for every qso-graph Python repo, rather than a style of
  this repo's own. They run once rather than per Python version: both read the source, and neither
  answer changes with the interpreter.
- The inter-process file lock tests `sys.platform` rather than `os.name`. Both are true on
  Windows, but only the first narrows for a type checker, so the Windows branch was being read
  against a POSIX stdlib with no `msvcrt` in it.
- The shared limiter and cache files name what their dicts and lists hold, `_run` types its
  `*args`, and a loop variable that shadowed the note read out of the same check-in record is
  renamed. Four test lines carry one statement each.
- `E501` is deferred rather than adopted (qso-graph-devel#70): what it reports in these repos are
  widths, not defects, and some lines are long because they name a publisher's field exactly.
- `mcp.run` is given the literal fastmcp asks for rather than a `str` that happens to hold the
  right word.
- **`fastmcp` is bounded: `>=4.0,<5`** (qso-graph-devel#60). It was `>=3.0` with no upper bound, and
  these servers are run with `uvx`, which resolves fresh — so a `fastmcp` 5.0 would have reached
  every user automatically, before anything here had been run against it. The floor rises to 4.0
  because that is what is actually tested: every lock in the fleet held a 4.x, and nothing in CI
  has ever exercised 3.x. A claim of 3.x support that no test backs is not support.
- `fastmcp` is locked at 4.1.0, the current release, so CI runs against what a new install gets.
- **The published contact is `maintainers@qso-graph.io`** (qso-graph-devel#69). The `authors` field
  carried a personal address, and that field is what PyPI shows on the package page. Everything in
  qso-graph is open source and open to contribution, so the contact is the project's.
- The README's User-Agent example named 0.1.0 while the package was 0.1.9. The version in it is
  read from the installed package, so the example says so rather than freezing a number that
  drifts every release.

## 0.1.9 (2026-10-07)

- LICENSE: the full GPL-3.0 text. The file held only its opening and a link, so GitHub detected no licence.

## 0.1.8 (2026-10-06)

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
