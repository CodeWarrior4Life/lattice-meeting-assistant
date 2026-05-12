"""Architectural Invariant 1-5 unit tests.

Spec §5 lists 5 Architectural Invariants:

    1. Separated Send Paths
    2. Transport-Bound Knowledge Access
    3. Per-Thread Memory Isolation
    4. Visibility-Tag Fail-Closed
    5. Admin Surface Isolation

These tests cover the W2 (Sub-dispatch A) primitives that enforce each
invariant at the library boundary. Higher-level integration coverage
(the 12 boundary tests T1-T12) lives in ``tests/test_privacy_boundary.py``
and is owned by Sub-dispatch B.
"""

from __future__ import annotations

import pytest

from lattice_meeting_assistant.exceptions import PrivacyBoundaryViolation
from lattice_meeting_assistant.privacy.invariants import (
    BLOCKED_IN_MEETING_TOOLS,
    assert_in_meeting_tools_safe,
    assert_not_admin_in_meeting,
    assert_separated_send_paths,
    enforce_visibility_tag,
    is_admin_command_syntax,
    thread_memory_key,
)

# ---------------------------------------------------------------------------
# Invariant 1 -- Separated Send Paths
# ---------------------------------------------------------------------------


def test_invariant_1_separated_send_paths() -> None:
    """Invariant 1 (Separated Send Paths).

    ``send_chat(to_user_id, message)`` and ``send_chat_public(message)``
    must be two distinct methods on the session surface. There is no
    ``broadcast=True`` flag, no single combined send method.

    The privacy module exposes ``assert_separated_send_paths(session)``
    so the Assistant can verify the session it has been handed satisfies
    the contract at boot.
    """

    class GoodSession:
        async def send_chat(self, to_user_id: str, message: str) -> None: ...
        async def send_chat_public(self, message: str) -> None: ...

    class BroadcastSession:
        async def send_chat(self, message: str, *, broadcast: bool = False) -> None: ...

    class MissingPublicSession:
        async def send_chat(self, to_user_id: str, message: str) -> None: ...

    # Good session: both methods present, send_chat requires to_user_id.
    assert_separated_send_paths(GoodSession())  # no raise

    # Broadcast-style API rejected.
    with pytest.raises(ValueError, match="broadcast"):
        assert_separated_send_paths(BroadcastSession())

    # Missing public path rejected.
    with pytest.raises(ValueError, match="send_chat_public"):
        assert_separated_send_paths(MissingPublicSession())


# ---------------------------------------------------------------------------
# Invariant 2 -- Transport-Bound Knowledge Access
# ---------------------------------------------------------------------------


def test_invariant_2_transport_bound_knowledge_access() -> None:
    """Invariant 2 (Transport-Bound Knowledge Access).

    ``BLOCKED_IN_MEETING_TOOLS`` enumerates the cortex tool names the
    in-meeting-dm transport may NEVER register. The resolver asserts
    disjointness at boot via ``assert_in_meeting_tools_safe(names)``.
    """
    # Frozen, non-empty, contains the spec-mandated core tool names.
    assert isinstance(BLOCKED_IN_MEETING_TOOLS, frozenset)
    expected_core = {
        "search_vault",
        "read_note",
        "search_email",
        "read_email",
        "nx_calendar_read",
        "nx_calendar_write",
        "create_calendar_event",
        "nx_contacts_read",
        "nx_contacts_search",
        "nx_contacts_add",
        "nx_contacts_update",
        "nx_db_query",
        "nx_vault_multi_read",
        "nx_vault_multi_search",
        "nx_vault_query",
        "nx_vault_write",
        "deep_research",
        "nx_context_gather",
        "download_media",
        "instagram_ingest",
        "x_status",
        "x_sync_bookmarks",
        "youtube_playlists",
        "youtube_sync_playlist",
        "search_whatsapp",
        "bible_lookup",
        "strongs_lookup",
        "create_note",
        "create_reminder",
        "create_ticket",
        "flush_note_queue",
        "ingest_url",
        "share_note",
        "update_note",
        "update_ticket",
        "list_tickets",
        "brain_chat",
        "vault_ask",
    }
    missing = expected_core - BLOCKED_IN_MEETING_TOOLS
    assert not missing, f"BLOCKED_IN_MEETING_TOOLS missing: {sorted(missing)}"

    # A clean curated set passes.
    assert_in_meeting_tools_safe(
        {
            "search_meeting_transcript",
            "read_meeting_transcript_window",
            "search_past_meetings",
            "search_public_references",
            "web_search",
        }
    )

    # A set containing a blocked tool raises.
    with pytest.raises(ValueError, match="blocked"):
        assert_in_meeting_tools_safe({"search_meeting_transcript", "search_vault"})

    # Fail-closed on UNKNOWN tools is NOT required here (resolver explicitly
    # enumerates allowed tools; this helper only checks the blocked set).
    # That stricter check lives in the resolver itself (W3).


# ---------------------------------------------------------------------------
# Invariant 3 -- Per-Thread Memory Isolation
# ---------------------------------------------------------------------------


