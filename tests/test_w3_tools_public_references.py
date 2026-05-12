"""Tests for ``SearchPublicReferencesTool`` (W3.4).

Spec §4 line 488:

    search_public_references(query)
      -> Brain ``nx_references_search`` scoped to
         ``profile.knowledge.public_references`` paths

Critical privacy semantic: the resolver constructs this tool with the
profile's ``public_references`` tuple as the scope; the tool MUST NOT
search outside that scope, even if the caller injects an alternative
``paths`` argument. The in-meeting transport's resolver passes the
profile-bound paths in; the tool ignores any caller-supplied path
override (defense in depth on top of the resolver).
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from lattice_meeting_assistant.brain_client import BrainMCPClient, BrainMCPError
from lattice_meeting_assistant.tools.public_references import (
    SearchPublicReferencesTool,
)


# ---------------------------------------------------------------------------
# Fake BrainMCPClient
# ---------------------------------------------------------------------------


class _FakeBrain:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.refs_search_calls: list[dict[str, Any]] = []
        self._result = result or {"results": []}
        self.raise_on_search: BrainMCPError | None = None

    async def nx_references_search(
        self,
        *,
        query: str,
        paths: tuple[str, ...] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if self.raise_on_search is not None:
            raise self.raise_on_search
        self.refs_search_calls.append({"query": query, "paths": paths, "limit": limit})
        return self._result


def test_public_refs_tool_metadata() -> None:
    """Tool exposes stable name + description."""
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchPublicReferencesTool(brain_mcp=brain, public_paths=())
    assert tool.name == "search_public_references"
    assert "reference" in tool.description.lower() or "public" in tool.description.lower()


async def test_public_refs_invoke_threads_paths_into_call() -> None:
    """Profile-bound paths flow into ``nx_references_search.paths``."""
    fake = _FakeBrain(
        result={
            "results": [
                {
                    "path": "References/RFC8259.md",
                    "snippet": "JSON syntax",
                }
            ]
        }
    )
    brain = cast(BrainMCPClient, fake)
    public_paths = ("References/", "Standards/")
    tool = SearchPublicReferencesTool(brain_mcp=brain, public_paths=public_paths)

    result = await tool.invoke({"query": "JSON syntax"})

    assert len(fake.refs_search_calls) == 1
    call = fake.refs_search_calls[0]
    assert call["query"] == "JSON syntax"
    assert call["paths"] == public_paths
    matches = cast(list[dict[str, Any]], result["matches"])
    assert len(matches) == 1


async def test_public_refs_invoke_ignores_caller_paths_override() -> None:
    """Even if the model passes ``paths`` in arguments, we MUST send the
    profile-bound scope, not the override (defense in depth on top of
    resolver-level enforcement of Invariant 2).
    """
    fake = _FakeBrain()
    brain = cast(BrainMCPClient, fake)
    public_paths = ("References/",)
    tool = SearchPublicReferencesTool(brain_mcp=brain, public_paths=public_paths)

    # Caller tries to inject a personal-vault path. The tool must NOT
    # forward it; profile-bound scope wins.
    await tool.invoke({"query": "anything", "paths": ["02_Projects/Personal/Diary/"]})

    call = fake.refs_search_calls[0]
    assert call["paths"] == public_paths  # NOT the caller-injected override


async def test_public_refs_invoke_empty_paths_returns_empty() -> None:
    """If profile defines NO public_references paths, the tool returns an
    empty result without making a Brain call -- there is nowhere to search
    so we short-circuit (avoids accidentally hitting full nx_references_search).
    """
    fake = _FakeBrain()
    brain = cast(BrainMCPClient, fake)
    tool = SearchPublicReferencesTool(brain_mcp=brain, public_paths=())

    result = await tool.invoke({"query": "anything"})

    # No Brain call should have been made.
    assert fake.refs_search_calls == []
    assert cast(list[Any], result["matches"]) == []
    assert "no public_references configured" in str(result.get("note", ""))


async def test_public_refs_invoke_missing_query_raises() -> None:
    brain = cast(BrainMCPClient, _FakeBrain())
    tool = SearchPublicReferencesTool(brain_mcp=brain, public_paths=("References/",))
    with pytest.raises(ValueError, match="query"):
        await tool.invoke({})


async def test_public_refs_propagates_brain_error() -> None:
    fake = _FakeBrain()
    fake.raise_on_search = BrainMCPError("HTTP 500", status_code=500)
    brain = cast(BrainMCPClient, fake)
    tool = SearchPublicReferencesTool(brain_mcp=brain, public_paths=("References/",))
    with pytest.raises(BrainMCPError, match="500"):
        await tool.invoke({"query": "x"})
