"""W7-prep cleanup test -- TKT-349645ab.

Defends the field-promotion contract that the W7-prep cleanup batch
landed before GA cut:

* ``AssistantConfig.meeting_shutdown_drain_timeout_s`` (TKT-349645ab) --
  the per-meeting envelope for ``Assistant.shutdown(drain_timeout_s=...)``
  is now a config field, not a module-level constant.
"""

from __future__ import annotations

from dataclasses import fields

from lattice_meeting_assistant.config import AssistantConfig


def test_assistant_config_has_meeting_shutdown_drain_timeout_s_default_30() -> None:
    """TKT-349645ab -- the drain-timeout envelope lives on config now."""
    cfg = AssistantConfig()
    assert cfg.meeting_shutdown_drain_timeout_s == 30.0
    # And the dataclass field is typed ``float`` (not int).
    field_map = {f.name: f for f in fields(AssistantConfig)}
    assert "meeting_shutdown_drain_timeout_s" in field_map
    assert field_map["meeting_shutdown_drain_timeout_s"].type in {"float", float}
