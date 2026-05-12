"""W4.1 -- ``ChatThreadActor`` FIFO worker tests.

Spec §7 (lines 856-932) — the per-thread actor drains a bounded FIFO
queue and dispatches to cortex serially via a single worker task. This
test file asserts:

* Three enqueued events are dispatched to ``cortex_call`` in FIFO
  order.
* Reply ``send_chat`` invocations target the correct
  ``sender_user_id`` per event.
* Within one actor, ``cortex_call`` invocations do not overlap
  (single-worker serialization).

The closure-injection pattern (``cortex_call: Callable``) keeps the
actor decoupled from the global semaphore; Part B wires the
semaphore-acquired closure, Part A uses a stub.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant import (
    AssistantConfig,
    ChatEvent,
    ChatThreadActor,
)


def _make_event(*, text: str, sender_user_id: str = "u1") -> ChatEvent:
    """Build a minimal ChatEvent for actor tests."""
    return ChatEvent(
        id=f"evt_{sender_user_id}_{text}",
        meeting_id="mtg_w4",
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id="cyril-grosse",
        sender_canonical_confidence=0.95,
        sender_display_name="Cyril Grosse",
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=True,
    )


def _make_session() -> MagicMock:
    """Session double with async ``send_chat`` + ``send_chat_public``."""
    s = MagicMock()
    s.send_chat = AsyncMock()
    s.send_chat_public = AsyncMock()
    return s


async def test_actor_processes_events_in_fifo_order() -> None:
    """Three sequential enqueues → three cortex calls in submitted order."""
    session = _make_session()
    config = AssistantConfig()
    call_order: list[str] = []

    async def cortex_call(**kwargs: Any) -> MagicMock:
        # Record the user message that triggered this call.
        conv = kwargs["conversation"]
        call_order.append(conv[-1].content)
        result = MagicMock()
        result.text = f"reply to {conv[-1].content}"
        return result

    actor = ChatThreadActor(
        key=("mtg_w4", "cyril-grosse"),
        cortex_call=cortex_call,
        session=session,
        config=config,
        tool_set=[],
        system_prompt_renderer=lambda: "you are Cody",
    )
    actor.start()
    try:
        for text in ("first", "second", "third"):
            ok = await actor.enqueue(_make_event(text=text))
            assert ok is True, f"enqueue failed for {text!r}"

        # Wait for queue to drain.
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    assert call_order == ["first", "second", "third"], call_order

    # Replies sent in same order, all to the original sender.
    send_calls = session.send_chat.await_args_list
    assert len(send_calls) == 3, send_calls
    for call, expected_text in zip(send_calls, ("first", "second", "third"), strict=True):
        assert call.kwargs["to_user_id"] == "u1"
        assert call.kwargs["message"] == f"reply to {expected_text}"


async def test_actor_serializes_cortex_calls_within_single_thread() -> None:
    """Single-worker invariant: cortex calls do not overlap inside one actor.

    We expose this by tracking concurrent-in-flight count and asserting it
    never exceeds 1 across the run of 4 sequential events.
    """
    session = _make_session()
    config = AssistantConfig()
    in_flight = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def cortex_call(**kwargs: Any) -> MagicMock:
        nonlocal in_flight, max_concurrent
        async with lock:
            in_flight += 1
            max_concurrent = max(max_concurrent, in_flight)
        # Simulate a non-trivial cortex round-trip.
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        result = MagicMock()
        result.text = "ok"
        return result

    actor = ChatThreadActor(
        key=("mtg_w4", "cyril-grosse"),
        cortex_call=cortex_call,
        session=session,
        config=config,
        tool_set=[],
        system_prompt_renderer=lambda: "system",
    )
    actor.start()
    try:
        for i in range(4):
            await actor.enqueue(_make_event(text=f"msg{i}"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    assert max_concurrent == 1, f"single-worker invariant breached: max_concurrent={max_concurrent}"


async def test_actor_public_key_uses_send_chat_public() -> None:
    """When ``key[1] == 'public'``, replies route via ``send_chat_public``.

    Spec §7 line 896-902: public-thread actor uses ``send_chat_public``
    (broadcast to room), private actor uses ``send_chat(to_user_id=...)``.
    """
    session = _make_session()
    config = AssistantConfig()

    async def cortex_call(**kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.text = "public reply"
        return result

    actor = ChatThreadActor(
        key=("mtg_w4", "public"),
        cortex_call=cortex_call,
        session=session,
        config=config,
        tool_set=[],
        system_prompt_renderer=lambda: "system",
    )
    actor.start()
    try:
        await actor.enqueue(_make_event(text="hi room"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    session.send_chat_public.assert_awaited_once_with("public reply")
    session.send_chat.assert_not_awaited()


async def test_actor_cortex_unavailable_sends_filler_fallback() -> None:
    """``CortexUnavailable`` raised by ``cortex_call`` → user-facing filler."""
    from lattice_meeting_assistant import CortexUnavailable

    session = _make_session()
    config = AssistantConfig()

    async def cortex_call(**kwargs: Any) -> MagicMock:
        raise CortexUnavailable("simulated outage")

    actor = ChatThreadActor(
        key=("mtg_w4", "cyril-grosse"),
        cortex_call=cortex_call,
        session=session,
        config=config,
        tool_set=[],
        system_prompt_renderer=lambda: "system",
    )
    actor.start()
    try:
        await actor.enqueue(_make_event(text="hi"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    # One reply sent; should be the filler string, not a stack trace.
    session.send_chat.assert_awaited_once()
    sent = session.send_chat.await_args_list[0].kwargs["message"]
    assert "trouble" in sent.lower(), sent


async def test_actor_appends_user_and_assistant_turns_to_history() -> None:
    """After one round-trip, history contains user turn + assistant turn."""
    session = _make_session()
    config = AssistantConfig()

    async def cortex_call(**kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.text = "assistant reply"
        return result

    actor = ChatThreadActor(
        key=("mtg_w4", "cyril-grosse"),
        cortex_call=cortex_call,
        session=session,
        config=config,
        tool_set=[],
        system_prompt_renderer=lambda: "system",
    )
    actor.start()
    try:
        await actor.enqueue(_make_event(text="ping"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    assert len(actor.history_snapshot()) == 2
    roles = [t.role for t in actor.history_snapshot()]
    assert roles == ["user", "assistant"]
    assert actor.history_snapshot()[0].content == "ping"
    assert actor.history_snapshot()[1].content == "assistant reply"
