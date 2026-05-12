"""W4.2 -- holding-message race tests.

Spec §7 lines 934-954: when ``cortex_call`` does not return within
``config.holding_message_after_ms``, the actor sends a filler stall
message AND continues to await the real reply (which is then sent
when it eventually arrives).

Critical correctness requirements (per dispatch prompt):

* The dispatch task is NOT cancelled by the wait_for race; the real
  reply must still arrive.
* Two ``send_chat`` invocations are observed when the dispatch is
  slow -- one filler, then the real reply.
* When the dispatch is fast (< holding threshold), only one reply is
  sent (the real one). No filler.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
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


async def test_slow_dispatch_sends_filler_then_real_reply() -> None:
    """Cortex takes longer than threshold → filler first, real reply after.

    Verifies the wait_for race does NOT cancel the dispatch task.
    """
    session = _make_session()
    # Threshold low enough to fire reliably in unit test (50ms);
    # cortex call deliberately slower (200ms).
    config = replace(AssistantConfig(), holding_message_after_ms=50)

    async def cortex_call(**kwargs: Any) -> MagicMock:
        await asyncio.sleep(0.2)
        result = MagicMock()
        result.text = "real reply"
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

    sent = session.send_chat.await_args_list
    assert len(sent) == 2, f"expected 2 sends (filler + real), got {len(sent)}"

    first_msg = sent[0].kwargs["message"]
    second_msg = sent[1].kwargs["message"]
    # Filler is the "one_moment" stall string; real reply differs.
    assert "one moment" in first_msg.lower(), first_msg
    assert second_msg == "real reply"
    assert first_msg != second_msg
    # Both replies routed to the original sender.
    assert sent[0].kwargs["to_user_id"] == "u1"
    assert sent[1].kwargs["to_user_id"] == "u1"


async def test_fast_dispatch_skips_filler() -> None:
    """Cortex returns before threshold → no filler, only real reply."""
    session = _make_session()
    # Threshold high; cortex returns immediately.
    config = replace(AssistantConfig(), holding_message_after_ms=1000)

    async def cortex_call(**kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.text = "quick reply"
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

    sent = session.send_chat.await_args_list
    assert len(sent) == 1, sent
    assert sent[0].kwargs["message"] == "quick reply"


async def test_slow_dispatch_for_public_thread_uses_send_chat_public() -> None:
    """Public-thread filler + real reply both broadcast via send_chat_public."""
    session = _make_session()
    config = replace(AssistantConfig(), holding_message_after_ms=50)

    async def cortex_call(**kwargs: Any) -> MagicMock:
        await asyncio.sleep(0.15)
        result = MagicMock()
        result.text = "real public reply"
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

    public_sends = session.send_chat_public.await_args_list
    assert len(public_sends) == 2, public_sends
    assert "one moment" in public_sends[0].args[0].lower()
    assert public_sends[1].args[0] == "real public reply"
    # Never routed to the private path.
    session.send_chat.assert_not_awaited()


async def test_real_reply_history_recorded_after_slow_dispatch() -> None:
    """Even when filler fires, history still gets user + real assistant turn.

    The filler is a fire-and-forget UX nudge, not a turn -- it should
    not be appended to history.
    """
    session = _make_session()
    config = replace(AssistantConfig(), holding_message_after_ms=50)

    async def cortex_call(**kwargs: Any) -> MagicMock:
        await asyncio.sleep(0.15)
        result = MagicMock()
        result.text = "the real answer"
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
        await actor.enqueue(_make_event(text="hi"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    history = actor.history_snapshot()
    assert len(history) == 2, history
    assert history[0].role == "user"
    assert history[0].content == "hi"
    assert history[1].role == "assistant"
    assert history[1].content == "the real answer"
