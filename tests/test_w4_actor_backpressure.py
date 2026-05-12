"""W4.3 -- queue-full backpressure (actor-side).

Spec §7 line 883-889: ``enqueue`` returns ``False`` on
``asyncio.QueueFull`` so the caller can surface a backpressure reply.
This test file covers the actor-side guarantees:

* With ``per_thread_queue_depth=5`` (the default), 5 enqueues succeed
  while the worker is paused.
* The 6th enqueue while the queue is full returns ``False`` without
  raising.
* When the worker resumes, the original 5 events are processed in
  FIFO order.
* ``queue_depth`` + ``is_queue_full`` predicates report accurate state
  during the burst.

The Assistant-side ``on_private_chat`` backpressure reply path is
W4.6 / Part B and is NOT exercised here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from lattice_meeting_assistant import (
    AssistantConfig,
    ChatEvent,
    ChatThreadActor,
)


def _make_event(*, text: str, sender_user_id: str = "u1") -> ChatEvent:
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
    s = MagicMock()
    s.send_chat = AsyncMock()
    s.send_chat_public = AsyncMock()
    return s


async def test_enqueue_returns_false_when_queue_full() -> None:
    """6th enqueue on a depth-5 actor returns ``False``; 1-5 still process.

    The actor is held in 'paused' state by a gate the cortex stub awaits
    before returning. We fill the queue while paused, observe the
    backpressure signal, then release and verify FIFO drain.
    """
    session = _make_session()
    config = AssistantConfig()  # per_thread_queue_depth=5

    cortex_gate = asyncio.Event()
    processed: list[str] = []

    async def cortex_call(**kwargs: Any) -> MagicMock:
        # Hold the in-flight call until the test releases the gate.
        await cortex_gate.wait()
        conv = kwargs["conversation"]
        processed.append(conv[-1].content)
        result = MagicMock()
        result.text = f"done {conv[-1].content}"
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
        # Submit msg0; the worker picks it up immediately and blocks on
        # the gate. Wait briefly for the worker to pull it off the queue.
        ok = await actor.enqueue(_make_event(text="msg0"))
        assert ok is True
        # Spin until the worker has dequeued msg0 so the queue capacity
        # frees up for the burst.
        for _ in range(100):
            if actor.queue_depth == 0:
                break
            await asyncio.sleep(0.005)
        assert actor.queue_depth == 0

        # Now fill the queue (depth=5) plus one extra.
        for i in range(1, 6):
            ok = await actor.enqueue(_make_event(text=f"msg{i}"))
            assert ok is True, f"enqueue {i} failed"
        # Queue is full at depth=5.
        assert actor.queue_depth == 5
        assert actor.is_queue_full is True

        # 6th enqueue while queue full -> False.
        ok6 = await actor.enqueue(_make_event(text="msg6"))
        assert ok6 is False
        # Predicate still True.
        assert actor.is_queue_full is True
        assert actor.queue_depth == 5

        # Release the worker and let it drain.
        cortex_gate.set()
        await actor.wait_idle(timeout=2.0)
    finally:
        cortex_gate.set()
        await actor.shutdown()

    # msg0..msg5 in FIFO order; msg6 was rejected and never processed.
    assert processed == [
        "msg0",
        "msg1",
        "msg2",
        "msg3",
        "msg4",
        "msg5",
    ], processed


async def test_queue_depth_reports_zero_when_idle() -> None:
    """Idle actor reports ``queue_depth == 0`` and ``is_queue_full == False``."""
    session = _make_session()
    config = AssistantConfig()

    async def cortex_call(**kwargs: Any) -> MagicMock:
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
    # Before start: zero, not full.
    assert actor.queue_depth == 0
    assert actor.is_queue_full is False

    actor.start()
    try:
        await actor.enqueue(_make_event(text="x"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    # Drained back to zero.
    assert actor.queue_depth == 0
    assert actor.is_queue_full is False


async def test_full_queue_resumes_after_drain() -> None:
    """After a full burst drains, a fresh enqueue succeeds again."""
    session = _make_session()
    config = AssistantConfig()

    cortex_gate = asyncio.Event()

    async def cortex_call(**kwargs: Any) -> MagicMock:
        await cortex_gate.wait()
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
        # First message is pulled by worker; wait for it to dequeue.
        await actor.enqueue(_make_event(text="m0"))
        for _ in range(100):
            if actor.queue_depth == 0:
                break
            await asyncio.sleep(0.005)
        # Fill to depth=5.
        for i in range(1, 6):
            await actor.enqueue(_make_event(text=f"m{i}"))
        # 6th rejected.
        assert (await actor.enqueue(_make_event(text="rejected"))) is False

        # Drain.
        cortex_gate.set()
        await actor.wait_idle(timeout=2.0)

        # Fresh enqueue succeeds now that worker has caught up.
        cortex_gate.clear()
        ok = await actor.enqueue(_make_event(text="post-drain"))
        assert ok is True
        cortex_gate.set()
        await actor.wait_idle(timeout=2.0)
    finally:
        cortex_gate.set()
        await actor.shutdown()
