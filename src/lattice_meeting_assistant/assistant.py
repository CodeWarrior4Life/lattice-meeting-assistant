"""Minimal :class:`Assistant` shell -- W3.7 scope.

Per Design Spec §3 (lines 232-292) the full ``Assistant`` class
exposes ``on_private_chat``, ``on_public_mention``, ``admin_command``,
``start``, ``shutdown``, and ``stats``. W3 ships only the constructor
shape plus :meth:`Assistant.start` -- the boot self-test that wires
the tool resolver for both transports and verifies Architectural
Invariants 2 + 4 end-to-end at session-start.

W4.6 backfills the rest of the public surface (actor pool,
chat-event ingest, lifecycle, semaphore). The methods that don't
exist yet raise :class:`NotImplementedError` with a pointer to the
landing W-phase so a premature caller gets a clear error rather
than a silent no-op.

Spec §4 boot self-test (lines 673-681):

1. Resolve tool sets for both transports.
2. Assert ``BLOCKED_IN_MEETING_TOOLS & in_meeting_set_names == ∅``.
3. Assert ``profile.knowledge.allow_personal_vault == False`` when the
   transport is ``in-meeting-dm`` (the resolver surfaces this via
   ``ValueError``; ``start()`` lets it propagate).
4. Log resolved tool set names at INFO (no content per Invariant 4).
5. If cortex's tool-use API surface is unavailable -> raise
   :class:`CapabilityNotSupported` (Spec §9 OQ2).
"""

from __future__ import annotations

import logging

from .brain_client import BrainMCPClient
from .config import AssistantConfig
from .exceptions import CapabilityNotSupported
from .privacy.invariants import BLOCKED_IN_MEETING_TOOLS, assert_in_meeting_tools_safe
from .profile import AssistantProfile
from .tools.resolver import resolve_tool_set

logger = logging.getLogger(__name__)


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
    """In-meeting AI assistant primitive (W3.7 minimal shell).

    Per spec §3 the full ``__init__`` accepts:

    * ``meeting_id`` -- the active meeting identifier.
    * ``session`` -- ``MeetingSession`` from ``lattice-meeting-contracts``
      (W4.6 wires; W3 shell omits).
    * ``persona_resolver`` -- ``PersonaResolver`` from
      ``lattice_meeting.persona`` (W4.6 wires; W3 shell omits).
    * ``transcript_buffer`` -- ``TranscriptBuffer`` from
      ``lattice-meeting-contracts``; threaded into transcript tools at
      resolve time.
    * ``cortex_registry`` -- ``CortexRegistry`` from ``lattice-cortex``
      (W4.6 wires; W3 shell omits because the boot self-test only
      probes the tool-use API surface, not a live registry).
    * ``brain_mcp`` -- ``BrainMCPClient | None``; ``None`` disables
      Brain-backed tools.
    * ``admin_transport`` -- ``AdminTransport | None`` (W5 wires; W3
      shell omits).
    * ``config`` -- ``AssistantConfig``.
    * ``profile`` -- ``AssistantProfile``.

    W3.7 only consumes ``meeting_id``, ``transcript_buffer``,
    ``brain_mcp``, ``config``, and ``profile`` -- everything else
    lands at W4.6. The signature here is the W3-minimal subset; W4.6
    will expand to the full spec §3 shape.
    """

    def __init__(
        self,
        *,
        meeting_id: str,
        transcript_buffer: object,
        brain_mcp: BrainMCPClient | None,
        config: AssistantConfig,
        profile: AssistantProfile,
    ) -> None:
        self.meeting_id = meeting_id
        self.config = config
        self.profile = profile
        self._transcript_buffer = transcript_buffer
        self._brain_mcp = brain_mcp

        # Populated by start(); empty until then.
        self.in_meeting_tool_names: frozenset[str] = frozenset()
        self.tg_owner_tool_names: frozenset[str] = frozenset()
        self._started: bool = False

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
    # W4.6 surface -- placeholders that fail clearly until backfilled.
    # -----------------------------------------------------------------

    async def on_private_chat(self, event: object) -> None:
        """Route private DM into per-(meeting, persona) actor.

        W3 shell raises ``NotImplementedError``. W4.6 backfills the
        actor wiring + Invariant 4/5 enforcement at ingest.
        """
        raise NotImplementedError(
            "Assistant.on_private_chat lands at W4.6 -- the W3 shell only ships the boot self-test."
        )

    async def on_public_mention(self, event: object) -> None:
        """Route public @-mention. W3 shell -- backfilled at W6.5."""
        raise NotImplementedError(
            "Assistant.on_public_mention lands at W6.5 -- the W3 shell "
            "only ships the boot self-test."
        )

    async def shutdown(self, *, drain_timeout_s: float = 30.0) -> None:
        """Drain in-flight actors. W3 shell -- backfilled at W4.6."""
        raise NotImplementedError(
            "Assistant.shutdown lands at W4.6 -- the W3 shell only ships the boot self-test."
        )


__all__ = ["Assistant"]
