"""Tests for the 6 TG-owner-only Nexus tool wrappers (W3.6).

Spec §4 "TG-owner adds" enumerates 6 unscoped Nexus wrappers exposed
only via the TG-owner transport (the resolver gates registration --
in-meeting-dm transport never sees these per Architectural
Invariant #2). They are thin pass-throughs over :class:`BrainMCPClient`
with no business logic; v0.1 contract is: forward arguments, re-shape
the response into an LLM-consumable dict.

The 6 tools:

* ``SearchVaultTool`` (``search_vault``) -- unscoped personal-vault
  search. Distinct from ``SearchPastMeetingsTool`` which series-scopes.
* ``ReadNoteTool`` (``read_note``) -- read a single vault note by path.
* ``SearchReferencesTool`` (``search_references``) -- unscoped public
  references search (no profile paths filter).
* ``NxCalendarReadTool`` (``nx_calendar_read``) -- read calendar events.
* ``NxEmailSearchTool`` (``nx_email_search``) -- search emails.
* ``VaultAskTool`` (``vault_ask``) -- natural-language Q&A over vault.

Each test follows the pattern:

* one happy-path test: invoke the tool, assert the BrainMCPClient method
  was called with the expected kwargs, assert the response dict has
  the expected shape.
* at least one input-validation failure: missing required argument
  raises ``ValueError``.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from lattice_meeting_assistant.brain_client import BrainMCPClient, BrainMCPError
from lattice_meeting_assistant.tools.tg_owner_tools import (
    NxCalendarReadTool,
    NxEmailSearchTool,
    ReadNoteTool,
    SearchReferencesTool,
    SearchVaultTool,
    VaultAskTool,
)


# ---------------------------------------------------------------------------
# Fake BrainMCPClient -- captures kwargs + returns canned payloads.
# ---------------------------------------------------------------------------


class _FakeBrain:
    """Stand-in for :class:`BrainMCPClient`; records every method call."""

    def __init__(self) -> None:
        self.vault_search_calls: list[dict[str, Any]] = []
        self.read_note_calls: list[dict[str, Any]] = []
        self.references_search_calls: list[dict[str, Any]] = []
        self.calendar_read_calls: list[dict[str, Any]] = []
        self.email_search_calls: list[dict[str, Any]] = []
        self.vault_ask_calls: list[dict[str, Any]] = []

        self.vault_search_result: dict[str, Any] = {"results": []}
        self.read_note_result: dict[str, Any] = {"path": "", "content": ""}
        self.references_search_result: dict[str, Any] = {"results": []}
        self.calendar_read_result: dict[str, Any] = {"events": []}
        self.email_search_result: dict[str, Any] = {"results": []}
        self.vault_ask_result: dict[str, Any] = {"answer": ""}

        self.raise_on_call: BrainMCPError | None = None

    async def nx_vault_search(
        self,
        *,
        query: str,
        filters: Any = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.vault_search_calls.append({"query": query, "filters": filters, "limit": limit})
        return self.vault_search_result

    async def nx_read_note(self, *, path: str) -> dict[str, Any]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.read_note_calls.append({"path": path})
        return self.read_note_result

    async def nx_references_search(
        self,
        *,
        query: str,
        paths: Any = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.references_search_calls.append({"query": query, "paths": paths, "limit": limit})
        return self.references_search_result

    async def nx_calendar_read(
        self,
        *,
        time_range: str | None = None,
        attendee: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.calendar_read_calls.append(
            {"time_range": time_range, "attendee": attendee, "limit": limit}
        )
        return self.calendar_read_result

    async def nx_email_search(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.email_search_calls.append({"query": query, "limit": limit})
        return self.email_search_result

    async def vault_ask(self, *, question: str) -> dict[str, Any]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.vault_ask_calls.append({"question": question})
        return self.vault_ask_result


# ---------------------------------------------------------------------------
# SearchVaultTool
# ---------------------------------------------------------------------------


def test_search_vault_tool_metadata() -> None:
    """Tool name + description are stable."""
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchVaultTool(brain_mcp=brain)
    assert tool.name == "search_vault"
    assert tool.description
    schema = tool.input_schema
    assert schema["type"] == "object"
    props = cast(dict[str, Any], schema["properties"])
    assert "query" in props


async def test_search_vault_invoke_passes_query_to_brain() -> None:
    """Happy path: ``invoke`` forwards the query to ``nx_vault_search``
    without any series filter -- this is the unscoped TG-owner search.
    """
    fake = _FakeBrain()
    fake.vault_search_result = {
        "results": [
            {
                "path": "02_Projects/Personal/Diary.md",
                "snippet": "private",
                "frontmatter": {},
            }
        ]
    }
    brain = cast(BrainMCPClient, fake)
    tool = SearchVaultTool(brain_mcp=brain)

    result = await tool.invoke({"query": "diary"})

    assert len(fake.vault_search_calls) == 1
    call = fake.vault_search_calls[0]
    assert call["query"] == "diary"
    # Unscoped: no filters (or empty filters) -- DOES NOT scope by series.
    assert not call["filters"]

    matches = cast(list[dict[str, Any]], result["matches"])
    assert len(matches) == 1
    assert matches[0]["path"] == "02_Projects/Personal/Diary.md"


async def test_search_vault_invoke_missing_query_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchVaultTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({})


async def test_search_vault_propagates_brain_error() -> None:
    fake = _FakeBrain()
    fake.raise_on_call = BrainMCPError("HTTP 500", status_code=500)
    brain = cast(BrainMCPClient, fake)
    tool = SearchVaultTool(brain_mcp=brain)
    with pytest.raises(BrainMCPError, match="500"):
        await tool.invoke({"query": "x"})


# ---------------------------------------------------------------------------
# ReadNoteTool
# ---------------------------------------------------------------------------


def test_read_note_tool_metadata() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = ReadNoteTool(brain_mcp=brain)
    assert tool.name == "read_note"
    assert tool.description
    props = cast(dict[str, Any], tool.input_schema["properties"])
    assert "path" in props


async def test_read_note_invoke_passes_path_to_brain() -> None:
    fake = _FakeBrain()
    fake.read_note_result = {
        "path": "Notes/MyNote.md",
        "content": "Hello world",
        "frontmatter": {"tags": ["test"]},
    }
    brain = cast(BrainMCPClient, fake)
    tool = ReadNoteTool(brain_mcp=brain)

    result = await tool.invoke({"path": "Notes/MyNote.md"})

    assert len(fake.read_note_calls) == 1
    assert fake.read_note_calls[0]["path"] == "Notes/MyNote.md"
    assert result["path"] == "Notes/MyNote.md"
    assert result["content"] == "Hello world"


async def test_read_note_invoke_missing_path_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = ReadNoteTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="path"):
        await tool.invoke({})


async def test_read_note_invoke_empty_path_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = ReadNoteTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="path"):
        await tool.invoke({"path": "   "})


# ---------------------------------------------------------------------------
# SearchReferencesTool (unscoped variant -- TG-owner only)
# ---------------------------------------------------------------------------


def test_search_references_tool_metadata() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchReferencesTool(brain_mcp=brain)
    assert tool.name == "search_references"
    assert tool.description
    props = cast(dict[str, Any], tool.input_schema["properties"])
    assert "query" in props


async def test_search_references_invoke_unscoped() -> None:
    """Unscoped variant: no paths filter sent to Brain. This is
    distinct from ``SearchPublicReferencesTool`` which restricts to
    profile-allowlisted paths.
    """
    fake = _FakeBrain()
    fake.references_search_result = {
        "results": [{"path": "References/RFC8259.md", "snippet": "JSON"}]
    }
    brain = cast(BrainMCPClient, fake)
    tool = SearchReferencesTool(brain_mcp=brain)

    result = await tool.invoke({"query": "JSON syntax"})

    assert len(fake.references_search_calls) == 1
    call = fake.references_search_calls[0]
    assert call["query"] == "JSON syntax"
    assert call["paths"] is None  # unscoped
    matches = cast(list[dict[str, Any]], result["matches"])
    assert len(matches) == 1


async def test_search_references_invoke_missing_query_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchReferencesTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({})


# ---------------------------------------------------------------------------
# NxCalendarReadTool
# ---------------------------------------------------------------------------


def test_nx_calendar_read_tool_metadata() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = NxCalendarReadTool(brain_mcp=brain)
    assert tool.name == "nx_calendar_read"
    assert tool.description


async def test_nx_calendar_read_invoke_passes_filters_to_brain() -> None:
    fake = _FakeBrain()
    fake.calendar_read_result = {
        "events": [
            {
                "title": "Lattice arch review",
                "start": "2026-05-15T14:00:00Z",
                "end": "2026-05-15T15:00:00Z",
            }
        ]
    }
    brain = cast(BrainMCPClient, fake)
    tool = NxCalendarReadTool(brain_mcp=brain)

    result = await tool.invoke({"time_range": "next_7d", "attendee": "cyril"})

    assert len(fake.calendar_read_calls) == 1
    call = fake.calendar_read_calls[0]
    assert call["time_range"] == "next_7d"
    assert call["attendee"] == "cyril"
    events = cast(list[dict[str, Any]], result["events"])
    assert len(events) == 1


async def test_nx_calendar_read_invoke_no_args_ok() -> None:
    """No required args: caller may invoke with no args (default range)."""
    fake = _FakeBrain()
    brain = cast(BrainMCPClient, fake)
    tool = NxCalendarReadTool(brain_mcp=brain)
    result = await tool.invoke({})
    assert len(fake.calendar_read_calls) == 1
    assert result is not None


# ---------------------------------------------------------------------------
# NxEmailSearchTool
# ---------------------------------------------------------------------------


def test_nx_email_search_tool_metadata() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = NxEmailSearchTool(brain_mcp=brain)
    assert tool.name == "nx_email_search"
    assert tool.description


async def test_nx_email_search_invoke_passes_query_to_brain() -> None:
    fake = _FakeBrain()
    fake.email_search_result = {
        "results": [{"subject": "Re: project", "from": "alice@example.com", "snippet": "..."}]
    }
    brain = cast(BrainMCPClient, fake)
    tool = NxEmailSearchTool(brain_mcp=brain)

    result = await tool.invoke({"query": "project update"})

    assert len(fake.email_search_calls) == 1
    assert fake.email_search_calls[0]["query"] == "project update"
    matches = cast(list[dict[str, Any]], result["matches"])
    assert len(matches) == 1


async def test_nx_email_search_invoke_missing_query_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = NxEmailSearchTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({})


# ---------------------------------------------------------------------------
# VaultAskTool
# ---------------------------------------------------------------------------


def test_vault_ask_tool_metadata() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = VaultAskTool(brain_mcp=brain)
    assert tool.name == "vault_ask"
    assert tool.description
    props = cast(dict[str, Any], tool.input_schema["properties"])
    assert "question" in props


async def test_vault_ask_invoke_passes_question_to_brain() -> None:
    fake = _FakeBrain()
    fake.vault_ask_result = {
        "answer": "Cyril's preferred async pattern is httpx + anyio.",
        "citations": [{"path": "Protocols/Async.md"}],
    }
    brain = cast(BrainMCPClient, fake)
    tool = VaultAskTool(brain_mcp=brain)

    result = await tool.invoke({"question": "What is Cyril's async pattern?"})

    assert len(fake.vault_ask_calls) == 1
    assert fake.vault_ask_calls[0]["question"] == "What is Cyril's async pattern?"
    assert "httpx" in str(result["answer"])


async def test_vault_ask_invoke_missing_question_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = VaultAskTool(brain_mcp=brain)
    with pytest.raises(ValueError, match="question"):
        await tool.invoke({})
