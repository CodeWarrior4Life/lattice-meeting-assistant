"""AssistantConfig + KnowledgeAccessConfig dataclasses.

See spec §3 for field semantics + defaults; spec §4 for ``KnowledgeAccessConfig``
enforcement (Architectural Invariant #2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TierName = Literal["interactive", "research"]


@dataclass(frozen=True)
class KnowledgeAccessConfig:
    """Per-profile knowledge access policy. Enforced transport-bound by
    the resolver -- ``allow_personal_vault=False`` is a HARD invariant for
    in-meeting-dm transport regardless of this config value (spec §4
    ``BLOCKED_IN_MEETING_TOOLS``).
    """

    # Architectural Invariant #2 -- in-meeting DM hard-deny on personal vault.
    # The resolver overrides this to False unconditionally for in-meeting-dm
    # transport; True is only meaningful for tg-owner transport.
    allow_personal_vault: bool = False

    # Live transcript window -- ALWAYS ON for in-meeting DM (spec §Q6 overlay).
    transcript_hot_window_seconds: int = 300
    enable_transcript_search_tool: bool = True

    # Past meetings (series-scoped, configurable).
    enable_past_meetings_search: bool = True

    # Public references.
    public_references: tuple[str, ...] = ()
    enable_public_references_tool: bool = True

    # Web search.
    enable_web_search: bool = True


@dataclass(frozen=True)
class AssistantConfig:
    """Behavioral knobs (Q3 + Q5 + Q7 overlays). All defaults from spec §3."""

    # Identity-in-chat (Q3).
    auto_intro: bool = False
    disclose_ai: bool = False  # per Cody Voice Identity §Banned
    address_by_canonical_name: bool = True
    canonical_name_min_confidence: float = 0.85

    # Latency + degradation (Q5).
    default_tier: TierName = "interactive"  # Sonnet
    deep_tier: TierName = "research"  # Opus
    deep_tier_message_flag: str = "/think"
    holding_message_after_ms: int = 3000
    max_response_tokens: int = 200
    per_sender_rate_min_interval_ms: int = 2000

    # Concurrency (Q7).
    per_thread_queue_depth: int = 5
    per_meeting_global_concurrency: int = 4
    actor_post_leave_grace_s: int = 60
    actor_history_max_tokens: int = 16000
    # Per-meeting drain envelope (spec §7 lifecycle table line 986).
    # Honored by ``Assistant.shutdown`` when caller does not pass an
    # explicit ``drain_timeout_s``.
    meeting_shutdown_drain_timeout_s: float = 30.0

    # Memory (Q4c + Q6).
    remember_across_meetings: bool = False

    # Series matching (Q6 overlay).
    series_ratification_timeout_s: int = 120

    # Observability.
    debug_chat_content: bool = False
