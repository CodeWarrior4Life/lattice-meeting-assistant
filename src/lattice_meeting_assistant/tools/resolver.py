"""Transport-bound tool resolver -- Architectural Invariant 2 enforcement.

Spec §4 'Resolver' pseudocode:

.. code-block:: python

    def resolve_tool_set(
        transport: AdminTransport,
        profile: AssistantProfile,
        *,
        transcript_buffer: TranscriptBuffer,
        brain_mcp: BrainMCPClient | None,
    ) -> list[CortexTool]:
        if transport.kind == "tg-owner":
            return _resolve_tg_owner_tools(...)
        elif transport.kind == "in-meeting-dm":
            return _resolve_in_meeting_dm_tools(...)
        else:
            raise CapabilityNotSupported(...)

Sub-C scope (this file at W3 close):

* in-meeting-dm path -- complete: 5 curated tools (transcript-search,
  transcript-window, past-meetings, public-references, web-search);
  Brain-backed tools toggle via profile flags; ``brain_mcp=None``
  drops the Brain-backed subset; calls
  :func:`assert_in_meeting_tools_safe` on the resolved name set
  before returning (Invariant 2 backstop on top of explicit
  enumeration).
* tg-owner path -- PARTIAL: returns the 5 curated tools. Sub-D adds
  the 6 TG-only Nexus wrappers (search_vault, read_note,
  search_references, nx_calendar_read, nx_email_search, vault_ask)
  at W3.6.

Sub-D scope (NOT in this file yet):

* TG-owner Nexus wrappers (W3.6).
* ``Assistant.start()`` boot self-test that calls this resolver for
  both transports and verifies the disjointness contract end-to-end
  (W3.7) -- removes the xfail from boundary tests T8/T9 (already
  PASS at W2 close in their contract-level form per the test file).

Signature note: the dispatch description used a simplified
``resolve_tool_set(thread_kind, allow_personal_vault)`` shape; the
actual signature here matches the spec's pseudocode (``thread_kind`` is
the literal transport name -- equivalent to ``transport.kind``;
``profile`` carries the ``allow_personal_vault`` flag plus the per-tool
enable knobs).
"""

from __future__ import annotations

from typing import Literal

from ..brain_client import BrainMCPClient
from ..exceptions import CapabilityNotSupported
from ..privacy.invariants import assert_in_meeting_tools_safe
from ..profile import AssistantProfile
from .base import CortexTool
from .past_meetings import SearchPastMeetingsTool
from .public_references import SearchPublicReferencesTool
from .transcript import ReadMeetingTranscriptWindowTool, SearchMeetingTranscriptTool
from .web_search import WebSearchTool

#: Literal alias for the transport kinds this resolver knows. Mirrors
#: ``lattice_meeting_contracts.AdminTransportKind`` minus the ones we
#: haven't wired (``tg-cohost``, ``slack``, ``local-http`` defer to v0.2).
ThreadKind = Literal["in-meeting-dm", "tg-owner"]


def resolve_tool_set(
    *,
    thread_kind: ThreadKind,
    profile: AssistantProfile,
    transcript_buffer: object,
    brain_mcp: BrainMCPClient | None,
) -> list[CortexTool]:
    """Return the ordered tool list to register for *thread_kind*.

    Per Spec §4 Resolver pseudocode + Architectural Invariant 2.

    Parameters:

    * ``thread_kind`` -- transport identifier; valid values are
      ``"in-meeting-dm"`` and ``"tg-owner"``. Other admin transports
      (``"tg-cohost"``, ``"local-http"``, ``"slack"``) raise
      :class:`CapabilityNotSupported` for v0.1.
    * ``profile`` -- the :class:`AssistantProfile` for the active
      session. The resolver:

      - REJECTS ``profile.knowledge.allow_personal_vault=True`` when
        ``thread_kind == "in-meeting-dm"`` (hard-deny per Invariant 2).
      - Honors per-tool enable flags (``enable_past_meetings_search``,
        ``enable_public_references_tool``, ``enable_web_search``).
    * ``transcript_buffer`` -- the in-process
      ``lattice_meeting_contracts.TranscriptBuffer`` to thread into the
      two transcript tools (always present; ``object`` rather than
      a Protocol bound to keep mypy happy across the import boundary).
    * ``brain_mcp`` -- optional :class:`BrainMCPClient`. ``None`` drops
      the Brain-backed subset (past-meetings, public-references,
      web-search) -- the in-meeting transport degrades to
      transcript-only.

    Raises:

    * :class:`ValueError` if a profile invariant is breached.
    * :class:`CapabilityNotSupported` for unknown ``thread_kind``.

    Returns:

    A list of :class:`CortexTool` instances. Names are guaranteed
    disjoint from ``BLOCKED_IN_MEETING_TOOLS`` when
    ``thread_kind=="in-meeting-dm"`` (asserted via
    :func:`assert_in_meeting_tools_safe`).
    """
    if thread_kind == "in-meeting-dm":
        tools = _resolve_in_meeting_dm_tools(
            profile=profile,
            transcript_buffer=transcript_buffer,
            brain_mcp=brain_mcp,
        )
    elif thread_kind == "tg-owner":
        tools = _resolve_tg_owner_tools(
            profile=profile,
            transcript_buffer=transcript_buffer,
            brain_mcp=brain_mcp,
        )
    else:
        raise CapabilityNotSupported(
            f"resolve_tool_set: thread_kind={thread_kind!r} is not supported in "
            "v0.1. Supported: 'in-meeting-dm', 'tg-owner'. Other admin "
            "transports defer to v0.2."
        )

    # Invariant 2 backstop on top of explicit enumeration. Belt AND
    # suspenders: even if a future bug adds a BLOCKED tool to the
    # in-meeting set, this assert raises before the registry returns.
    if thread_kind == "in-meeting-dm":
        assert_in_meeting_tools_safe(t.name for t in tools)

    return tools


