"""``SearchPublicReferencesTool`` -- scoped reference search.

Spec §4 line 488:

    search_public_references(query)
      -> Brain ``nx_references_search`` scoped to
         ``profile.knowledge.public_references`` paths

The in-meeting transport exposes a curated reference-search tool whose
search scope is bounded to the profile-declared ``public_references``
tuple. The resolver constructs the tool with those paths baked in;
the tool MUST ignore any caller-supplied ``paths`` override because:

1. The model could be tricked (prompt injection) into requesting a
   personal-vault path expansion.
2. The full ``nx_references_search`` (no path scope) is a TG-owner
   tool (W3.6, Sub-D) -- in-meeting transport never gets the unscoped
   version.

This is defense in depth on top of resolver-level Invariant 2
enforcement. If the profile declares NO ``public_references``, the
tool returns an empty result and does NOT call Brain (no fallback to
unscoped search).
"""

from __future__ import annotations

from typing import Mapping

from ..brain_client import BrainMCPClient
from .base import CortexTool


class SearchPublicReferencesTool(CortexTool):
    """Search a profile-bounded subset of vault reference notes.

    Constructor parameters:

    * ``brain_mcp`` -- live :class:`BrainMCPClient` instance.
    * ``public_paths`` -- tuple of vault path prefixes this tool may
      search; comes from
      :attr:`KnowledgeAccessConfig.public_references` at resolve-time.
      Empty tuple means "no public references configured" -- the tool
      returns empty without calling Brain.
    * ``default_limit`` -- result cap (default 10).
    """

    name = "search_public_references"
    description = (
        "Search a curated set of public reference notes for content "
        "matching the query. Scope is bounded to references the meeting "
        "profile has explicitly opted into; this tool does NOT access "
        "personal vault content. Use for general-knowledge follow-ups "
        "where a vetted reference exists."
    )

    def __init__(
        self,
        *,
        brain_mcp: BrainMCPClient,
        public_paths: tuple[str, ...],
        default_limit: int = 10,
    ) -> None:
        self._brain = brain_mcp
        self._public_paths = tuple(public_paths)
        self._default_limit = default_limit

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search terms to match across the profile-curated public references."
                    ),
                },
            },
            "required": ["query"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        query_raw = arguments.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            raise ValueError(
                "search_public_references: 'query' is required and must be a non-empty string."
            )

        # Defense in depth: ignore ANY caller-supplied ``paths`` override.
        # The profile-bound scope is the sole source of truth (Invariant 2
        # backstop in case a future resolver bug lets a path escape).
        # (The schema doesn't advertise ``paths`` either, so a well-behaved
        # model won't ask; this guard catches prompt-injection attempts.)

        if not self._public_paths:
            return {
                "matches": [],
                "total_matches": 0,
                "note": (
                    "no public_references configured on this profile; "
                    "this tool is effectively disabled."
                ),
            }

        response = await self._brain.nx_references_search(
            query=query_raw,
            paths=self._public_paths,
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
                }
            )

        return {
            "matches": matches,
            "total_matches": len(matches),
            "query": query_raw,
            "scope_paths": list(self._public_paths),
        }


__all__ = ["SearchPublicReferencesTool"]
