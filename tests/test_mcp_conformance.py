"""Conformance with the Model Context Protocol, revision 2026-07-28.

Nothing in this project's documents required this until 2026-10-11 — not
CLAUDE.md, not .claude/rules/security.md, not MCP-SECURITY-FRAMEWORK.md, not
qso-graph-spec. We documented how to *publish* an MCP server in detail and
never wrote down what makes one *valid*, which is how a missing ``isError`` and
missing annotations reached all 22 servers in the fleet unnoticed.

So these are asserted rather than trusted.

Two things here are unlike the nine servers swept before it:

* **Not every tool reads.** ``netlogger_set_callsign`` writes the operator's
  callsign to a settings file, so its hints differ from the rest — and a
  careless "all tools are read-only" sweep would have published a plain untruth
  about it. ``TestTheOneToolThatWrites`` exists for that.
* **Needing a callsign is not really an error, and is reported as one anyway.**
  It is a refusal the caller can fix in a single step, which is the case the
  specification describes when it says a model must be able to see that an
  error occurred and self-correct. ``TestTheRefusalThatTeaches`` covers it.

There is no ``test_release_gate.py`` here, deliberately. This repo's release
gate installs the package (``pip install -e ".[test]"``), unlike the other nine,
so ``test_security.py`` *may* import ``netlogger_mcp`` and a guard forbidding it
would assert a constraint that does not apply.

Test IDs: NL-C01 onward.
"""

from __future__ import annotations

import asyncio
import os

os.environ["NETLOGGER_MCP_MOCK"] = "1"
os.environ.pop("NETLOGGER_MCP_CALLSIGN", None)

import pytest  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from netlogger_mcp import server, settings  # noqa: E402

ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

READS_NETLOGGER = {
    "netlogger_active_nets",
    "netlogger_checkins",
    "netlogger_past_nets",
    "netlogger_past_checkins",
}
WRITES_LOCALLY = {"netlogger_set_callsign"}
ANSWERS_FROM_THE_PACKAGE = {"get_version_info"}


@pytest.fixture(autouse=True)
def saved_callsign(monkeypatch):
    """Each test starts with no saved callsign and its own settings folder.

    ``conftest.py`` already points ``NETLOGGER_MCP_CONFIG_DIR`` at a per-test
    directory, so the path is *asked for* here rather than assumed — a test
    that wrote to the operator's real settings file would be a defect of its
    own. The module globals are reset because a tool memoises the source,
    limiter and cache, and the callsign is baked into the source.
    """
    monkeypatch.delenv(settings.ENV_CALLSIGN, raising=False)
    server._source = None
    server._limiter = None
    server._cache = None
    yield settings.settings_file()
    server._source = None
    server._limiter = None
    server._cache = None


def _tools() -> dict[str, object]:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def _wire(tool: object) -> dict[str, object]:
    """The serialised annotations, which is what a client reads."""
    annotations = getattr(tool, "annotations", None)
    assert annotations is not None, "tool declares no annotations"
    return annotations.model_dump(by_alias=True, exclude_none=True)


def _call(name: str):
    """The underlying function of a registered tool."""
    tool = getattr(server, name)
    return getattr(tool, "fn", tool)


class TestToolAnnotations:
    def test_every_tool_declares_all_four_hints(self) -> None:
        """NL-C01: the defaults are pessimistic, so silence is the wrong answer."""
        for name, tool in _tools().items():
            wire = _wire(tool)
            for hint in ANNOTATION_HINTS:
                assert hint in wire, f"{name} omits {hint} on the wire; got {sorted(wire)}"

    def test_the_five_that_read_say_so(self) -> None:
        """NL-C02: read-only, non-destructive, idempotent — for the five that read."""
        tools = _tools()
        for name in READS_NETLOGGER | ANSWERS_FROM_THE_PACKAGE:
            wire = _wire(tools[name])
            assert wire["readOnlyHint"] is True, name
            assert wire["destructiveHint"] is False, name
            assert wire["idempotentHint"] is True, name

    def test_open_world_is_read_per_tool(self) -> None:
        """NL-C03: four reach NetLogger; two do not.

        ``netlogger_set_callsign`` writes locally and tells NetLogger nothing
        until the next lookup, so it is not open-world either.
        """
        tools = _tools()
        assert set(tools) == READS_NETLOGGER | WRITES_LOCALLY | ANSWERS_FROM_THE_PACKAGE
        for name in READS_NETLOGGER:
            assert _wire(tools[name])["openWorldHint"] is True, name
        for name in WRITES_LOCALLY | ANSWERS_FROM_THE_PACKAGE:
            assert _wire(tools[name])["openWorldHint"] is False, name


