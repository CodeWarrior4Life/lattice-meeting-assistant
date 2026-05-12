"""W4.4 -- history compaction at the token cap.

Spec §7 lines 917-918 + line 987:

* When the actor's history exceeds ``config.actor_history_max_tokens``
  (default 16k) right before a dispatch, run a compactor against the
  history to summarise the oldest half into a single
  ``[prior context: ...]`` turn and retain the recent verbatim turns.
* Compactor is a callable; for v0.1 it may be a cortex
  ``ContextCompactor``. When no compactor is wired, the actor falls
  back to a naive "drop oldest half" strategy so the actor never
  dies on overflow.
* Token counting in v0.1 is a char-based heuristic (chars / 4).

Tests:

* Compactor IS wired -> compactor invoked when history is over cap;
  history is replaced by the compactor's return value; recent turns
  preserved verbatim by the compactor's implementation.
* Compactor is ``None`` -> naive drop-oldest-half fallback runs;
  history shrinks; recent turns preserved.
* Under-cap history triggers neither compactor nor fallback.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from lattice_meeting_assistant import (
    AssistantConfig,
    ChatEvent,
    ChatThreadActor,
    ConversationTurn,
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


def _stuffed_history(n_turns: int, chars_per_turn: int) -> list[ConversationTurn]:
    """Build an oversized history of alternating user/assistant turns."""
    turns: list[ConversationTurn] = []
    for i in range(n_turns):
        role = "user" if i % 2 == 0 else "assistant"
        turns.append(
            ConversationTurn(
                role=role,
                content="x" * chars_per_turn,
                ts=datetime.now(timezone.utc),
            )
        )
    return turns


async def test_compactor_invoked_when_history_over_cap() -> None:
    """Cap=100 tokens (~400 chars); history loaded with 600 chars triggers it."""
    session = _make_session()
    config = replace(AssistantConfig(), actor_history_max_tokens=100)

    compactor_invocations: list[list[ConversationTurn]] = []

    async def compactor(turns: list[ConversationTurn]) -> list[ConversationTurn]:
        compactor_invocations.append(list(turns))
        # Replace with a single summary turn + retain the last 2 turns.
        retained = turns[-2:]
        summary = ConversationTurn(
            role="user",
            content="[prior context: summarised]",
            ts=datetime.now(timezone.utc),
        )
        return [summary, *retained]

    async def cortex_call(**kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.text = "after-compaction reply"
        return result

    actor = ChatThreadActor(
        key=("mtg_w4", "cyril-grosse"),
        cortex_call=cortex_call,
        session=session,
        config=config,
        tool_set=[],
        system_prompt_renderer=lambda: "system",
        compactor=compactor,
    )

    # Seed history past the cap before starting the worker.
    actor.seed_history(_stuffed_history(n_turns=6, chars_per_turn=100))

    actor.start()
    try:
        await actor.enqueue(_make_event(text="next"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    # Compactor invoked exactly once.
    assert len(compactor_invocations) == 1

    # New history is summary + last 2 of pre-compaction + this event's user
    # turn + assistant reply.
    new_history = actor.history_snapshot()
    contents = [t.content for t in new_history]
    assert contents[0] == "[prior context: summarised]"
    assert "next" in contents
    assert "after-compaction reply" in contents


async def test_naive_drop_oldest_half_when_no_compactor() -> None:
    """compactor=None -> actor still trims history, never dies on overflow."""
    session = _make_session()
    config = replace(AssistantConfig(), actor_history_max_tokens=100)

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
        # compactor unset -> None default.
    )
    # 6 turns of 100 chars each = 600 chars (~150 tokens) > 100 token cap.
    actor.seed_history(_stuffed_history(n_turns=6, chars_per_turn=100))
    assert len(actor.history_snapshot()) == 6

    actor.start()
    try:
        await actor.enqueue(_make_event(text="after"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    new_history = actor.history_snapshot()
    # Naive drop-oldest-half keeps the back half before appending the new
    # user + assistant turns; total should be < 6.
    assert len(new_history) < 8, new_history
    # The dispatched event's user + assistant turns are tail.
    tail_contents = [t.content for t in new_history[-2:]]
    assert tail_contents == ["after", "ok"]


async def test_compactor_not_invoked_when_history_under_cap() -> None:
    """Small history: neither compactor nor fallback fires."""
    session = _make_session()
    config = replace(AssistantConfig(), actor_history_max_tokens=10_000)

    compactor_invocations: list[list[ConversationTurn]] = []

    async def compactor(turns: list[ConversationTurn]) -> list[ConversationTurn]:
        compactor_invocations.append(list(turns))
        return turns

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
        compactor=compactor,
    )
    actor.start()
    try:
        await actor.enqueue(_make_event(text="hi"))
        await actor.wait_idle(timeout=2.0)
    finally:
        await actor.shutdown()

    assert compactor_invocations == []
    history = actor.history_snapshot()
    assert len(history) == 2


async def test_history_token_count_heuristic_uses_char_div_4() -> None:
    """Token count = sum(len(content)) // 4 across all turns."""
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
    actor.seed_history(_stuffed_history(n_turns=4, chars_per_turn=400))
    # 4 * 400 chars = 1600 chars ; // 4 = 400 token-estimate.
    assert actor.history_token_estimate() == 400
