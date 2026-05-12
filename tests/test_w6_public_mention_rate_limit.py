"""W6.3 -- meeting-level rate limit + ``public_mentions_enabled`` toggle.

Spec §3 lines 261-265 + spec §11 R5 (line 1128). Two policy gates:

* ``profile.public_mentions_enabled = False`` -> silent decline for ALL
  public @-mentions in this meeting (no reply, no actor spawn).
* Per-meeting rate limit -- if a public reply happened within the last
  ``profile.public_mention_rate_limit_per_meeting_s`` seconds, silently
  decline. R5 mitigation: prevents an infinite loop when Cody's public
  reply triggers another participant's @cody mention.

Rate limit is **per-meeting** -- two different meetings hosted by the
same Assistant must not share rate-limit state.

Tests inject a controllable clock via the
:class:`PublicMentionHandler` ``clock=`` parameter to advance time
deterministically without sleeping.
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
    text: str = "@cody hi",
    meeting_id: str = "m1",
) -> ChatEvent:
    return ChatEvent(
        id=f"evt_{meeting_id}_{sender_user_id}_{text}",
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


class _FakeClock:
    """Controllable monotonic clock for rate-limit tests."""

    def __init__(self, start: float = 1_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, secs: float) -> None:
        self._now += secs


def _make_assistant(
    *,
    registry: MagicMock,
    session: MagicMock,
    profile: AssistantProfile | None = None,
    config: AssistantConfig | None = None,
    clock: _FakeClock | None = None,
    meeting_id: str = "m1",
) -> Assistant:
    profile = profile or _make_profile()
    asst = Assistant(
        meeting_id=meeting_id,
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=config or AssistantConfig(),
        profile=profile,
        session=session,
        cortex_registry=registry,
    )
    asst.start()
    # Re-bind the handler with the fake clock (Assistant.__init__
    # eagerly wires the default time.monotonic; for tests we swap in
    # the controllable clock).
    if clock is not None:
        asst._public_mention_handler = PublicMentionHandler(  # type: ignore[attr-defined]
            profile=profile, clock=clock
        )
    return asst


# ---------------------------------------------------------------------------
# Rate-limit tests
# ---------------------------------------------------------------------------


async def test_second_mention_within_window_silently_declined() -> None:
    """Two @-mentions within 30s in the same meeting: only the first
    triggers a reply. The second is silently declined (no reply, no
    duplicate actor work).
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    clock = _FakeClock()
    asst = _make_assistant(registry=registry, session=session, clock=clock)
    try:
        ev1 = _make_public_event()
        ev2 = _make_public_event(text="@cody another question")

        await asst.on_public_mention(ev1)
        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)

        # Advance only 10s -- still well inside the 30s window.
        clock.advance(10.0)

        await asst.on_public_mention(ev2)
        # No new actor enqueue or send.
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Exactly ONE public reply -- the second mention silently declined.
    assert session.send_chat_public.await_count == 1


async def test_second_mention_after_window_replies() -> None:
    """Two @-mentions ~31s apart: BOTH trigger a reply.

    The rate-limit window has elapsed for the second, so the gate is
    cleared.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    clock = _FakeClock()
    asst = _make_assistant(registry=registry, session=session, clock=clock)
    try:
        ev1 = _make_public_event()
        ev2 = _make_public_event(text="@cody another question")

        await asst.on_public_mention(ev1)
        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)

        # Advance 31s -- past the 30s default window.
        clock.advance(31.0)

        await asst.on_public_mention(ev2)
        await actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # TWO public replies -- both went through.
    assert session.send_chat_public.await_count == 2


async def test_public_mentions_disabled_silences_everything() -> None:
    """When ``profile.public_mentions_enabled = False`` every @-mention
    is silently declined regardless of the rate-limit window.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock(return_value=MagicMock(text="public reply"))

    profile = _make_profile(public_mentions_enabled=False)
    clock = _FakeClock()
    asst = _make_assistant(registry=registry, session=session, profile=profile, clock=clock)
    try:
        for i in range(3):
            clock.advance(60.0)  # well outside rate-limit window each iteration
            await asst.on_public_mention(_make_public_event(text=f"@cody mention {i}"))
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Zero replies, zero actor spawned.
    assert session.send_chat_public.await_count == 0
    assert ("m1", "public") not in asst._actors


