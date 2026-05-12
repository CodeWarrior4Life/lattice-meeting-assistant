"""Tests for ``resolve_tool_set`` -- transport-bound tool resolver.

Per Spec §4 Resolver pseudocode + Architectural Invariant 2:

* Default-deny: each transport gets an explicitly enumerated set of
  tools; no automatic inheritance from a parent set.
* in-meeting-dm transport: 5 curated tools (transcript-search,
  transcript-window, past-meetings, public-references, web-search);
  resolver calls ``assert_in_meeting_tools_safe`` on the resolved set
  -- the W2 helper asserts disjointness vs BLOCKED_IN_MEETING_TOOLS.
* tg-owner transport: same 5 curated tools PLUS the 6 TG-owner-only
  Nexus wrappers (Sub-D scope, W3.6). The resolver knows the name
  list but cannot construct instances of the wrappers Sub-D adds; for
  Sub-C scope, the resolver returns the curated 5 plus a placeholder
  pattern that Sub-D fills in. This test only verifies the
  in-meeting-dm path completely.
* ``allow_personal_vault=True`` is REJECTED when ``thread_kind`` is
  ``in-meeting-dm`` -- the transport-bound hard-deny per Invariant 2.

Sub-C scope:

* in-meeting-dm path returns 5 curated tools; passes
  ``assert_in_meeting_tools_safe``.
* ``allow_personal_vault=True`` + in-meeting-dm -> ValueError.
* Unknown transport -> CapabilityNotSupported.

Sub-D will:

* Add the 6 TG-owner wrappers and verify tg-owner-path returns 11 tools.
* Add the ``Assistant.start()`` boot self-test integration (T8/T9
  resolver-side verification).
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from lattice_meeting_assistant.brain_client import BrainMCPClient
from lattice_meeting_assistant.config import KnowledgeAccessConfig
from lattice_meeting_assistant.exceptions import CapabilityNotSupported
from lattice_meeting_assistant.privacy.invariants import BLOCKED_IN_MEETING_TOOLS
from lattice_meeting_assistant.profile import AssistantProfile
from lattice_meeting_assistant.tools.resolver import resolve_tool_set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    allow_personal_vault: bool = False,
    enable_past_meetings_search: bool = True,
    enable_public_references_tool: bool = True,
    enable_web_search: bool = True,
    public_references: tuple[str, ...] = ("References/",),
    series_id: str | None = "default-series",
) -> AssistantProfile:
    """Build an ``AssistantProfile`` for resolver tests."""
    knowledge = KnowledgeAccessConfig(
        allow_personal_vault=allow_personal_vault,
        enable_past_meetings_search=enable_past_meetings_search,
        enable_public_references_tool=enable_public_references_tool,
        enable_web_search=enable_web_search,
        public_references=public_references,
    )
    return AssistantProfile(
        profile_id="test-profile",
        series_id=series_id,
        dm_allowlist=("cyril-grosse",),
        admins=("cyril-grosse",),
        knowledge=knowledge,
    )


def _fake_transcript_buffer() -> object:
    """Return a TranscriptBuffer-shaped fake (we only need the attributes
    the tools store on construction; no method calls happen in resolver)."""
    return MagicMock(name="FakeTranscriptBuffer")


def _fake_brain() -> BrainMCPClient:
    """Return a BrainMCPClient stand-in. The resolver only stores the
    reference on the constructed tools; no method calls."""
    return cast(BrainMCPClient, MagicMock(name="FakeBrainMCPClient"))


# ---------------------------------------------------------------------------
# In-meeting-dm path -- the privacy-critical happy path
# ---------------------------------------------------------------------------


def test_resolve_in_meeting_dm_returns_five_curated_tools() -> None:
    """in-meeting-dm transport: 5 curated tools per Spec §4 line 481-489."""
    profile = _make_profile()
    tools = resolve_tool_set(
        thread_kind="in-meeting-dm",
        profile=profile,
        transcript_buffer=_fake_transcript_buffer(),
        brain_mcp=_fake_brain(),
    )
    names = {t.name for t in tools}
    assert names == {
        "search_meeting_transcript",
        "read_meeting_transcript_window",
        "search_past_meetings",
        "search_public_references",
        "web_search",
    }


def test_resolve_in_meeting_dm_passes_invariant_2_check() -> None:
    """Resolved in-meeting-dm tool names MUST be disjoint from BLOCKED."""
    profile = _make_profile()
    tools = resolve_tool_set(
        thread_kind="in-meeting-dm",
        profile=profile,
        transcript_buffer=_fake_transcript_buffer(),
        brain_mcp=_fake_brain(),
    )
    names = {t.name for t in tools}
    overlap = names & BLOCKED_IN_MEETING_TOOLS
    assert overlap == set(), f"Invariant 2 breach: blocked tools resolved: {overlap}"


def test_resolve_in_meeting_dm_rejects_allow_personal_vault_true() -> None:
    """Profile with ``allow_personal_vault=True`` + in-meeting-dm raises
    ValueError. This is the resolver-level enforcement of Invariant 2's
    hard-deny on personal vault for in-meeting transport. (T9 backing.)
    """
    profile = _make_profile(allow_personal_vault=True)
    with pytest.raises(ValueError, match="allow_personal_vault"):
        resolve_tool_set(
            thread_kind="in-meeting-dm",
            profile=profile,
            transcript_buffer=_fake_transcript_buffer(),
            brain_mcp=_fake_brain(),
        )


def test_resolve_in_meeting_dm_with_brain_none_drops_brain_backed_tools() -> None:
    """``brain_mcp=None`` drops the Brain-backed subset (past-meetings,
    public-references, web-search) and returns the transcript-only
    tools. The two transcript tools are always-enabled."""
    profile = _make_profile()
    tools = resolve_tool_set(
        thread_kind="in-meeting-dm",
        profile=profile,
        transcript_buffer=_fake_transcript_buffer(),
        brain_mcp=None,
    )
    names = {t.name for t in tools}
    assert names == {
        "search_meeting_transcript",
        "read_meeting_transcript_window",
    }


def test_resolve_in_meeting_dm_respects_profile_disable_flags() -> None:
    """Each Brain-backed tool's profile flag toggles its presence."""
    profile = _make_profile(
        enable_past_meetings_search=False,
        enable_public_references_tool=False,
        enable_web_search=False,
    )
    tools = resolve_tool_set(
        thread_kind="in-meeting-dm",
        profile=profile,
        transcript_buffer=_fake_transcript_buffer(),
        brain_mcp=_fake_brain(),
    )
    names = {t.name for t in tools}
    # Only the two always-enabled transcript tools remain.
    assert names == {
        "search_meeting_transcript",
        "read_meeting_transcript_window",
    }


