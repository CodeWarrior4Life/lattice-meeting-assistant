"""AssistantProfile + YAML loader/dumper.

See spec §3 + §6 for profile semantics. Profile YAMLs live at
``02_Projects/Lattice/{consuming-project}/Profiles/{slug}.yaml`` in the
vault.

YAML serialization uses ``ruamel.yaml`` round-trip mode so operator-
authored comments + anchors + field order survive a load/dump cycle.
Closes TKT-b65ae591. Cyril hand-authors profile YAMLs; without
round-trip preservation an ``allowlist add X persistent`` admin command
would silently strip comments on write-back.

Architecture (Option A per the W7-prep cleanup brief):

* :class:`AssistantProfile` carries a non-comparing sidecar field
  ``_yaml_doc`` holding the source ``ruamel.yaml.CommentedMap`` when
  the profile was loaded from YAML (``None`` for synthesized profiles).
* :func:`load_profile_from_yaml` populates ``_yaml_doc``.
* :func:`dump_profile_to_yaml` (and ``admin._render_profile_yaml``)
  mutate the stored CommentedMap with the current dataclass values
  when present, falling back to a fresh-write CommentedMap for
  synthesized profiles. ``dataclasses.replace`` preserves the sidecar
  automatically, so admin mutations land back on the original doc.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .config import KnowledgeAccessConfig
from .types import CanonicalPersonaId, ProfileMutation

SeriesMatchBinding = Literal["explicit", "implicit-host-cohost", "implicit-host-cohort", "none"]
SeriesMatchConfidence = Literal["high", "medium", "ratified-low"]


def _yaml_rt() -> YAML:
    """Build a fresh ruamel.yaml round-trip serializer.

    Configured to mirror the legacy PyYAML behavior on field order
    (preserved by default in round-trip mode) and to keep a stable
    indent footprint so existing fixture YAMLs round-trip byte-for-byte
    on the field-order axis.
    """
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    yaml_rt.indent(mapping=2, sequence=2, offset=0)
    yaml_rt.default_flow_style = False
    return yaml_rt


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
    profile_vault_path: str | None = None
    in_memory_mutations_history: tuple[ProfileMutation, ...] = ()

    # Source CommentedMap (ruamel.yaml round-trip preservation).
    # Not part of equality or repr; preserved through ``replace()``.
    # ``None`` for synthesized profiles -- the dump path falls back to
    # a fresh CommentedMap in that case.
    _yaml_doc: CommentedMap | None = field(default=None, compare=False, repr=False)


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
    Returns an :class:`AssistantProfile` whose ``_yaml_doc`` sidecar is
    the ruamel.yaml CommentedMap so subsequent dumps preserve comments
    + anchors + field order.
    """
    yaml_rt = _yaml_rt()
    raw_obj = yaml_rt.load(path.read_text(encoding="utf-8"))
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
    profile_vault_path_raw = raw.get("profile_vault_path")
    profile_vault_path: str | None = (
        None if profile_vault_path_raw is None else str(profile_vault_path_raw)
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

    # Preserve the source CommentedMap for round-trip dumps.
    yaml_doc: CommentedMap | None = raw_obj if isinstance(raw_obj, CommentedMap) else None

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
        profile_vault_path=profile_vault_path,
        in_memory_mutations_history=mutations,
        _yaml_doc=yaml_doc,
    )


def _build_fresh_commented_map(profile: AssistantProfile) -> CommentedMap:
    """Build a CommentedMap from scratch when no source doc is preserved.

    Used by :func:`render_profile_yaml` when the profile was constructed
    programmatically (no ``_yaml_doc`` sidecar). Field order matches the
    canonical layout established by the legacy PyYAML ``dump_profile_to_yaml``.
    """
    doc = CommentedMap()
    doc["schema_version"] = profile.schema_version
    doc["profile_id"] = profile.profile_id
    doc["series_id"] = profile.series_id
    doc["dm_allowlist"] = CommentedSeq(list(profile.dm_allowlist))
    doc["admins"] = CommentedSeq(list(profile.admins))
    doc["dm_min_confidence"] = profile.dm_min_confidence
    doc["allow_mapped_dm"] = profile.allow_mapped_dm
    doc["allow_anonymous_dm"] = profile.allow_anonymous_dm
    doc["public_mentions_enabled"] = profile.public_mentions_enabled
    doc["public_mention_allowlist"] = (
        CommentedSeq(list(profile.public_mention_allowlist))
        if profile.public_mention_allowlist is not None
        else None
    )
    doc["public_mention_rate_limit_per_meeting_s"] = profile.public_mention_rate_limit_per_meeting_s
    knowledge = CommentedMap()
    knowledge["allow_personal_vault"] = profile.knowledge.allow_personal_vault
    knowledge["transcript_hot_window_seconds"] = profile.knowledge.transcript_hot_window_seconds
    knowledge["enable_transcript_search_tool"] = profile.knowledge.enable_transcript_search_tool
    knowledge["enable_past_meetings_search"] = profile.knowledge.enable_past_meetings_search
    knowledge["enable_public_references_tool"] = profile.knowledge.enable_public_references_tool
    knowledge["enable_web_search"] = profile.knowledge.enable_web_search
    knowledge["public_references"] = CommentedSeq(list(profile.knowledge.public_references))
    doc["knowledge"] = knowledge
    doc["series_match_binding"] = profile.series_match_binding
    doc["series_match_confidence"] = profile.series_match_confidence
    doc["profile_vault_path"] = profile.profile_vault_path
    doc["in_memory_mutations_history"] = CommentedSeq(
        [
            {
                "ts": m.ts,
                "action": m.action,
                "target": m.target,
                "by": m.by,
                "session_id": m.session_id,
            }
            for m in profile.in_memory_mutations_history
        ]
    )
    return doc


