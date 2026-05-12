"""TG-owner-only Nexus tool wrappers (W3.6, Sub-D).

Spec §4 enumerates 6 unscoped Nexus wrappers exposed exclusively via
the TG-owner transport. The resolver in :mod:`.resolver`
``_resolve_tg_owner_tools`` appends instances of these classes; the
in-meeting-dm transport NEVER receives them per
``BLOCKED_IN_MEETING_TOOLS`` + Architectural Invariant #2.

All 6 are thin pass-throughs over :class:`BrainMCPClient`:

* :class:`SearchVaultTool` (``search_vault``) -- unscoped personal-vault
  search. Distinct from the in-meeting ``SearchPastMeetingsTool`` which
  filters by ``series_id`` frontmatter.
* :class:`ReadNoteTool` (``read_note``) -- read a single vault note by
  path.
* :class:`SearchReferencesTool` (``search_references``) -- unscoped
  references search (no profile path scope). Distinct from the
  in-meeting ``SearchPublicReferencesTool`` which restricts the
  ``paths`` filter to the profile's curated allowlist.
* :class:`NxCalendarReadTool` (``nx_calendar_read``) -- read calendar
  events (optional ``time_range`` + ``attendee`` filters).
* :class:`NxEmailSearchTool` (``nx_email_search``) -- search emails.
* :class:`VaultAskTool` (``vault_ask``) -- natural-language Q&A over
  the vault (Brain's RAG-shaped tool).

Per spec §4 "Tool implementation pattern" each tool validates required
inputs and raises :class:`ValueError` for missing/empty strings; the
dispatcher wraps the raise as ``ToolResultPart(is_error=True)`` so a
single misbehaving call does not abort the agent loop.
"""

from __future__ import annotations

from typing import Mapping

from ..brain_client import BrainMCPClient
from .base import CortexTool


# ---------------------------------------------------------------------------
# SearchVaultTool
# ---------------------------------------------------------------------------


class SearchVaultTool(CortexTool):
    """Unscoped personal-vault search via Brain ``nx_vault_search``.

    Reuses :meth:`BrainMCPClient.nx_vault_search` but does NOT apply a
    ``series_id`` filter -- this is the full-vault surface that lives
    in :data:`BLOCKED_IN_MEETING_TOOLS`, intentionally TG-owner-only.
    """

    name = "search_vault"
    description = (
        "Search the personal vault (unscoped) for notes matching the query. "
        "Returns matching paths + snippets. Use for general lookups across "
        "all vault content (not series-scoped)."
    )

    def __init__(self, *, brain_mcp: BrainMCPClient, default_limit: int = 10) -> None:
        self._brain = brain_mcp
        self._default_limit = default_limit

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms to match across all vault notes.",
                },
            },
            "required": ["query"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        query_raw = arguments.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            raise ValueError("search_vault: 'query' is required and must be a non-empty string.")

        response = await self._brain.nx_vault_search(
            query=query_raw,
            filters=None,  # unscoped per TG-owner contract
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
        }


# ---------------------------------------------------------------------------
# ReadNoteTool
# ---------------------------------------------------------------------------


class ReadNoteTool(CortexTool):
    """Read a single vault note by path via Brain ``nx_read_note``."""

    name = "read_note"
    description = (
        "Read a single vault note by its path. Returns the note content "
        "and frontmatter. Use when a prior search surfaced a path and "
        "you need the full content."
    )

    def __init__(self, *, brain_mcp: BrainMCPClient) -> None:
        self._brain = brain_mcp

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Vault-relative path of the note to read.",
                },
            },
            "required": ["path"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        path_raw = arguments.get("path")
        if not isinstance(path_raw, str) or not path_raw.strip():
            raise ValueError("read_note: 'path' is required and must be a non-empty string.")

        response = await self._brain.nx_read_note(path=path_raw)

        return {
            "path": response.get("path", path_raw),
            "content": response.get("content", ""),
            "frontmatter": response.get("frontmatter", {}),
        }


# ---------------------------------------------------------------------------
# SearchReferencesTool (unscoped variant)
# ---------------------------------------------------------------------------


class SearchReferencesTool(CortexTool):
    """Unscoped references search via Brain ``nx_references_search``.

    Distinct from :class:`SearchPublicReferencesTool` -- the in-meeting
    variant which restricts the ``paths`` filter to the profile's
    curated allowlist. This unscoped version is TG-owner-only because
    the unrestricted reference surface may expose paths the in-meeting
    transport should not see.
    """

    name = "search_references"
    description = (
        "Search across all reference notes in the vault (unscoped). "
        "Returns matching paths + snippets. Use for general-knowledge "
        "lookups against the vault's reference corpus."
    )

    def __init__(self, *, brain_mcp: BrainMCPClient, default_limit: int = 10) -> None:
        self._brain = brain_mcp
        self._default_limit = default_limit

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms to match across all reference notes.",
                },
            },
            "required": ["query"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        query_raw = arguments.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            raise ValueError(
                "search_references: 'query' is required and must be a non-empty string."
            )

        response = await self._brain.nx_references_search(
            query=query_raw,
            paths=None,  # unscoped per TG-owner contract
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
        }


# ---------------------------------------------------------------------------
# NxCalendarReadTool
# ---------------------------------------------------------------------------


class NxCalendarReadTool(CortexTool):
    """Read calendar events via Brain ``nx_calendar_read``."""

    name = "nx_calendar_read"
    description = (
        "Read calendar events for the active owner's calendar. "
        "Optional filters: 'time_range' (e.g. 'today', 'next_7d', "
        "'last_30d') and 'attendee' (filter to events including this "
        "attendee). Returns the matching events list."
    )

    def __init__(self, *, brain_mcp: BrainMCPClient, default_limit: int = 10) -> None:
        self._brain = brain_mcp
        self._default_limit = default_limit

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "time_range": {
                    "type": "string",
                    "description": (
                        "Optional time-range filter (e.g. 'today', "
                        "'next_7d', 'last_30d', or an ISO date range)."
                    ),
                },
                "attendee": {
                    "type": "string",
                    "description": "Optional attendee filter (email or canonical id).",
                },
            },
            "required": [],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        time_range_raw = arguments.get("time_range")
        time_range: str | None = time_range_raw if isinstance(time_range_raw, str) else None
        attendee_raw = arguments.get("attendee")
        attendee: str | None = attendee_raw if isinstance(attendee_raw, str) else None

        response = await self._brain.nx_calendar_read(
            time_range=time_range,
            attendee=attendee,
            limit=self._default_limit,
        )

        raw_events = response.get("events", [])
        events: list[dict[str, object]] = []
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            events.append(
                {
                    "title": item.get("title", ""),
                    "start": item.get("start", ""),
                    "end": item.get("end", ""),
                    "attendees": item.get("attendees", []),
                }
            )

        return {
            "events": events,
            "total": len(events),
            "time_range": time_range,
            "attendee": attendee,
        }


