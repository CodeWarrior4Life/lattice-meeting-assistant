"""W6.2 -- public actor wiring + send_chat_public routing.

Spec §3 line 261 + spec §7 lines 838-915. ``Assistant.on_public_mention``
spawns a singleton-per-meeting public actor keyed on
``(meeting_id, "public")``. The actor uses the public-variant system
prompt (per spec §4 lines 644-671) and routes replies via
``session.send_chat_public(message)``, never via
``session.send_chat(to_user_id, message)``.

Two-bench shape, like the W4 routing tests:

* :func:`_make_assistant` -- spin up an Assistant with a captured
  cortex registry + a mock session.
* :func:`_make_public_event` -- build a public-mention ``ChatEvent``
  (``is_private=False``, ``is_at_mention_to_bot=True``).
"""

from __future__ import annotations

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
from lattice_meeting_assistant.exceptions import PrivacyBoundaryViolation


# ---------------------------------------------------------------------------
# Helpers (mirror test_privacy_boundary.py shape)
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    public_mentions_enabled: bool = True,
    public_mention_allowlist: tuple[str, ...] | None = None,
    public_mention_rate_limit_per_meeting_s: int = 30,
) -> AssistantProfile:
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
        public_mentions_enabled=public_mentions_enabled,
        public_mention_allowlist=public_mention_allowlist,
        public_mention_rate_limit_per_meeting_s=public_mention_rate_limit_per_meeting_s,
    )


def _make_session() -> MagicMock:
    s = MagicMock()
    s.send_chat = AsyncMock()
    s.send_chat_public = AsyncMock()
    return s


def _make_public_event(
    *,
    sender_user_id: str = "user_A",
    sender_canonical_id: str = "alice",
    text: str = "@cody what was just said?",
    meeting_id: str = "m1",
) -> ChatEvent:
    return ChatEvent(
        id=f"evt_public_{sender_user_id}_{text}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=sender_canonical_id,
        sender_canonical_confidence=0.95,
        sender_display_name=sender_canonical_id,
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=False,
        is_at_mention_to_bot=True,
    )


def _make_assistant(
    *,
    registry: MagicMock,
    session: MagicMock,
    profile: AssistantProfile | None = None,
    config: AssistantConfig | None = None,
) -> Assistant:
    asst = Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=config or AssistantConfig(),
        profile=profile or _make_profile(),
        session=session,
        cortex_registry=registry,
    )
    asst.start()
    return asst


# ---------------------------------------------------------------------------
# W6.2 tests
# ---------------------------------------------------------------------------


async def test_public_mention_spawns_singleton_actor_per_meeting() -> None:
    """An @-mention with ``is_private=False`` MUST spawn an actor whose
    key is ``(meeting_id, "public")`` -- not a per-sender private actor.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(
        return_value=MagicMock(text="public reply"),
    )

    asst = _make_assistant(registry=registry, session=session)
    try:
        ev = _make_public_event()
        await asst.on_public_mention(ev)

        # Singleton public actor keyed on (meeting, "public").
        assert ("m1", "public") in asst._actors
        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_public_mention_reuses_existing_public_actor() -> None:
    """A second @-mention in the same meeting MUST reuse the existing
    public actor (singleton-per-meeting per spec §7 line 982).
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    asst = _make_assistant(registry=registry, session=session)
    # Use a wide rate-limit window so the second mention isn't denied.
    # Override the profile-bound handler so it never falls into the
    # rate-limit gate while we're testing actor reuse.
    profile = _make_profile(public_mention_rate_limit_per_meeting_s=0)
    asst.profile = profile  # type: ignore[misc]  -- frozen dataclass; replace ref for test
    # The PublicMentionHandler is constructed eagerly with the original
    # profile; re-bind it so it picks up the relaxed rate-limit window.
    from lattice_meeting_assistant.public_mentions import PublicMentionHandler

    asst._public_mention_handler = PublicMentionHandler(profile=profile)  # type: ignore[attr-defined]
    try:
        ev1 = _make_public_event(sender_user_id="user_A", sender_canonical_id="alice")
        ev2 = _make_public_event(sender_user_id="user_B", sender_canonical_id="bob")

        await asst.on_public_mention(ev1)
        actor_after_first = asst._actors[("m1", "public")]
        await actor_after_first.drain(timeout_s=2.0)

        await asst.on_public_mention(ev2)
        actor_after_second = asst._actors[("m1", "public")]

        # Exact same actor instance reused.
        assert actor_after_second is actor_after_first
        await actor_after_second.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


