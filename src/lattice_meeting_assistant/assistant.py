"""Minimal :class:`Assistant` shell -- W3.7 scope, extended at W4.6.

Per Design Spec §3 (lines 232-292) the full ``Assistant`` class
exposes ``on_private_chat``, ``on_public_mention``, ``admin_command``,
``start``, ``shutdown``, and ``stats``. W3 ships the constructor shape
plus :meth:`Assistant.start` -- the boot self-test. W4.6 backfills
``on_private_chat`` + per-(meeting, persona) actor pool + global
concurrency semaphore + lifecycle hooks. ``on_public_mention`` lands
at W6.5; ``admin_command`` at W5.6.

Spec §4 boot self-test (lines 673-681):

1. Resolve tool sets for both transports.
2. Assert ``BLOCKED_IN_MEETING_TOOLS & in_meeting_set_names == ∅``.
3. Assert ``profile.knowledge.allow_personal_vault == False`` when the
   transport is ``in-meeting-dm`` (the resolver surfaces this via
   ``ValueError``; ``start()`` lets it propagate).
4. Log resolved tool set names at INFO (no content per Invariant 4).
5. If cortex's tool-use API surface is unavailable -> raise
   :class:`CapabilityNotSupported` (Spec §9 OQ2).

Spec §7 concurrency wiring (W4.6):

* ``self._global_semaphore = asyncio.Semaphore(per_meeting_global_concurrency)``
  -- one semaphore per Assistant; injected into every actor's
  ``cortex_call`` closure so the cap applies uniformly across threads.
* ``self._actors: dict[tuple[str, str], ChatThreadActor]`` -- per-
  ``(meeting_id, persona_id)`` for private DM actors and
  ``(meeting_id, "public")`` for the public-mention singleton (W6.5).
* ``self._reap_timers: dict[tuple[str, str], TimerHandle]`` -- 60s
  post-leave reap timer (cancelled on rejoin).

W5/W6 follow-ups commented inline at the seam (``# W5:``/``# W6:``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .actor import POST_LEAVE_GRACE_SECS_DEFAULT, ChatThreadActor
from .brain_client import BrainMCPClient
from .config import AssistantConfig
from .exceptions import CapabilityNotSupported
from .privacy.invariants import (
    BLOCKED_IN_MEETING_TOOLS,
    assert_in_meeting_tools_safe,
    enforce_visibility_tag,
    is_admin_command_syntax,
)
from .profile import AssistantProfile
from .prompts import render_in_meeting_dm_prompt, render_public_mention_prompt
from .public_mentions import PublicMentionHandler
from .tools.resolver import resolve_tool_set

logger = logging.getLogger(__name__)


# Drain-timeout default for ``Assistant.shutdown``. Sourced from spec §7
# lifecycle table (line 986: "Drain all queues (timeout=30s)").
# OQ-followup: surface ``meeting_shutdown_drain_timeout_secs`` as a
# config field on :class:`AssistantConfig` so consumers can tune.
SHUTDOWN_DRAIN_TIMEOUT_DEFAULT_S: float = 30.0

# Spec §5 line 714 verbatim phrasing for the in-meeting admin-command
# rejection reply. Architectural Invariant 5 (Admin Surface Isolation):
# admin commands route exclusively through TG transport; in-meeting DM
# events matching admin grammar are rejected with this stock string and
# never mutate profile state.
ADMIN_NOT_SUPPORTED_HERE_REPLY: str = "admin commands not supported here"


def _cortex_tool_use_available() -> bool:
    """Return True iff the installed ``lattice_cortex`` exposes the
    v0.6.0+ tool-use API surface (``AgentSession``, ``ToolSpec``,
    ``ToolCallPart``, ``ToolResultPart``).

    Probed as a discrete function so the boot self-test can monkeypatch
    this in unit tests rather than mucking with the import system.
    """
    try:
        import lattice_cortex  # noqa: F401 -- import probe
    except ImportError:
        return False
    required_symbols = ("AgentSession", "ToolSpec", "ToolCallPart", "ToolResultPart")
    return all(hasattr(lattice_cortex, sym) for sym in required_symbols)


class Assistant:
    """In-meeting AI assistant primitive (W3.7 shell + W4.6 actor wiring).

    Per spec §3 the full ``__init__`` accepts:

    * ``meeting_id`` -- the active meeting identifier.
    * ``session`` -- ``MeetingSession`` from ``lattice-meeting-contracts``
      (W4.6 wires).
    * ``persona_resolver`` -- ``PersonaResolver`` from
      ``lattice_meeting.persona`` (W5 wires; W4.6 shell omits because
      ingest uses ``event.sender_canonical_id`` directly).
    * ``transcript_buffer`` -- ``TranscriptBuffer`` from
      ``lattice-meeting-contracts``; threaded into transcript tools at
      resolve time.
    * ``cortex_registry`` -- ``CortexRegistry`` from ``lattice-cortex``
      (W4.6 wires; consumed by the per-actor cortex-call closure).
    * ``brain_mcp`` -- ``BrainMCPClient | None``; ``None`` disables
      Brain-backed tools.
    * ``admin_transport`` -- ``AdminTransport | None`` (W5 wires; W4.6
      shell omits).
    * ``config`` -- ``AssistantConfig``.
    * ``profile`` -- ``AssistantProfile``.

    W4.6 consumes ``meeting_id``, ``transcript_buffer``, ``brain_mcp``,
    ``config``, ``profile``, ``session`` (new), and ``cortex_registry``
    (new). ``session`` and ``cortex_registry`` default to ``None`` so
    the W3.7 ``start()`` boot self-test still works without them
    (boot does not touch the actor pool); routing/lifecycle methods
    assert they are non-``None`` at call time.
    """

    def __init__(
        self,
        *,
        meeting_id: str,
        transcript_buffer: object,
        brain_mcp: BrainMCPClient | None,
        config: AssistantConfig,
        profile: AssistantProfile,
        session: object | None = None,
        cortex_registry: object | None = None,
    ) -> None:
        self.meeting_id = meeting_id
        self.config = config
        self.profile = profile
        self._transcript_buffer = transcript_buffer
        self._brain_mcp = brain_mcp
        self._session = session
        self._cortex_registry = cortex_registry

        # Populated by start(); empty until then.
        self.in_meeting_tool_names: frozenset[str] = frozenset()
        self.tg_owner_tool_names: frozenset[str] = frozenset()
        self._started: bool = False

        # Layer 3 -- one semaphore per Assistant instance; bound at
        # construction so callers can probe ``_global_semaphore._value``
        # without first calling ``start()`` (test affordance).
        self._global_semaphore: asyncio.Semaphore = asyncio.Semaphore(
            config.per_meeting_global_concurrency
        )

        # Layer 1 ownership -- actor pool + reap timers.
        # ``key`` = ``(meeting_id, persona_id)`` for private DM actors,
        # ``(meeting_id, "public")`` for the public-mention singleton.
        self._actors: dict[tuple[str, str], ChatThreadActor] = {}
        self._reap_timers: dict[tuple[str, str], asyncio.TimerHandle] = {}

        # Public-mention policy gates (W6.2). The handler owns
        # per-meeting rate-limit state + the enabled/allowlist
        # short-circuits per spec §3 lines 261-265 + spec §11 R5.
        self._public_mention_handler: PublicMentionHandler = PublicMentionHandler(
            profile=profile,
        )

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self) -> None:
        """Boot self-test per Spec §4 lines 673-681.

        Synchronous in v0.1 because all 5 steps are in-process probes
        (no I/O). W4.6 may async this when transcript-buffer
        subscription wiring lands; for now ``start()`` is a no-arg
        ``def`` so consumers don't need an event loop just to verify
        the privacy invariants at boot.

        Raises:

        * :class:`CapabilityNotSupported` -- cortex tool-use API
          surface unavailable.
        * :class:`ValueError` -- profile breaches Invariant 2 for the
          in-meeting-dm transport (e.g. ``allow_personal_vault=True``).
        """
        # Step 5 (run first so capability failure preempts every other
        # check -- if cortex can't accept tools we can't proceed
        # regardless of profile or invariants).
        if not _cortex_tool_use_available():
            raise CapabilityNotSupported(
                "cortex 0.6.0+ tool-use API required; the installed "
                "lattice_cortex does not expose the required surface "
                "(AgentSession, ToolSpec, ToolCallPart, ToolResultPart). "
                "Upgrade lattice-cortex or set ``brain_mcp=None`` + a "
                "tool-free profile if running in a degraded test mode."
            )

        # Step 1: resolve both transports. Resolver raises ValueError
        # for in-meeting-dm + allow_personal_vault=True (Invariant 2);
        # we let it propagate -- the test/consumer surface this as the
        # transport-bound hard-deny.
        in_meeting_tools = resolve_tool_set(
            thread_kind="in-meeting-dm",
            profile=self.profile,
            transcript_buffer=self._transcript_buffer,
            brain_mcp=self._brain_mcp,
        )
        tg_owner_tools = resolve_tool_set(
            thread_kind="tg-owner",
            profile=self.profile,
            transcript_buffer=self._transcript_buffer,
            brain_mcp=self._brain_mcp,
        )

        in_meeting_names = frozenset(t.name for t in in_meeting_tools)
        tg_owner_names = frozenset(t.name for t in tg_owner_tools)

        # Step 2: re-assert Invariant 2 backstop. (Resolver already
        # asserts via assert_in_meeting_tools_safe; do it again here
        # so the boot self-test owns its own diagnostic message even
        # if a future resolver bug skips the internal check.)
        assert_in_meeting_tools_safe(in_meeting_names)
        overlap = in_meeting_names & BLOCKED_IN_MEETING_TOOLS
        if overlap:
            # Defensive: assert_in_meeting_tools_safe should have raised
            # already. If it didn't (test seam manipulated the BLOCKED
            # set, etc.), surface the breach here.
            raise ValueError(
                "boot self-test: in-meeting tool set overlaps "
                f"BLOCKED_IN_MEETING_TOOLS: {sorted(overlap)}"
            )

        # Step 3: profile invariant on personal-vault for in-meeting-dm.
        # The resolver already raised if allow_personal_vault=True; we
        # re-assert here so the contract is documented at the
        # ``start()`` callsite too.
        if self.profile.knowledge.allow_personal_vault:
            # Unreachable in practice (resolver raised above); kept as
            # a documented sentinel so a reader of ``start()`` sees the
            # full §4 step list inline.
            raise ValueError(
                "profile.knowledge.allow_personal_vault=True is incompatible "
                "with the in-meeting-dm transport (Invariant 2)."
            )

        # Step 4: log resolved names at INFO. Names only -- never any
        # user/chat content (Invariant 4 INFO-no-content rule).
        logger.info(
            "Assistant.start(): resolved tool sets meeting_id=%s in_meeting=%s tg_owner=%s",
            self.meeting_id,
            sorted(in_meeting_names),
            sorted(tg_owner_names),
        )

        self.in_meeting_tool_names = in_meeting_names
        self.tg_owner_tool_names = tg_owner_names
        self._started = True

    # -----------------------------------------------------------------
    # W4.6 -- ingest + actor pool + lifecycle.
    # -----------------------------------------------------------------

    async def _cortex_call_with_semaphore(self, **kwargs: object) -> object:
        """Acquire the global semaphore, then delegate to the registry.

        Spec §7 lines 992-995. Every actor's ``cortex_call`` closure
        threads through this method so the per-meeting cap applies
        uniformly across the actor pool regardless of how many threads
        are running.
        """
        if self._cortex_registry is None:
            raise RuntimeError(
                "Assistant has no cortex_registry; pass one at construction "
                "for any code path that issues cortex calls (actor pool)."
            )
        async with self._global_semaphore:
            return await self._cortex_registry.call(**kwargs)  # type: ignore[attr-defined]

    def _is_allowed(
        self,
        sender_canonical_id: str | None,
        *,
        confidence: float | None,
    ) -> bool:
        """Allowlist tier check per spec §5 line 1009.

        Three tiers (T1 / T2 / T3 are the spec's allowlist-tier names;
        they are NOT the boundary-test names T1-T12):

        * **T1** -- ``sender_canonical_id`` appears in
          ``self.profile.dm_allowlist``. Allow unconditionally; confidence
          is not consulted (explicit listing is final).
        * **T2** -- ``sender_canonical_id`` resolves (not ``None``) AND
          ``confidence is not None`` AND
          ``confidence >= self.profile.dm_min_confidence``. Allow.
        * **T3** -- everything else (no canonical id, no confidence, or
          confidence below threshold). Default-deny; the caller surfaces
          the deny silently (no reply, no spam per spec §7 line 966).

        The min-confidence threshold is sourced from ``profile.dm_min_confidence``
        (default 0.85; spec §3 line 341).
        """
        # T1 -- explicit allowlist hit wins unconditionally.
        if sender_canonical_id is not None and sender_canonical_id in self.profile.dm_allowlist:
            return True

        # T3 -- unresolved persona id.
        if sender_canonical_id is None:
            return False

        # T3 -- no confidence signal at all.
        if confidence is None:
            return False

        # T2 / T3 split on confidence threshold.
        return confidence >= self.profile.dm_min_confidence

    # ---------------------------------------------------------------------
    # System-prompt renderers (W6.1+)
    # ---------------------------------------------------------------------

    # OQ-followup (OQ-W6-1): the W6 prompt-renderer plumbing wires the
    # full Spec §4 templates through to cortex, but several inputs are
    # still placeholders pending W7 integration:
    #   * persona_voice_block -- full Cody Voice Identity render not
    #     wired here; currently returns an empty stub. Will land when
    #     lattice-persona-profile v0.1 is consumable.
    #   * tool_list -- assembled by sorting the resolved tool name set,
    #     but the human-friendly "what each tool does" descriptions are
    #     not in the template surface yet (model sees names only).
    #   * transcript_hot_window -- empty stub; the W3 transcript-buffer
    #     `get_hot_window` is not yet bound here (lands in W7 AQH
    #     integration alongside the wrap-up wiring).
    #   * conversation_history / current_message_text -- the cortex
    #     tool-use loop threads turns via its conversation messages
    #     array, so these template tokens render to empty strings here.
    # Surface follow-up filed at W6 close.

    def _render_dm_system_prompt(self, *, event: object | None = None) -> str:
        """Render the in-meeting-DM system prompt for the private path.

        Pulled into a helper rather than embedded so the actor's
        per-instance closure (constructed below in :meth:`_get_or_spawn_actor`)
        can capture the sender context cleanly. The actor itself never
        inspects the string -- it threads it through to cortex verbatim.
        """
        # OQ-followup: persona_voice_block + transcript_hot_window
        # placeholders pending W7 (see OQ-W6-1 above).
        sender_display = "Unknown Participant"
        sender_canonical_id = "anonymous"
        sender_confidence = 0.0
        if event is not None:
            sender_display = getattr(event, "sender_display_name", sender_display)
            sender_canonical_id = getattr(event, "sender_canonical_id", None) or sender_canonical_id
            sender_confidence = getattr(event, "sender_canonical_confidence", None) or 0.0

        return render_in_meeting_dm_prompt(
            meeting_title=self.meeting_id,  # v0.1 stub: meeting_id-as-title; W7 wires real title
            persona_voice_block="",
            tool_list=", ".join(sorted(self.in_meeting_tool_names)),
            transcript_hot_window="",
            sender_canonical_display_name=sender_display,
            sender_canonical_id=sender_canonical_id,
            sender_canonical_confidence=sender_confidence,
        )

    def _render_public_mention_system_prompt(self) -> str:
        """Render the public-mention system prompt for the public path.

        Same Cody Voice Identity scaffolding as
        :meth:`_render_dm_system_prompt` but uses the public-variant
        template per Spec §4 lines 644-671. The public actor binds
        this method as its ``system_prompt_renderer`` -- no per-event
        sender substitution needed (public mentions key on
        ``(meeting_id, "public")``).
        """
        # OQ-followup: persona_voice_block + transcript_hot_window
        # placeholders pending W7 (see OQ-W6-1 above).
        return render_public_mention_prompt(
            meeting_title=self.meeting_id,
            persona_voice_block="",
            tool_list=", ".join(sorted(self.in_meeting_tool_names)),
            transcript_hot_window="",
        )

    def _render_system_prompt(self) -> str:
        """No-arg DM-prompt renderer. Retained for back-compat with the
        W4 actor wiring (private actors bind this via
        :meth:`_make_dm_renderer_for_event`). For public actors, the
        public-mention renderer is bound directly.
        """
        return self._render_dm_system_prompt(event=None)

    def _make_dm_renderer_for_event(self, event: object) -> "Callable[[], str]":
        """Return a no-arg closure that renders the DM prompt for
        ``event``'s sender context.

        The actor's ``system_prompt_renderer`` signature is no-arg, so
        sender context has to be captured in the closure rather than
        threaded through at call time.
        """

        def _render() -> str:
            return self._render_dm_system_prompt(event=event)

        return _render

    def _get_or_spawn_actor(self, event: object) -> ChatThreadActor:
        """Return the actor for ``event``'s key.

        Spawns a fresh :class:`ChatThreadActor` on cache miss; cancels
        any pending reap timer for the key on cache hit (the sender
        rejoined while the timer was still pending). Routes:

        * private DM (``is_private=True``) -> key
          ``(meeting_id, sender_canonical_id)`` + DM prompt renderer +
          in-meeting-dm tool set.
        * public mention (``is_private=False``) -> key
          ``(meeting_id, "public")`` + public-mention prompt renderer +
          same in-meeting-dm tool set (Invariant 2: same curated set
          applies to both transports since both run in-meeting).
        """
        meeting_id = getattr(event, "meeting_id", self.meeting_id)
        is_private = getattr(event, "is_private", True)
        if is_private:
            persona_id = getattr(event, "sender_canonical_id", None) or "anonymous"
            key: tuple[str, str] = (meeting_id, persona_id)
            renderer: Callable[[], str] = self._make_dm_renderer_for_event(event)
        else:
            key = (meeting_id, "public")
            renderer = self._render_public_mention_system_prompt

        if key in self._actors:
            # Cache hit -- cancel any reap timer that may still be
            # ticking (the sender rejoined before the grace expired).
            timer = self._reap_timers.pop(key, None)
            if timer is not None:
                timer.cancel()
            actor = self._actors[key]
            actor.cancel_idle()
            return actor

        # Cache miss -- resolve the curated in-meeting-dm tool set.
        # Both private DM and public mention bind to the in-meeting-dm
        # transport per Invariant 2: same curated set, no personal-vault
        # access. The public-mention prompt template ALSO instructs the
        # model not to reveal vault access (defense in depth).
        tool_set = resolve_tool_set(
            thread_kind="in-meeting-dm",
            profile=self.profile,
            transcript_buffer=self._transcript_buffer,
            brain_mcp=self._brain_mcp,
        )

        actor = ChatThreadActor(
            key=key,
            cortex_call=self._cortex_call_with_semaphore,
            session=self._session,
            config=self.config,
            tool_set=tool_set,
            system_prompt_renderer=renderer,
        )
        actor.start()
        self._actors[key] = actor
        return actor

    async def on_private_chat(self, event: object) -> None:
        """Route private DM into per-(meeting, persona) actor.

        Spec §7 lines 958-975 + spec §5 line 714 (T7). Order matters:

        1. Invariant 4 fail-closed visibility check (missing/None
           ``is_private`` -> :class:`PrivacyBoundaryViolation`).
        2. Allowlist gate (W4 stub returns True; W5 implements the
           tier semantics + silent-deny on T3).
        3. Admin-grammar rejection (Invariant 5, T7): the in-meeting-dm
           transport rejects strings matching the admin grammar with
           the stock reply. ``on_private_chat`` IS the in-meeting-dm
           ingress in v0.1; this check fires unconditionally for events
           that clear the allowlist gate. Non-allowlisted senders
           sending admin grammar receive the silent T3 deny first --
           no information leak about admin command syntax.
        4. Spawn-or-reuse actor for the ``(meeting, persona)`` key.
        5. ``enqueue`` -> on ``False`` (queue full), surface the
           backpressure reply via ``session.send_chat`` addressed to
           the originating ``sender_user_id``.
        """
        # Step 1: Invariant 4 fail-closed.
        enforce_visibility_tag(event)

        # Step 2: allowlist tier gate (W5.1) -- T1/T2/T3 per spec §5 line 1009.
        sender_canonical_id = getattr(event, "sender_canonical_id", None)
        confidence = getattr(event, "sender_canonical_confidence", None)
        if not self._is_allowed(sender_canonical_id, confidence=confidence):
            return  # silent deny -- no reply, no spam (spec §7 line 966)

        # Step 3: Invariant 5 admin-grammar rejection (T7).
        # ``on_private_chat`` is the in-meeting-dm ingress -- admin
        # commands route exclusively through TG transport per
        # ``[[Meeting Platform Admin Surface Isolation]]``.
        text = getattr(event, "text", "")
        if is_admin_command_syntax(text):
            sender_user_id = getattr(event, "sender_user_id", None)
            if sender_user_id is not None and self._session is not None:
                await self._session.send_chat(  # type: ignore[attr-defined]
                    to_user_id=sender_user_id,
                    message=ADMIN_NOT_SUPPORTED_HERE_REPLY,
                )
            else:
                # Defensive: misconfigured caller. Log + return without
                # spawning an actor or mutating state.
                logger.warning(
                    "Assistant.on_private_chat: admin-grammar event but no "
                    "session/sender to reply via meeting_id=%s text=<redacted>",
                    self.meeting_id,
                )
            return  # NEVER route to actor / cortex / Brain write-back

        # Step 4 + 5.
        actor = self._get_or_spawn_actor(event)
        ok = await actor.enqueue(event)  # type: ignore[arg-type]
        if not ok:
            sender_user_id = getattr(event, "sender_user_id", None)
            if sender_user_id is None or self._session is None:
                # Defensive: a misconfigured caller shouldn't crash the
                # actor pool. Log + return.
                logger.warning(
                    "Assistant.on_private_chat: backpressure but no "
                    "session/sender to reply via meeting_id=%s key=%s",
                    self.meeting_id,
                    actor.key,
                )
                return
            await self._session.send_chat(  # type: ignore[attr-defined]
                to_user_id=sender_user_id,
                message="I'm catching up on your earlier messages -- give me a sec.",
            )

    async def on_participant_left(self, participant_canonical_id: str) -> None:
        """Mark the participant's actor idle + schedule a reap timer.

        Spec §7 lifecycle table (lines 977-987): on leave, the actor
        is marked idle and the reap timer fires after
        ``POST_LEAVE_GRACE_SECS_DEFAULT`` seconds. On rejoin
        (:meth:`on_participant_joined`) the timer is cancelled.

        Public actors are not subject to leave-based reaping (they
        live the full meeting); only the private DM actor for the
        leaving participant is touched.
        """
        key = (self.meeting_id, participant_canonical_id)
        actor = self._actors.get(key)
        if actor is None:
            # No actor for this participant -- nothing to reap.
            return

        actor.mark_idle()
        # Schedule the reap. Use ``loop.call_later`` so the timer fires
        # in the host loop's clock (the same one the actor's
        # ``is_idle_for`` consults).
        loop = asyncio.get_event_loop()

        def _fire_reap(k: tuple[str, str] = key) -> None:
            # call_later expects a sync callback; we spawn the async
            # reap as a task so the loop is not blocked.
            asyncio.create_task(self._reap_actor(k))

        timer = loop.call_later(POST_LEAVE_GRACE_SECS_DEFAULT, _fire_reap)
        # If a timer already existed (rare -- two leaves without an
        # intervening join), cancel the stale one before storing the
        # fresh one so we don't leak.
        old = self._reap_timers.get(key)
        if old is not None:
            old.cancel()
        self._reap_timers[key] = timer

    async def on_participant_joined(self, participant_canonical_id: str) -> None:
        """Cancel any pending reap timer + clear the idle marker.

        Spec §7 lifecycle table: on rejoin within the grace window,
        the same actor continues with its memory intact.
        """
        key = (self.meeting_id, participant_canonical_id)
        actor = self._actors.get(key)
        if actor is not None:
            actor.cancel_idle()
        timer = self._reap_timers.pop(key, None)
        if timer is not None:
            timer.cancel()

    async def _reap_actor(self, key: tuple[str, str]) -> None:
        """Drain + shutdown the actor at ``key`` and remove from the pool.

        Invoked from the reap timer scheduled by
        :meth:`on_participant_left`. Idempotent: a second call when the
        actor has already been removed (e.g. by ``shutdown``) is safe.
        """
        actor = self._actors.pop(key, None)
        self._reap_timers.pop(key, None)
        if actor is None:
            return
        try:
            await actor.drain(timeout_s=5.0)
        except asyncio.TimeoutError:
            logger.warning(
                "Assistant._reap_actor: drain timeout key=%s; forcing shutdown",
                key,
            )
        await actor.shutdown()

    async def on_public_mention(self, event: object) -> None:
        """Route public @-mention into the per-meeting public actor.

        Spec §3 lines 261-265 + spec §5 T11/T12. Order:

        1. Invariant 4 fail-closed visibility check (missing/None
           ``is_private`` -> :class:`PrivacyBoundaryViolation`).
        2. :class:`PublicMentionHandler` policy gates:

           * ``profile.public_mentions_enabled is False`` -> silent
             decline (no reply, no actor spawn).
           * ``profile.public_mention_allowlist`` set and sender NOT
             listed -> silent decline.
           * Per-meeting rate-limit window not yet elapsed -> silent
             decline.

        3. Spawn-or-reuse the singleton ``(meeting_id, "public")``
           actor; enqueue the event. The actor's worker dispatches to
           cortex and routes the reply via ``session.send_chat_public``.
        4. Record the reply timestamp on the handler so the rate-limit
           window applies to subsequent @-mentions in this meeting.

        Public-mention queue-full backpressure: unlike the private DM
        path, public mentions deliberately do NOT surface a backpressure
        reply when the queue saturates -- a public-chat "I'm catching
        up" string would (a) leak operational context to every
        participant and (b) compound the loop-trigger risk that R5
        defends against. Public mentions on a saturated queue silently
        drop; the rate-limit gate already prevents the saturation
        cause in practice.
        """
        # Step 1: Invariant 4 fail-closed.
        enforce_visibility_tag(event)

        # Step 2: policy gates.
        meeting_id = getattr(event, "meeting_id", self.meeting_id)
        sender_canonical_id = getattr(event, "sender_canonical_id", None)
        verdict = self._public_mention_handler.evaluate(
            meeting_id=meeting_id,
            sender_canonical_id=sender_canonical_id,
        )
        if verdict.decision != "allow":
            logger.info(
                "Assistant.on_public_mention: silent decline meeting_id=%s decision=%s reason=%s",
                meeting_id,
                verdict.decision,
                verdict.reason,
            )
            return

        # Step 3: spawn-or-reuse public actor + enqueue.
        actor = self._get_or_spawn_actor(event)
        ok = await actor.enqueue(event)  # type: ignore[arg-type]
        if not ok:
            # Saturated queue: silent drop (see docstring rationale).
            logger.info(
                "Assistant.on_public_mention: public actor queue full; "
                "silent drop meeting_id=%s key=%s",
                meeting_id,
                actor.key,
            )
            return

        # Step 4: record the reply timestamp so the rate-limit window
        # ticks. We record on enqueue rather than on send_chat_public
        # because the queue is bounded + serialized -- a successful
        # enqueue is a near-certain reply (modulo cortex failure, which
        # the actor handles with a fallback string).
        self._public_mention_handler.record_reply(meeting_id=meeting_id)

    async def shutdown(self, *, drain_timeout_s: float = SHUTDOWN_DRAIN_TIMEOUT_DEFAULT_S) -> None:
        """Drain every actor in the pool, then cancel its worker.

        Spec §7 lifecycle table (line 986). Iterates a snapshot of the
        pool so concurrent reap timers don't disturb the iteration.
        Each actor's ``drain(timeout_s=...)`` is awaited; if it times
        out we still proceed to :meth:`ChatThreadActor.shutdown` so the
        worker task is cancelled and the asyncio runtime cleans up.

        Reap timers are cancelled before draining so the loop doesn't
        race with a fresh timer-driven reap on the same key.
        """
        # Cancel pending reap timers first so we don't double-shutdown.
        for timer in list(self._reap_timers.values()):
            timer.cancel()
        self._reap_timers.clear()

        # Snapshot the actor pool so we can iterate while we mutate it.
        actors = list(self._actors.items())
        # Per-actor drain timeout: split the budget across the pool so
        # one stuck actor can't eat the entire envelope. ``drain`` is
        # the cooperative path; ``shutdown`` is the cancel-all backstop.
        per_actor = max(0.1, drain_timeout_s / max(1, len(actors)))
        for key, actor in actors:
            try:
                await actor.drain(timeout_s=per_actor)
            except asyncio.TimeoutError:
                logger.warning(
                    "Assistant.shutdown: drain timed out key=%s; cancelling worker",
                    key,
                )
            await actor.shutdown()
        self._actors.clear()


__all__ = ["Assistant"]
