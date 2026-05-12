"""W4.5 -- actor lifecycle (idle marker + drain + shutdown).

Spec §7 lines 977-987 (lifecycle table):

* Sender leaves meeting -> ``mark_idle`` sets ``_idle_since=now()``
  and the actor-pool starts a 60s reap timer.
* Sender rejoins within 60s -> ``cancel_idle`` clears the marker; same
  actor continues.
* 60s reap fires -> drain queue, cancel worker, remove from pool.
* Meeting ends -> drain all queues with a 30s timeout; cancel workers.

The actor-pool coordination (timer scheduling + pool removal) lives
in :class:`Assistant` (Part B / W4.6). The actor itself exposes the
primitives:

* ``mark_idle()`` / ``cancel_idle()`` / ``is_idle_for(secs)``
* ``async drain(timeout_s)`` -- wait for queue empty + worker done.
* ``async shutdown()`` -- cancel worker, await its cancellation.

These are the surfaces Part B will call from the pool's reap timer
and from ``Assistant.shutdown``.
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
from lattice_meeting_assistant.actor import POST_LEAVE_GRACE_SECS_DEFAULT


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


def _make_actor(*, config: AssistantConfig | None = None) -> ChatThreadActor:
    cfg = config or AssistantConfig()
    session = _make_session()

    async def cortex_call(**kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.text = "ok"
        return result

    return ChatThreadActor(
        key=("mtg_w4", "cyril-grosse"),
        cortex_call=cortex_call,
        session=session,
        config=cfg,
        tool_set=[],
        system_prompt_renderer=lambda: "system",
    )


async def test_mark_idle_records_loop_time_and_is_idle_for_threshold(
    monkeypatch: Any,
) -> None:
    """``mark_idle`` + ``is_idle_for`` measure elapsed time on the loop clock."""
    actor = _make_actor()

    # Patch the loop clock so we can simulate time advancing.
    fake_now = {"t": 1000.0}

    def fake_loop_time() -> float:
        return fake_now["t"]

    loop = asyncio.get_event_loop()
    monkeypatch.setattr(loop, "time", fake_loop_time)

    actor.mark_idle()
    assert actor.idle_since == 1000.0
    assert actor.is_idle_for(0.0) is True
    assert actor.is_idle_for(60.0) is False

    fake_now["t"] = 1060.5
    assert actor.is_idle_for(60.0) is True


async def test_cancel_idle_clears_marker() -> None:
    """``cancel_idle`` after ``mark_idle`` clears the marker."""
    actor = _make_actor()
    actor.mark_idle()
    assert actor.idle_since is not None
    actor.cancel_idle()
    assert actor.idle_since is None
    # ``is_idle_for`` always False when no marker.
    assert actor.is_idle_for(0.0) is False


async def test_is_idle_for_false_when_never_marked() -> None:
    """Without ``mark_idle``, ``is_idle_for`` always returns False."""
    actor = _make_actor()
    assert actor.idle_since is None
    assert actor.is_idle_for(0.0) is False
    assert actor.is_idle_for(1_000.0) is False


async def test_drain_returns_when_queue_empties() -> None:
    """``drain`` returns once the queue is empty and worker is idle."""
    actor = _make_actor()
    actor.start()
    try:
        for i in range(3):
            await actor.enqueue(_make_event(text=f"m{i}"))
        await actor.drain(timeout_s=2.0)
    finally:
        await actor.shutdown()

    assert actor.queue_depth == 0


async def test_drain_times_out_when_worker_stuck() -> None:
    """``drain`` raises ``asyncio.TimeoutError`` when the worker is blocked."""
    session = _make_session()
    cfg = AssistantConfig()
    gate = asyncio.Event()

    async def cortex_call(**kwargs: Any) -> MagicMock:
        await gate.wait()
        result = MagicMock()
        result.text = "ok"
        return result

    actor = ChatThreadActor(
        key=("mtg_w4", "cyril-grosse"),
        cortex_call=cortex_call,
        session=session,
        config=cfg,
        tool_set=[],
        system_prompt_renderer=lambda: "system",
    )
    actor.start()
    try:
        await actor.enqueue(_make_event(text="hang"))
        # Worker is stuck waiting on the gate -- drain must time out.
        try:
            await actor.drain(timeout_s=0.1)
            raise AssertionError("drain should have timed out")
        except asyncio.TimeoutError:
            pass
    finally:
        gate.set()
        await actor.shutdown()


async def test_shutdown_cancels_worker_cleanly() -> None:
    """``shutdown`` cancels the worker task and leaves no zombies."""
    actor = _make_actor()
    actor.start()
    # Snapshot the worker reference.
    worker = actor._worker
    assert worker is not None
    assert not worker.done()

    await actor.shutdown()
    assert actor._worker is None
    assert worker.done()
    # CancelledError or completed normally; not a re-raised user exception.
    assert worker.cancelled() or worker.exception() is None


async def test_post_leave_grace_secs_default_matches_config() -> None:
    """Module constant equals the ``actor_post_leave_grace_s`` default.

    Part B / W4.6 reads this constant when scheduling the pool's reap
    timer; defending its value here prevents config drift.
    """
    assert POST_LEAVE_GRACE_SECS_DEFAULT == AssistantConfig().actor_post_leave_grace_s


async def test_shutdown_is_idempotent() -> None:
    """Calling ``shutdown`` twice is safe (second call is a no-op)."""
    actor = _make_actor()
    actor.start()
    await actor.shutdown()
    # Second shutdown should not raise.
    await actor.shutdown()
    assert actor._worker is None


async def test_start_is_idempotent() -> None:
    """Calling ``start`` twice does not spawn a second worker."""
    actor = _make_actor()
    actor.start()
    first = actor._worker
    actor.start()
    assert actor._worker is first
    await actor.shutdown()
