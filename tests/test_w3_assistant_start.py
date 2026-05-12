"""Tests for ``Assistant.start()`` boot self-test (W3.7).

Per Design Spec §4 "Tool resolver self-test (boot-time)" lines 673-681,
``Assistant.start()`` runs 5 steps:

1. Resolve tool sets for both transports.
2. Assert ``BLOCKED_IN_MEETING_TOOLS & in_meeting_set_names == ∅``.
3. Assert ``profile.knowledge.allow_personal_vault == False`` when
   transport is ``in-meeting-dm`` (resolver surfaces this via
   ``ValueError``; the self-test re-asserts).
4. Log resolved tool set names at INFO (no content).
5. If cortex doesn't expose the tool-use registration API the way v0.1
   assumes -> fail-fast with ``CapabilityNotSupported`` + clear message.

W3 ships a minimal :class:`Assistant` shell exposing only the
constructor + ``start()``. The full lifecycle (``on_private_chat``,
``on_public_mention``, ``admin_command``, ``shutdown``) lands at W4.6.
"""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import MagicMock

import pytest

from lattice_meeting_assistant import (
    Assistant,
    AssistantConfig,
    AssistantProfile,
    KnowledgeAccessConfig,
)
from lattice_meeting_assistant.brain_client import BrainMCPClient
from lattice_meeting_assistant.exceptions import CapabilityNotSupported


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    allow_personal_vault: bool = False,
    enable_past_meetings_search: bool = True,
    enable_public_references_tool: bool = True,
    enable_web_search: bool = True,
) -> AssistantProfile:
    knowledge = KnowledgeAccessConfig(
        allow_personal_vault=allow_personal_vault,
        enable_past_meetings_search=enable_past_meetings_search,
        enable_public_references_tool=enable_public_references_tool,
        enable_web_search=enable_web_search,
        public_references=("References/",),
    )
    return AssistantProfile(
        profile_id="test-profile",
        series_id="series-x",
        dm_allowlist=("cyril-grosse",),
        admins=("cyril-grosse",),
        knowledge=knowledge,
    )


def _make_assistant(
    *,
    profile: AssistantProfile | None = None,
    brain_mcp: BrainMCPClient | None = "default",  # type: ignore[assignment]
) -> Assistant:
    """Construct an ``Assistant`` with reasonable test defaults."""
    if profile is None:
        profile = _make_profile()
    brain: BrainMCPClient | None
    if brain_mcp == "default":
        brain = cast(BrainMCPClient, MagicMock(name="FakeBrainMCPClient"))
    else:
        brain = cast("BrainMCPClient | None", brain_mcp)
    return Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=brain,
        config=AssistantConfig(),
        profile=profile,
    )


# ---------------------------------------------------------------------------
# Boot self-test: resolves both transports successfully
# ---------------------------------------------------------------------------


def test_boot_self_test_resolves_both_transports() -> None:
    """``Assistant.start()`` succeeds when configured with a valid
    profile (default ``allow_personal_vault=False``) -- both resolver
    paths run, the in-meeting set passes
    ``assert_in_meeting_tools_safe``, no exception escapes.
    """
    asst = _make_assistant()
    asst.start()  # should not raise

    # Resolved sets are exposed for observability/tests via attributes
    # the constructor stores after start(). Names only (Invariant 4 --
    # we never expose chat content).
    assert isinstance(asst.in_meeting_tool_names, frozenset)
    assert isinstance(asst.tg_owner_tool_names, frozenset)
    assert len(asst.in_meeting_tool_names) == 5
    assert len(asst.tg_owner_tool_names) == 11


def test_boot_self_test_rejects_in_meeting_personal_vault() -> None:
    """A profile with ``allow_personal_vault=True`` MUST cause
    ``Assistant.start()`` to raise ``ValueError`` -- this is the
    transport-bound hard-deny (Invariant 2) bubbling up from the
    resolver into the boot self-test (T9 integration backstop).
    """
    profile = _make_profile(allow_personal_vault=True)
    asst = _make_assistant(profile=profile)
    with pytest.raises(ValueError, match="allow_personal_vault"):
        asst.start()


