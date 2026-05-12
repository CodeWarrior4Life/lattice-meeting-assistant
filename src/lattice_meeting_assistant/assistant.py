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

from .actor import POST_LEAVE_GRACE_SECS_DEFAULT, ChatThreadActor
from .brain_client import BrainMCPClient
from .config import AssistantConfig
from .exceptions import CapabilityNotSupported
from .privacy.invariants import (
    BLOCKED_IN_MEETING_TOOLS,
    assert_in_meeting_tools_safe,
    enforce_visibility_tag,
)
from .profile import AssistantProfile
from .tools.resolver import resolve_tool_set

logger = logging.getLogger(__name__)


# Drain-timeout default for ``Assistant.shutdown``. Sourced from spec §7
# lifecycle table (line 986: "Drain all queues (timeout=30s)").
# OQ-followup: surface ``meeting_shutdown_drain_timeout_secs`` as a
# config field on :class:`AssistantConfig` so consumers can tune.
SHUTDOWN_DRAIN_TIMEOUT_DEFAULT_S: float = 30.0


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

    def _is_allowed(self, sender_canonical_id: str | None) -> bool:
        """Tier check stub (W4); W5 implements the real allowlist gate.

        W5 will consult ``self.profile.dm_allowlist`` plus the Q4a
        mapped-confidence tier. For W4 we accept every sender so the
        ingest pipeline can be exercised end-to-end; the boundary
        tests T1/T6/T10 do not depend on the allowlist semantics.
        """
        # W5: tier check
        return True

    def _render_system_prompt(self) -> str:
        """Trivial system-prompt renderer for W4.

        W5 wires the full Cody-Voice-Identity-driven render path; W4
        returns a static string so the actor has *something* to send
        with the cortex call. The actor never inspects the string --
        it threads it through to cortex verbatim.
        """
        # W5: full template render per Cody Voice Identity protocol.
        return "You are the in-meeting assistant."

    def _get_or_spawn_actor(self, event: object) -> ChatThreadActor:
        """Return the actor for ``event``'s (meeting, persona) key.

        Spawns a fresh :class:`ChatThreadActor` on cache miss; cancels
        any pending reap timer for the key on cache hit (the sender
        rejoined while the timer was still pending).
        """
        meeting_id = getattr(event, "meeting_id", self.meeting_id)
        # W5/W6: derive thread_kind from event transport. v0.1 anchors
        # on the meeting DM as the in-meeting case.
        thread_kind: str = "in-meeting-dm"
        is_private = getattr(event, "is_private", True)
        if is_private:
            persona_id = getattr(event, "sender_canonical_id", None) or "anonymous"
            key: tuple[str, str] = (meeting_id, persona_id)
        else:
            key = (meeting_id, "public")
            thread_kind = "in-meeting-public"

        if key in self._actors:
            # Cache hit -- cancel any reap timer that may still be
            # ticking (the sender rejoined before the grace expired).
            timer = self._reap_timers.pop(key, None)
            if timer is not None:
                timer.cancel()
            actor = self._actors[key]
            actor.cancel_idle()
            return actor

        # Cache miss -- resolve the curated tool set for the transport
        # and instantiate the actor.
        # W5/W6: thread_kind may be "in-meeting-public" once the
        # public-mention path lands; for W4 every routed event is a
        # private DM so the curated in-meeting-dm tool set applies.
        tool_set = resolve_tool_set(
            thread_kind="in-meeting-dm",  # W6: thread_kind for public
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
            system_prompt_renderer=self._render_system_prompt,
        )
        actor.start()
        self._actors[key] = actor
        return actor

    async def on_private_chat(self, event: object) -> None:
        """Route private DM into per-(meeting, persona) actor.

        Spec §7 lines 958-975. Order matters:

        1. Invariant 4 fail-closed visibility check (missing/None
           ``is_private`` -> :class:`PrivacyBoundaryViolation`).
        2. Allowlist gate (W4 stub returns True; W5 implements the
           tier semantics + silent-deny on T3).
        3. Spawn-or-reuse actor for the ``(meeting, persona)`` key.
        4. ``enqueue`` -> on ``False`` (queue full), surface the
           backpressure reply via ``session.send_chat`` addressed to
           the originating ``sender_user_id``.
        """
        # Step 1: Invariant 4 fail-closed.
        enforce_visibility_tag(event)

        # Step 2: allowlist tier gate (W5 backfills the real check).
        sender_canonical_id = getattr(event, "sender_canonical_id", None)
        if not self._is_allowed(sender_canonical_id):
            return  # silent deny -- no reply, no spam

        # Step 3 + 4.
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
        """Route public @-mention. W3 shell -- backfilled at W6.5."""
        raise NotImplementedError(
            "Assistant.on_public_mention lands at W6.5 -- the W4 shell "
            "only ships the private-DM path."
        )

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
