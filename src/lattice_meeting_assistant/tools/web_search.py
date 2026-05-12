"""``WebSearchTool`` -- in-meeting curated web/research wrapper.

Spec §4 line 489:

    web_search(query)
      -> Brain ``deep_research`` (lightweight mode) -- see §9 OQ3

This is the ONLY path through which the in-meeting transport reaches
the web. The unscoped ``deep_research`` is in
``BLOCKED_IN_MEETING_TOOLS`` (heavyweight; cost gate; full surface
deferred to v0.2 TG-owner). The lightweight wrapper here forces
``mode='lightweight'`` regardless of caller-supplied overrides.

Per spec §9 OQ3 resolution recommendation:

> Recommend Brain ``deep_research`` with ``mode=lightweight`` if param
> exists; otherwise Tavily direct via httpx.

W3.5 ships the Brain ``deep_research(mode='lightweight')`` path. If
Brain doesn't yet implement the ``mode`` parameter, it returns
results as if full mode were used; we still pass the mode arg
so that when Brain ships the param honoring it, we get the
cost-shedding behavior automatically.
"""

from __future__ import annotations

from typing import Mapping

from ..brain_client import BrainMCPClient
from .base import CortexTool


class WebSearchTool(CortexTool):
    """Web search via Brain ``deep_research`` with mandatory lightweight
    mode.

    Constructor parameters:

    * ``brain_mcp`` -- live :class:`BrainMCPClient`.

    The tool does NOT accept a caller-overridable ``mode`` argument.
    Even if a model passes ``mode='full'`` in arguments, the tool
    sends ``'lightweight'`` to Brain.
    """

    name = "web_search"
    description = (
        "Search the web for content matching the query. Returns a "
        "brief summary and citation URLs. Use when the user asks for "
        "general knowledge outside the meeting context or the curated "
        "references."
    )

    # The lightweight-only constant; the in-meeting transport never gets
    # the full ``deep_research`` mode.
    _MODE_LIGHTWEIGHT: str = "lightweight"

    def __init__(self, *, brain_mcp: BrainMCPClient) -> None:
        self._brain = brain_mcp

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query. The tool runs a lightweight web "
                        "search and returns a brief summary."
                    ),
                },
            },
            "required": ["query"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        query_raw = arguments.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            raise ValueError("web_search: 'query' is required and must be a non-empty string.")

        # Defense in depth: ignore any caller-supplied ``mode`` argument.
        # ``BLOCKED_IN_MEETING_TOOLS`` already excludes the unscoped
        # ``deep_research``; this wrapper pins ``lightweight`` so even
        # a future bug where the full tool leaked through here would not
        # escalate mode. The schema doesn't advertise ``mode`` so well-
        # behaved models won't ask.

        response = await self._brain.deep_research(
            query=query_raw,
            mode=self._MODE_LIGHTWEIGHT,
        )

        summary = response.get("summary", "")
        citations_raw = response.get("citations", [])
        citations: list[dict[str, object]] = []
        for item in citations_raw:
            if not isinstance(item, dict):
                continue
            citations.append(
                {
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                }
            )

        return {
            "summary": summary,
            "citations": citations,
            "query": query_raw,
            "mode": self._MODE_LIGHTWEIGHT,
        }


__all__ = ["WebSearchTool"]
