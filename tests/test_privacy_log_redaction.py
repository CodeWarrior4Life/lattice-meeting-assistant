"""Unit tests for log redaction policy (privacy/log_redaction.py).

INFO-level logs MUST NOT carry message body. DEBUG-level logs MUST NOT
carry body unless the explicit ``AssistantConfig.debug_chat_content``
flag is True. Belt-and-suspenders -- flipping logging to DEBUG alone is
not sufficient to leak content.
"""

from __future__ import annotations

import logging

import pytest

from lattice_meeting_assistant.config import AssistantConfig
from lattice_meeting_assistant.privacy import log_chat_event


class _FakeEvent:
    def __init__(self, text: str = "secret content nobody should see") -> None:
        self.id = "evt_123"
        self.meeting_id = "mtg_456"
        self.sender_user_id = "user_789"
        self.text = text
        self.is_private = True


def test_info_log_omits_content(caplog: pytest.LogCaptureFixture) -> None:
    """At INFO level (default), message content is NEVER emitted; only
    metadata (event id, meeting id, sender id, msg_len) appears."""
    cfg = AssistantConfig(debug_chat_content=False)
    caplog.set_level(logging.INFO, logger="lattice_meeting_assistant.privacy")
    log_chat_event("private_chat_received", _FakeEvent(), cfg)
    record = caplog.records[-1]
    msg = record.getMessage()
    assert "secret content" not in msg
    assert "evt_123" in msg
    assert "mtg_456" in msg
    assert "user_789" in msg
    assert "msg_len=" in msg
    assert record.levelno == logging.INFO


def test_debug_log_includes_content_when_flag_set(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``debug_chat_content=True`` the DEBUG record carries body."""
    cfg = AssistantConfig(debug_chat_content=True)
    caplog.set_level(logging.DEBUG, logger="lattice_meeting_assistant.privacy")
    log_chat_event("private_chat_received", _FakeEvent(), cfg)
    record = caplog.records[-1]
    msg = record.getMessage()
    assert "secret content" in msg
    assert record.levelno == logging.DEBUG


def test_debug_log_omits_content_when_flag_unset(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Belt-and-suspenders: even with logger at DEBUG, content is redacted
    until the explicit ``debug_chat_content`` flag is True."""
    cfg = AssistantConfig(debug_chat_content=False)
    caplog.set_level(logging.DEBUG, logger="lattice_meeting_assistant.privacy")
    log_chat_event("private_chat_received", _FakeEvent(), cfg)
    record = caplog.records[-1]
    msg = record.getMessage()
    assert "secret content" not in msg
    # Path taken is the INFO branch (no content) -- record level reflects.
    assert record.levelno == logging.INFO