# ---------------------------------------------------------------------------
# NxEmailSearchTool
# ---------------------------------------------------------------------------


class NxEmailSearchTool(CortexTool):
    """Search emails via Brain ``nx_email_search``."""

    name = "nx_email_search"
    description = (
        "Search the owner's email for messages matching the query. "
        "Returns matching messages (subject, from, snippet). Use for "
        "email lookups when the owner asks about past correspondence."
    )

    def __init__(self, *, brain_mcp: BrainMCPClient, default_limit: int = 10) -> None:
        self._brain = brain_mcp
        self._default_limit = default_limit

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms to match across email subject + body.",
                },
            },
            "required": ["query"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        query_raw = arguments.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            raise ValueError("nx_email_search: 'query' is required and must be a non-empty string.")

        response = await self._brain.nx_email_search(
            query=query_raw,
            limit=self._default_limit,
        )

        raw_results = response.get("results", [])
        matches: list[dict[str, object]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            matches.append(
                {
                    "subject": item.get("subject", ""),
                    "from": item.get("from", ""),
                    "snippet": item.get("snippet", ""),
                    "date": item.get("date", ""),
                }
            )

        return {
            "matches": matches,
            "total_matches": len(matches),
            "query": query_raw,
        }


# ---------------------------------------------------------------------------
# VaultAskTool
# ---------------------------------------------------------------------------


class VaultAskTool(CortexTool):
    """Natural-language Q&A over the vault via Brain ``vault_ask``.

    Brain's RAG-shaped tool: pass a free-form question, get back an
    answer with citations. Heavier than ``search_vault`` (Brain runs
    its own LLM step on the retrieved chunks); use when the question
    benefits from synthesis across multiple notes.
    """

    name = "vault_ask"
    description = (
        "Ask a natural-language question over the full vault content. "
        "Brain performs retrieval + synthesis and returns an answer "
        "with citation paths. Use for questions that benefit from "
        "synthesis across multiple notes."
    )

    def __init__(self, *, brain_mcp: BrainMCPClient) -> None:
        self._brain = brain_mcp

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The natural-language question to ask of the vault.",
                },
            },
            "required": ["question"],
        }

    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        question_raw = arguments.get("question")
        if not isinstance(question_raw, str) or not question_raw.strip():
            raise ValueError("vault_ask: 'question' is required and must be a non-empty string.")

        response = await self._brain.vault_ask(question=question_raw)

        raw_citations = response.get("citations", [])
        citations: list[dict[str, object]] = []
        for item in raw_citations:
            if not isinstance(item, dict):
                continue
            citations.append(
                {
                    "path": item.get("path", ""),
                    "snippet": item.get("snippet", ""),
                }
            )

        return {
            "answer": response.get("answer", ""),
            "citations": citations,
            "question": question_raw,
        }


__all__ = [
    "NxCalendarReadTool",
    "NxEmailSearchTool",
    "ReadNoteTool",
    "SearchReferencesTool",
    "SearchVaultTool",
    "VaultAskTool",
]
