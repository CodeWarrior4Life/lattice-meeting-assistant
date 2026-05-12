"""W4.6 Step 2 -- Assistant on_private_chat routing, lifecycle, shutdown.

Spec §7 lines 958-987 + 989-995:

* ``on_private_chat`` enforces Invariant 4 fail-closed at ingest
  (missing ``is_private`` -> ``PrivacyBoundaryViolation``).
* ``on_private_chat`` consults the allowlist (W4 stub returns True;
  W5 lands the real tier check).
* ``on_private_chat`` spawns a fresh ``ChatThreadActor`` for an unknown
  ``(meeting, persona)`` key and reuses an existing one on the next
  event from the same sender.
* ``on_private_chat`` surfaces a backpressure reply via
  ``session.send_chat(to_user_id=, message=...)`` when the actor's
  per-thread queue is full (``enqueue`` returned ``False``).
* Lifecycle: ``on_participant_left`` marks the actor idle + schedules a
  ``POST_LEAVE_GRACE_SECS_DEFAULT`` reap timer; ``on_participant_joined``
  cancels the timer and clears the idle marker.
* ``shutdown`` drains every actor in the pool with a bounded timeout
  and removes them all.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant import (
    Assistant,
    AssistantConfig,
    AssistantProfile,
    ChatEvent,
    KnowledgeAccessConfig,
    PrivacyBoundaryViolation,
)
from lattice_meeting_assistant.actor import POST_LEAVE_GRACE_SECS_DEFAULT
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


def _make_registry(*, reply_text: str = "ok") -> MagicMock:
    """Build a cortex-registry-shaped mock whose ``.call`` returns a stub."""
    r = MagicMock()
    reply = MagicMock()
    reply.text = reply_text
    r.call = AsyncMock(return_value=reply)
    return r


def _make_event(
    *,
    sender_user_id: str = "u1",
    sender_canonical_id: str = "cyril-grosse",
    meeting_id: str = "m1",
    text: str = "hi",
    is_private: bool | None = True,
) -> Any:
    """Build a ChatEvent OR a minimal duck-typed substitute when
    ``is_private`` is missing.

    For the fail-closed test path we cannot construct a real
    :class:`ChatEvent` with ``is_private=None`` because the dataclass
    field is typed ``bool``. Tests that need a missing/None tag use the
    ``_BadEvent`` sentinel class below.
    """
    assert is_private is not None
    return ChatEvent(
        id=f"evt_{sender_user_id}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=sender_canonical_id,
        sender_canonical_confidence=0.95,
        sender_display_name=sender_user_id,
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=is_private,
    )


class _BadEventMissingTag:
    """Stand-in event that lacks the ``is_private`` attribute entirely.

    Used to exercise the :func:`enforce_visibility_tag` short-circuit at
    the top of ``on_private_chat`` (Architectural Invariant 4).
    """

    id = "evt_bad_missing"
    meeting_id = "m1"
    sender_user_id = "u1"
    sender_canonical_id = "cyril-grosse"
    text = "hi"


class _BadEventNoneTag:
    """Stand-in event whose ``is_private`` is explicitly ``None``."""

    id = "evt_bad_none"
    meeting_id = "m1"
    sender_user_id = "u1"
    sender_canonical_id = "cyril-grosse"
    text = "hi"
    is_private = None


def _make_assistant(
    *,
    registry: MagicMock | None = None,
    session: MagicMock | None = None,
    config: AssistantConfig | None = None,
) -> Assistant:
    asst = Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=config or AssistantConfig(),
        profile=_make_profile(),
        session=session or _make_session(),
        cortex_registry=registry or _make_registry(),
    )
    asst.start()
    return asst


# ---------------------------------------------------------------------------
# Invariant 4 fail-closed at ingest
# ---------------------------------------------------------------------------


async def test_on_private_chat_raises_on_missing_visibility_tag() -> None:
    """Missing ``is_private`` -> ``PrivacyBoundaryViolation`` (Inv 4)."""
    asst = _make_assistant()
    try:
        with pytest.raises(PrivacyBoundaryViolation, match="is_private"):
            await asst.on_private_chat(_BadEventMissingTag())
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_on_private_chat_raises_on_none_visibility_tag() -> None:
    """``is_private=None`` -> ``PrivacyBoundaryViolation`` (Inv 4)."""
    asst = _make_assistant()
    try:
        with pytest.raises(PrivacyBoundaryViolation, match="is_private"):
            await asst.on_private_chat(_BadEventNoneTag())
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


# ---------------------------------------------------------------------------
# Spawn-on-first-message + reuse-on-second
# ---------------------------------------------------------------------------


async def test_on_private_chat_spawns_actor_for_unknown_sender() -> None:
    """First event from a sender spawns a new actor; second reuses it."""
    registry = _make_registry()
    asst = _make_assistant(registry=registry)
    try:
        ev1 = _make_event(sender_user_id="u1", text="first")
        await asst.on_private_chat(ev1)
        assert ("m1", "cyril-grosse") in asst._actors
        first_actor = asst._actors[("m1", "cyril-grosse")]

        # Second event from same sender -> reuse, no new actor.
        ev2 = _make_event(sender_user_id="u1", text="second")
        await asst.on_private_chat(ev2)
        assert asst._actors[("m1", "cyril-grosse")] is first_actor
        assert len(asst._actors) == 1

        # Let the worker drain.
        await first_actor.drain(timeout_s=2.0)
        assert registry.call.await_count == 2
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_on_private_chat_spawns_distinct_actor_per_sender() -> None:
    """Two senders -> two distinct actors with distinct keys."""
    registry = _make_registry()
    asst = _make_assistant(registry=registry)
    try:
        await asst.on_private_chat(_make_event(sender_user_id="u1", sender_canonical_id="alice"))
        await asst.on_private_chat(_make_event(sender_user_id="u2", sender_canonical_id="bob"))
        assert ("m1", "alice") in asst._actors
        assert ("m1", "bob") in asst._actors
        assert asst._actors[("m1", "alice")] is not asst._actors[("m1", "bob")]

        for actor in asst._actors.values():
            await actor.drain(timeout_s=2.0)
        assert registry.call.await_count == 2
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


# ---------------------------------------------------------------------------
# Backpressure surface
# ---------------------------------------------------------------------------


async def test_on_private_chat_surfaces_backpressure_reply_when_queue_full() -> None:
    """Queue-full -> Assistant sends a "catching up" reply via send_chat."""
    session = _make_session()
    config = AssistantConfig()  # per_thread_queue_depth=5

    cortex_gate = asyncio.Event()
    registry = MagicMock()

    async def fake_call(**kwargs: Any) -> MagicMock:
        await cortex_gate.wait()
        result = MagicMock()
        result.text = "ok"
        return result

    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session, config=config)

    try:
        # First message: worker picks it up immediately and blocks on the
        # gate; the queue empties momentarily. Wait for that to happen so
        # the next 5 messages all land in the queue cleanly.
        await asst.on_private_chat(_make_event(sender_user_id="u1", text="msg0"))
        actor = asst._actors[("m1", "cyril-grosse")]
        for _ in range(100):
            if actor.queue_depth == 0:
                break
            await asyncio.sleep(0.005)
        assert actor.queue_depth == 0

        # Now fill the queue to depth=5.
        for i in range(1, 6):
            await asst.on_private_chat(_make_event(sender_user_id="u1", text=f"msg{i}"))
        assert actor.queue_depth == 5
        # No backpressure reply yet -- everything fit.
        assert session.send_chat.await_count == 0

        # 7th event while queue is full -> backpressure reply.
        await asst.on_private_chat(_make_event(sender_user_id="u1", text="overflow"))

        # send_chat called once with the catching-up reply, addressed to
        # the actual sender_user_id.
        session.send_chat.assert_awaited_once()
        sent = session.send_chat.await_args_list[0]
        assert sent.kwargs["to_user_id"] == "u1"
        assert "catching up" in sent.kwargs["message"].lower()

        # Release gate; let the actor drain so shutdown completes.
        cortex_gate.set()
        await actor.drain(timeout_s=2.0)
    finally:
        cortex_gate.set()
        await asst.shutdown(drain_timeout_s=2.0)


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------


async def test_on_participant_left_schedules_reap_timer() -> None:
    """Leave event marks actor idle + schedules a reap timer."""
    asst = _make_assistant()
    try:
        await asst.on_private_chat(_make_event(sender_user_id="u1", sender_canonical_id="alice"))
        key = ("m1", "alice")
        actor = asst._actors[key]
        await actor.drain(timeout_s=2.0)

        await asst.on_participant_left("alice")
        assert actor.idle_since is not None
        assert key in asst._reap_timers
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_on_participant_joined_cancels_reap_timer() -> None:
    """Rejoin clears idle marker + cancels the pending reap timer."""
    asst = _make_assistant()
    try:
        await asst.on_private_chat(_make_event(sender_user_id="u1", sender_canonical_id="alice"))
        key = ("m1", "alice")
        actor = asst._actors[key]
        await actor.drain(timeout_s=2.0)

        await asst.on_participant_left("alice")
        timer = asst._reap_timers[key]
        assert not timer.cancelled()

        await asst.on_participant_joined("alice")
        assert actor.idle_since is None
        assert key not in asst._reap_timers
        # The timer we captured was actually cancelled.
        assert timer.cancelled()
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_post_leave_grace_default_constant() -> None:
    """Module constant is sourced from the actor module and is 60s.

    Defends against drift between :mod:`actor` and :mod:`assistant`.
    """
    assert POST_LEAVE_GRACE_SECS_DEFAULT == AssistantConfig().actor_post_leave_grace_s


# ---------------------------------------------------------------------------
# shutdown drains all actors
# ---------------------------------------------------------------------------


async def test_shutdown_drains_all_actors() -> None:
    """``shutdown`` empties the actor pool + clears reap timers."""
    asst = _make_assistant()
    try:
        for sender in ("alice", "bob", "carol"):
            await asst.on_private_chat(
                _make_event(sender_user_id=f"u_{sender}", sender_canonical_id=sender)
            )
        # All 3 actors enqueued.
        assert len(asst._actors) == 3
        # Schedule a leave for one to seed a reap timer.
        await asst.on_participant_left("alice")
        assert ("m1", "alice") in asst._reap_timers
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Pool is empty, timers cleared.
    assert asst._actors == {}
    assert asst._reap_timers == {}
