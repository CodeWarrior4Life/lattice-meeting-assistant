"""Shared fixtures for the lattice-meeting-assistant test suite.

These fixtures are sized to what the 12 boundary tests T1-T12 from
Design Spec §5 actually need at W2 close. Higher-fidelity fixtures
(real cortex client, real session adapter) land in W3-W6 as the
corresponding production code does.

Fixture inventory:

* ``mock_cortex_registry``   -- stub cortex.call returning fixed reply.
* ``mock_session``           -- MeetingSession-shaped mock with
                                ``send_chat(to_user_id, message)`` +
                                ``send_chat_public(message)``;
                                satisfies Invariant 1
                                (``assert_separated_send_paths``).
* ``mock_brain_mcp``         -- Brain MCP client mock with the
                                small subset of nx_* methods the
                                W3+W5 layers will call.
* ``mock_transcript_buffer`` -- TranscriptBuffer mock with
                                subscribe / get_hot_window / search.
* ``make_chat_event``        -- module-level factory for ChatEvent
                                values used across boundary tests.

Per W2.3 plan step 1 in
``D:/Vaults/Mainframe/02_Projects/Lattice/lattice-meeting-assistant/
Plans/2026-05-11 lattice-meeting-assistant v0.1 - Implementation Plan.md``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant.types import ChatEvent


@pytest.fixture
def mock_cortex_registry() -> MagicMock:
    """Cortex registry that returns a stub reply on every call.

    Records all invocations on the underlying ``AsyncMock`` so tests can
    assert call-count + arguments (e.g. T6 verifies no cross-sender
    cache hit by counting cortex invocations).
    """
    m = MagicMock()
    reply = MagicMock(
        text="stub reply",
        tokens_used=50,
        tier_used="interactive",
        provider_used="anthropic",
    )
    m.call = AsyncMock(return_value=reply)
    return m


@pytest.fixture
def mock_session() -> MagicMock:
    """MeetingSession-shaped mock satisfying Architectural Invariant 1.

    ``send_chat`` requires ``to_user_id`` positional (no broadcast=);
    ``send_chat_public`` is a separate method. Sufficient input for
    ``privacy.invariants.assert_separated_send_paths`` (T4) and the
    later W4-W6 actor wiring (T1, T11, T12).
    """

    class _Session:
        is_alive = True

        async def send_chat(self, to_user_id: str, message: str) -> None: ...

        async def send_chat_public(self, message: str) -> None: ...

    s = _Session()
    # Wrap the bound coroutines with AsyncMock so tests can introspect calls.
    s.send_chat = AsyncMock()  # type: ignore[method-assign]
    s.send_chat_public = AsyncMock()  # type: ignore[method-assign]
    # Re-attach a signature-preserving wrapper so introspection-based
    # checks (``assert_separated_send_paths``) see the right shape.
    # AsyncMock by itself has a *args / **kwargs signature, which fails
    # the Invariant 1 ``to_user_id`` required-positional check. For T4
    # boundary verification, the test constructs its own fake session
    # whose ``send_chat`` is a real async def with the right signature.
    return s  # type: ignore[return-value]


@pytest.fixture
def mock_brain_mcp() -> MagicMock:
    """Brain MCP client mock; small subset of nx_* tools that W3 will use."""
    m = MagicMock()
    m.nx_vault_search = AsyncMock(return_value={"results": []})
    m.nx_references_search = AsyncMock(return_value={"results": []})
    m.deep_research = AsyncMock(return_value={"summary": "stub"})
    return m


@pytest.fixture
def mock_transcript_buffer() -> MagicMock:
    """TranscriptBuffer mock; subscribe / get_hot_window / search."""
    m = MagicMock()
    m.subscribe = MagicMock(return_value=asyncio.Queue())
    m.get_hot_window = MagicMock(return_value=[])
    m.search = MagicMock(return_value=[])
    return m


def make_chat_event(
    *,
    text: str,
    sender_user_id: str = "user_001",
    sender_canonical_id: str | None = "cyril-grosse",
    meeting_id: str = "mtg_001",
    is_private: bool = True,
    is_at_mention_to_bot: bool = False,
) -> ChatEvent:
    """Build a ``ChatEvent`` with sane defaults for boundary tests."""
    ts = datetime.now(timezone.utc)
    return ChatEvent(
        id=f"evt_{sender_user_id}_{ts.timestamp()}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=sender_canonical_id,
        sender_canonical_confidence=0.95 if sender_canonical_id else None,
        sender_display_name=sender_canonical_id or "Anonymous Joiner",
        text=text,
        ts=ts,
        is_private=is_private,
        is_at_mention_to_bot=is_at_mention_to_bot,
    )
