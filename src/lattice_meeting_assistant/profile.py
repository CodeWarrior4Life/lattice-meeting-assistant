"""AssistantProfile + YAML loader/dumper.

See spec §3 + §6 for profile semantics. Profile YAMLs live at
``02_Projects/Lattice/{consuming-project}/Profiles/{slug}.yaml`` in the
vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from .config import KnowledgeAccessConfig
from .types import CanonicalPersonaId, ProfileMutation

SeriesMatchBinding = Literal["explicit", "implicit-host-cohost", "implicit-host-cohort", "none"]
SeriesMatchConfidence = Literal["high", "medium", "ratified-low"]


@dataclass(frozen=True)
class AssistantProfile:
    """Per-meeting/series policy. See spec §3."""

    profile_id: str
    series_id: str | None
    dm_allowlist: tuple[CanonicalPersonaId, ...]
    admins: tuple[CanonicalPersonaId, ...]
    knowledge: KnowledgeAccessConfig

    schema_version: int = 1
    dm_min_confidence: float = 0.85
    allow_mapped_dm: bool = True
    allow_anonymous_dm: bool = False

    # Public mentions.
    public_mentions_enabled: bool = True
    # None = anyone-can-mention; tuple = explicit allowlist.
    public_mention_allowlist: tuple[CanonicalPersonaId, ...] | None = None
    public_mention_rate_limit_per_meeting_s: int = 30

    # Series matching context.
    series_match_binding: SeriesMatchBinding = "none"
    series_match_confidence: SeriesMatchConfidence | None = None

    # Provenance.
    source_vault_note: str | None = None
    in_memory_mutations_history: tuple[ProfileMutation, ...] = ()


def _require_bool(raw: dict[str, Any], key: str, path: Path) -> None:
    """Validate that ``raw[key]`` is a bool if present; raise ValueError
    with a useful path/type message otherwise.
    """
    if key in raw and not isinstance(raw[key], bool):
        raise ValueError(
            f"profile.knowledge.{key} must be bool at {path}; got {type(raw[key]).__name__}"
        )


def load_profile_from_yaml(path: Path) -> AssistantProfile:
    """Load a profile from a vault YAML file.

    Raises ``ValueError`` on schema violations (typed-field mismatches).
    """
    raw_obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw_obj, dict):
        raise ValueError(f"profile YAML must be a mapping at {path}")
    raw: dict[str, Any] = raw_obj

    # Coerce + validate nested KnowledgeAccessConfig.
    k_obj = raw.get("knowledge", {})
    if not isinstance(k_obj, dict):
        raise ValueError(f"profile.knowledge must be a mapping at {path}")
    k_raw: dict[str, Any] = k_obj
    for boolean_field in (
        "allow_personal_vault",
        "enable_transcript_search_tool",
        "enable_past_meetings_search",
        "enable_public_references_tool",
        "enable_web_search",
    ):
        _require_bool(k_raw, boolean_field, path)

    pr_raw = k_raw.get("public_references") or []
    public_references_t: tuple[str, ...] = tuple(str(x) for x in pr_raw)
    knowledge = KnowledgeAccessConfig(
        allow_personal_vault=bool(k_raw.get("allow_personal_vault", False)),
        transcript_hot_window_seconds=int(k_raw.get("transcript_hot_window_seconds", 300)),
        enable_transcript_search_tool=bool(k_raw.get("enable_transcript_search_tool", True)),
        enable_past_meetings_search=bool(k_raw.get("enable_past_meetings_search", True)),
        public_references=public_references_t,
        enable_public_references_tool=bool(k_raw.get("enable_public_references_tool", True)),
        enable_web_search=bool(k_raw.get("enable_web_search", True)),
    )

    pma_raw = raw.get("public_mention_allowlist")
    public_mention_allowlist: tuple[str, ...] | None
    if pma_raw is None:
        public_mention_allowlist = None
    else:
        public_mention_allowlist = tuple(str(x) for x in pma_raw)

    mutations_raw_list = raw.get("in_memory_mutations_history") or []
    mutations_list: list[ProfileMutation] = []
    for m in mutations_raw_list:
        if isinstance(m, dict):
            mutations_list.append(ProfileMutation(**m))
        else:
            mutations_list.append(cast(ProfileMutation, m))
    mutations: tuple[ProfileMutation, ...] = tuple(mutations_list)

    dm_allowlist_t: tuple[str, ...] = tuple(str(x) for x in (raw.get("dm_allowlist") or []))
    admins_t: tuple[str, ...] = tuple(str(x) for x in (raw.get("admins") or []))

    series_id_raw = raw.get("series_id")
    series_id: str | None = None if series_id_raw is None else str(series_id_raw)
    source_vault_note_raw = raw.get("source_vault_note")
    source_vault_note: str | None = (
        None if source_vault_note_raw is None else str(source_vault_note_raw)
    )

    smb_raw = raw.get("series_match_binding", "none")
    if smb_raw not in (
        "explicit",
        "implicit-host-cohost",
        "implicit-host-cohort",
        "none",
    ):
        raise ValueError(f"profile.series_match_binding has invalid value {smb_raw!r} at {path}")
    series_match_binding: SeriesMatchBinding = cast(SeriesMatchBinding, smb_raw)

    smc_raw = raw.get("series_match_confidence")
    series_match_confidence: SeriesMatchConfidence | None
    if smc_raw is None:
        series_match_confidence = None
    elif smc_raw in ("high", "medium", "ratified-low"):
        series_match_confidence = cast(SeriesMatchConfidence, smc_raw)
    else:
        raise ValueError(f"profile.series_match_confidence has invalid value {smc_raw!r} at {path}")

    return AssistantProfile(
        profile_id=str(raw["profile_id"]),
        series_id=series_id,
        dm_allowlist=dm_allowlist_t,
        admins=admins_t,
        knowledge=knowledge,
        schema_version=int(raw.get("schema_version", 1)),
        dm_min_confidence=float(raw.get("dm_min_confidence", 0.85)),
        allow_mapped_dm=bool(raw.get("allow_mapped_dm", True)),
        allow_anonymous_dm=bool(raw.get("allow_anonymous_dm", False)),
        public_mentions_enabled=bool(raw.get("public_mentions_enabled", True)),
        public_mention_allowlist=public_mention_allowlist,
        public_mention_rate_limit_per_meeting_s=int(
            raw.get("public_mention_rate_limit_per_meeting_s", 30)
        ),
        series_match_binding=series_match_binding,
        series_match_confidence=series_match_confidence,
        source_vault_note=source_vault_note,
        in_memory_mutations_history=mutations,
    )


def dump_profile_to_yaml(profile: AssistantProfile, path: Path) -> None:
    """Dump a profile to YAML preserving field order + comments-free shape."""
    payload: dict[str, Any] = {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "series_id": profile.series_id,
        "dm_allowlist": list(profile.dm_allowlist),
        "admins": list(profile.admins),
        "dm_min_confidence": profile.dm_min_confidence,
        "allow_mapped_dm": profile.allow_mapped_dm,
        "allow_anonymous_dm": profile.allow_anonymous_dm,
        "public_mentions_enabled": profile.public_mentions_enabled,
        "public_mention_allowlist": (
            list(profile.public_mention_allowlist)
            if profile.public_mention_allowlist is not None
            else None
        ),
        "public_mention_rate_limit_per_meeting_s": (
            profile.public_mention_rate_limit_per_meeting_s
        ),
        "knowledge": {
            "allow_personal_vault": profile.knowledge.allow_personal_vault,
            "transcript_hot_window_seconds": (profile.knowledge.transcript_hot_window_seconds),
            "enable_transcript_search_tool": (profile.knowledge.enable_transcript_search_tool),
            "enable_past_meetings_search": (profile.knowledge.enable_past_meetings_search),
            "enable_public_references_tool": (profile.knowledge.enable_public_references_tool),
            "enable_web_search": profile.knowledge.enable_web_search,
            "public_references": list(profile.knowledge.public_references),
        },
        "series_match_binding": profile.series_match_binding,
        "series_match_confidence": profile.series_match_confidence,
        "source_vault_note": profile.source_vault_note,
        "in_memory_mutations_history": [
            {
                "ts": m.ts,
                "action": m.action,
                "target": m.target,
                "by": m.by,
                "session_id": m.session_id,
            }
            for m in profile.in_memory_mutations_history
        ],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
