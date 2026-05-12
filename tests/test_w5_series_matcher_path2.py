"""W5.3 -- SeriesMatcher Path 2 (implicit host-cohort) + ratification flow.

Spec §6 Path 2 (lines 753-773):

* Query Meeting Series/ notes where ``host_canonical_id`` matches.
* For each candidate, Jaccard overlap between current attendee set and
  candidate's ``typical_participants``.
* Best candidate with overlap >= 0.5 -> MEDIUM-confidence,
  ``requires_ratification=True``.
* Ratification flow: send TG ping; await yes/no/new-series/timeout;
  ``yes`` -> ratified; ``no``/timeout -> default profile.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant import SeriesMatch, SeriesMatcher
from lattice_meeting_assistant.brain_client import BrainMCPClient
from lattice_meeting_assistant.series import PATH_2_JACCARD_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _brain_with_search(results: list[dict[str, object]]) -> MagicMock:
    m = MagicMock(spec=BrainMCPClient)
    m.nx_vault_search = AsyncMock(return_value={"results": results})
    return m


def _candidate(
    *,
    series_id: str,
    typical: list[str],
    last_updated: str = "",
    path: str | None = None,
) -> dict[str, object]:
    return {
        "path": path or f"Meeting Series/{series_id}.md",
        "frontmatter": {
            "series_id": series_id,
            "host_canonical_id": "cyril-grosse",
            "typical_participants": typical,
            "last_updated": last_updated,
        },
    }


class _ScriptedTransport:
    """Minimal duck-typed AdminTransport.

    Implements both halves of the matcher's ratification protocol:
    ``post_admin_response`` (send) + ``await_admin_reply`` (receive).
    The receive half is the duck-typed extension the matcher probes
    via ``getattr`` -- rc2 ``AdminTransport`` is send-only.
    """

    def __init__(self, *, reply: str | None = None, delay_s: float = 0.0) -> None:
        self.kind = "tg-owner"
        self.sent: list[tuple[Any, str]] = []
        self._reply = reply
        self._delay_s = delay_s

    async def post_admin_response(self, handle: Any, response_text: str) -> None:
        self.sent.append((handle, response_text))

    async def await_admin_reply(self, handle: Any, *, timeout_s: float) -> str:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        if self._reply is None:
            # Block forever -- caller's wait_for budgets the wait.
            await asyncio.sleep(timeout_s + 1)
            return ""
        return self._reply


def _make_match(
    *,
    series_id: str = "family-council",
    overlap: float = 0.6,
    path: str = "Meeting Series/family-council.md",
) -> SeriesMatch:
    """Construct a SeriesMatch directly for ratify-only tests."""
    return SeriesMatch(
        series_id=series_id,
        binding="implicit-host-cohort",
        confidence="medium",
        requires_ratification=True,
        cohort_overlap_score=overlap,
        profile_vault_path=path,
    )


# ---------------------------------------------------------------------------
# Path 2 scoring
# ---------------------------------------------------------------------------


async def test_path2_single_candidate_above_threshold_returns_medium() -> None:
    """One candidate with overlap >= 0.5 -> MEDIUM + requires_ratification."""
    # Attendees: {a, b, c}; typical: {a, b, d} -> overlap = 2/4 = 0.5.
    brain = _brain_with_search([_candidate(series_id="family-council", typical=["a", "b", "d"])])
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=frozenset({"a", "b", "c"}),
    )
    assert match is not None
    assert match.series_id == "family-council"
    assert match.binding == "implicit-host-cohort"
    assert match.confidence == "medium"
    assert match.requires_ratification is True
    assert match.cohort_overlap_score is not None
    assert match.cohort_overlap_score >= PATH_2_JACCARD_THRESHOLD


async def test_path2_single_candidate_below_threshold_returns_none() -> None:
    """Single candidate with overlap < 0.5 -> ``None`` (below threshold)."""
    # Attendees: {a, b, c}; typical: {x, y} -> overlap = 0/5 = 0.0.
    brain = _brain_with_search([_candidate(series_id="family-council", typical=["x", "y"])])
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=frozenset({"a", "b", "c"}),
    )
    assert match is None


async def test_path2_no_results_returns_none() -> None:
    """No host-match candidates -> ``None``."""
    brain = _brain_with_search([])
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=frozenset({"a", "b"}),
    )
    assert match is None


async def test_path2_picks_highest_overlap_when_multiple_above_threshold() -> None:
    """Multiple candidates clear the threshold -> highest-overlap wins."""
    # Attendees: {a, b, c, d}
    # Candidate "low":  typical {a, b}      -> overlap = 2/4 = 0.50
    # Candidate "high": typical {a, b, c}   -> overlap = 3/4 = 0.75
    brain = _brain_with_search(
        [
            _candidate(series_id="low", typical=["a", "b"]),
            _candidate(series_id="high", typical=["a", "b", "c"]),
        ]
    )
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=frozenset({"a", "b", "c", "d"}),
    )
    assert match is not None
    assert match.series_id == "high"
    assert match.cohort_overlap_score == pytest.approx(0.75)


async def test_path2_ties_broken_by_recency() -> None:
    """Same overlap -> tie broken by descending ``last_updated``."""
    # Attendees: {a, b}; both candidates overlap 1.0 (typical = {a, b}).
    # "older"  has last_updated 2024-01-01
    # "newer"  has last_updated 2026-05-12 -> wins
    brain = _brain_with_search(
        [
            _candidate(
                series_id="older",
                typical=["a", "b"],
                last_updated="2024-01-01T00:00:00Z",
            ),
            _candidate(
                series_id="newer",
                typical=["a", "b"],
                last_updated="2026-05-12T00:00:00Z",
            ),
        ]
    )
    matcher = SeriesMatcher(brain_mcp=brain)
    match = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=frozenset({"a", "b"}),
    )
    assert match is not None
    assert match.series_id == "newer"


async def test_path2_filters_brain_query_by_host_canonical_id() -> None:
    """Path 2 passes ``host_canonical_id`` as a structured filter."""
    brain = _brain_with_search([])
    matcher = SeriesMatcher(brain_mcp=brain)
    await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=frozenset({"a"}),
    )
    brain.nx_vault_search.assert_awaited_once()
    filters = brain.nx_vault_search.await_args.kwargs.get("filters") or {}
    assert filters.get("host_canonical_id") == "cyril-grosse"


# ---------------------------------------------------------------------------
# Ratification flow
# ---------------------------------------------------------------------------


async def test_ratify_yes_returns_match_with_ratification_false() -> None:
    """``yes`` reply -> SeriesMatch with ``requires_ratification=False``."""
    transport = _ScriptedTransport(reply="yes")
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
    )
    pending = _make_match()
    ratified = await matcher.ratify(pending, timeout_s=2.0)

    assert ratified is not None
    assert ratified.series_id == "family-council"
    assert ratified.requires_ratification is False
    assert ratified.confidence == "medium"  # confidence stays MEDIUM post-ratify
    assert ratified.binding == "implicit-host-cohort"
    # Transport received the prompt.
    assert len(transport.sent) == 1
    assert "family-council" in transport.sent[0][1]


async def test_ratify_no_returns_none_default_profile_fallback() -> None:
    """``no`` reply -> ``None`` (caller falls back to default profile)."""
    transport = _ScriptedTransport(reply="no")
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
    )
    pending = _make_match()
    ratified = await matcher.ratify(pending, timeout_s=2.0)
    assert ratified is None


async def test_ratify_new_series_returns_new_match_with_supplied_slug() -> None:
    """``new-series <slug>`` reply -> new SeriesMatch with the slug."""
    transport = _ScriptedTransport(reply="new-series tuesday-standup")
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
    )
    pending = _make_match()
    ratified = await matcher.ratify(pending, timeout_s=2.0)

    assert ratified is not None
    assert ratified.series_id == "tuesday-standup"
    assert ratified.binding == "implicit-host-cohort"
    assert ratified.requires_ratification is False


async def test_ratify_timeout_returns_none() -> None:
    """Reply takes longer than ``timeout_s`` -> ``None`` (timeout fallback)."""
    # delay_s greater than timeout_s -> wait_for cancels the receive.
    transport = _ScriptedTransport(reply="yes", delay_s=10.0)
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
    )
    pending = _make_match()
    ratified = await matcher.ratify(pending, timeout_s=0.1)
    assert ratified is None


async def test_ratify_no_admin_transport_wired_returns_none() -> None:
    """``admin_transport=None`` -> ratify is a silent no-op (default profile)."""
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=None,
    )
    pending = _make_match()
    ratified = await matcher.ratify(pending, timeout_s=1.0)
    assert ratified is None


async def test_ratify_transport_without_await_reply_returns_none() -> None:
    """Send-only ``AdminTransport`` (rc2 contract) -> timeout-fallback.

    The rc2 contract is send-only. When ``await_admin_reply`` is not
    implemented the matcher conservatively treats the ratification as
    a timeout. Concrete production transports (BrainTGAdminTransport)
    implement both halves.
    """

    class _SendOnly:
        kind = "tg-owner"

        async def post_admin_response(self, handle: Any, response_text: str) -> None: ...

    transport = _SendOnly()
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
    )
    pending = _make_match()
    ratified = await matcher.ratify(pending, timeout_s=1.0)
    assert ratified is None
    # Nothing to assert on sent log -- the bare class has no recorder;
    # the absence of a crash + None return is the success criterion.


async def test_ratify_unknown_reply_treated_as_deny() -> None:
    """Replies that aren't yes/no/new-series -> deny (conservative)."""
    transport = _ScriptedTransport(reply="huh?")
    matcher = SeriesMatcher(
        brain_mcp=MagicMock(spec=BrainMCPClient),
        admin_transport=transport,
    )
    pending = _make_match()
    ratified = await matcher.ratify(pending, timeout_s=2.0)
    assert ratified is None
