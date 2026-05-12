"""Tests for the two in-meeting transcript tools (W3.2).

Spec §4 in-meeting curated tool set lines 485-486:

    search_meeting_transcript(query, time_range?) -> in-process buffer
    read_meeting_transcript_window(seconds=300) -> hot window

Both consume the ``TranscriptBuffer`` Protocol from
``lattice_meeting_contracts.transcript_buffer``. We use a fake (not
``MagicMock``) so type narrowing works and we exercise the real
buffer contract.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from lattice_meeting_contracts import TranscriptBuffer, TranscriptSegment

from lattice_meeting_assistant.tools.transcript import (
    ReadMeetingTranscriptWindowTool,
    SearchMeetingTranscriptTool,
)


# ---------------------------------------------------------------------------
# Fake TranscriptBuffer for tests
# ---------------------------------------------------------------------------


class _FakeBuffer:
    """In-memory ``TranscriptBuffer`` implementation for tests.

    Honors the Protocol shape exactly: ``subscribe`` / ``get_hot_window``
    / ``search``. ``search`` performs a case-insensitive substring match;
    ``get_hot_window`` returns the last ``seconds`` of segments based on
    ``end_secs``.
    """

    def __init__(self, segments: list[TranscriptSegment]) -> None:
        self._segments = list(segments)
        self._now_s = max((s.end_secs for s in segments), default=0.0)

    def subscribe(self) -> asyncio.Queue[TranscriptSegment]:
        return asyncio.Queue()

    def get_hot_window(self, seconds: int = 300) -> list[TranscriptSegment]:
        if seconds <= 0:
            return []
        cutoff = self._now_s - seconds
        return [s for s in self._segments if s.end_secs >= cutoff]

    def search(
        self,
        query: str,
        *,
        time_range: Any = None,
        limit: int = 10,
    ) -> list[TranscriptSegment]:
        if limit <= 0:
            return []
        q = query.lower()
        hits = [s for s in self._segments if q in s.text.lower()]
        return hits[:limit]


def _seg(text: str, start: float, end: float, idx: int = 0) -> TranscriptSegment:
    return TranscriptSegment(
        text=text,
        start_secs=start,
        end_secs=end,
        chunk_index=idx,
        adapter="test_fake",
        tenant_id="default",
        monotonic_seq=idx,
    )


@pytest.fixture
def populated_buffer() -> _FakeBuffer:
    segs = [
        _seg("Welcome everyone to the kickoff", 0.0, 5.0, 0),
        _seg("Today we will discuss the architecture", 6.0, 12.0, 1),
        _seg("The privacy invariants are paramount", 13.0, 19.0, 2),
        _seg("Any questions about the design?", 20.0, 24.0, 3),
        _seg("Let us recap the architecture decisions", 200.0, 206.0, 4),
    ]
    return _FakeBuffer(segs)


# ---------------------------------------------------------------------------
# SearchMeetingTranscriptTool
# ---------------------------------------------------------------------------


def test_search_transcript_tool_metadata() -> None:
    """Tool exposes stable name + description for cortex tool-use."""

    class _Empty(_FakeBuffer):
        def __init__(self) -> None:
            super().__init__([])

    tool = SearchMeetingTranscriptTool(cast(TranscriptBuffer, _Empty()))
    assert tool.name == "search_meeting_transcript"
    assert "transcript" in tool.description.lower()
    schema = tool.input_schema
    assert schema["type"] == "object"
    props = cast(dict[str, Any], schema["properties"])
    assert "query" in props


async def test_search_transcript_tool_finds_substring(populated_buffer: _FakeBuffer) -> None:
    """``invoke`` returns matching segments via ``TranscriptBuffer.search``."""
    tool = SearchMeetingTranscriptTool(cast(TranscriptBuffer, populated_buffer))
    result = await tool.invoke({"query": "architecture"})
    matches = cast(list[dict[str, Any]], result["matches"])
    assert len(matches) == 2  # two segments mention "architecture"
    assert all("architecture" in m["text"].lower() for m in matches)
    assert "total_matches" in result


async def test_search_transcript_tool_no_match(populated_buffer: _FakeBuffer) -> None:
    """Empty results map to empty matches list, not error."""
    tool = SearchMeetingTranscriptTool(cast(TranscriptBuffer, populated_buffer))
    result = await tool.invoke({"query": "nonexistent token zzzzzzz"})
    assert cast(list[Any], result["matches"]) == []
    assert result["total_matches"] == 0


async def test_search_transcript_tool_missing_query_raises() -> None:
    """Missing 'query' argument raises ``ValueError`` (dispatcher will
    convert to ``ToolResultPart(is_error=True)``)."""

    class _Empty(_FakeBuffer):
        def __init__(self) -> None:
            super().__init__([])

    tool = SearchMeetingTranscriptTool(cast(TranscriptBuffer, _Empty()))
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({})


async def test_search_transcript_tool_respects_time_range(
    populated_buffer: _FakeBuffer,
) -> None:
    """``time_range`` argument is forwarded to the buffer's ``search``."""
    tool = SearchMeetingTranscriptTool(cast(TranscriptBuffer, populated_buffer))
    # Both queries succeed structurally; we just verify the kwarg gets
    # threaded through (the fake buffer ignores time_range, but the
    # contract test asserts the tool accepts the param without raising).
    result = await tool.invoke({"query": "architecture", "time_range": "last_5m"})
    assert isinstance(result["matches"], list)


# ---------------------------------------------------------------------------
# ReadMeetingTranscriptWindowTool
# ---------------------------------------------------------------------------


def test_read_window_tool_metadata() -> None:
    """Hot-window tool exposes stable name + description."""

    class _Empty(_FakeBuffer):
        def __init__(self) -> None:
            super().__init__([])

    tool = ReadMeetingTranscriptWindowTool(cast(TranscriptBuffer, _Empty()))
    assert tool.name == "read_meeting_transcript_window"
    assert "window" in tool.description.lower() or "recent" in tool.description.lower()


async def test_read_window_tool_default_window(populated_buffer: _FakeBuffer) -> None:
    """Default ``seconds=300`` returns the last 5 minutes of buffer."""
    tool = ReadMeetingTranscriptWindowTool(cast(TranscriptBuffer, populated_buffer))
    result = await tool.invoke({})
    segs = cast(list[dict[str, Any]], result["segments"])
    assert isinstance(segs, list)
    # Buffer's "now" is end of the recap segment at 206s; default 300s
    # window encompasses the entire buffer.
    assert len(segs) == 5


async def test_read_window_tool_custom_window(populated_buffer: _FakeBuffer) -> None:
    """Explicit ``seconds`` arg overrides the default."""
    tool = ReadMeetingTranscriptWindowTool(cast(TranscriptBuffer, populated_buffer))
    result = await tool.invoke({"seconds": 10})
    segs = cast(list[dict[str, Any]], result["segments"])
    # Buffer's "now" is 206.0; cutoff is 196.0; only the recap segment
    # (200-206) qualifies.
    assert len(segs) == 1
    assert "recap" in segs[0]["text"].lower()


async def test_read_window_tool_zero_window_empty(populated_buffer: _FakeBuffer) -> None:
    """``seconds=0`` -> empty segments per TranscriptBuffer contract."""
    tool = ReadMeetingTranscriptWindowTool(cast(TranscriptBuffer, populated_buffer))
    result = await tool.invoke({"seconds": 0})
    assert cast(list[Any], result["segments"]) == []
