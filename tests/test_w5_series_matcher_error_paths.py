"""W5 series.py defensive-error-path coverage (closes W6.6 OQ-W6-2).

These tests exercise the defensive/error branches in
``lattice_meeting_assistant.series`` that the W5.2/W5.3 happy-path
tests did not hit. Together they lift series.py from 87% to ≥90%
critical-path coverage required by W6.6 exit gate.

Lines targeted (per ``pytest --cov`` term-missing output at W6 close):
206, 223-227, 284-289, 317-322, 336, 339, 347, 354, 362, 389-393, 442.

No production-code changes -- tests only.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant.brain_client import BrainMCPClient
from lattice_meeting_assistant.series import (
    SeriesMatch,
    SeriesMatcher,
    _as_str_set,
    _build_path1_match,
    _extract_results,
    _jaccard,
    _parse_ratification_reply,
    _safe_frontmatter,
)


def _brain_with_search(results: list[dict[str, object]]) -> MagicMock:
    m = MagicMock(spec=BrainMCPClient)
    m.nx_vault_search = AsyncMock(return_value={"results": results})
    return m


# ---------------------------------------------------------------------------
# Helper-function defensive branches
# ---------------------------------------------------------------------------


def test_jaccard_empty_union_returns_zero() -> None:
    """Both inputs empty -> 0.0 (line 362)."""
    assert _jaccard(frozenset(), frozenset()) == 0.0


def test_extract_results_handles_none_envelope() -> None:
    """envelope=None -> [] (line 336)."""
    assert _extract_results(None) == []


def test_extract_results_handles_non_list_results_field() -> None:
    """results field non-list -> [] (line 339)."""
    assert _extract_results({"results": "not-a-list"}) == []
    assert _extract_results({"results": None}) == []
    assert _extract_results({"results": {"k": "v"}}) == []


def test_safe_frontmatter_handles_non_dict() -> None:
    """frontmatter field non-dict -> {} (line 347)."""
    assert _safe_frontmatter({"frontmatter": "not-a-dict"}) == {}
    assert _safe_frontmatter({"frontmatter": None}) == {}
    assert _safe_frontmatter({"frontmatter": ["a", "b"]}) == {}


def test_as_str_set_handles_non_iterable() -> None:
    """Non-iterable input (e.g. int) -> empty frozenset (line 354)."""
    assert _as_str_set(42) == frozenset()
    assert _as_str_set(None) == frozenset()
    assert _as_str_set("a string is not a list here") == frozenset()


# ---------------------------------------------------------------------------
# Path 1: missing series_id in result frontmatter
# ---------------------------------------------------------------------------


def test_build_path1_match_returns_none_when_series_id_missing() -> None:
    """Helper returns None + logs when frontmatter has no series_id (lines 389-393)."""
    result: dict[str, object] = {
        "path": "02_Projects/Lattice/lattice-meetbot/Meeting Series/x.md",
        "frontmatter": {"zoom_recurring_meeting_id": "x"},  # no series_id
    }
    assert _build_path1_match(result) is None


def test_build_path1_match_returns_none_when_series_id_empty_string() -> None:
    """Empty-string series_id is rejected the same as missing (lines 389-393)."""
    result: dict[str, object] = {
        "path": "02_Projects/Lattice/lattice-meetbot/Meeting Series/y.md",
        "frontmatter": {"series_id": ""},
    }
    assert _build_path1_match(result) is None


# ---------------------------------------------------------------------------
# Path 2: empty typical_participants + malformed best candidate
# ---------------------------------------------------------------------------


async def test_path2_skips_candidate_with_empty_typical_participants() -> None:
    """Candidate with empty ``typical_participants`` is skipped (line 206)."""
    brain = _brain_with_search(
        [
            {
                "path": "02_Projects/Lattice/lattice-meetbot/Meeting Series/ghost.md",
                "frontmatter": {
                    "series_id": "ghost-series",
                    "typical_participants": [],  # empty -> skip
                    "last_updated": "2026-05-01",
                },
            }
        ]
    )
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_2(
        host_canonical_id="cyril",
        attendee_canonical_ids=frozenset({"cyril", "danielle"}),
    )
    assert match is None


async def test_path2_returns_none_when_best_candidate_missing_series_id() -> None:
    """Highest-overlap candidate has malformed series_id -> log + return None (lines 223-227).

    Subtle: the candidate must pass the typical_participants + jaccard
    threshold checks first so it reaches the series_id validation.
    """
    brain = _brain_with_search(
        [
            {
                "path": "02_Projects/Lattice/lattice-meetbot/Meeting Series/malformed.md",
                "frontmatter": {
                    # series_id missing -> rejected at line 222 isinstance check
                    "typical_participants": ["cyril", "danielle"],
                    "last_updated": "2026-05-01",
                },
            }
        ]
    )
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_2(
        host_canonical_id="cyril",
        attendee_canonical_ids=frozenset({"cyril", "danielle"}),
    )
    assert match is None


# ---------------------------------------------------------------------------
# Ratify: post_admin_response + await_admin_reply exception paths
# ---------------------------------------------------------------------------


def _seed_match() -> SeriesMatch:
    return SeriesMatch(
        series_id="acme-q3",
        binding="implicit-host-cohort",
        confidence="medium",
        requires_ratification=True,
        cohort_overlap_score=0.67,
        profile_vault_path="02_Projects/Lattice/lattice-meetbot/Meeting Series/acme-q3.md",
    )


async def test_ratify_returns_none_when_post_admin_response_raises() -> None:
    """post_admin_response raises -> log + return None (lines 284-289)."""
    transport = MagicMock()
    transport.post_admin_response = AsyncMock(side_effect=RuntimeError("network"))
    transport.await_admin_reply = AsyncMock(return_value="yes")
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
        ratification_timeout_s=0.5,
    )
    result = await matcher.ratify(_seed_match())
    assert result is None


async def test_ratify_returns_none_when_await_admin_reply_raises_nontimeout() -> None:
    """await_admin_reply raises non-Timeout -> log + return None (lines 317-322)."""
    transport = MagicMock()
    transport.post_admin_response = AsyncMock(return_value=None)
    transport.await_admin_reply = AsyncMock(side_effect=RuntimeError("websocket dropped"))
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
        ratification_timeout_s=0.5,
    )
    result = await matcher.ratify(_seed_match())
    assert result is None


# ---------------------------------------------------------------------------
# Parse: malformed inputs (unknown verb, empty, None-ish)
# ---------------------------------------------------------------------------
#
# Note: line 442 (``new-series`` with empty-slug after the prefix) is
# actually defensive dead code reachable only via direct internal call:
# the public ``reply`` is .strip()'d at line 427, which removes the
# trailing whitespace that would otherwise leave the prefix matching
# but the slug empty. We accept the 99% coverage that the rest of this
# file produces and leave line 442 as a no-op defensive guard.


def test_parse_ratification_reply_unknown_verb_returns_none() -> None:
    """Replies that don't match yes/no/new-series fall to the conservative deny."""
    match = _seed_match()
    assert _parse_ratification_reply("maybe later", match) is None
    assert _parse_ratification_reply("", match) is None
    # whitespace-only also stripped to empty + then falls through
    assert _parse_ratification_reply("   ", match) is None
