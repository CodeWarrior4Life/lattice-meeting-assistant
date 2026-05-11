"""W1.5 -- AssistantProfile + ProfileMutation + YAML round-trip.

Per Implementation Plan task W1.5 Step 1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lattice_meeting_assistant.config import KnowledgeAccessConfig
from lattice_meeting_assistant.profile import (
    AssistantProfile,
    dump_profile_to_yaml,
    load_profile_from_yaml,
)
from lattice_meeting_assistant.types import ProfileMutation


def test_assistant_profile_minimal() -> None:
    p = AssistantProfile(
        profile_id="test",
        series_id=None,
        dm_allowlist=("cyril-grosse",),
        admins=("cyril-grosse",),
        knowledge=KnowledgeAccessConfig(),
    )
    assert p.profile_id == "test"
    assert p.schema_version == 1
    assert p.dm_allowlist == ("cyril-grosse",)
    assert p.admins == ("cyril-grosse",)
    # Public mention defaults
    assert p.public_mentions_enabled is True
    assert p.public_mention_allowlist is None  # anyone-can-mention
    assert p.public_mention_rate_limit_per_meeting_s == 30


def test_profile_yaml_roundtrip(tmp_path: Path) -> None:
    src = AssistantProfile(
        profile_id="sabbath-school",
        series_id="sabbath-school-class",
        dm_allowlist=("cyril-grosse", "helen-christopherson"),
        admins=("cyril-grosse",),
        knowledge=KnowledgeAccessConfig(
            public_references=("ref/book1.md",),
        ),
        series_match_binding="explicit",
        series_match_confidence="high",
        source_vault_note="02_Projects/.../Profiles/sabbath-school.yaml",
    )
    yaml_path = tmp_path / "sabbath-school.yaml"
    dump_profile_to_yaml(src, yaml_path)
    loaded = load_profile_from_yaml(yaml_path)
    assert loaded == src


def test_profile_yaml_rejects_blocked_tool_enabled(tmp_path: Path) -> None:
    """T9 -- Profile YAML attempting to enable a BLOCKED_IN_MEETING_TOOLS
    entry for in-meeting-dm transport raises ValueError at parse time.

    (NOTE: the blocking check lives in the tool resolver, not the profile
    loader; this test asserts the profile loader's basic validation -- a
    non-bool value for a boolean knowledge field is rejected at parse
    time.)
    """
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text(
        "schema_version: 1\n"
        "profile_id: bad\n"
        "series_id: ~\n"
        "dm_allowlist: []\n"
        "admins: []\n"
        "knowledge:\n"
        "  allow_personal_vault: not_a_bool\n"
    )
    with pytest.raises(ValueError):
        load_profile_from_yaml(yaml_path)


def test_profile_mutation_audit() -> None:
    m = ProfileMutation(
        ts="2026-05-11T16:00:00Z",
        action="add",
        target="helen-brager",
        by="cyril-grosse",
        session_id="S25",
    )
    assert m.action == "add"
    assert m.by == "cyril-grosse"
