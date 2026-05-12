"""W5.1 -- T1/T2/T3 allowlist tier enforcement.

Spec §5 line 1009 + spec §7 lines 958-975:

* **T1 (explicit allowlist hit):** ``sender_canonical_id`` appears in
  ``profile.dm_allowlist`` -- allow unconditionally. Confidence is not
  consulted; explicit listing is final.
* **T2 (mapped persona >= confidence threshold):** ``sender_canonical_id``
  resolves AND ``sender_canonical_confidence >= profile.dm_min_confidence``
  (default 0.85). Allow.
* **T3 (unresolved / anonymous / below threshold):** any of:
  ``sender_canonical_id is None``, ``confidence is None``, or
  ``confidence < dm_min_confidence``. Default-deny -- silent (no reply,
  no spam per spec §7 line 966).

The W5 backfill replaces the W4 stub ``Assistant._is_allowed`` (which
returned True unconditionally). ``on_private_chat`` now passes the
canonical id + confidence into the gate; on deny it returns silently
without spawning an actor or routing to ``send_chat``.
"""

from __future__ import annotations

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
)
from lattice_meeting_assistant.brain_client import BrainMCPClient


def _make_knowledge() -> KnowledgeAccessConfig:
    return KnowledgeAccessConfig(
        allow_personal_vault=False,
        enable_past_meetings_search=True,
        enable_public_references_tool=True,
        enable_web_search=True,
        public_references=("References/",),
    )


def _make_profile(
    *,
    dm_allowlist: tuple[str, ...] = (),
    dm_min_confidence: float = 0.85,
    admins: tuple[str, ...] = (),
) -> AssistantProfile:
    return AssistantProfile(
        profile_id="test-profile",
        series_id="series-x",
        dm_allowlist=dm_allowlist,
        admins=admins,
        knowledge=_make_knowledge(),
        dm_min_confidence=dm_min_confidence,
    )


def _make_session() -> MagicMock:
    s = MagicMock()
    s.send_chat = AsyncMock()
    s.send_chat_public = AsyncMock()
    return s


def _make_registry() -> MagicMock:
    r = MagicMock()
    reply = MagicMock()
    reply.text = "ok"
    r.call = AsyncMock(return_value=reply)
    return r


def _make_assistant(
    *,
    profile: AssistantProfile,
    registry: MagicMock | None = None,
    session: MagicMock | None = None,
    config: AssistantConfig | None = None,
) -> Assistant:
    asst = Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=config or AssistantConfig(),
        profile=profile,
        session=session or _make_session(),
        cortex_registry=registry or _make_registry(),
    )
    asst.start()
    return asst


def _event(
    *,
    sender_canonical_id: str | None,
    sender_canonical_confidence: float | None,
    sender_user_id: str = "u1",
    meeting_id: str = "m1",
    text: str = "hi",
    is_private: bool = True,
) -> ChatEvent:
    return ChatEvent(
        id=f"evt_{sender_user_id}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=sender_canonical_id,
        sender_canonical_confidence=sender_canonical_confidence,
        sender_display_name=sender_canonical_id or "Anonymous Joiner",
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=is_private,
    )


# ---------------------------------------------------------------------------
# Unit-level: ``Assistant._is_allowed`` semantics
# ---------------------------------------------------------------------------


def test_is_allowed_t1_explicit_listing_allows_regardless_of_confidence() -> None:
    """T1 -- ``sender_canonical_id`` in ``dm_allowlist`` allows even at low confidence."""
    profile = _make_profile(dm_allowlist=("user-x",))
    asst = _make_assistant(profile=profile)
    try:
        # Confidence below threshold but explicit listing wins.
        assert asst._is_allowed("user-x", confidence=0.1) is True
        # Even None confidence with explicit listing -> allow.
        assert asst._is_allowed("user-x", confidence=None) is True
    finally:
        pass  # no shutdown -- _is_allowed is sync, no actor spawned


def test_is_allowed_t2_mapped_persona_above_threshold_allows() -> None:
    """T2 -- mapped persona + confidence >= threshold allows."""
    profile = _make_profile(dm_allowlist=(), dm_min_confidence=0.85)
    asst = _make_assistant(profile=profile)
    try:
        assert asst._is_allowed("user-y", confidence=0.90) is True
        assert asst._is_allowed("user-y", confidence=0.85) is True  # at threshold
    finally:
        pass