def _resolve_in_meeting_dm_tools(
    *,
    profile: AssistantProfile,
    transcript_buffer: object,
    brain_mcp: BrainMCPClient | None,
) -> list[CortexTool]:
    """Build the curated in-meeting-dm tool list.

    Always-enabled: ``search_meeting_transcript``,
    ``read_meeting_transcript_window`` (the transcript Q6 overlay --
    in-meeting assistant must know what was just said).

    Profile-gated (each respects the corresponding ``enable_*`` flag in
    :class:`KnowledgeAccessConfig`):

    * ``search_past_meetings`` -- ``enable_past_meetings_search``
    * ``search_public_references`` -- ``enable_public_references_tool``
    * ``web_search`` -- ``enable_web_search``

    Hard invariant: ``profile.knowledge.allow_personal_vault`` MUST be
    ``False`` -- the in-meeting transport's anchor on Invariant 2. The
    resolver raises ``ValueError`` if a caller tries to enable it
    (rather than silently overriding to False, which would hide
    misconfiguration).
    """
    knowledge = profile.knowledge
    if knowledge.allow_personal_vault:
        raise ValueError(
            "in-meeting-dm transport: allow_personal_vault=True is a hard "
            "violation of Architectural Invariant 2. Personal vault access "
            "is exclusively available via the TG-owner transport. Profile "
            f"{profile.profile_id!r} attempted to enable it for in-meeting."
        )

    buf = transcript_buffer

    tools: list[CortexTool] = [
        SearchMeetingTranscriptTool(buf),  # always enabled (Q6 overlay)
        ReadMeetingTranscriptWindowTool(buf),  # always enabled
    ]

    if brain_mcp is None:
        # Brain unavailable: degrade gracefully to transcript-only.
        return tools

    if knowledge.enable_past_meetings_search:
        tools.append(
            SearchPastMeetingsTool(
                brain_mcp=brain_mcp,
                default_series_id=profile.series_id,
            )
        )

    if knowledge.enable_public_references_tool:
        tools.append(
            SearchPublicReferencesTool(
                brain_mcp=brain_mcp,
                public_paths=knowledge.public_references,
            )
        )

    if knowledge.enable_web_search:
        tools.append(WebSearchTool(brain_mcp=brain_mcp))

    return tools


def _resolve_tg_owner_tools(
    *,
    profile: AssistantProfile,
    transcript_buffer: object,
    brain_mcp: BrainMCPClient | None,
) -> list[CortexTool]:
    """Build the TG-owner tool list.

    Sub-C ships the curated 5 (same as in-meeting-dm); Sub-D adds the
    6 TG-only Nexus wrappers in W3.6. Note that the in-meeting-dm
    invariant on ``allow_personal_vault`` does NOT apply here -- the
    TG-owner transport is the only place that flag may be True.

    The curated 5 are reused here intentionally: the tg-owner has at
    least the same surface as in-meeting-dm; Sub-D extends it.
    """
    buf = transcript_buffer

    knowledge = profile.knowledge
    tools: list[CortexTool] = [
        SearchMeetingTranscriptTool(buf),
        ReadMeetingTranscriptWindowTool(buf),
    ]

    if brain_mcp is None:
        # Brain unavailable: tg-owner degrades to transcript-only too.
        # Sub-D will add the 6 wrappers which all require brain_mcp.
        return tools

    if knowledge.enable_past_meetings_search:
        tools.append(
            SearchPastMeetingsTool(
                brain_mcp=brain_mcp,
                default_series_id=profile.series_id,
            )
        )

    if knowledge.enable_public_references_tool:
        tools.append(
            SearchPublicReferencesTool(
                brain_mcp=brain_mcp,
                public_paths=knowledge.public_references,
            )
        )

    if knowledge.enable_web_search:
        tools.append(WebSearchTool(brain_mcp=brain_mcp))

    # Sub-D (W3.6): append the 6 TG-owner Nexus wrappers here.

    return tools


__all__ = ["ThreadKind", "resolve_tool_set"]
