"""W4.6 Step 1 -- global semaphore caps simultaneous cortex calls.

Spec §7 lines 989-995 (Layer 3 -- Global Semaphore): the
:class:`Assistant` owns a single ``asyncio.Semaphore`` keyed on
``config.per_meeting_global_concurrency`` (default ``4``). Every
``cortex_call`` issued by every actor in the meeting must acquire that
semaphore. With ``N`` actors in flight, at most
``per_meeting_global_concurrency`` round-trips run concurrently; the
rest queue.

This test arms 10 actors via the public ``on_private_chat`` ingest path
(different senders -> different actor pool entries) and observes the
high-water mark of *concurrent* cortex calls. The cortex stub bumps a
counter on entry, sleeps long enough for the burst to overlap, then
decrements on exit. The assertion is exact: ``max_concurrent == 4``
(the cap), not "<= 4" -- with 10 inflight events and a sleep that
forces serialization on the cap, the semaphore MUST saturate.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from lattice_meeting_assistant import (
    Assistant,
    AssistantConfig,
    AssistantProfile,
    ChatEvent,
    KnowledgeAccessConfig,
)
from lattice_meeting_assistant.brain_client import BrainMCPClient


def _make_profile() -> AssistantProfile:
    knowledge = KnowledgeAccessConfig(
        allow_personal_vault=False,
        enable_past_meetings_search=True,
        enable_public_references_tool=True,
        enable_web_search=True,
        public_references=("References/",),
    )
    return AssistantProfile(
        profile_id="test-profile",
        series_id="series-x",
        dm_allowlist=("cyril-grosse",),
        admins=("cyril-grosse",),
        knowledge=knowledge,
    )


def _make_session() -> MagicMock:
    s = MagicMock()
    s.send_chat = AsyncMock()
    s.send_chat_public = AsyncMock()
    return s


def _make_event(*, sender_user_id: str, text: str = "hi", meeting_id: str = "m1") -> ChatEvent:
    return ChatEvent(
        id=f"evt_{sender_user_id}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=f"persona-{sender_user_id}",
        sender_canonical_confidence=0.95,
        sender_display_name=sender_user_id,
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=True,
    )


async def test_global_semaphore_caps_concurrent_cortex_calls() -> None:
    """10 actors firing simultaneously -> at most 4 cortex calls in flight.

    The Assistant injects a wrapping closure around the supplied
    ``cortex_registry.call`` that acquires the semaphore before
    delegating, so the cap is enforced uniformly across actors.
    """
    config = AssistantConfig()  # per_meeting_global_concurrency=4

    in_flight = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def fake_call(**kwargs: Any) -> MagicMock:
        nonlocal in_flight, max_concurrent
        async with lock:
            in_flight += 1
            max_concurrent = max(max_concurrent, in_flight)
        # Hold long enough that the burst actually overlaps; 50ms is far
        # longer than the actor's enqueue + worker pickup.
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        result = MagicMock()
        result.text = "ok"
        return result

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=config,
        profile=_make_profile(),
        session=_make_session(),
        cortex_registry=registry,
    )
    asst.start()

    try:
        # Fire 10 private chats from 10 distinct senders -- each spawns
        # its own actor, all share the Assistant's global semaphore.
        for i in range(10):
            await asst.on_private_chat(_make_event(sender_user_id=f"u{i}"))

        # Wait for the burst to drain.
        for _ in range(400):
            if registry.call.await_count >= 10:
                break
            await asyncio.sleep(0.01)
    finally:
        await asst.shutdown(drain_timeout_s=5.0)

    assert registry.call.await_count == 10, registry.call.await_count
    assert max_concurrent == config.per_meeting_global_concurrency, (
        f"Global semaphore failed to cap concurrency: max_concurrent="
        f"{max_concurrent}, cap={config.per_meeting_global_concurrency}"
    )


async def test_global_semaphore_value_matches_config() -> None:
    """The Assistant constructs its semaphore with the configured cap.

    Probes ``_global_semaphore._value`` (the unused-permits counter) at
    rest. CPython's :class:`asyncio.Semaphore` exposes the available
    permits via the private ``_value`` attribute; this is the standard
    inspection hook used by the asyncio test suite.
    """
    config = AssistantConfig(per_meeting_global_concurrency=7)

    asst = Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=config,
        profile=_make_profile(),
        session=_make_session(),
        cortex_registry=MagicMock(),
    )
    # Available permits before any cortex call has acquired one == cap.
    assert asst._global_semaphore._value == 7  # type: ignore[attr-defined]
