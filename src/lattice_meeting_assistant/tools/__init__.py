"""Cortex tool implementations + transport-bound resolver.

This sub-package houses the v0.1 cortex tools the Assistant registers
with :class:`lattice_cortex.AgentSession` plus the resolver that selects
which tools to expose per transport (Architectural Invariant #2).

Sub-C scope (W3.1-W3.5 + resolver core):

* :class:`CortexTool` -- ABC every tool implements
  (see :mod:`lattice_meeting_assistant.tools.base`).
* ``build_tool_spec(tool)`` -- adapter to :class:`lattice_cortex.ToolSpec`.
* ``dispatch_tool_call(call_part, registry)`` -- the
  ``tool_handler`` callable :class:`~lattice_cortex.AgentSession.run`
  accepts.
* In-meeting-dm curated tool set (W3.2-W3.5):

  - :class:`SearchMeetingTranscriptTool`
  - :class:`ReadMeetingTranscriptWindowTool`
  - :class:`SearchPastMeetingsTool`
  - :class:`SearchPublicReferencesTool`
  - :class:`WebSearchTool`

* :func:`resolve_tool_set` -- transport-bound filter; in-meeting-dm
  resolver invokes
  :func:`lattice_meeting_assistant.privacy.invariants.assert_in_meeting_tools_safe`
  on its resolved set per Invariant 2.

Sub-D scope (W3.6 -- this module now exports):

* TG-owner-only Nexus wrappers (W3.6) -- 6 unscoped Nexus
  pass-throughs the TG-owner transport receives in addition to the
  curated 5:

  - :class:`SearchVaultTool`
  - :class:`ReadNoteTool`
  - :class:`SearchReferencesTool`
  - :class:`NxCalendarReadTool`
  - :class:`NxEmailSearchTool`
  - :class:`VaultAskTool`

Sub-D also wires :class:`Assistant.start()` boot self-test (in
:mod:`lattice_meeting_assistant.assistant`), which calls
:func:`resolve_tool_set` for both transports at session-start and
verifies the disjointness contract end-to-end (T8/T9 boundary
backstop).
"""

from __future__ import annotations

from .base import CortexTool, build_tool_spec, dispatch_tool_call
from .past_meetings import SearchPastMeetingsTool
from .public_references import SearchPublicReferencesTool
from .registry import ToolRegistry, build_registry
from .resolver import resolve_tool_set
from .tg_owner_tools import (
    NxCalendarReadTool,
    NxEmailSearchTool,
    ReadNoteTool,
    SearchReferencesTool,
    SearchVaultTool,
    VaultAskTool,
)
from .transcript import ReadMeetingTranscriptWindowTool, SearchMeetingTranscriptTool
from .web_search import WebSearchTool

__all__ = [
    "CortexTool",
    "NxCalendarReadTool",
    "NxEmailSearchTool",
    "ReadMeetingTranscriptWindowTool",
    "ReadNoteTool",
    "SearchMeetingTranscriptTool",
    "SearchPastMeetingsTool",
    "SearchPublicReferencesTool",
    "SearchReferencesTool",
    "SearchVaultTool",
    "ToolRegistry",
    "VaultAskTool",
    "WebSearchTool",
    "build_registry",
    "build_tool_spec",
    "dispatch_tool_call",
    "resolve_tool_set",
]
