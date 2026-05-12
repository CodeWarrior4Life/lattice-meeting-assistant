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

Sub-D scope (NOT in this module yet):

* TG-owner-only Nexus wrappers (W3.6).
* :class:`Assistant.start()` boot self-test wiring (W3.7).
"""

from __future__ import annotations

from .base import CortexTool, build_tool_spec, dispatch_tool_call

__all__ = [
    "CortexTool",
    "build_tool_spec",
    "dispatch_tool_call",
]