async def test_public_mention_reply_routes_via_send_chat_public_only() -> None:
    """The public actor's worker MUST send replies via
    ``session.send_chat_public(message)`` -- never via
    ``session.send_chat(to_user_id, message)``.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(
        return_value=MagicMock(text="public reply"),
    )

    asst = _make_assistant(registry=registry, session=session)
    try:
        ev = _make_public_event()
        await asst.on_public_mention(ev)

        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Exactly one public reply via send_chat_public.
    assert session.send_chat_public.await_count == 1
    public_call = session.send_chat_public.await_args_list[0]
    # send_chat_public takes the message positionally (Invariant 1).
    assert (
        public_call.args == ("public reply",) or public_call.kwargs.get("message") == "public reply"
    )

    # The private send_chat path is NEVER touched for a public mention.
    session.send_chat.assert_not_awaited()


async def test_public_mention_actor_uses_public_system_prompt() -> None:
    """The public actor's ``system_prompt_renderer`` MUST produce a
    string carrying the public-variant markers (PUBLIC meeting chat +
    decline-private-shaped guidance) -- not the in-meeting-DM template.
    """
    session = _make_session()
    captured: list[dict[str, Any]] = []

    async def fake_call(**kwargs: Any) -> MagicMock:
        captured.append(kwargs)
        return MagicMock(text="public reply")

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session)
    try:
        ev = _make_public_event()
        await asst.on_public_mention(ev)
        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # cortex_call captured the system_prompt -- inspect it.
    assert len(captured) == 1
    sys_prompt = captured[0]["system_prompt"]
    assert "PUBLIC meeting chat" in sys_prompt
    assert "decline politely" in sys_prompt
    assert "DM you instead" in sys_prompt


async def test_public_mention_uses_public_cache_namespace() -> None:
    """The cortex call MUST thread the actor's key ``(meeting, "public")``
    as ``cache_namespace`` so the public thread is in its own cache
    namespace (Invariant 3 + spec §5 T12).
    """
    session = _make_session()
    captured: list[dict[str, Any]] = []

    async def fake_call(**kwargs: Any) -> MagicMock:
        captured.append(kwargs)
        return MagicMock(text="public reply")

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session)
    try:
        ev = _make_public_event()
        await asst.on_public_mention(ev)
        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    assert len(captured) == 1
    assert captured[0]["cache_namespace"] == ("m1", "public")


async def test_public_mention_fails_closed_on_missing_visibility_tag() -> None:
    """Invariant 4 (visibility-tag fail-closed): on_public_mention MUST
    raise ``PrivacyBoundaryViolation`` for events with no/None
    ``is_private`` tag.
    """
    import pytest

    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="reply"))
    asst = _make_assistant(registry=registry, session=session)

    class MissingTagEvent:
        id = "evt_no_tag"
        meeting_id = "m1"
        sender_user_id = "user_A"
        sender_canonical_id = "alice"
        sender_canonical_confidence = 0.95
        text = "@cody hi"
        is_at_mention_to_bot = True
        # No ``is_private`` attribute.

    try:
        with pytest.raises(PrivacyBoundaryViolation, match="is_private"):
            await asst.on_public_mention(MissingTagEvent())

        # No actor spawned, no public reply sent.
        assert ("m1", "public") not in asst._actors
        session.send_chat_public.assert_not_awaited()
        session.send_chat.assert_not_awaited()
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


__all__: list[str] = []