def test_is_allowed_t2_negative_below_threshold_denies() -> None:
    """T2 negative -- mapped persona but confidence < threshold denies."""
    profile = _make_profile(dm_allowlist=(), dm_min_confidence=0.85)
    asst = _make_assistant(profile=profile)
    try:
        assert asst._is_allowed("user-y", confidence=0.50) is False
        assert asst._is_allowed("user-y", confidence=0.84) is False
    finally:
        pass


def test_is_allowed_t3_unresolved_canonical_id_denies() -> None:
    """T3 -- ``sender_canonical_id`` is None -> default-deny."""
    profile = _make_profile(dm_allowlist=("user-x",))
    asst = _make_assistant(profile=profile)
    try:
        assert asst._is_allowed(None, confidence=None) is False
        assert asst._is_allowed(None, confidence=0.99) is False
    finally:
        pass


def test_is_allowed_t3_missing_confidence_denies() -> None:
    """T3 -- resolved id but confidence None denies (no signal to trust)."""
    profile = _make_profile(dm_allowlist=())
    asst = _make_assistant(profile=profile)
    try:
        assert asst._is_allowed("user-z", confidence=None) is False
    finally:
        pass


# ---------------------------------------------------------------------------
# Integration: ``on_private_chat`` denies silently (no reply, no actor)
# ---------------------------------------------------------------------------


async def test_on_private_chat_silently_denies_t3_event() -> None:
    """Denied event -> no actor spawned, no send_chat, no cortex.call.

    Per spec §7 line 966: ``return # silent deny - no reply, no spam``.
    """
    profile = _make_profile(dm_allowlist=())
    session = _make_session()
    registry = _make_registry()
    asst = _make_assistant(profile=profile, session=session, registry=registry)
    try:
        ev = _event(sender_canonical_id=None, sender_canonical_confidence=None)
        await asst.on_private_chat(ev)

        # No actor spawned.
        assert len(asst._actors) == 0
        # No reply sent.
        assert session.send_chat.await_count == 0
        # No cortex call.
        assert registry.call.await_count == 0
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_on_private_chat_routes_allowed_t1_event_to_actor() -> None:
    """T1 allowlist hit -> actor spawned, cortex called, history grows."""
    profile = _make_profile(dm_allowlist=("user-x",))
    session = _make_session()
    registry = _make_registry()
    asst = _make_assistant(profile=profile, session=session, registry=registry)
    try:
        ev = _event(sender_canonical_id="user-x", sender_canonical_confidence=0.1)
        await asst.on_private_chat(ev)
        # Actor created.
        assert ("m1", "user-x") in asst._actors
        actor = asst._actors[("m1", "user-x")]
        await actor.drain(timeout_s=2.0)
        assert registry.call.await_count == 1
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_on_private_chat_routes_allowed_t2_event_to_actor() -> None:
    """T2 mapped + confidence >= threshold -> actor spawned."""
    profile = _make_profile(dm_allowlist=(), dm_min_confidence=0.85)
    session = _make_session()
    registry = _make_registry()
    asst = _make_assistant(profile=profile, session=session, registry=registry)
    try:
        ev = _event(sender_canonical_id="user-y", sender_canonical_confidence=0.90)
        await asst.on_private_chat(ev)
        assert ("m1", "user-y") in asst._actors
        actor = asst._actors[("m1", "user-y")]
        await actor.drain(timeout_s=2.0)
        assert registry.call.await_count == 1
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_on_private_chat_silently_denies_t2_below_threshold() -> None:
    """T2 negative -- resolved but below threshold -> silent deny."""
    profile = _make_profile(dm_allowlist=(), dm_min_confidence=0.85)
    session = _make_session()
    registry = _make_registry()
    asst = _make_assistant(profile=profile, session=session, registry=registry)
    try:
        ev = _event(sender_canonical_id="user-y", sender_canonical_confidence=0.5)
        await asst.on_private_chat(ev)
        assert len(asst._actors) == 0
        assert session.send_chat.await_count == 0
        assert registry.call.await_count == 0
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_on_private_chat_silently_denies_t3_missing_confidence() -> None:
    """T3 -- resolved id but ``sender_canonical_confidence=None`` -> silent deny."""
    profile = _make_profile(dm_allowlist=(), dm_min_confidence=0.85)
    session = _make_session()
    registry = _make_registry()
    asst = _make_assistant(profile=profile, session=session, registry=registry)
    try:
        ev = _event(sender_canonical_id="user-z", sender_canonical_confidence=None)
        await asst.on_private_chat(ev)
        assert len(asst._actors) == 0
        assert session.send_chat.await_count == 0
        assert registry.call.await_count == 0
    finally:
        await asst.shutdown(drain_timeout_s=2.0)