def _sync_profile_into_doc(profile: AssistantProfile, doc: CommentedMap) -> CommentedMap:
    """Mutate *doc* in place to reflect the current dataclass values.

    Only top-level fields the admin write-back path can mutate are
    touched; comments + anchors + ordering on every other key remain
    untouched. Lists are replaced with ``CommentedSeq`` to preserve
    block-style formatting on the changed sequences.
    """
    doc["schema_version"] = profile.schema_version
    doc["profile_id"] = profile.profile_id
    doc["series_id"] = profile.series_id
    # dm_allowlist + admins commonly mutate via admin commands; only
    # overwrite when the value changed to preserve any user-authored
    # comments attached to the original sequence.
    new_dm = CommentedSeq(list(profile.dm_allowlist))
    if list(doc.get("dm_allowlist", [])) != list(profile.dm_allowlist):
        doc["dm_allowlist"] = new_dm
    new_admins = CommentedSeq(list(profile.admins))
    if list(doc.get("admins", [])) != list(profile.admins):
        doc["admins"] = new_admins
    doc["dm_min_confidence"] = profile.dm_min_confidence
    doc["allow_mapped_dm"] = profile.allow_mapped_dm
    doc["allow_anonymous_dm"] = profile.allow_anonymous_dm
    doc["public_mentions_enabled"] = profile.public_mentions_enabled
    doc["public_mention_allowlist"] = (
        CommentedSeq(list(profile.public_mention_allowlist))
        if profile.public_mention_allowlist is not None
        else None
    )
    doc["public_mention_rate_limit_per_meeting_s"] = profile.public_mention_rate_limit_per_meeting_s
    # Refresh knowledge sub-map but preserve its ordering + comments
    # when the keys already exist.
    knowledge = doc.get("knowledge")
    if not isinstance(knowledge, CommentedMap):
        knowledge = CommentedMap()
        doc["knowledge"] = knowledge
    knowledge["allow_personal_vault"] = profile.knowledge.allow_personal_vault
    knowledge["transcript_hot_window_seconds"] = profile.knowledge.transcript_hot_window_seconds
    knowledge["enable_transcript_search_tool"] = profile.knowledge.enable_transcript_search_tool
    knowledge["enable_past_meetings_search"] = profile.knowledge.enable_past_meetings_search
    knowledge["enable_public_references_tool"] = profile.knowledge.enable_public_references_tool
    knowledge["enable_web_search"] = profile.knowledge.enable_web_search
    knowledge["public_references"] = CommentedSeq(list(profile.knowledge.public_references))
    doc["series_match_binding"] = profile.series_match_binding
    doc["series_match_confidence"] = profile.series_match_confidence
    doc["profile_vault_path"] = profile.profile_vault_path
    doc["in_memory_mutations_history"] = CommentedSeq(
        [
            {
                "ts": m.ts,
                "action": m.action,
                "target": m.target,
                "by": m.by,
                "session_id": m.session_id,
            }
            for m in profile.in_memory_mutations_history
        ]
    )
    return doc


def render_profile_yaml(profile: AssistantProfile) -> str:
    """Serialize *profile* to YAML preserving comments + anchors + field order.

    When the profile carries a ``_yaml_doc`` sidecar (the typical path:
    loaded from YAML and mutated via admin commands), the CommentedMap
    is updated in place and re-emitted. For synthesized profiles a
    fresh CommentedMap is built in canonical field order.
    """
    if profile._yaml_doc is not None:
        doc = _sync_profile_into_doc(profile, profile._yaml_doc)
    else:
        doc = _build_fresh_commented_map(profile)
    buffer = io.StringIO()
    _yaml_rt().dump(doc, buffer)
    return buffer.getvalue()


def dump_profile_to_yaml(profile: AssistantProfile, path: Path) -> None:
    """Dump a profile to YAML preserving field order + comments + anchors.

    Convenience wrapper over :func:`render_profile_yaml`. Used at
    bootstrap time (synthesized profiles) and by tests (round-trip
    fixtures); admin write-back uses :func:`render_profile_yaml`
    directly via the admin module's renderer.
    """
    path.write_text(render_profile_yaml(profile), encoding="utf-8")
