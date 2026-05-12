"""lattice-meeting-assistant -- in-meeting AI assistant primitive.

See vault ``02_Projects/Lattice/lattice-meeting-assistant/Mission.md`` and the
v0.1 Design Spec for the full surface. Public API grows across W1-W7.
"""

from __future__ import annotations

from typing import Literal

from ._version import __version__
from .actor import ChatThreadActor
from .admin import (
    AdminCommand,
    AdminCommandDispatcher,
    AdminCommandError,
    AdminVerb,
    parse_admin_command,
)
from .assistant import Assistant
from .config import AssistantConfig, KnowledgeAccessConfig
from .exceptions import (
    AdminAuthorizationDenied,
    CapabilityNotSupported,
    CortexUnavailable,
    PrivacyBoundaryViolation,
)
from .profile import (
    AssistantProfile,
    dump_profile_to_yaml,
    load_profile_from_yaml,
)
from .series import SeriesMatch, SeriesMatcher
from .types import (
    AdminCommandResult,
    AssistantStats,
    CanonicalPersonaId,
    ChatEvent,
    ConversationTurn,
    ProfileMutation,
)

TierName = Literal["interactive", "research"]

__all__ = [
    "__version__",
    "TierName",
    # Assistant
    "Assistant",
    # Actor (W4)
    "ChatThreadActor",
    # Exceptions
    "PrivacyBoundaryViolation",
    "AdminAuthorizationDenied",
    "CapabilityNotSupported",
    "CortexUnavailable",
    # Config
    "AssistantConfig",
    "KnowledgeAccessConfig",
    # Profile
    "AssistantProfile",
    "ProfileMutation",
    "load_profile_from_yaml",
    "dump_profile_to_yaml",
    # Series (W5)
    "SeriesMatch",
    "SeriesMatcher",
    # Admin (W5.4)
    "AdminCommand",
    "AdminCommandDispatcher",
    "AdminCommandError",
    "AdminVerb",
    "parse_admin_command",
    # Types
    "ChatEvent",
    "ConversationTurn",
    "AdminCommandResult",
    "AssistantStats",
    "CanonicalPersonaId",
]
