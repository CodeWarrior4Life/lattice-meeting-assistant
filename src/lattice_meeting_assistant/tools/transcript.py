"""In-meeting transcript tools.

Two tools backed by the in-process :class:`~lattice_meeting_contracts.TranscriptBuffer`:

* :class:`SearchMeetingTranscriptTool` -- substring/keyword search over
  everything said so far in the current meeting.
* :class:`ReadMeetingTranscriptWindowTool` -- read a recent time-window
  of segments (default 300s) for context.

These tools are ALWAYS enabled for the in-meeting-dm transport (the
hard invariant per spec §4: a meeting assistant must know what was just
said). They do NOT touch personal vault, email, calendar, or contacts;
their data plane is bounded to the current meeting's transcript buffer
owned by the adapter (meetbot, future Meet/Teams).
"""

from __future__ import annotations

from typing import Any, Mapping

from lattice_meeting_contracts import TranscriptBuffer

from .base import CortexTool


class SearchMeetingTranscriptTool(CortexTool):
    """Search the current meeting's transcript for matching utterances.

    Backed by :meth:`TranscriptBuffer.search`. v0.1 uses substring/
    keyword matching (case-insensitive) per the contract; embedding-
    based retrieval defers to v0.2.

    Per spec §4 tool implementation pattern; this is one of the five
    in-meeting-dm curated tools and is always enabled (Q6 overlay).
    """

    name = "search_meeting_transcript"
    description = (
        "Search the current meeting's transcript (everything said so far) "
        "for content matching the query. Returns matching utterances with "
        "timestamps. Use when the user asks about something said earlier "
        "in this meeting."
    )

    def __init__(self, transcript_buffer: TranscriptBuffer) -> None:
        self._buf = transcript_buffer

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms to match (case-insensitive substring).",
                },
                "time_range": {
                    "type": "string",
                    "description": (
                        "Optional time-range filter: 'all', 'last_5m', 'last_15m'. Default 'all'."
                    ),
                    "enum": ["all", "last_5m", "last_15m"],
                },
            },
            "required": ["query"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(
                "search_meeting_transcript: 'query' is required and must be a non-empty string."
            )
        time_range_raw = arguments.get("time_range")
        time_range: str | None = time_range_raw if isinstance(time_range_raw, str) else None

        segments = self._buf.search(query, time_range=time_range)
        matches = [
            {
                "text": seg.text,
                "start_secs": seg.start_secs,
                "end_secs": seg.end_secs,
                "chunk_index": seg.chunk_index,
                "monotonic_seq": seg.monotonic_seq,
            }
            for seg in segments[:10]
        ]
        return {
            "matches": matches,
            "total_matches": len(segments),
            "query": query,
        }


class ReadMeetingTranscriptWindowTool(CortexTool):
    """Read the recent N-second window of the current meeting's transcript.

    Backed by :meth:`TranscriptBuffer.get_hot_window`. The default window
    is 300 seconds (5 minutes), matching the hot-window injected into
    the in-meeting-DM system prompt per spec §4 'Hot-window injection'.

    The model can call this directly when the user explicitly asks
    'what was just said?' or 'recap the last few minutes'.
    """

    name = "read_meeting_transcript_window"
    description = (
        "Read the recent transcript window from the current meeting "
        "(default last 5 minutes). Returns segments in chronological "
        "order. Use when the user asks what was recently said or wants "
        "a recap of the last few minutes."
    )

    DEFAULT_WINDOW_SECONDS: int = 300

    def __init__(
        self,
        transcript_buffer: TranscriptBuffer,
        *,
        default_window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self._buf = transcript_buffer
        self._default_window = default_window_seconds

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": (
                        f"Window length in seconds (default {self._default_window}). "
                        "Returns empty list if <= 0."
                    ),
                    "minimum": 0,
                },
            },
            "required": [],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        raw_seconds: Any = arguments.get("seconds", self._default_window)
        try:
            seconds = int(raw_seconds)
        except (TypeError, ValueError):
            raise ValueError(
                f"read_meeting_transcript_window: 'seconds' must be int; got "
                f"{type(raw_seconds).__name__}={raw_seconds!r}"
            )

        segments = self._buf.get_hot_window(seconds)
        out_segments = [
            {
                "text": seg.text,
                "start_secs": seg.start_secs,
                "end_secs": seg.end_secs,
                "chunk_index": seg.chunk_index,
                "monotonic_seq": seg.monotonic_seq,
            }
            for seg in segments
        ]
        return {
            "segments": out_segments,
            "window_seconds": seconds,
            "segment_count": len(out_segments),
        }


__all__ = [
    "ReadMeetingTranscriptWindowTool",
    "SearchMeetingTranscriptTool",
]
