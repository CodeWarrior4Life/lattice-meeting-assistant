"""W5.2 -- SeriesMatcher Path 1 (explicit recurring meeting ID).

Spec §6 Path 1 (lines 746-751):

* Input: ``zoom_recurring_meeting_id`` (e.g. ``"81050295086"``).
* Brain ``nx_vault_search`` filters Meeting Series/ frontmatter notes
  where ``zoom_recurring_meeting_id == <id>``.
* On a single hit -> :class:`SeriesMatch` with
  ``binding="explicit"``, ``confidence="high"``,
  ``requires_ratification=False``, ``cohort_overlap_score=None``.
* On no hits -> ``None``.
* On multiple hits -> pick the first (deterministic, document the choice).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant.brain_client import BrainMCPClient
from lattice_meeting_assistant.series import SeriesMatch, SeriesMatcher


def _brain_with_search(results: list[dict[str, object]]) -> MagicMock:
    """Build a BrainMCPClient-shaped mock whose nx_vault_search returns
    a fixed list of result dicts wrapped in the Brain envelope shape.
    """
    m = MagicMock(spec=BrainMCPClient)
    m.nx_vault_search = AsyncMock(return_value={"results": results})
    return m


async def test_path1_single_match_returns_high_confidence_explicit() -> None:
    """One frontmatter match -> HIGH explicit binding, no ratification."""
    brain = _brain_with_search(
        [
            {
                "path": "02_Projects/Lattice/lattice-meetbot/Meeting Series/sabbath-school-class.md",
                "frontmatter": {
                    "series_id": "sabbath-school-class",
                    "zoom_recurring_meeting_id": "81050295086",
                    "assistant_profile": "Profiles/sabbath-school.yaml",
                },
            }
        ]
    )
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_1(zoom_recurring_meeting_id="81050295086")

    assert match is not None
    assert match.series_id == "sabbath-school-class"
    assert match.binding == "explicit"
    assert match.confidence == "high"
    assert match.requires_ratification is False
    assert match.cohort_overlap_score is None
    assert match.profile_vault_path.endswith("sabbath-school-class.md")


async def test_path1_no_results_returns_none() -> None:
    """Empty results envelope -> ``None``."""
    brain = _brain_with_search([])
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_1(zoom_recurring_meeting_id="nonexistent-id")
    assert match is None


async def test_path1_multiple_matches_picks_first_deterministic() -> None:
    """Multiple hits -> pick the first (documented deterministic choice).

    Real recurring-id collisions should never happen (Zoom assigns
    unique IDs per series), but we tolerate it by deterministically
    returning the first result so behaviour is reproducible. Spec §6
    treats Path 1 as a HIGH-confidence single-result lookup; collisions
    should be surfaced separately to admin (out of v0.1 scope).
    """
    brain = _brain_with_search(
        [
            {
                "path": "Meeting Series/first.md",
                "frontmatter": {
                    "series_id": "first",
                    "zoom_recurring_meeting_id": "X",
                },
            },
            {
                "path": "Meeting Series/second.md",
                "frontmatter": {
                    "series_id": "second",
                    "zoom_recurring_meeting_id": "X",
                },
            },
        ]
    )
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_1(zoom_recurring_meeting_id="X")
    assert match is not None
    assert match.series_id == "first"
    assert match.profile_vault_path.endswith("first.md")


async def test_path1_filters_by_recurring_id_in_brain_query() -> None:
    """Path 1 passes the recurring-id as a structured filter to Brain.

    Defends against drift in the Brain query shape -- the matcher MUST
    constrain the search by the recurring id, never just fall back to
    a free-text query.
    """
    brain = _brain_with_search([])
    matcher = SeriesMatcher(brain_mcp=brain)
    await matcher.match_path_1(zoom_recurring_meeting_id="81050295086")

    # Brain was queried with a filter that includes the recurring id.
    brain.nx_vault_search.assert_awaited_once()
    call_kwargs = brain.nx_vault_search.await_args.kwargs
    filters = call_kwargs.get("filters") or {}
    assert filters.get("zoom_recurring_meeting_id") == "81050295086"
