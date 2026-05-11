"""lattice-meeting-assistant -- in-meeting AI assistant primitive.

See vault ``02_Projects/Lattice/lattice-meeting-assistant/Mission.md`` and the
v0.1 Design Spec for the full surface. Public API grows across W1-W7.
"""

from __future__ import annotations

from typing import Literal

from ._version import __version__
from .exceptions import (
    AdminAuthorizationDenied,
    CapabilityNotSupported,
    CortexUnavailable,
    PrivacyBoundaryViolation,
)

TierName = Literal["interactive", "research"]

__all__ = [
    "__version__",
    "TierName",
    "PrivacyBoundaryViolation",
    "AdminAuthorizationDenied",
    "CapabilityNotSupported",
    "CortexUnavailable",
]
