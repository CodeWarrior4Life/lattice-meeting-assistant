"""Tests for the tool registry helpers (Sub-C, W3 resolver core).

``ToolRegistry`` = ``Mapping[str, CortexTool]`` mapping registered name to
instance. ``build_registry(tools)`` assembles one from an iterable of
``CortexTool``; duplicate names raise.
"""

from __future__ import annotations

from typing import Mapping

import pytest

from lattice_meeting_assistant.tools.base import CortexTool
from lattice_meeting_assistant.tools.registry import (
    ToolRegistry,
    build_registry,
)


def _make_stub_tool(tool_name: str) -> CortexTool:
    """Build a concrete CortexTool subclass with the given ``name``.

    Uses class attribute (not property) because ``CortexTool.name`` is a
    class attr per the documented contract (spec §4 tool implementation
    pattern: ``name = "..."`` at class scope).
    """

    class _Stub(CortexTool):
        name = tool_name
        description = f"stub tool {tool_name}"

        @property
        def input_schema(self) -> dict[str, object]:
            return {"type": "object", "properties": {}}

        async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
            return {"stub_for": tool_name}

    return _Stub()


def test_build_registry_indexes_by_name() -> None:
    """``build_registry`` returns a mapping from ``tool.name`` -> tool."""
    a = _make_stub_tool("alpha")
    b = _make_stub_tool("beta")
    reg = build_registry([a, b])
    assert isinstance(reg, Mapping)
    assert reg["alpha"] is a
    assert reg["beta"] is b
    assert len(reg) == 2


def test_build_registry_rejects_duplicate_name() -> None:
    """Two tools sharing a ``name`` is a programming error -- raise."""
    a = _make_stub_tool("dup")
    b = _make_stub_tool("dup")
    with pytest.raises(ValueError, match="duplicate"):
        build_registry([a, b])


def test_build_registry_rejects_empty_name() -> None:
    """A tool whose ``name`` is empty/whitespace cannot be registered."""
    bad = _make_stub_tool("")
    with pytest.raises(ValueError, match="name"):
        build_registry([bad])


def test_tool_registry_type_alias_callable() -> None:
    """``ToolRegistry`` is the public mapping-shape alias."""
    a = _make_stub_tool("alpha")
    reg: ToolRegistry = build_registry([a])
    assert reg["alpha"] is a
