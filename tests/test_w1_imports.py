"""W1.3 — smoke test for version + initial public-API imports.

Per Implementation Plan task W1.3 Step 1. Written failing-first per TDD;
implementation lands in `_version.py` + `__init__.py` + `exceptions.py`.
"""

from __future__ import annotations


def test_version_exposed() -> None:
    import lattice_meeting_assistant

    assert lattice_meeting_assistant.__version__ == "0.1.0.dev0"


def test_public_api_imports_clean() -> None:
    # Will be filled out as the API surface lands; for now just smoke
    from lattice_meeting_assistant import (
        AdminAuthorizationDenied,
        CapabilityNotSupported,
        CortexUnavailable,
        PrivacyBoundaryViolation,
        TierName,
    )

    # Just ensure imports resolve
    assert PrivacyBoundaryViolation is not None
    assert AdminAuthorizationDenied is not None
    assert CapabilityNotSupported is not None
    assert CortexUnavailable is not None
    assert TierName is not None
