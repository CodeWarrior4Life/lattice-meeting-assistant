"""Tests for ``WebSearchTool`` (W3.5).

Spec §4 line 489:

    web_search(query)
      -> Brain ``deep_research`` (lightweight mode) -- see §9 OQ3

Spec §9 OQ3 default: ``mode='lightweight'`` if Brain supports the
``mode`` param; otherwise fall back to a summary-only prompt prefix
to ``deep_research``. The unscoped ``deep_research`` (full mode) is
in ``BLOCKED_IN_MEETING_TOOLS`` -- this tool is the only path for
in-meeting transports to reach the web.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from lattice_meeting_assistant.brain_client import BrainMCPClient, BrainMCPError
from lattice_meeting_assistant.tools.web_search import WebSearchTool


# ---------------------------------------------------------------------------
# Fake BrainMCPClient
# ---------------------------------------------------------------------------


class _FakeBrain:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.research_calls: list[dict[str, Any]] = []
        self._result = result or {"summary": "stub summary"}
        self.raise_on_research: BrainMCPError | None = None

    async def deep_research(
        self,
        *,
        query: str,
        mode: str = "lightweight",
    ) -> dict[str, Any]:
        if self.raise_on_research is not None:
            raise self.raise_on_research
        self.research_calls.append({"query": query, "mode": mode})
        return self._result


def test_web_search_tool_metadata() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = WebSearchTool(brain_mcp=brain)
    assert tool.name == "web_search"
    assert "web" in tool.description.lower() or "search" in tool.description.lower()
    schema = tool.input_schema
    props = cast(dict[str, Any], schema["properties"])
    assert "query" in props


async def test_web_search_invoke_calls_deep_research_lightweight() -> None:
    """Default invocation must call deep_research with mode='lightweight'."""
    fake = _FakeBrain(
        result={
            "summary": "Quantum entanglement is correlated quantum states.",
            "citations": [{"url": "https://example.com/qe"}],
        }
    )
    brain = cast(BrainMCPClient, fake)
    tool = WebSearchTool(brain_mcp=brain)

    result = await tool.invoke({"query": "quantum entanglement"})

    assert len(fake.research_calls) == 1
    call = fake.research_calls[0]
    assert call["query"] == "quantum entanglement"
    assert call["mode"] == "lightweight"  # Spec §9 OQ3 default.
    assert "summary" in result
    assert "Quantum entanglement" in cast(str, result["summary"])


async def test_web_search_invoke_missing_query_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = WebSearchTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({})


async def test_web_search_invoke_empty_query_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = WebSearchTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({"query": "   "})


async def test_web_search_invoke_ignores_caller_mode_override() -> None:
    """If a model passes mode='full' to escalate, the tool ignores it and
    sends 'lightweight' anyway. Defense in depth on Invariant 2: the full
    ``deep_research`` is BLOCKED for in-meeting transports.
    """
    fake = _FakeBrain()
    brain = cast(BrainMCPClient, fake)
    tool = WebSearchTool(brain_mcp=brain)
    await tool.invoke({"query": "x", "mode": "full"})  # caller tries to escalate
    assert fake.research_calls[0]["mode"] == "lightweight"


async def test_web_search_propagates_brain_error() -> None:
    fake = _FakeBrain()
    fake.raise_on_research = BrainMCPError("HTTP 502", status_code=502)
    brain = cast(BrainMCPClient, fake)
    tool = WebSearchTool(brain_mcp=brain)
    with pytest.raises(BrainMCPError, match="502"):
        await tool.invoke({"query": "anything"})


async def test_web_search_invoke_preserves_citations() -> None:
    """Citations from deep_research flow into the result payload."""
    fake = _FakeBrain(
        result={
            "summary": "stub",
            "citations": [
                {"url": "https://a.example.com", "title": "A"},
                {"url": "https://b.example.com", "title": "B"},
            ],
        }
    )
    brain = cast(BrainMCPClient, fake)
    tool = WebSearchTool(brain_mcp=brain)
    result = await tool.invoke({"query": "x"})
    citations = cast(list[dict[str, Any]], result.get("citations", []))
    assert len(citations) == 2
