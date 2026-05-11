"""Exception types raised by the Assistant. Stable public API."""

from __future__ import annotations


class PrivacyBoundaryViolation(Exception):
    """Raised when a chat event reaches the Assistant without an
    ``is_private`` visibility tag (Architectural Invariant 4 fail-closed).

    Never silently default; ambiguity = refuse.
    """


class AdminAuthorizationDenied(Exception):
    """Raised when ``admin_command()`` is called with a ratifying user who
    is not in ``profile.admins``."""


class CapabilityNotSupported(Exception):
    """Raised when the caller invokes a method gated on a
    ``PlatformChatCapability`` flag that the current platform's adapter
    denies (e.g., ``proactive_dm`` on a platform that does not allow it)."""


class CortexUnavailable(Exception):
    """Raised when the cortex registry exhausts its fallback cascade and
    cannot produce a reply.

    The Assistant catches this internally and surfaces a user-facing
    graceful-degradation message; callers see this only in test paths.
    """
