"""``SearchPastMeetingsTool`` -- in-meeting curated wrapper over Brain
``nx_vault_search`` filtered by series.

Spec §4 in-meeting curated tool set line 487:

    search_past_meetings(query, series_id?, time_range?)
      -> Brain ``nx_vault_search`` filtered by ``series_id`` frontmatter

Series-scoping rationale: in-meeting transport must NOT search the
full personal vault (that's ``search_vault`` which lives in
``BLOCKED_IN_MEETING_TOOLS``). Series-scoping restricts the result
set to notes whose frontmatter declares the same ``series_id`` as
the active meeting -- past instances of the same recurring series
(weekly stand-up, fortnightly architecture review, etc).

The Assistant constructs the tool with ``default_series_id=``
matching the active session's series; the model may override on a
per-invocation basis but only to a series in the same scope (no
across-series escalation -- if an attacker tries to inject a different
series_id, the result is still constrained to vault notes whose
frontmatter matches, and the resolver never grants the unscoped
``search_vault``).
"""

from __future__ import annotations

from typing import Any, Mapping

from ..brain_client import BrainMCPClient
from .base import CortexTool


class SearchPastMeetingsTool(CortexTool):
    """Search past meetings in the same series via Brain
    ``nx_vault_search``.

    Constructor parameters:

    * ``brain_mcp`` -- live :class:`BrainMCPClient` instance; required.
    * ``default_series_id`` -- the active meeting's series id; injected
      into the ``filters`` payload when the caller doesn't pass an
      explicit override. ``None`` disables series-scoping (fall back
      to vault-wide nx_vault_search; the resolver decides whether to
      register this tool at all in that case).
    * ``default_limit`` -- result cap (default 10 matches; bounded to
      keep the LLM context payload sane).
    """

    name = "search_past_meetings"
    description = (
        "Search past meetings in the same series for notes matching the "
        "query. Returns matching meeting notes (titles, dates, snippets). "
        "Use when the user references something from an earlier session "
        "of this series (e.g., 'last time we discussed X')."
    )

    def __init__(
        self,
        *,
        brain_mcp: BrainMCPClient,
        default_series_id: str | None = None,
        default_limit: int = 10,
    ) -> None:
        self._brain = brain_mcp
        self._default_series_id = default_series_id
        self._default_limit = default_limit

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": ("Search terms to match across past meeting notes."),
                },
                "series_id": {
                    "type": "string",
                    "description": (
                        "Optional explicit series id; defaults to the "
                        "currently-active meeting's series."
                    ),
                },
                "time_range": {
                    "type": "string",
                    "description": (
                        "Optional time-range filter (e.g., 'last_30d', "
                        "'last_90d'). Applied as a vault frontmatter filter."
                    ),
                },
            },
            "required": ["query"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        query_raw = arguments.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            raise ValueError(
                "search_past_meetings: 'query' is required and must be a non-empty string."
            )

        # Series scoping: explicit arg > constructor default.
        series_id_arg = arguments.get("series_id")
        series_id: str | None
        if isinstance(series_id_arg, str) and series_id_arg.strip():
            series_id = series_id_arg
        else:
            series_id = self._default_series_id

        time_range_arg = arguments.get("time_range")
        time_range: str | None = time_range_arg if isinstance(time_range_arg, str) else None

        filters: dict[str, Any] = {}
        if series_id is not None:
            filters["series_id"] = series_id
        if time_range is not None:
            filters["time_range"] = time_range

        # Brain's nx_vault_search ignores empty filters dicts; the client
        # forwards either ``None`` or the populated dict.
        response = await self._brain.nx_vault_search(
            query=query_raw,
            filters=filters if filters else None,
            limit=self._default_limit,
        )

        raw_results = response.get("results", [])
        matches: list[dict[str, object]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            matches.append(
                {
                    "path": item.get("path", ""),
                    "snippet": item.get("snippet", ""),
                    "frontmatter": item.get("frontmatter", {}),
                }
            )

        return {
            "matches": matches,
            "total_matches": len(matches),
            "query": query_raw,
            "series_id_used": series_id,
            "time_range_used": time_range,
        }


__all__ = ["SearchPastMeetingsTool"]
