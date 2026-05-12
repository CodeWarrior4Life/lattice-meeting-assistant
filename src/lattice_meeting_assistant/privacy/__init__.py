"""Privacy invariants + log redaction primitives.

This sub-package houses the in-code enforcement of the five Architectural
Invariants from the v0.1 Design Spec §5:

    1. Separated Send Paths           -- ``assert_separated_send_paths``
    2. Transport-Bound Knowledge      -- ``BLOCKED_IN_MEETING_TOOLS`` +
                                          ``assert_in_meeting_tools_safe``
    3. Per-Thread Memory Isolation    -- ``thread_memory_key``
    4. Visibility-Tag Fail-Closed     -- ``enforce_visibility_tag``
    5. Admin Surface Isolation        -- ``is_admin_command_syntax`` +
                                          ``assert_not_admin_in_meeting``

Plus log redaction (Q4c defense #3):

    ``log_chat_event`` -- INFO never carries content; DEBUG carries content
    only when ``AssistantConfig.debug_chat_content=True``.
"""

from __future__ import annotations

from .consumers import WrapupTranscriptConsumer
from .invariants import (
    BLOCKED_IN_MEETING_TOOLS,
    assert_in_meeting_tools_safe,
    assert_not_admin_in_meeting,
    assert_separated_send_paths,
    enforce_visibility_tag,
    is_admin_command_syntax,
    thread_memory_key,
)
from .log_redaction import log_chat_event

__all__ = [
    "BLOCKED_IN_MEETING_TOOLS",
    "WrapupTranscriptConsumer",
    "assert_in_meeting_tools_safe",
    "assert_not_admin_in_meeting",
    "assert_separated_send_paths",
    "enforce_visibility_tag",
    "is_admin_command_syntax",
    "log_chat_event",
    "thread_memory_key",
]