class TestTheOneToolThatWrites:
    """``netlogger_set_callsign`` is the first non-read-only tool in the sweep.

    Nine servers before this one declared every tool read-only, correctly. Had
    the same block been copied here it would have published a plain untruth
    about a tool that writes to the operator's settings file — and the
    specification tells a client it may put a confirmation prompt in front of a
    tool whose hints say it changes something, so the hint has to be right in
    both directions.
    """

    def test_it_does_not_claim_to_be_read_only(self) -> None:
        """NL-C10: the assertion that would have caught a copied block."""
        wire = _wire(_tools()["netlogger_set_callsign"])
        assert wire["readOnlyHint"] is False

    def test_it_is_idempotent_and_not_destructive(self) -> None:
        """NL-C11: it replaces one value the operator set themselves.

        The specification reserves ``destructive`` for updates that destroy;
        this overwrites a single setting with the caller's own new value and
        loses nothing else. Saving the same callsign twice leaves the same
        state, so a client may safely retry.
        """
        wire = _wire(_tools()["netlogger_set_callsign"])
        assert wire["destructiveHint"] is False
        assert wire["idempotentHint"] is True

    def test_it_really_does_write(self, saved_callsign) -> None:
        """NL-C12: the control — ``readOnlyHint: False`` has to be true of it.

        A hint is worth what the code behind it is worth, and this one claims
        the tool changes something on disk.
        """
        _call("netlogger_set_callsign")(callsign="KI7MT")
        assert saved_callsign.exists(), "the tool claims to write and did not"

    def test_a_refused_callsign_writes_nothing(self, saved_callsign) -> None:
        """NL-C13: refusing has to mean the file is untouched, not just a no."""
        with pytest.raises(ToolError):
            _call("netlogger_set_callsign")(callsign="not a call")
        assert not saved_callsign.exists()


class TestTheRefusalThatTeaches:
    """Needing a callsign is a refusal the caller can fix in one step.

    It used to be a *successful* result carrying ``needs_callsign: True`` and a
    ``next_step``, which left the model to notice from the payload that nothing
    had happened. That is precisely what the specification warns about: without
    the flag "the LLM would not be able to see that an error occurred and
    self-correct".
    """

    def test_it_is_flagged(self) -> None:
        """NL-C20: a failure, not an answer."""
        with pytest.raises(ToolError):
            _call("netlogger_active_nets")()

    def test_the_instruction_survives_the_change(self) -> None:
        """NL-C21: and the whole of it, not just "needs a callsign".

        Dropping the structured fields is only acceptable because the message
        still tells the caller exactly what to do. If that stopped being true
        the change would have cost more than it bought.
        """
        with pytest.raises(ToolError) as caught:
            _call("netlogger_active_nets")()
        message = str(caught.value)
        assert "netlogger_set_callsign" in message
        assert "Ask the user" in message

    def test_every_net_tool_refuses_the_same_way(self) -> None:
        """NL-C22: not just the first one anybody tried."""
        for name, kwargs in [
            ("netlogger_active_nets", {}),
            ("netlogger_checkins", {"server_name": "s", "net_name": "n"}),
            ("netlogger_past_nets", {}),
            ("netlogger_past_checkins", {"server_name": "s", "net_name": "n", "net_id": "1"}),
        ]:
            with pytest.raises(ToolError, match="netlogger_set_callsign"):
                _call(name)(**kwargs)


class TestAnAnswerIsNotAnError:
    """The distinction the specification draws."""

    def test_a_normal_lookup_is_a_successful_call(self) -> None:
        """NL-C30: the control, once the callsign is known."""
        _call("netlogger_set_callsign")(callsign="KI7MT")
        answer = _call("netlogger_active_nets")()
        assert isinstance(answer, dict)
        assert "total" in answer

    def test_a_successful_answer_still_carries_its_timestamp(self) -> None:
        """NL-C31: ``as_of_utc`` was on the error payloads too, and is not lost.

        It comes from the source layer, not from the error branches that were
        removed, so a successful answer still says when it was true.
        """
        _call("netlogger_set_callsign")(callsign="KI7MT")
        assert "as_of_utc" in _call("netlogger_active_nets")()


class TestVersionInfoShape:
    def test_it_matches_the_shape_the_fleet_returns(self) -> None:
        """NL-C40: the convention that drifted because nobody asserted it."""
        info = _call("get_version_info")()
        assert info["service_name"] == "netlogger-mcp"
        assert info["service_version"]
        assert info["spec_version"]


class TestRegistration:
    def test_the_six_tools_a_client_sees(self) -> None:
        """NL-C50: calling a function directly is not proof a client can."""
        assert set(_tools()) == READS_NETLOGGER | WRITES_LOCALLY | ANSWERS_FROM_THE_PACKAGE