def test_boot_self_test_in_meeting_tools_disjoint_from_blocked() -> None:
    """The in-meeting tool set MUST be disjoint from
    ``BLOCKED_IN_MEETING_TOOLS`` after ``Assistant.start()`` (T8
    integration backstop).
    """
    from lattice_meeting_assistant.privacy.invariants import BLOCKED_IN_MEETING_TOOLS

    asst = _make_assistant()
    asst.start()

    overlap = asst.in_meeting_tool_names & BLOCKED_IN_MEETING_TOOLS
    assert overlap == frozenset(), (
        f"Invariant 2 breach: in-meeting set overlaps BLOCKED: {sorted(overlap)}"
    )


def test_boot_self_test_tg_owner_count() -> None:
    """TG-owner resolver returns 11 tools (5 curated + 6 wrappers)
    when ``brain_mcp`` is non-None and all profile flags default.
    """
    asst = _make_assistant()
    asst.start()
    assert len(asst.tg_owner_tool_names) == 11
    # Verify the 6 TG-owner-only names are present.
    assert {
        "search_vault",
        "read_note",
        "search_references",
        "nx_calendar_read",
        "nx_email_search",
        "vault_ask",
    } <= asst.tg_owner_tool_names


def test_boot_self_test_in_meeting_count() -> None:
    """in-meeting-dm resolver returns 5 tools when ``brain_mcp`` is
    non-None and all profile flags default.
    """
    asst = _make_assistant()
    asst.start()
    assert asst.in_meeting_tool_names == frozenset(
        {
            "search_meeting_transcript",
            "read_meeting_transcript_window",
            "search_past_meetings",
            "search_public_references",
            "web_search",
        }
    )


# ---------------------------------------------------------------------------
# Boot self-test: cortex tool-use surface probe
# ---------------------------------------------------------------------------


def test_boot_self_test_passes_with_cortex_0_6_0_present() -> None:
    """When ``lattice_cortex`` 0.6.0+ is importable with the expected
    tool-use surface (``AgentSession``, ``ToolSpec``, ``ToolCallPart``,
    ``ToolResultPart``), ``Assistant.start()`` does NOT raise
    ``CapabilityNotSupported``.
    """
    asst = _make_assistant()
    # This must not raise -- cortex is in the venv.
    asst.start()


def test_boot_self_test_raises_capability_not_supported_when_cortex_api_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If cortex's tool-use API surface is unavailable (e.g. older
    cortex without ``ToolSpec``), ``Assistant.start()`` raises
    ``CapabilityNotSupported`` with a clear message (Spec §4 step 5).
    """
    import lattice_meeting_assistant.assistant as assistant_mod

    # Force the capability probe to return False.
    monkeypatch.setattr(assistant_mod, "_cortex_tool_use_available", lambda: False)

    asst = _make_assistant()
    with pytest.raises(CapabilityNotSupported, match="cortex"):
        asst.start()


# ---------------------------------------------------------------------------
# Boot self-test: logging discipline (no content)
# ---------------------------------------------------------------------------


def test_boot_self_test_logs_tool_names_at_info(caplog: pytest.LogCaptureFixture) -> None:
    """Step 4: log resolved tool set names at INFO (no content).
    The log line MUST include the names but NEVER any user/chat content.
    """
    asst = _make_assistant()
    with caplog.at_level(logging.INFO, logger="lattice_meeting_assistant.assistant"):
        asst.start()

    # At least one INFO record about tool resolution.
    records = [r for r in caplog.records if r.levelno == logging.INFO]
    # Some record must mention "tool" + a known tool name.
    relevant = [r for r in records if "tool" in r.getMessage().lower()]
    assert relevant, (
        f"Expected at least one INFO log mentioning tool names; got {[r.getMessage() for r in records]}"
    )
    combined = " ".join(r.getMessage() for r in relevant)
    assert "search_meeting_transcript" in combined or "search_vault" in combined
