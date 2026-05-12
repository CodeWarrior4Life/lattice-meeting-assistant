"""W7-prep cleanup tests -- TKT-b65ae591.

Defends the ruamel.yaml round-trip contract for profile YAML
serialization. PyYAML's ``safe_dump`` preserves field order but loses
comments + anchors + trailing whitespace. Cyril hand-authors profile
YAMLs and may include comments documenting why a particular allowlist
entry exists; ``allowlist add X persistent`` writing back through
PyYAML would silently strip them. The W7-prep upgrade routes profile
load/dump through ``ruamel.yaml.YAML(typ='rt')`` so admin write-back
preserves operator-authored decorations.

The tests below exercise:

1. Comment lines survive a round trip through
   ``load_profile_from_yaml + dump_profile_to_yaml``.
2. Anchors + references survive a round trip.
3. Field order is preserved (regression guard for the existing PyYAML
   ``sort_keys=False`` behavior carried forward to ruamel.yaml).

The admin-side renderer ``admin._render_profile_yaml`` shares the same
underlying serializer, so a per-function test on the profile helpers
covers both surfaces.
"""

from __future__ import annotations

from pathlib import Path

from lattice_meeting_assistant.profile import (
    dump_profile_to_yaml,
    load_profile_from_yaml,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _commented_profile_yaml() -> str:
    """Profile YAML with operator comments at multiple positions.

    Comments appear before the schema_version header, beside the
    profile_id, and immediately preceding a single dm_allowlist entry --
    mirroring shapes Cyril is likely to hand-author.
    """
    return """\
# Sabbath School class series profile.
# Maintainer: Cyril
schema_version: 1
profile_id: sabbath-school  # canonical slug
series_id: sabbath-school-class
dm_allowlist:
  - cyril-grosse
  # Co-host added 2026-05-04 after the host ratified.
  - helen-christopherson
admins:
  - cyril-grosse
dm_min_confidence: 0.85
allow_mapped_dm: true
allow_anonymous_dm: false
public_mentions_enabled: true
public_mention_allowlist: ~
public_mention_rate_limit_per_meeting_s: 30
knowledge:
  allow_personal_vault: false
  transcript_hot_window_seconds: 300
  enable_transcript_search_tool: true
  enable_past_meetings_search: true
  enable_public_references_tool: true
  enable_web_search: true
  public_references: []
series_match_binding: explicit
series_match_confidence: high
profile_vault_path: "02_Projects/Lattice/lattice-meetbot/Profiles/sabbath-school.yaml"
in_memory_mutations_history: []
"""


def _anchored_profile_yaml() -> str:
    """Profile YAML using a YAML anchor + alias inside dm_allowlist.

    The anchor/alias pattern is unusual for profile YAMLs but used here
    purely to validate ruamel.yaml's round-trip mode forwards the
    construct unchanged when there is no semantic mutation.
    """
    return """\
schema_version: 1
profile_id: anchor-test
series_id: anchor-series
dm_allowlist: &core
  - cyril-grosse
  - helen-christopherson
admins: *core
dm_min_confidence: 0.85
allow_mapped_dm: true
allow_anonymous_dm: false
public_mentions_enabled: true
public_mention_allowlist: ~
public_mention_rate_limit_per_meeting_s: 30
knowledge:
  allow_personal_vault: false
  transcript_hot_window_seconds: 300
  enable_transcript_search_tool: true
  enable_past_meetings_search: true
  enable_public_references_tool: true
  enable_web_search: true
  public_references: []
series_match_binding: none
profile_vault_path: ~
in_memory_mutations_history: []
"""


def _ordered_profile_yaml() -> str:
    """Profile YAML in canonical field order."""
    return """\
schema_version: 1
profile_id: ordered-test
series_id: ordered-series
dm_allowlist:
  - cyril-grosse
admins:
  - cyril-grosse
dm_min_confidence: 0.85
allow_mapped_dm: true
allow_anonymous_dm: false
public_mentions_enabled: true
public_mention_allowlist: ~
public_mention_rate_limit_per_meeting_s: 30
knowledge:
  allow_personal_vault: false
  transcript_hot_window_seconds: 300
  enable_transcript_search_tool: true
  enable_past_meetings_search: true
  enable_public_references_tool: true
  enable_web_search: true
  public_references: []
series_match_binding: none
profile_vault_path: ~
in_memory_mutations_history: []
"""


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------


def test_profile_yaml_roundtrip_preserves_comments(tmp_path: Path) -> None:
    """Operator-authored ``# comment`` lines survive load -> dump."""
    src = tmp_path / "commented.yaml"
    dst = tmp_path / "roundtrip.yaml"
    src.write_text(_commented_profile_yaml(), encoding="utf-8")

    profile = load_profile_from_yaml(src)
    dump_profile_to_yaml(profile, dst)
    text = dst.read_text(encoding="utf-8")

    assert "# Sabbath School class series profile." in text
    assert "# Maintainer: Cyril" in text
    assert "canonical slug" in text
    assert "Co-host added 2026-05-04 after the host ratified." in text


def test_profile_yaml_roundtrip_preserves_anchors(tmp_path: Path) -> None:
    """YAML ``&anchor`` + ``*alias`` survive load -> dump unchanged."""
    src = tmp_path / "anchored.yaml"
    dst = tmp_path / "roundtrip.yaml"
    src.write_text(_anchored_profile_yaml(), encoding="utf-8")

    profile = load_profile_from_yaml(src)
    dump_profile_to_yaml(profile, dst)
    text = dst.read_text(encoding="utf-8")

    assert "&core" in text, "named anchor should survive the round trip"
    assert "*core" in text, "alias reference should survive the round trip"


def test_profile_yaml_roundtrip_preserves_field_order(tmp_path: Path) -> None:
    """Top-level field order is preserved across load -> dump."""
    src = tmp_path / "ordered.yaml"
    dst = tmp_path / "roundtrip.yaml"
    src.write_text(_ordered_profile_yaml(), encoding="utf-8")

    profile = load_profile_from_yaml(src)
    dump_profile_to_yaml(profile, dst)
    text = dst.read_text(encoding="utf-8")

    keys = [
        "schema_version",
        "profile_id",
        "series_id",
        "dm_allowlist",
        "admins",
        "dm_min_confidence",
        "allow_mapped_dm",
        "allow_anonymous_dm",
        "public_mentions_enabled",
        "public_mention_allowlist",
        "public_mention_rate_limit_per_meeting_s",
        "knowledge",
        "series_match_binding",
        "profile_vault_path",
        "in_memory_mutations_history",
    ]
    positions = []
    for k in keys:
        idx = text.find(f"\n{k}:")
        # First key is at file start (no leading newline)
        if idx == -1 and text.startswith(f"{k}:"):
            idx = 0
        assert idx != -1, f"expected key {k!r} in round-tripped YAML"
        positions.append(idx)
    assert positions == sorted(positions), (
        f"field order broke after round trip: positions={positions}"
    )
