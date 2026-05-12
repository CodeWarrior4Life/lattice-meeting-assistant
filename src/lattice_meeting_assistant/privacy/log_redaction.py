"""Log redaction primitives -- Q4c defense #3.

Policy:

    * INFO logs: metadata only -- event id, meeting id, sender id, message
      length. NEVER message body / transcript text.
    * DEBUG logs: include message body ONLY when
      ``AssistantConfig.debug_chat_content=True``. Default is False, so
      flipping the root logger to DEBUG alone is NOT sufficient to leak
      content -- the flag is an explicit second gate.

This belt-and-suspenders posture means a production deployment whose log
backend defaults to INFO never persists chat content, and a developer
who flips logging to DEBUG without setting the config flag still does
not leak content.
"""

from __future__ import annotations

import logging

from ..config import AssistantConfig

_log = logging.getLogger("lattice_meeting_assistant.privacy")


def log_chat_event(
    event_kind: str,
    event: object,
    config: AssistantConfig,
) -> None:
    """Log a chat event with redaction policy applied.

    Parameters
    ----------
    event_kind:
        Short event-type tag, e.g. ``"private_chat_received"``,
        ``"public_mention_received"``, ``"reply_sent"``,
        ``"admin_command_received"``.
    event:
        Any object exposing ``id``, ``meeting_id``, ``sender_user_id``,
        ``text`` attributes (``ChatEvent`` in the canonical case;
        duck-typed for test fakes and admin-command audit entries).
    config:
        The active ``AssistantConfig``. ``config.debug_chat_content``
        gates DEBUG content emission.
    """
    event_id = getattr(event, "id", "<unknown>")
    meeting_id = getattr(event, "meeting_id", "<unknown>")
    sender_id = getattr(event, "sender_user_id", "<unknown>")
    text = getattr(event, "text", "")
    msg_len = len(text) if isinstance(text, str) else 0

    if config.debug_chat_content:
        _log.debug(
            "%s evt=%s mtg=%s sender=%s msg_len=%d content=%r",
            event_kind,
            event_id,
            meeting_id,
            sender_id,
            msg_len,
            text,
        )
    else:
        _log.info(
            "%s evt=%s mtg=%s sender=%s msg_len=%d",
            event_kind,
            event_id,
            meeting_id,
            sender_id,
            msg_len,
        )


__all__ = ["log_chat_event"]
