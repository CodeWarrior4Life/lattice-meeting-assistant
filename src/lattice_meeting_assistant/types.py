"""Shared types for the assistant library.

See spec §3 for the public API surface; this module defines the value
types (frozen dataclasses) used at the library boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

# Type alias; real validation in ``lattice_meeting.persona``.
CanonicalPersonaId = str


@dataclass(frozen=True)
class ChatEvent:
    """An inbound chat event from a meeting-platform adapter.

    Adapter-agnostic; concrete adapters translate platform events to this
    shape.
    """

    id: str
    meeting_id: str
    platform: str  # "zoom" | "google-meet" | "ms-teams"
    sender_user_id: str  # platform-native user id (ephemeral for some platforms)
    sender_canonical_id: CanonicalPersonaId | None  # resolved; None = unresolved (T3)
    sender_canonical_confidence: float | None
    sender_display_name: str
    text: str
    ts: datetime
    is_private: bool  # Invariant 4 -- MUST be present, never missing
    is_at_mention_to_bot: bool = False  # True for public @-mentions of self
    tier: str | None = None  # parsed from message flag (e.g., "/think" -> "research")


@dataclass(frozen=True)
class ConversationTurn:
    """One turn in a ``ChatThreadActor``'s conversation history."""

    role: str  # "user" | "assistant"
    content: str
    ts: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileMutation:
    """Audit entry written to ``AssistantProfile.in_memory_mutations_history``
    and persisted to profile YAML when ``persistent`` flag set.
    """

    ts: str  # ISO 8601
    action: str  # "add" | "remove" | "mode_change" | "mute" | "unmute"
    # canonical persona id for allowlist mutations; tier name for
    # mode_change; None for mute/unmute
    target: str | None
    by: CanonicalPersonaId
    session_id: str


@dataclass(frozen=True)
class AdminCommandResult:
    """Return type from ``Assistant.admin_command()``."""

    ok: bool
    response_text: str
    mutation: ProfileMutation | None = None  # set when allowlist mutated
    error_kind: str | None = None  # set when ok=False


@dataclass
class AssistantStats:
    """Observability snapshot (mutable; refreshed via ``Assistant.stats``)."""

    actor_count: int = 0
    in_flight_cortex_calls: int = 0
    total_cortex_tokens_consumed: int = 0
    total_replies_sent: int = 0
    privacy_boundary_violations: int = 0
    per_thread_queue_depth_max: int = 0
