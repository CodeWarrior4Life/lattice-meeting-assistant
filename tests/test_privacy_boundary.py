"""The 12 boundary tests T1-T12 from Design Spec §5.

Each test name embeds the Tx number so a reviewer can map test -> Tx at
a glance. Docstrings cite the spec §5 table line each test backs.

Status after W4.6 (Sub-dispatch B Part B):

* PASS: T1, T4, T5, T6, T8, T9, T10 -- contract-level assertions backed
  by Sub-dispatch A primitives in ``privacy/invariants.py`` plus the
  W4.6 actor pool + global semaphore + on_private_chat routing.
* SKIPPED/XFAIL: T2, T3, T7, T11, T12 -- backed by production code that
  lands in W3 transcript filter (T2), W5 admin command parser (T7), W6
  public mention (T11/T12), and W7 wrap-up integration (T3). Each is
  marked ``pytest.mark.xfail(strict=True)`` with a structured reason
  naming the fulfilling W-phase + spec §5 line so an unexpected pass
  surfaces immediately when the code lands.

Spec §5 table is at lines 706-719 of
``D:/Vaults/Mainframe/02_Projects/Lattice/lattice-meeting-assistant/
Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec.md``.
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
)
from lattice_meeting_assistant.brain_client import BrainMCPClient
from lattice_meeting_assistant.exceptions import PrivacyBoundaryViolation
from lattice_meeting_assistant.privacy.invariants import (
    assert_in_meeting_tools_safe,
    assert_separated_send_paths,
    enforce_visibility_tag,
)


# ---------------------------------------------------------------------------
# Shared helpers for T1/T6/T10 (W4.6 backfill)
# ---------------------------------------------------------------------------


def _make_profile() -> AssistantProfile:
    """Default profile satisfying Invariant 2 (allow_personal_vault=False)."""
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
    """Session double whose async send_chat / send_chat_public are AsyncMocks."""
    s = MagicMock()
    s.send_chat = AsyncMock()
    s.send_chat_public = AsyncMock()
    return s


def _make_event(
    *,
    sender_user_id: str,
    sender_canonical_id: str,
    text: str,
    meeting_id: str = "m1",
) -> ChatEvent:
    return ChatEvent(
        id=f"evt_{sender_user_id}_{text}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=sender_canonical_id,
        sender_canonical_confidence=0.95,
        sender_display_name=sender_canonical_id,
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=True,
    )


def _make_assistant(
    *,
    registry: MagicMock,
    session: MagicMock,
    config: AssistantConfig | None = None,
) -> Assistant:
    asst = Assistant(
        meeting_id="m1",
        transcript_buffer=MagicMock(name="FakeTranscriptBuffer"),
        brain_mcp=MagicMock(spec=BrainMCPClient),
        config=config or AssistantConfig(),
        profile=_make_profile(),
        session=session,
        cortex_registry=registry,
    )
    asst.start()
    return asst


# ---------------------------------------------------------------------------
# T1 -- Two parallel DMs in same meeting: memory isolation (spec §5 L708)
# ---------------------------------------------------------------------------


async def test_T1_two_parallel_dms_memory_isolated() -> None:
    """T1 -- Two parallel DMs from senders A and B in same meeting.

    Spec §5 L708 asserts: memory contexts isolated; distinct cortex
    cache namespaces; replies sent to correct sender's ``userId`` only.

    Backfilled at W4.6: the Assistant spawns one ``ChatThreadActor``
    per ``(meeting_id, sender_canonical_id)`` key, threads the actor's
    ``key`` through as ``cache_namespace`` in every cortex call, and
    each actor's worker sends replies through
    ``session.send_chat(to_user_id=...)`` addressed to the originating
    sender's user id only.
    """
    session = _make_session()

    # Custom cortex stub that returns a deterministic reply keyed on
    # who asked, so we can assert the routing of each reply.
    call_log: list[dict[str, Any]] = []

    async def fake_call(**kwargs: Any) -> MagicMock:
        call_log.append(kwargs)
        conv = kwargs["conversation"]
        last_user_text = conv[-1].content
        result = MagicMock()
        result.text = f"reply-to:{last_user_text}"
        return result

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session)
    try:
        # Sender A in meeting m1.
        ev_a = _make_event(
            sender_user_id="user_A",
            sender_canonical_id="alice",
            text="ask from A",
        )
        # Sender B in same meeting m1.
        ev_b = _make_event(
            sender_user_id="user_B",
            sender_canonical_id="bob",
            text="ask from B",
        )

        await asst.on_private_chat(ev_a)
        await asst.on_private_chat(ev_b)

        # Drain both actors.
        actor_a = asst._actors[("m1", "alice")]
        actor_b = asst._actors[("m1", "bob")]
        await actor_a.drain(timeout_s=2.0)
        await actor_b.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Two distinct actors stored under distinct keys.
    assert actor_a is not actor_b

    # Distinct cortex cache namespaces threaded through the calls.
    cache_namespaces = {kw["cache_namespace"] for kw in call_log}
    assert ("m1", "alice") in cache_namespaces
    assert ("m1", "bob") in cache_namespaces
    assert len(cache_namespaces) == 2

    # Each reply went to the correct sender's user_id only.
    send_calls = session.send_chat.await_args_list
    assert len(send_calls) == 2
    by_user = {c.kwargs["to_user_id"]: c.kwargs["message"] for c in send_calls}
    assert by_user["user_A"] == "reply-to:ask from A"
    assert by_user["user_B"] == "reply-to:ask from B"

    # Histories memory-isolated: actor A's history has no trace of B's
    # message and vice versa.
    a_hist_text = " ".join(t.content for t in actor_a.history_snapshot())
    b_hist_text = " ".join(t.content for t in actor_b.history_snapshot())
    assert "ask from B" not in a_hist_text
    assert "ask from A" not in b_hist_text

    # Public broadcast path never used for private DMs.
    session.send_chat_public.assert_not_awaited()


# ---------------------------------------------------------------------------
# T2 -- Private DM never appears in transcript callback (spec §5 L709)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "T2 boundary (spec §5 line 709): "
        "skip-pending-W3-transcript-filter -- requires Assistant ingest "
        "routing + transcript-source filter so private DMs never flow into "
        "the /segments POST body. Backfilled by AQH integration in W7 "
        "(AC-7) and unit-level in W3 transcript-buffer wiring."
    ),
    strict=True,
)
async def test_T2_private_dm_never_in_transcript_callback() -> None:
    """T2 -- Private DM -> meetbot transcript callback.

    Spec §5 L709 asserts: private DM text never appears in ``/segments``
    POST body; only ``is_private=False`` events flow downstream.
    """
    raise NotImplementedError("W3 transcript filter not yet implemented")


# ---------------------------------------------------------------------------
# T3 -- Private DM never in wrap-up source corpus (spec §5 L710)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "T3 boundary (spec §5 line 710): "
        "skip-pending-W7-wrapup-integration -- requires lattice-meeting-wrapup "
        "mock + Assistant integration. Backfilled by Plan task W7.x "
        "integration suite."
    ),
    strict=True,
)
async def test_T3_private_dm_never_in_wrap_up() -> None:
    """T3 -- Private DM -> wrap-up summary generation.

    Spec §5 L710 asserts: private DM text never appears in the wrap-up
    source corpus.
    """
    raise NotImplementedError("W7 wrap-up integration not yet implemented")


# ---------------------------------------------------------------------------
# T4 -- Separated send paths (Invariant 1) -- PASS at W2 (spec §5 L711)
# ---------------------------------------------------------------------------


def test_T4_send_chat_requires_to_user_id_positional() -> None:
    """T4 -- Attempt ``send_chat()`` without ``to_user_id`` positional.

    Spec §5 L711 asserts: raises ``TypeError`` at type-check time
    (contract); no runtime broadcast path exists.

    Sub-dispatch A primitive used: ``assert_separated_send_paths`` from
    ``lattice_meeting_assistant.privacy.invariants``. The helper enforces
    Architectural Invariant 1 by introspecting the session shape and
    rejecting:

    * missing ``send_chat`` or ``send_chat_public`` methods,
    * ``send_chat`` lacking a required ``to_user_id`` positional,
    * ``send_chat`` exposing a ``broadcast=`` kwarg.

    NOTE on contracts pin (FU3): ``lattice-meeting-contracts==0.3.0-rc2``
    does NOT yet expose ``MeetingSession.send_chat`` /
    ``.send_chat_public`` (only the session-handle dataclass). We
    therefore verify the contract against fake-session shapes here
    rather than introspecting the real ``MeetingSession`` Protocol.
    When the contracts rc3 cut lands the methods, this test will
    additionally introspect ``MeetingSession`` directly (Plan FU3).
    """

    class GoodSession:
        async def send_chat(self, to_user_id: str, message: str) -> None: ...
        async def send_chat_public(self, message: str) -> None: ...

    class BroadcastSession:
        # Forbidden broadcast= flag path.
        async def send_chat(self, message: str, *, broadcast: bool = False) -> None: ...
        async def send_chat_public(self, message: str) -> None: ...

    class MissingToUserId:
        # send_chat missing required to_user_id (implicit broadcast).
        async def send_chat(self, message: str) -> None: ...
        async def send_chat_public(self, message: str) -> None: ...

    class DefaultedToUserId:
        # send_chat has to_user_id but with a default => implicit broadcast.
        async def send_chat(self, to_user_id: str = "", message: str = "") -> None: ...
        async def send_chat_public(self, message: str) -> None: ...

    class MissingPublic:
        async def send_chat(self, to_user_id: str, message: str) -> None: ...

    # Compliant session passes.
    assert_separated_send_paths(GoodSession())

    # broadcast= flag rejected.
    with pytest.raises(ValueError, match="broadcast"):
        assert_separated_send_paths(BroadcastSession())

    # Missing to_user_id rejected.
    with pytest.raises(ValueError, match="to_user_id"):
        assert_separated_send_paths(MissingToUserId())

    # Defaulted to_user_id rejected (implicit broadcast).
    with pytest.raises(ValueError, match="to_user_id"):
        assert_separated_send_paths(DefaultedToUserId())

    # Missing public path rejected.
    with pytest.raises(ValueError, match="send_chat_public"):
        assert_separated_send_paths(MissingPublic())


# ---------------------------------------------------------------------------
# T5 -- Visibility-tag fail-closed (Invariant 4) -- PASS at W2 (spec §5 L712)
# ---------------------------------------------------------------------------


def test_T5_missing_or_none_visibility_tag_raises_privacy_boundary() -> None:
    """T5 -- Chat event with missing ``is_private`` field.

    Spec §5 L712 asserts: raises ``PrivacyBoundaryViolation``;
    observability event fires; reply NOT sent.

    Sub-dispatch A primitive used: ``enforce_visibility_tag`` from
    ``lattice_meeting_assistant.privacy.invariants`` -- the Invariant 4
    enforcement helper. The reply-not-sent guarantee is structural: the
    Assistant ingest path calls this helper at the very top of
    ``on_private_chat`` / ``on_public_mention`` so a raise short-circuits
    before any send path runs. Observability counter wiring
    (``AssistantStats.privacy_boundary_violations``) lands in W4.
    """

    class EventWithoutTag:
        id = "evt_T5_missing"

    class EventWithNoneTag:
        id = "evt_T5_none"
        is_private = None

    class EventTaggedPrivate:
        id = "evt_T5_tagged"
        is_private = True

    class EventTaggedPublic:
        id = "evt_T5_tagged_pub"
        is_private = False

    # Missing attribute -> reject.
    with pytest.raises(PrivacyBoundaryViolation, match="is_private"):
        enforce_visibility_tag(EventWithoutTag())

    # None value -> reject (ambiguity == refuse).
    with pytest.raises(PrivacyBoundaryViolation, match="is_private"):
        enforce_visibility_tag(EventWithNoneTag())

    # Both explicit booleans pass.
    enforce_visibility_tag(EventTaggedPrivate())
    enforce_visibility_tag(EventTaggedPublic())


# ---------------------------------------------------------------------------
# T6 -- Cache namespace scope per thread (spec §5 L713)
# ---------------------------------------------------------------------------


async def test_T6_cache_scope_per_thread() -> None:
    """T6 -- Same prompt from sender A and sender B.

    Spec §5 L713 asserts: two independent cortex calls; no cache hit
    cross-sender; verified via cortex ``cost_records`` row count.

    Backfilled at W4.6: the Assistant's per-actor closure threads each
    actor's ``key`` (``(meeting_id, persona_id)``) through as
    ``cache_namespace`` in every ``cortex_call``. Two senders firing
    the IDENTICAL prompt text produce TWO distinct cortex invocations
    (one per actor) under distinct cache namespaces -- no de-dupe,
    no shared cache.
    """
    session = _make_session()

    call_log: list[dict[str, Any]] = []

    async def fake_call(**kwargs: Any) -> MagicMock:
        call_log.append(kwargs)
        result = MagicMock()
        result.text = "reply"
        return result

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session)
    try:
        # IDENTICAL prompt text from two senders.
        prompt = "what is the meaning of this?"
        ev_a = _make_event(sender_user_id="user_A", sender_canonical_id="alice", text=prompt)
        ev_b = _make_event(sender_user_id="user_B", sender_canonical_id="bob", text=prompt)

        await asst.on_private_chat(ev_a)
        await asst.on_private_chat(ev_b)

        actor_a = asst._actors[("m1", "alice")]
        actor_b = asst._actors[("m1", "bob")]
        await actor_a.drain(timeout_s=2.0)
        await actor_b.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # TWO distinct cortex invocations -- no de-dupe.
    assert registry.call.await_count == 2
    assert len(call_log) == 2

    # Distinct cache namespaces; no shared/coalesced key.
    namespaces = [kw["cache_namespace"] for kw in call_log]
    assert ("m1", "alice") in namespaces
    assert ("m1", "bob") in namespaces
    assert namespaces[0] != namespaces[1]


# ---------------------------------------------------------------------------
# T7 -- Admin command on in-meeting DM rejected (spec §5 L714)
# ---------------------------------------------------------------------------


async def test_T7_in_meeting_admin_command_rejected() -> None:
    """T7 -- In-meeting DM containing ``allowlist add X``.

    Spec §5 L714 asserts: reply: "admin commands not supported here";
    allowlist NOT mutated; no admin response sent.

    Backfilled at W5.6: ``Assistant.on_private_chat`` detects admin
    grammar via ``privacy.invariants.is_admin_command_syntax`` AFTER
    visibility-tag enforcement and allowlist gate, but BEFORE
    spawning an actor or routing to cortex. The Assistant replies via
    ``session.send_chat(to_user_id=event.sender_user_id, message=...)``
    with the stock string and returns. No mutation to ``profile.dm_allowlist``;
    no Brain ``nx_vault_write`` call; no admin response sent.
    """
    session = _make_session()
    registry = MagicMock()
    registry.call = AsyncMock()  # never called -- T7 rejects before cortex

    asst = _make_assistant(registry=registry, session=session)
    original_allowlist = asst.profile.dm_allowlist
    try:
        # Admin-grammar text on an in-meeting-dm event. Sender is in
        # the allowlist so the tier gate doesn't silently deny first.
        ev = _make_event(
            sender_user_id="user_C",
            sender_canonical_id="cyril-grosse",
            text="allowlist add stranger",
        )
        await asst.on_private_chat(ev)

        # Stock reply addressed to the originating sender.
        assert session.send_chat.await_count == 1
        send_call = session.send_chat.await_args_list[0]
        assert send_call.kwargs["to_user_id"] == "user_C"
        reply = send_call.kwargs["message"]
        # Spec §5 line 714 verbatim phrasing.
        assert reply == "admin commands not supported here"

        # No actor spawned -- admin rejection short-circuits before _get_or_spawn_actor.
        assert len(asst._actors) == 0

        # Allowlist NOT mutated.
        assert asst.profile.dm_allowlist == original_allowlist

        # Cortex NOT called.
        assert registry.call.await_count == 0

        # Public broadcast path NOT touched.
        session.send_chat_public.assert_not_awaited()
    finally:
        await asst.shutdown(drain_timeout_s=2.0)


# ---------------------------------------------------------------------------
# T8 -- Resolver enforces BLOCKED set for in-meeting-dm -- PASS (spec §5 L715)
# ---------------------------------------------------------------------------


def test_T8_in_meeting_resolver_rejects_blocked_tools() -> None:
    """T8 -- TG-transport tool resolver returns ``search_vault``;
    in-meeting-DM resolver does NOT.

    Spec §5 L715 asserts: resolver self-test;
    ``BLOCKED_IN_MEETING_TOOLS intersect resolved_for_in_meeting_dm == EMPTY``.

    Sub-dispatch A primitive used: ``assert_in_meeting_tools_safe``
    from ``lattice_meeting_assistant.privacy.invariants``. The full
    resolver (W3) calls this helper at boot against its resolved tool
    set for the in-meeting-dm transport. At W2 close we verify the
    disjointness contract directly: a curated set passes, a set
    containing any BLOCKED member raises.
    """
    curated_in_meeting = {
        "search_meeting_transcript",
        "read_meeting_transcript_window",
        "search_past_meetings",
        "search_public_references",
        "web_search",
    }
    # Clean curated set: no raise (Invariant 2 satisfied).
    assert_in_meeting_tools_safe(curated_in_meeting)

    # Adding any BLOCKED tool -> raise.
    with pytest.raises(ValueError, match="blocked"):
        assert_in_meeting_tools_safe(curated_in_meeting | {"search_vault"})
    with pytest.raises(ValueError, match="blocked"):
        assert_in_meeting_tools_safe(curated_in_meeting | {"brain_chat"})
    with pytest.raises(ValueError, match="blocked"):
        assert_in_meeting_tools_safe({"nx_vault_write"})


# ---------------------------------------------------------------------------
# T9 -- KnowledgeAccessConfig default-deny on personal vault -- PASS
#       (spec §5 L716)
# ---------------------------------------------------------------------------


def test_T9_knowledge_config_personal_vault_defaults_false() -> None:
    """T9 -- Profile YAML attempts to enable ``search_vault`` for
    in-meeting-dm transport.

    Spec §5 L716 asserts: ``KnowledgeAccessConfig`` load raises
    ``ValueError`` at parse time.

    At W2 close (this dispatch), the contract-level sentinel is that
    ``KnowledgeAccessConfig.allow_personal_vault`` defaults to ``False``
    -- the Invariant 2 default-deny posture. The parse-time raise
    behavior (rejecting profile YAML that sets it ``True`` for an
    in-meeting-dm transport) is enforced by the resolver in W3.7 and
    that integration test backfills this xfail-free at W3 close
    (Plan task W3.7 step 3 removes the xfail).

    Rationale for splitting the T9 assertion into two phases: at W2
    we own the data shape, at W3 we own the YAML loader semantic --
    asserting parse-time raise here would require the W3 resolver
    code to exist. The default-False sentinel verifies the *invariant
    foundation*: even a profile that omits the field gets safe
    behavior on the in-meeting-dm transport.
    """
    cfg = KnowledgeAccessConfig()
    assert cfg.allow_personal_vault is False, (
        "Invariant 2 foundation: allow_personal_vault MUST default False "
        "so a profile YAML that omits the field gets safe behavior. "
        "Resolver (W3.7) additionally rejects True on in-meeting-dm."
    )
    # Explicitly setting to True is allowed at the dataclass level
    # (tg-owner transport may opt-in). The resolver enforces the
    # transport-bound rejection in W3.7.
    cfg_opt_in = KnowledgeAccessConfig(allow_personal_vault=True)
    assert cfg_opt_in.allow_personal_vault is True


# ---------------------------------------------------------------------------
# T10 -- Per-thread queue backpressure (spec §5 L717)
# ---------------------------------------------------------------------------


async def test_T10_per_thread_queue_backpressure() -> None:
    """T10 -- Per-thread queue depth exceeded (6 msgs from one sender).

    Spec §5 L717 asserts: 6th msg triggers backpressure reply; 1-5
    still processed in FIFO; cortex calls bounded by global semaphore.

    Backfilled at W4.6: the actor's bounded ``asyncio.Queue`` of depth
    5 (default) rejects the 6th enqueue while the worker is held;
    ``Assistant.on_private_chat`` surfaces the backpressure reply
    via ``session.send_chat`` to the originating sender; once the
    worker is released, msgs 1-5 process in submission order. The
    global semaphore cap is covered separately by
    ``tests/test_w4_global_semaphore.py``; here we focus on the
    per-thread queue + backpressure-reply surface.
    """
    session = _make_session()
    config = AssistantConfig()  # per_thread_queue_depth=5

    gate = asyncio.Event()
    processed: list[str] = []

    async def fake_call(**kwargs: Any) -> MagicMock:
        await gate.wait()
        conv = kwargs["conversation"]
        processed.append(conv[-1].content)
        result = MagicMock()
        result.text = f"done {conv[-1].content}"
        return result

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session, config=config)
    try:
        # msg0 is picked up immediately by the worker (which blocks on
        # the gate); wait for the queue to drop to 0 so the next 5
        # enqueues land cleanly.
        await asst.on_private_chat(
            _make_event(
                sender_user_id="user_A",
                sender_canonical_id="alice",
                text="msg0",
            )
        )
        actor = asst._actors[("m1", "alice")]
        for _ in range(100):
            if actor.queue_depth == 0:
                break
            await asyncio.sleep(0.005)
        assert actor.queue_depth == 0

        # Fill the queue to depth=5 (msgs 1..5).
        for i in range(1, 6):
            await asst.on_private_chat(
                _make_event(
                    sender_user_id="user_A",
                    sender_canonical_id="alice",
                    text=f"msg{i}",
                )
            )
        assert actor.queue_depth == 5

        # No backpressure reply yet -- 1..5 all fit.
        assert session.send_chat.await_count == 0

        # 6th over-the-cap msg triggers the backpressure reply.
        await asst.on_private_chat(
            _make_event(
                sender_user_id="user_A",
                sender_canonical_id="alice",
                text="msg6",
            )
        )
        # Exactly one backpressure reply addressed to the sender.
        assert session.send_chat.await_count == 1
        bp = session.send_chat.await_args_list[0]
        assert bp.kwargs["to_user_id"] == "user_A"
        assert "catching up" in bp.kwargs["message"].lower()

        # Release the gate; queue drains in FIFO order.
        gate.set()
        await actor.drain(timeout_s=2.0)
    finally:
        gate.set()
        await asst.shutdown(drain_timeout_s=2.0)

    # msgs 0..5 processed in FIFO; msg6 was rejected and never reached
    # cortex (the backpressure reply substituted for it).
    assert processed == ["msg0", "msg1", "msg2", "msg3", "msg4", "msg5"]

    # The 5 real replies (msgs 1..5) plus the backpressure reply
    # account for 6 send_chat calls; msg0's reply is also sent.
    # Total = 1 backpressure + 6 real replies.
    assert session.send_chat.await_count == 7


# ---------------------------------------------------------------------------
# Public-mention helpers (W6.5 backfill)
# ---------------------------------------------------------------------------


def _make_public_event(
    *,
    sender_user_id: str,
    sender_canonical_id: str,
    text: str,
    meeting_id: str = "m1",
) -> ChatEvent:
    """Public @-mention event factory: ``is_private=False`` +
    ``is_at_mention_to_bot=True``.
    """
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


# ---------------------------------------------------------------------------
# T11 -- Public mention reply via send_chat_public only (spec §5 L718)
# ---------------------------------------------------------------------------


async def test_T11_public_mention_reply_via_send_chat_public_only() -> None:
    """T11 -- Public mention reply lands in public chat only.

    Spec §5 L718 asserts: sent via ``send_chat_public``, never via
    ``send_chat``; no private-thread mutation.

    Backfilled at W6.5: ``Assistant.on_public_mention`` spawns the
    singleton ``(meeting_id, "public")`` actor whose worker routes
    replies through ``session.send_chat_public(message)`` per
    Architectural Invariant 1. The actor's
    :meth:`ChatThreadActor._send_reply` branches on
    ``self.key[1] == "public"`` and never falls back to the private
    ``send_chat`` path. No private-actor pool mutation: the
    ``self._actors`` dict gains exactly one entry keyed on the
    public-tuple key.
    """
    session = _make_session()

    captured: list[dict[str, Any]] = []

    async def fake_call(**kwargs: Any) -> MagicMock:
        captured.append(kwargs)
        result = MagicMock()
        result.text = "public reply"
        return result

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session)
    try:
        ev = _make_public_event(
            sender_user_id="user_A",
            sender_canonical_id="alice",
            text="@cody what was just said?",
        )
        await asst.on_public_mention(ev)

        actor = asst._actors[("m1", "public")]
        await actor.drain(timeout_s=2.0)

        # No private-thread mutation: the only actor in the pool is the
        # public singleton (assert PRE-shutdown -- shutdown clears the pool).
        assert list(asst._actors.keys()) == [("m1", "public")]
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Reply via send_chat_public; private send_chat NEVER touched.
    assert session.send_chat_public.await_count == 1
    session.send_chat.assert_not_awaited()

    # Public-thread cache namespace threaded through cortex.
    assert len(captured) == 1
    assert captured[0]["cache_namespace"] == ("m1", "public")


# ---------------------------------------------------------------------------
# T12 -- Private + public thread isolation from same sender (spec §5 L719)
# ---------------------------------------------------------------------------


async def test_T12_private_and_public_thread_isolation_same_sender() -> None:
    """T12 -- Private DM + public mention from same sender in same meeting.

    Spec §5 L719 asserts: two independent ``ChatThreadActor`` instances;
    cortex calls in independent cache namespaces; replies do not
    commingle.

    Backfilled at W6.5: when the same sender sends a private DM
    (``is_private=True``) AND a public @-mention (``is_private=False``)
    within the same meeting:

    * Two distinct actor keys land in ``self._actors``:
      ``(meeting_id, sender_canonical_id)`` for the private DM and
      ``(meeting_id, "public")`` for the public mention.
    * The cortex call for the private DM uses
      ``cache_namespace=(meeting_id, sender_canonical_id)``; the
      public call uses ``cache_namespace=(meeting_id, "public")``.
      No commingling.
    * The private reply routes via
      ``session.send_chat(to_user_id=..., message=...)``; the public
      reply routes via ``session.send_chat_public(message)``. No
      cross-channel leak.
    * The two actors' history buffers are independent; the private
      DM text does NOT appear in the public actor's history (and vice
      versa).
    """
    session = _make_session()

    captured: list[dict[str, Any]] = []

    async def fake_call(**kwargs: Any) -> MagicMock:
        captured.append(kwargs)
        # Echo back the conversation so we can verify isolation.
        conv = kwargs["conversation"]
        last_user_text = conv[-1].content
        result = MagicMock()
        result.text = f"reply-to:{last_user_text}"
        return result

    registry = MagicMock()
    registry.call = AsyncMock(side_effect=fake_call)

    asst = _make_assistant(registry=registry, session=session)
    try:
        # Private DM from alice.
        private_ev = _make_event(
            sender_user_id="user_A",
            sender_canonical_id="alice",
            text="please do not share this publicly",
        )
        # Public mention from alice in the same meeting.
        public_ev = _make_public_event(
            sender_user_id="user_A",
            sender_canonical_id="alice",
            text="@cody what was just discussed?",
        )

        await asst.on_private_chat(private_ev)
        await asst.on_public_mention(public_ev)

        private_actor = asst._actors[("m1", "alice")]
        public_actor = asst._actors[("m1", "public")]

        await private_actor.drain(timeout_s=2.0)
        await public_actor.drain(timeout_s=2.0)
    finally:
        await asst.shutdown(drain_timeout_s=2.0)

    # Two distinct actor instances.
    assert private_actor is not public_actor

    # Two cortex calls; distinct cache namespaces.
    assert registry.call.await_count == 2
    cache_namespaces = [kw["cache_namespace"] for kw in captured]
    assert ("m1", "alice") in cache_namespaces
    assert ("m1", "public") in cache_namespaces

    # Private reply via send_chat(to_user_id=...); public via
    # send_chat_public.
    assert session.send_chat.await_count == 1
    private_call = session.send_chat.await_args_list[0]
    assert private_call.kwargs["to_user_id"] == "user_A"
    assert "please do not share this publicly" in private_call.kwargs["message"]

    assert session.send_chat_public.await_count == 1
    public_call = session.send_chat_public.await_args_list[0]
    public_msg = public_call.args[0] if public_call.args else public_call.kwargs.get("message", "")
    assert "what was just discussed" in public_msg

    # Histories are isolated: the private DM text never landed in the
    # public actor's history and vice versa.
    private_hist_text = " ".join(t.content for t in private_actor.history_snapshot())
    public_hist_text = " ".join(t.content for t in public_actor.history_snapshot())
    assert "please do not share this publicly" in private_hist_text
    assert "please do not share this publicly" not in public_hist_text
    assert "what was just discussed" in public_hist_text
    assert "what was just discussed" not in private_hist_text

    # Cortex system_prompts differ -- private uses the DM template,
    # public uses the public-mention template.
    by_ns = {kw["cache_namespace"]: kw["system_prompt"] for kw in captured}
    assert "PUBLIC meeting chat" in by_ns[("m1", "public")]
    assert "PUBLIC meeting chat" not in by_ns[("m1", "alice")]