def test_resolve_in_meeting_dm_empty_public_paths_still_registers_tool() -> None:
    """Empty public_references still registers the tool (its invoke
    short-circuits to empty); resolver does NOT hide the tool. This
    keeps the in-meeting tool surface stable across profiles.
    """
    profile = _make_profile(public_references=())
    tools = resolve_tool_set(
        thread_kind="in-meeting-dm",
        profile=profile,
        transcript_buffer=_fake_transcript_buffer(),
        brain_mcp=_fake_brain(),
    )
    names = {t.name for t in tools}
    assert "search_public_references" in names


# ---------------------------------------------------------------------------
# Unknown transport
# ---------------------------------------------------------------------------


def test_resolve_unknown_transport_raises_capability_not_supported() -> None:
    """Default-deny: any transport name we don't know -> raise."""
    profile = _make_profile()
    with pytest.raises(CapabilityNotSupported, match="thread_kind"):
        resolve_tool_set(
            thread_kind="local-http",  # type: ignore[arg-type]
            profile=profile,
            transcript_buffer=_fake_transcript_buffer(),
            brain_mcp=_fake_brain(),
        )


# ---------------------------------------------------------------------------
# tg-owner path: Sub-C returns the 5 curated tools (Sub-D extends to 11)
# ---------------------------------------------------------------------------


def test_resolve_tg_owner_returns_curated_tools_at_minimum() -> None:
    """tg-owner transport MUST include all 5 in-meeting curated tools.
    Sub-D adds the 6 TG-only Nexus wrappers; this test asserts the
    Sub-C-shippable subset is present.
    """
    profile = _make_profile()
    tools = resolve_tool_set(
        thread_kind="tg-owner",
        profile=profile,
        transcript_buffer=_fake_transcript_buffer(),
        brain_mcp=_fake_brain(),
    )
    names = {t.name for t in tools}
    assert {
        "search_meeting_transcript",
        "read_meeting_transcript_window",
        "search_past_meetings",
        "search_public_references",
        "web_search",
    } <= names


def test_resolve_tg_owner_allows_personal_vault_true() -> None:
    """tg-owner transport: allow_personal_vault=True is the only place
    this flag may be True. The resolver does NOT raise here -- the
    hard-deny is in-meeting-dm only.
    """
    profile = _make_profile(allow_personal_vault=True)
    tools = resolve_tool_set(
        thread_kind="tg-owner",
        profile=profile,
        transcript_buffer=_fake_transcript_buffer(),
        brain_mcp=_fake_brain(),
    )
    # No exception. The tool list at minimum contains the curated 5.
    assert len(tools) >= 5
