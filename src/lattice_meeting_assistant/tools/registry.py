"""Tool registry helpers.

The Assistant builds a per-transport tool registry (via
:func:`resolve_tool_set` in :mod:`.resolver`) and hands the resulting
:class:`ToolRegistry` to :func:`dispatch_tool_call` as the lookup
table when the cortex agent loop emits a :class:`ToolCallPart`.

A registry is a plain ``Mapping[str, CortexTool]`` keyed by
``tool.name``; :func:`build_registry` performs the validation
(duplicate-name rejection, non-empty-name requirement) so consumers
get a clear failure at boot rather than a confusing missing-tool
error mid-conversation.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from .base import CortexTool

#: Public type alias: the lookup table the dispatcher consults to
#: route :class:`ToolCallPart` instances to their handler tool. Kept
#: as ``Mapping`` so callers cannot mutate the live registry.
ToolRegistry = Mapping[str, CortexTool]


def build_registry(tools: Iterable[CortexTool]) -> ToolRegistry:
    """Build a :class:`ToolRegistry` from an iterable of tools.

    Validation:

    * Each tool MUST have a non-empty ``name`` (after stripping
      whitespace).
    * Names MUST be unique across the iterable.

    Both are programming errors that should surface at boot, not at
    invocation. ``ValueError`` is raised with a diagnostic message
    naming the offending tool name.
    """
    registry: dict[str, CortexTool] = {}
    for tool in tools:
        name = tool.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"tool {type(tool).__name__} has empty/non-string name; "
                "set ``name = '...'`` at class scope per CortexTool contract."
            )
        if name in registry:
            raise ValueError(
                f"duplicate tool name {name!r}: each tool name must be "
                f"unique across a resolved registry (got {type(tool).__name__} "
                f"and {type(registry[name]).__name__})."
            )
        registry[name] = tool
    return registry


__all__ = ["ToolRegistry", "build_registry"]
