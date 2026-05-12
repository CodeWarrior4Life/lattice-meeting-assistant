"""W6.1 -- public-mention + in-meeting-DM prompt rendering.

Spec §4 ships two system-prompt variants:

* **in-meeting-DM prompt** (Design Spec lines 608-640) -- the private
  thread template. ``persona_voice_block`` from Cody Voice Identity, tool
  list enumeration, recent transcript hot-window, NEVER-reveal-vault
  guardrail.
* **public-mention prompt** (Design Spec lines 642-671) -- the public
  @-mention variant. Same Cody Voice Identity block, but explicitly
  flags the reply is **PUBLIC meeting chat** visible to everyone,
  emphasises terseness, and tells the model to decline private-shaped
  questions politely.

This test module owns the renderer contract before the production
``Assistant`` uses either string. The renderers are pure functions on
``prompts.py``; they take typed kwargs and return a single rendered
string. No side effects.
"""

from __future__ import annotations

import pytest

from lattice_meeting_assistant.prompts import (
    render_in_meeting_dm_prompt,
    render_public_mention_prompt,
)


# ---------------------------------------------------------------------------
# Public-mention prompt
# ---------------------------------------------------------------------------


def test_public_mention_prompt_contains_public_meeting_chat_marker() -> None:
    """Spec §4 line 649-650: the public-mention system prompt MUST flag
    that the reply lands in PUBLIC meeting chat visible to EVERYONE.
    """
    rendered = render_public_mention_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list="search_meeting_transcript, web_search",
        transcript_hot_window="(no recent transcript yet)",
    )
    assert "PUBLIC meeting chat" in rendered


def test_public_mention_prompt_contains_decline_private_shaped_guidance() -> None:
    """Spec §4 lines 654-657: the public-mention prompt MUST tell the
    model to decline private-shaped questions and suggest DM instead.
    """
    rendered = render_public_mention_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list="search_meeting_transcript, web_search",
        transcript_hot_window="(no recent transcript yet)",
    )
    # The spec's verbatim phrasing: "decline politely and suggest they DM
    # you instead". Assert against the marker phrase to avoid coupling on
    # surrounding whitespace.
    assert "decline politely" in rendered
    assert "DM you instead" in rendered


def test_public_mention_prompt_substitutes_tool_list_token() -> None:
    """Spec §4 line 658: the template includes ``{tool_list}`` -- the
    renderer must substitute the caller-supplied tool list verbatim.
    """
    tool_list = "search_meeting_transcript, read_meeting_transcript_window, web_search"
    rendered = render_public_mention_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list=tool_list,
        transcript_hot_window="(no recent transcript yet)",
    )
    assert tool_list in rendered
    # No raw template tokens left behind.
    assert "{tool_list}" not in rendered


def test_public_mention_prompt_substitutes_meeting_title_and_transcript() -> None:
    """The remaining template variables -- ``{meeting_title}``,
    ``{transcript_hot_window}``, ``{persona_voice_block}`` -- must all
    be substituted in the rendered output.
    """
    rendered = render_public_mention_prompt(
        meeting_title="Trinity Architecture Review",
        persona_voice_block="(custom persona block)",
        tool_list="web_search",
        transcript_hot_window="cyril-grosse: we should talk about Switch...",
    )
    assert "Trinity Architecture Review" in rendered
    assert "(custom persona block)" in rendered
    assert "cyril-grosse: we should talk about Switch..." in rendered
    # No raw template tokens left behind.
    for token in (
        "{meeting_title}",
        "{persona_voice_block_from_Cody_Voice_Identity}",
        "{persona_voice_block}",
        "{transcript_hot_window}",
    ):
        assert token not in rendered


def test_public_mention_prompt_structure_matches_spec_template() -> None:
    """Spec §4 lines 644-671: the prompt MUST be wrapped in the
    ``<system>...</system> <conversation_history>...</conversation_history>
    <user>...</user>`` structure described in the spec.
    """
    rendered = render_public_mention_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list="search_meeting_transcript",
        transcript_hot_window="(no recent transcript)",
    )
    assert "<system>" in rendered
    assert "</system>" in rendered
    assert "<conversation_history>" in rendered
    assert "</conversation_history>" in rendered
    assert "<user>" in rendered
    assert "</user>" in rendered


# ---------------------------------------------------------------------------
# In-meeting-DM prompt
# ---------------------------------------------------------------------------


def test_in_meeting_dm_prompt_contains_sender_canonical_id() -> None:
    """Spec §4 line 613-614: the in-meeting-DM system prompt MUST
    include the participant's canonical display name and id.
    """
    rendered = render_in_meeting_dm_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list="search_meeting_transcript",
        transcript_hot_window="(no recent transcript)",
        sender_canonical_display_name="Cyril Grosse",
        sender_canonical_id="cyril-grosse",
        sender_canonical_confidence=0.95,
    )
    assert "Cyril Grosse" in rendered
    assert "cyril-grosse" in rendered


def test_in_meeting_dm_prompt_contains_never_reveal_guardrail() -> None:
    """Spec §4 lines 626-628: the in-meeting-DM prompt MUST include the
    "NEVER reveal you have access to vault" defense-in-depth
    instruction.
    """
    rendered = render_in_meeting_dm_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list="search_meeting_transcript",
        transcript_hot_window="(no recent transcript)",
        sender_canonical_display_name="Cyril Grosse",
        sender_canonical_id="cyril-grosse",
        sender_canonical_confidence=0.95,
    )
    assert "NEVER reveal" in rendered
    assert "vault" in rendered


def test_in_meeting_dm_prompt_structure_matches_spec_template() -> None:
    """Spec §4 lines 608-638: the prompt MUST be wrapped in the same
    ``<system>...<conversation_history>...<user>...`` structure as the
    public-mention variant.
    """
    rendered = render_in_meeting_dm_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list="search_meeting_transcript",
        transcript_hot_window="(no recent transcript)",
        sender_canonical_display_name="Cyril Grosse",
        sender_canonical_id="cyril-grosse",
        sender_canonical_confidence=0.95,
    )
    assert "<system>" in rendered
    assert "</system>" in rendered
    assert "<conversation_history>" in rendered
    assert "</conversation_history>" in rendered
    assert "<user>" in rendered
    assert "</user>" in rendered


def test_in_meeting_dm_prompt_does_not_have_public_marker() -> None:
    """The DM prompt must NOT include the public-chat marker -- that
    string is unique to the public variant so a misrendered template
    can't accidentally mark a private reply as public.
    """
    rendered = render_in_meeting_dm_prompt(
        meeting_title="Sabbath School class",
        persona_voice_block="(persona voice block stub)",
        tool_list="search_meeting_transcript",
        transcript_hot_window="(no recent transcript)",
        sender_canonical_display_name="Cyril Grosse",
        sender_canonical_id="cyril-grosse",
        sender_canonical_confidence=0.95,
    )
    assert "PUBLIC meeting chat" not in rendered


__all__: list[str] = []
