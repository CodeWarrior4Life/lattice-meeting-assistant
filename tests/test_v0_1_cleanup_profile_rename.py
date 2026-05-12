"""W7-prep cleanup test -- TKT-aeff7083.

Defends the spec-parity rename ``source_vault_note`` ->
``profile_vault_path`` on :class:`AssistantProfile`. Spec §3 line 398
already used ``profile_vault_path`` for ``SeriesMatch.profile_vault_path``;
the implementation diverged with the legacy name. This regression guard
fixes the term across the surface.
"""

from __future__ import annotations

from dataclasses import fields

from lattice_meeting_assistant.profile import AssistantProfile


def test_assistant_profile_uses_profile_vault_path_field_name() -> None:
    """TKT-aeff7083 -- spec uses ``profile_vault_path``, not ``source_vault_note``."""
    field_map = {f.name: f for f in fields(AssistantProfile)}
    assert "profile_vault_path" in field_map, (
        "AssistantProfile must expose ``profile_vault_path`` for spec parity "
        "(spec §3 line 398 + W5.5 plan reference)."
    )
    assert "source_vault_note" not in field_map, (
        "Legacy ``source_vault_note`` name must be removed after rename."
    )