async def test_rate_limit_is_per_meeting() -> None:
    """Rate-limit is per-meeting; two different meetings can both reply
    within 30s of each other without interference.

    The handler holds per-meeting state in a dict keyed on meeting_id,
    so a reply in meeting m1 does NOT trip the rate-limit gate in
    meeting m2.
    """
    # Two parallel sessions, one per meeting -- the Assistant
    # constructor is per-meeting in v0.1 (single meeting_id slot), so
    # we spin up two Assistant instances backed by the same handler
    # *contract* (per-meeting rate-state).
    #
    # Simpler test: drive the handler directly with two different
    # meeting_ids and verify the gates are independent. This still
    # backs the spec assertion -- the Assistant just wires through.
    profile = _make_profile()
    clock = _FakeClock()
    handler = PublicMentionHandler(profile=profile, clock=clock)

    # Meeting m1 replies, then a second mention 10s later is declined.
    v1 = handler.evaluate(meeting_id="m1", sender_canonical_id="alice")
    assert v1.decision == "allow"
    handler.record_reply(meeting_id="m1")

    # Meeting m2 replies (separate meeting -- rate limit doesn't apply).
    v2 = handler.evaluate(meeting_id="m2", sender_canonical_id="bob")
    assert v2.decision == "allow"
    handler.record_reply(meeting_id="m2")

    # Both meetings see their own decline gate when a second mention
    # arrives within the window.
    clock.advance(5.0)
    v1b = handler.evaluate(meeting_id="m1", sender_canonical_id="alice")
    v2b = handler.evaluate(meeting_id="m2", sender_canonical_id="bob")
    assert v1b.decision == "deny_rate_limit"
    assert v2b.decision == "deny_rate_limit"

    # m1's rate clock clears independently of m2's: advance another
    # 28s (total 33s since m1's record) and m1 clears while m2 (only
    # 33s since record but its window is the same 30s) also clears.
    clock.advance(28.0)
    v1c = handler.evaluate(meeting_id="m1", sender_canonical_id="alice")
    v2c = handler.evaluate(meeting_id="m2", sender_canonical_id="bob")
    assert v1c.decision == "allow"
    assert v2c.decision == "allow"


async def test_rate_limit_via_assistant_two_meetings() -> None:
    """End-to-end Assistant-level: m1 and m2 each accept their first
    @-mention even when both fire within seconds.
    """
    session_m1 = _make_session()
    registry_m1 = MagicMock()
    registry_m1.call = AsyncMock(return_value=MagicMock(text="reply m1"))

    session_m2 = _make_session()
    registry_m2 = MagicMock()
    registry_m2.call = AsyncMock(return_value=MagicMock(text="reply m2"))

    clock_m1 = _FakeClock()
    clock_m2 = _FakeClock()
    asst_m1 = _make_assistant(
        registry=registry_m1, session=session_m1, clock=clock_m1, meeting_id="m1"
    )
    asst_m2 = _make_assistant(
        registry=registry_m2, session=session_m2, clock=clock_m2, meeting_id="m2"
    )
    try:
        await asst_m1.on_public_mention(_make_public_event(meeting_id="m1", text="@cody from m1"))
        await asst_m2.on_public_mention(_make_public_event(meeting_id="m2", text="@cody from m2"))
        actor_m1 = asst_m1._actors[("m1", "public")]
        actor_m2 = asst_m2._actors[("m2", "public")]
        await actor_m1.drain(timeout_s=2.0)
        await actor_m2.drain(timeout_s=2.0)
    finally:
        await asst_m1.shutdown(drain_timeout_s=2.0)
        await asst_m2.shutdown(drain_timeout_s=2.0)

    # Each meeting got its reply -- per-meeting isolation honored.
    assert session_m1.send_chat_public.await_count == 1
    assert session_m2.send_chat_public.await_count == 1


__all__: list[str] = []
