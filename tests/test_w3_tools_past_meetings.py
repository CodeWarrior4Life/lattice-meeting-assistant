"""Tests for ``SearchPastMeetingsTool`` (W3.3).

Spec §4 in-meeting curated tool set line 487:

    search_past_meetings(query, series_id?, time_range?)
      -> Brain ``nx_vault_search`` filtered by ``series_id`` frontmatter

The tool wraps :class:`BrainMCPClient` and applies a series-scope
filter when configured, so the in-meeting transport's past-meetings
queries stay within the active series rather than the full vault.

Visibility-tag fail-closed (Invariant 4) does NOT apply here because
this tool is read-only against vault notes that the adapter already
filtered for in-meeting safety; the resolver (W3.7, Sub-D) is what
gates which transports may register this tool at all.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from lattice_meeting_assistant.brain_client import BrainMCPClient, BrainMCPError
from lattice_meeting_assistant.tools.past_meetings import SearchPastMeetingsTool


# ---------------------------------------------------------------------------
# Fake BrainMCPClient for tests -- avoids real httpx wiring.
# ---------------------------------------------------------------------------


class _FakeBrain:
    """Captures the kwargs each Brain method receives + returns canned payloads."""

    def __init__(self, vault_search_result: dict[str, Any] | None = None) -> None:
        self.vault_search_calls: list[dict[str, Any]] = []
        self._vault_search_result = vault_search_result or {"results": []}
        self.raise_on_search: BrainMCPError | None = None

    async def nx_vault_search(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if self.raise_on_search is not None:
            raise self.raise_on_search
        self.vault_search_calls.append({"query": query, "filters": filters, "limit": limit})
        return self._vault_search_result


def test_past_meetings_tool_metadata() -> None:
    """Tool exposes stable name + description for cortex tool-use."""
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchPastMeetingsTool(brain_mcp=brain)
    assert tool.name == "search_past_meetings"
    assert "past" in tool.description.lower() or "previous" in tool.description.lower()
    schema = tool.input_schema
    props = cast(dict[str, Any], schema["properties"])
    assert "query" in props
    # series_id is optional; the tool may also accept it but the
    # in-meeting consumer typically passes the active series_id as
    # constructor-bound default.
    assert "required" in schema


async def test_past_meetings_invoke_passes_query_to_vault_search() -> None:
    """``invoke`` forwards the query to ``BrainMCPClient.nx_vault_search``."""
    fake = _FakeBrain(
        vault_search_result={
            "results": [
                {
                    "path": "02_Projects/Lattice/Meetings/2026-04-12.md",
                    "snippet": "Discussed architecture",
                    "frontmatter": {"series_id": "lattice-arch"},
                },
            ]
        }
    )
    brain = cast(BrainMCPClient, fake)
    tool = SearchPastMeetingsTool(brain_mcp=brain, default_series_id="lattice-arch")

    result = await tool.invoke({"query": "architecture"})

    assert len(fake.vault_search_calls) == 1
    call = fake.vault_search_calls[0]
    assert call["query"] == "architecture"
    # series_id should land in filters per series-scoping semantics.
    assert call["filters"] is not None
    assert call["filters"].get("series_id") == "lattice-arch"

    matches = cast(list[dict[str, Any]], result["matches"])
    assert len(matches) == 1
    assert "2026-04-12" in matches[0]["path"]


async def test_past_meetings_invoke_without_default_series() -> None:
    """If no default series + no series_id arg, filters omit series."""
    fake = _FakeBrain()
    brain = cast(BrainMCPClient, fake)
    tool = SearchPastMeetingsTool(brain_mcp=brain, default_series_id=None)
    await tool.invoke({"query": "kickoff"})

    call = fake.vault_search_calls[0]
    # No series filter => either no filters key or filters without series_id.
    if call["filters"] is not None:
        assert "series_id" not in call["filters"]


async def test_past_meetings_invoke_caller_series_overrides_default() -> None:
    """Explicit ``series_id`` argument overrides the constructor default."""
    fake = _FakeBrain()
    brain = cast(BrainMCPClient, fake)
    tool = SearchPastMeetingsTool(brain_mcp=brain, default_series_id="default-series")
    await tool.invoke({"query": "x", "series_id": "different-series"})

    call = fake.vault_search_calls[0]
    assert call["filters"]["series_id"] == "different-series"


async def test_past_meetings_invoke_requires_query() -> None:
    """Missing query -> ValueError (dispatcher converts to is_error)."""
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchPastMeetingsTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({})


async def test_past_meetings_propagates_brain_error() -> None:
    """Brain HTTP error propagates as BrainMCPError (dispatcher wraps)."""
    fake = _FakeBrain()
    fake.raise_on_search = BrainMCPError("HTTP 403", status_code=403)
    brain = cast(BrainMCPClient, fake)
    tool = SearchPastMeetingsTool(brain_mcp=brain)
    with pytest.raises(BrainMCPError, match="403"):
        await tool.invoke({"query": "x"})


async def test_past_meetings_invoke_respects_time_range_param() -> None:
    """Optional ``time_range`` param threaded into the query payload."""
    fake = _FakeBrain()
    brain = cast(BrainMCPClient, fake)
    tool = SearchPastMeetingsTool(brain_mcp=brain, default_series_id="s1")
    await tool.invoke({"query": "design", "time_range": "last_30d"})

    call = fake.vault_search_calls[0]
    # time_range may surface as a filter or be embedded in the query string;
    # we accept either as long as it lands in the call.
    payload_text = repr(call)
    assert "last_30d" in payload_text or "30d" in payload_text
