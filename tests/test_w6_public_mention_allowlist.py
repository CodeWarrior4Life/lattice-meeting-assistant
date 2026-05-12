"""W6.4 -- ``public_mention_allowlist`` override.

Spec §3 lines 346-348 + plan task W6.4. The allowlist is a separate
control surface from the DM allowlist:

* ``profile.public_mention_allowlist is None`` (default) -> anyone may
  @-mention; rate-limit + enabled toggle still apply.
* ``profile.public_mention_allowlist = ("alice", "bob")`` -> only
  ``alice`` and ``bob`` may successfully @-mention; others get a
  silent decline (no reply, no actor spawn -- same shape as the
  rate-limit decline).

Allowlist check fires BEFORE the rate-limit gate so a non-allowlisted
@-mention does not arm the per-meeting rate-limit clock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from lattice_meeting_assistant import (
    Assistant,
    AssistantConfig,
    AssistantProfile,
    ChatEvent,
    KnowledgeAccessConfig,
)
from lattice_meeting_assistant.brain_client import BrainMCPClient
from lattice_meeting_assistant.public_mentions import PublicMentionHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    public_mention_allowlist: tuple[str, ...] | None = None,
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
        public_mentions_enabled=True,
        public_mention_allowlist=public_mention_allowlist,
        # Wide rate-limit window for these tests -- we want the allowlist
        # gate to be the sole decision point, not rate-limit shadowing.
        public_mention_rate_limit_per_meeting_s=0,
    )


def _make_session() -> MagicMock:
    s = MagicMock()
    s.send_chat = AsyncMock()
    s.send_chat_public = AsyncMock()
    return s


def _make_public_event(
    *,
    sender_user_id: str,
    sender_canonical_id: str | None,
    text: str = "@cody hi",
    meeting_id: str = "m1",
) -> ChatEvent:
    return ChatEvent(
        id=f"evt_{meeting_id}_{sender_user_id}_{text}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=sender_canonical_id,
        sender_canonical_confidence=0.95 if sender_canonical_id else None,
        sender_display_name=sender_canonical_id or "Anonymous",
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=False,
        is_at_mention_to_bot=True,
    )


def _make_assistant(
    *,
    registry: MagicMock,
    session: MagicMock,
    profile: AssistantProfile,
) -> Assistant:
    asst = Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=AssistantConfig(),
        profile=profile,
        session=session,
        cortex_registry=registry,
    )
    asst.start()
    return asst


# ---------------------------------------------------------------------------
# W6.4 tests
# ---------------------------------------------------------------------------


async def test_allowlist_set_non_allowlisted_silent_decline() -> None:
    """When the allowlist is set, an @-mention from a non-allowlisted
    sender is silently declined: no reply, no actor spawn.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    profile = _make_profile(public_mention_allowlist=("alice",))
    asst = _make_assistant(registry=registry, session=session, profile=profile)
    try:
        # user_y is not on the allowlist.
        ev = _make_public_event(
            sender_user_id="user_Y",
            sender_canonical_id="user-y",
            text="@cody what's up?",
        )
        await asst.on_public_mention(ev)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Zero replies, zero actor, zero cortex calls.
    session.send_chat_public.assert_not_awaited()
    session.send_chat.assert_not_awaited()
    assert ("m1", "public") not in asst._actors
    registry.call.assert_not_awaited()


async def test_allowlist_set_allowlisted_sender_replies() -> None:
    """When the allowlist is set and the sender is allowlisted, the
    public-mention path proceeds as normal (singleton actor + reply
    via send_chat_public).
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    profile = _make_profile(public_mention_allowlist=("alice",))
    asst = _make_assistant(registry=registry, session=session, profile=profile)
    try:
        ev = _make_public_event(
            sender_user_id="user_A",
            sender_canonical_id="alice",
            text="@cody hello?",
        )
        await asst.on_public_mention(ev)
        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    assert session.send_chat_public.await_count == 1


async def test_allowlist_none_means_anyone_can_mention() -> None:
    """When ``public_mention_allowlist is None`` (default), anyone with
    a resolved canonical id may successfully @-mention -- subject to
    the enabled toggle + rate limit, both clear here.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    profile = _make_profile(public_mention_allowlist=None)
    asst = _make_assistant(registry=registry, session=session, profile=profile)
    try:
        # Any sender (even one not in the dm_allowlist) goes through.
        ev = _make_public_event(
            sender_user_id="user_X",
            sender_canonical_id="random-stranger",
            text="@cody hello?",
        )
        await asst.on_public_mention(ev)
        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    assert session.send_chat_public.await_count == 1


async def test_allowlist_set_unresolved_canonical_id_silent_decline() -> None:
    """Defensive: when the allowlist is set and the event has no
    resolved canonical id (``sender_canonical_id is None``), treat as
    not-allowlisted and silently decline.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    profile = _make_profile(public_mention_allowlist=("alice",))
    asst = _make_assistant(registry=registry, session=session, profile=profile)
    try:
        ev = _make_public_event(
            sender_user_id="user_Z",
            sender_canonical_id=None,  # unresolved
            text="@cody hello?",
        )
        await asst.on_public_mention(ev)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    session.send_chat_public.assert_not_awaited()


def test_allowlist_handler_direct_set_vs_none() -> None:
    """Direct handler-level coverage of the allowlist gate decision."""
    # allowlist=None (anyone) -> allow.
    handler_open = PublicMentionHandler(profile=_make_profile(public_mention_allowlist=None))
    v_open = handler_open.evaluate(meeting_id="m1", sender_canonical_id="anyone")
    assert v_open.decision == "allow"

    # allowlist=("alice",) -> bob is denied; alice is allowed.
    handler_closed = PublicMentionHandler(
        profile=_make_profile(public_mention_allowlist=("alice",))
    )
    v_bob = handler_closed.evaluate(meeting_id="m1", sender_canonical_id="bob")
    assert v_bob.decision == "deny_allowlist"
    v_alice = handler_closed.evaluate(meeting_id="m1", sender_canonical_id="alice")
    assert v_alice.decision == "allow"


__all__: list[str] = []
