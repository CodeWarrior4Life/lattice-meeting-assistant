"""Tests for the ``CortexTool`` ABC + the tools sub-package surface.

Per Plan task W3.1. Verifies the contract the W3.2-W3.5 concrete tools
will plug into, plus the cortex-compatible :class:`~lattice_cortex.ToolSpec`
adapter shape (W0.2-verified against cortex 0.6.0).
"""

from __future__ import annotations

import pytest
from lattice_cortex import ToolCallPart, ToolResultPart, ToolSpec

from lattice_meeting_assistant.tools import CortexTool
from lattice_meeting_assistant.tools.base import build_tool_spec, dispatch_tool_call


# ---------------------------------------------------------------------------
# CortexTool ABC contract
# ---------------------------------------------------------------------------


def test_cortextool_is_abstract_protocol() -> None:
    """The library's ``CortexTool`` ABC cannot be instantiated directly;
    concrete tools (W3.2-W3.5) implement the contract.
    """

    # Subclassing without overrides raises at instantiation.
    class _NoOverrides(CortexTool):
        pass

    with pytest.raises(TypeError):
        _NoOverrides()  # type: ignore[abstract]


def test_cortextool_subclass_must_define_name_and_description() -> None:
    """A concrete subclass MUST set ``name`` + ``description`` class attrs
    AND implement ``invoke`` + ``input_schema``.
    """

    class _Concrete(CortexTool):
        name = "demo_tool"
        description = "A demo tool that echoes the input."

        @property
        def input_schema(self) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }

        async def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
            return {"echo": arguments.get("query")}

    tool = _Concrete()
    assert tool.name == "demo_tool"
    assert "echoes" in tool.description


async def test_cortextool_invoke_returns_dict() -> None:
    """``invoke()`` is async and returns a JSON-serializable mapping."""

    class _Concrete(CortexTool):
        name = "demo_tool"
        description = "A demo tool."

        @property
        def input_schema(self) -> dict[str, object]:
            return {"type": "object", "properties": {}}

        async def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
            return {"result": "ok"}

    tool = _Concrete()
    result = await tool.invoke({"q": "hello"})
    assert result == {"result": "ok"}


# ---------------------------------------------------------------------------
# build_tool_spec adapter -- emit cortex 0.6.0 ToolSpec
# ---------------------------------------------------------------------------


def test_build_tool_spec_emits_cortex_toolspec() -> None:
    """``build_tool_spec(tool)`` returns a :class:`lattice_cortex.ToolSpec`
    populated from the tool's ``name`` / ``description`` / ``input_schema``.
    Provider adapters consume this directly when serializing tools to
    Anthropic / OpenAI / OpenRouter wire format.
    """

    class _Concrete(CortexTool):
        name = "demo_tool"
        description = "A demo tool."

        @property
        def input_schema(self) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }

        async def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
            return {}

    spec = build_tool_spec(_Concrete())
    assert isinstance(spec, ToolSpec)
    assert spec.name == "demo_tool"
    assert spec.description == "A demo tool."
    assert spec.input_schema["type"] == "object"


# ---------------------------------------------------------------------------
# dispatch_tool_call -- the tool_handler factory for AgentSession.run
# ---------------------------------------------------------------------------


async def test_dispatch_tool_call_returns_tool_result_part() -> None:
    """``dispatch_tool_call`` resolves a ``ToolCallPart`` against a tool
    registry and returns a ``ToolResultPart`` suitable for
    :class:`lattice_cortex.AgentSession`.
    """

    class _Echo(CortexTool):
        name = "echo"
        description = "Echo the query."

        @property
        def input_schema(self) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }

        async def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
            return {"echo": arguments["query"]}

    registry = {"echo": _Echo()}
    call = ToolCallPart(call_id="c1", tool_name="echo", arguments={"query": "hi"})
    result = await dispatch_tool_call(call, registry)
    assert isinstance(result, ToolResultPart)
    assert result.call_id == "c1"
    assert result.is_error is False
    # content is a tuple of Parts -- first should be a TextPart with the
    # JSON-serialized payload.
    assert len(result.content) >= 1


async def test_dispatch_tool_call_unknown_tool_is_error() -> None:
    """Unknown tool name routes to ``is_error=True``."""
    call = ToolCallPart(call_id="c2", tool_name="not_a_tool", arguments={})
    result = await dispatch_tool_call(call, registry={})
    assert isinstance(result, ToolResultPart)
    assert result.is_error is True


async def test_dispatch_tool_call_invoke_exception_is_error() -> None:
    """A tool that raises returns ``is_error=True`` with the message."""

    class _Boom(CortexTool):
        name = "boom"
        description = "Always raises."

        @property
        def input_schema(self) -> dict[str, object]:
            return {"type": "object", "properties": {}}

        async def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("nope")

    call = ToolCallPart(call_id="c3", tool_name="boom", arguments={})
    result = await dispatch_tool_call(call, registry={"boom": _Boom()})
    assert result.is_error is True