def test_invariant_3_per_thread_memory_isolation() -> None:
    """Invariant 3 (Per-Thread Memory Isolation).

    Conversation memory keys on ``(meeting_id, canonical_persona_id)``
    for private DMs and ``(meeting_id, "public")`` for public mentions.
    Two senders in same meeting -> two distinct keys. Same sender's
    private and public threads -> two distinct keys.
    """
    private_a = thread_memory_key(meeting_id="mtg_001", persona_id="alice")
    private_b = thread_memory_key(meeting_id="mtg_001", persona_id="bob")
    public = thread_memory_key(meeting_id="mtg_001", persona_id=None, public=True)
    private_a_other_meeting = thread_memory_key(meeting_id="mtg_002", persona_id="alice")

    # Senders in same meeting -> distinct keys.
    assert private_a != private_b

    # Private vs public from same meeting -> distinct keys.
    assert private_a != public
    assert private_b != public

    # Same sender across meetings -> distinct keys (no cross-meeting leak).
    assert private_a != private_a_other_meeting

    # Keys are deterministic.
    assert private_a == thread_memory_key(meeting_id="mtg_001", persona_id="alice")
    assert public == thread_memory_key(meeting_id="mtg_001", persona_id=None, public=True)

    # Public key contract: must NOT collide with any plausible persona id
    # named "public" by encoding the discriminator structurally.
    public_collider = thread_memory_key(meeting_id="mtg_001", persona_id="public")
    assert public != public_collider


# ---------------------------------------------------------------------------
# Invariant 4 -- Visibility-Tag Fail-Closed
# ---------------------------------------------------------------------------


def test_invariant_4_visibility_tag_fail_closed() -> None:
    """Invariant 4 (Visibility-Tag Fail-Closed).

    Every chat event MUST carry an ``is_private`` tag. Missing or None
    => REJECT with ``PrivacyBoundaryViolation``. No silent default.
    """

    class TaggedPrivate:
        id = "evt_priv"
        is_private = True

    class TaggedPublic:
        id = "evt_pub"
        is_private = False

    class Untagged:
        id = "evt_untagged"

    class NoneTagged:
        id = "evt_none"
        is_private = None

    # Both explicit values pass.
    enforce_visibility_tag(TaggedPrivate())
    enforce_visibility_tag(TaggedPublic())

    # Missing attribute => fail-closed.
    with pytest.raises(PrivacyBoundaryViolation, match="is_private"):
        enforce_visibility_tag(Untagged())

    # None value => fail-closed (ambiguity == refuse).
    with pytest.raises(PrivacyBoundaryViolation, match="is_private"):
        enforce_visibility_tag(NoneTagged())


# ---------------------------------------------------------------------------
# Invariant 5 -- Admin Surface Isolation
# ---------------------------------------------------------------------------


def test_invariant_5_admin_surface_isolation() -> None:
    """Invariant 5 (Admin Surface Isolation).

    Admin commands route EXCLUSIVELY through TG transport. The in-meeting
    DM handler MUST detect admin command syntax and refuse it -- never
    mutate state, never silently process. ``is_admin_command_syntax(text)``
    recognizes the grammar from spec §3 Admin command syntax; the helper
    ``assert_not_admin_in_meeting(text, transport_kind)`` raises
    ``PrivacyBoundaryViolation`` when an admin-grammar string lands on
    the ``in-meeting-dm`` transport.
    """
    # Admin grammar is detected.
    assert is_admin_command_syntax("allowlist add cyril-grosse")
    assert is_admin_command_syntax("allowlist add cyril-grosse persistent")
    assert is_admin_command_syntax("allowlist remove cyril-grosse")
    assert is_admin_command_syntax("allowlist show")
    assert is_admin_command_syntax("mode interactive")
    assert is_admin_command_syntax("mode research")
    assert is_admin_command_syntax("mute")
    assert is_admin_command_syntax("unmute")
    assert is_admin_command_syntax("help")
    assert is_admin_command_syntax("status")

    # Leading/trailing whitespace tolerated.
    assert is_admin_command_syntax("   allowlist show   ")

    # Casual chat is NOT admin grammar.
    assert not is_admin_command_syntax("what was just said?")
    assert not is_admin_command_syntax("can you summarize the last 5 minutes")
    assert not is_admin_command_syntax("")

    # Admin command on TG-owner transport is fine -- no raise.
    assert_not_admin_in_meeting("allowlist add bob", transport_kind="tg-owner")

    # Casual chat on in-meeting-dm transport is fine -- no raise.
    assert_not_admin_in_meeting("what is happening?", transport_kind="in-meeting-dm")

    # Admin grammar on in-meeting-dm transport REJECTED.
    with pytest.raises(PrivacyBoundaryViolation, match="admin"):
        assert_not_admin_in_meeting("allowlist add bob", transport_kind="in-meeting-dm")
    with pytest.raises(PrivacyBoundaryViolation, match="admin"):
        assert_not_admin_in_meeting("mute", transport_kind="in-meeting-dm")
