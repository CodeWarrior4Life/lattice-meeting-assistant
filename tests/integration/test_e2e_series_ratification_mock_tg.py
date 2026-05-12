"""AC-6 -- SeriesMatcher Path 2 ratification round-trip via mock AdminTransport.

Plan §2446-2449 (Task W5.7). Exercises the full Path-2 ratification
flow with a scripted ``AdminTransport`` mock standing in for the
production Brain TG transport:

* **yes flow** -- match -> ratify("yes") -> SeriesMatch with
  ``requires_ratification=False`` (Assistant binds to the ratified series).
* **no flow** -- match -> ratify("no") -> ``None`` (Assistant falls back
  to default profile).
* **new-series flow** -- match -> ratify("new-series acme-q3") -> new
  SeriesMatch carrying the user-supplied slug.
* **timeout flow** -- match -> ratify slow -> ``None`` (timeout
  fallback). The mock blocks past ``ratification_timeout_s``.

The mock uses an ``asyncio.Queue`` of scripted replies; ``await_admin_reply``
pops with the matcher-supplied ``timeout_s`` budget. The matcher's
duck-typed ``_RatificationTransport`` Protocol (series.py:82-95) is the
contract this mock satisfies; OQ-W5A-1 tracks lifting the receive half
into ``lattice-meeting-contracts`` proper.

Brain MCP for the Path-2 vault-search call is also mocked (single
candidate matching the test attendee cohort >= 0.5 Jaccard threshold)
so the matcher returns a MEDIUM/requires_ratification match before
ratification fires.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant import SeriesMatch, SeriesMatcher
from lattice_meeting_assistant.brain_client import BrainMCPClient


# ---------------------------------------------------------------------------
# Scripted mock AdminTransport (E2E surface for the ratification round-trip)
# ---------------------------------------------------------------------------


class MockAdminTransport:
    """Mock TG AdminTransport with scripted replies.

    Replicates the duck-typed ``_RatificationTransport`` shape SeriesMatcher
    expects (``post_admin_response`` + ``await_admin_reply``). Replies are
    pushed into an ``asyncio.Queue`` by the test setup; ``await_admin_reply``
    pops from the queue with the caller-supplied timeout. A configurable
    ``reply_delay_s`` lets tests script the timeout-fallback case by
    pushing a reply but making the receive slower than the matcher's
    ratification budget.
    """

    def __init__(self, *, reply_delay_s: float = 0.0) -> None:
        self.kind = "tg-owner"
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._reply_delay_s = reply_delay_s
        # Audit log -- tests assert what the matcher sent to TG.
        self.posts: list[tuple[Any, str]] = []
        self.replies_consumed: list[str] = []

    def script_reply(self, reply: str) -> None:
        """Push a scripted reply onto the queue."""
        self._queue.put_nowait(reply)

    async def post_admin_response(self, handle: Any, response_text: str) -> None:
        """Record the outbound ratification prompt."""
        self.posts.append((handle, response_text))

    async def await_admin_reply(self, handle: Any, *, timeout_s: float) -> str:
        """Block on the reply queue with optional delay.

        Implementation detail: SeriesMatcher.ratify() wraps THIS call in
        ``asyncio.wait_for(..., timeout=budget)`` so even if we sleep
        longer than ``timeout_s`` here, the outer ``wait_for`` enforces
        the budget. Tests that script timeout set ``reply_delay_s`` > the
        matcher's ratification budget.
        """
        if self._reply_delay_s > 0:
            await asyncio.sleep(self._reply_delay_s)
        reply = await self._queue.get()
        self.replies_consumed.append(reply)
        return reply


# ---------------------------------------------------------------------------
# Brain MCP mock returning a single Path-2 candidate
# ---------------------------------------------------------------------------


_PATH = "Meeting Series/family-council.md"


def _brain_with_single_candidate() -> MagicMock:
    """Brain MCP mock returning one Meeting Series/ candidate that yields
    a Jaccard overlap of 1.0 with the test attendee cohort.
    """
    candidate = {
        "path": _PATH,
        "frontmatter": {
            "series_id": "family-council",
            "host_canonical_id": "cyril-grosse",
            "typical_participants": ["alice", "bob"],
            "last_updated": "2026-05-01T00:00:00Z",
        },
    }
    m = MagicMock(spec=BrainMCPClient)
    m.nx_vault_search = AsyncMock(return_value={"results": [candidate]})
    return m


def _attendees() -> frozenset[str]:
    """Attendee set fully overlapping the candidate's typical participants
    (Jaccard = 1.0 >= 0.5 threshold)."""
    return frozenset({"alice", "bob"})


# ---------------------------------------------------------------------------
# AC-6 -- yes flow
# ---------------------------------------------------------------------------


async def test_ac6_yes_flow_ratifies_and_binds() -> None:
    """``yes`` -> SeriesMatch with ``requires_ratification=False``."""
    brain = _brain_with_single_candidate()
    transport = MockAdminTransport()
    transport.script_reply("yes")
    matcher = SeriesMatcher(
        brain_mcp=brain,
        admin_transport=transport,
        ratification_timeout_s=2.0,
    )

    # Stage 1: Path-2 candidate match.
    pending = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=_attendees(),
    )
    assert pending is not None
    assert pending.requires_ratification is True
    assert pending.series_id == "family-council"

    # Stage 2: ratification round-trip via mock TG transport.
    ratified = await matcher.ratify(pending)

    assert ratified is not None
    assert ratified.series_id == "family-council"
    assert ratified.requires_ratification is False
    assert ratified.binding == "implicit-host-cohort"
    assert ratified.confidence == "medium"

    # Mock transport saw the prompt + consumed the scripted reply.
    assert len(transport.posts) == 1
    assert "family-council" in transport.posts[0][1]
    assert transport.replies_consumed == ["yes"]


# ---------------------------------------------------------------------------
# AC-6 -- no flow
# ---------------------------------------------------------------------------


async def test_ac6_no_flow_falls_back_to_default_profile() -> None:
    """``no`` -> ratify returns None; caller uses default profile."""
    brain = _brain_with_single_candidate()
    transport = MockAdminTransport()
    transport.script_reply("no")
    matcher = SeriesMatcher(
        brain_mcp=brain,
        admin_transport=transport,
        ratification_timeout_s=2.0,
    )

    pending = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=_attendees(),
    )
    assert pending is not None
    ratified = await matcher.ratify(pending)
    assert ratified is None

    # Prompt sent, reply consumed -- TG round-trip happened even though
    # the answer was decline.
    assert len(transport.posts) == 1
    assert transport.replies_consumed == ["no"]


# ---------------------------------------------------------------------------
# AC-6 -- new-series flow
# ---------------------------------------------------------------------------


async def test_ac6_new_series_flow_returns_new_match_with_supplied_slug() -> None:
    """``new-series <slug>`` -> new SeriesMatch with the supplied slug."""
    brain = _brain_with_single_candidate()
    transport = MockAdminTransport()
    transport.script_reply("new-series acme-q3-arch")
    matcher = SeriesMatcher(
        brain_mcp=brain,
        admin_transport=transport,
        ratification_timeout_s=2.0,
    )

    pending = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=_attendees(),
    )
    assert pending is not None
    ratified = await matcher.ratify(pending)
    assert ratified is not None
    assert ratified.series_id == "acme-q3-arch"
    assert ratified.binding == "implicit-host-cohort"
    assert ratified.requires_ratification is False
    # cohort_overlap_score carried over from the pending match.
    assert ratified.cohort_overlap_score == pending.cohort_overlap_score


# ---------------------------------------------------------------------------
# AC-6 -- timeout flow
# ---------------------------------------------------------------------------


async def test_ac6_timeout_flow_falls_back_to_default_profile() -> None:
    """Reply arrives later than the ratification budget -> None."""
    brain = _brain_with_single_candidate()
    transport = MockAdminTransport(reply_delay_s=2.0)
    # Reply IS scripted but the delay exceeds the matcher's budget.
    transport.script_reply("yes")
    matcher = SeriesMatcher(
        brain_mcp=brain,
        admin_transport=transport,
        ratification_timeout_s=0.1,  # tight budget < transport delay
    )

    pending = await matcher.match_path_2(
        host_canonical_id="cyril-grosse",
        attendee_canonical_ids=_attendees(),
    )
    assert pending is not None
    ratified = await matcher.ratify(pending)
    assert ratified is None

    # Prompt was sent but the reply never consumed (the receive future was
    # cancelled by the outer wait_for budget).
    assert len(transport.posts) == 1
    assert transport.replies_consumed == []
