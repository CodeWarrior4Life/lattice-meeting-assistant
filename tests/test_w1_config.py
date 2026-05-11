"""W1.4 — AssistantConfig + KnowledgeAccessConfig defaults + frozen-ness.

Per Implementation Plan task W1.4 Step 1.
"""

from __future__ import annotations

import pytest

from lattice_meeting_assistant.config import (
    AssistantConfig,
    KnowledgeAccessConfig,
)


def test_assistant_config_defaults() -> None:
    cfg = AssistantConfig()
    # Q3 defaults
    assert cfg.auto_intro is False
    assert cfg.disclose_ai is False  # per Cody Voice Identity §Banned
    assert cfg.address_by_canonical_name is True
    assert cfg.canonical_name_min_confidence == 0.85
    # Q5 defaults
    assert cfg.default_tier == "interactive"
    assert cfg.deep_tier == "research"
    assert cfg.deep_tier_message_flag == "/think"
    assert cfg.holding_message_after_ms == 3000
    assert cfg.max_response_tokens == 200
    # Q7 defaults
    assert cfg.per_thread_queue_depth == 5
    assert cfg.per_meeting_global_concurrency == 4
    assert cfg.actor_post_leave_grace_s == 60
    assert cfg.actor_history_max_tokens == 16000
    # Memory
    assert cfg.remember_across_meetings is False
    # Series
    assert cfg.series_ratification_timeout_s == 120


def test_assistant_config_frozen() -> None:
    cfg = AssistantConfig()
    with pytest.raises(Exception):  # FrozenInstanceError is an Exception
        cfg.auto_intro = True  # type: ignore[misc]


def test_knowledge_access_config_defaults() -> None:
    k = KnowledgeAccessConfig()
    # Architectural Invariant #2 — hard deny on personal vault by default
    assert k.allow_personal_vault is False
    # Transcript always-on
    assert k.transcript_hot_window_seconds == 300
    assert k.enable_transcript_search_tool is True
    # Past meetings + refs + web all enabled by default
    assert k.enable_past_meetings_search is True
    assert k.enable_public_references_tool is True
    assert k.enable_web_search is True
    assert k.public_references == ()


def test_knowledge_access_config_with_public_refs() -> None:
    k = KnowledgeAccessConfig(public_references=("ref/book1.md", "ref/book2.md"))
    assert k.public_references == ("ref/book1.md", "ref/book2.md")
