"""Architectural Invariant 1-5 enforcement primitives.

See ``02_Projects/Lattice/lattice-meeting-assistant/Specifications/
2026-05-11 lattice-meeting-assistant v0.1 - Design Spec.md`` §5 for the
full statement of each invariant.

These primitives are consumed by:

    * the cortex tool resolver  (W3 -- Invariant 2)
    * ``ChatThreadActor``        (W4 -- Invariant 3)
    * ``Assistant`` ingest       (W4-W6 -- Invariants 1, 4, 5)
"""

from __future__ import annotations

import inspect
import re
from typing import Final, Iterable, Literal

from ..exceptions import PrivacyBoundaryViolation

# ---------------------------------------------------------------------------
# Invariant 2 -- Transport-Bound Knowledge Access
# ---------------------------------------------------------------------------

#: Cortex tool names the ``in-meeting-dm`` transport may NEVER register.
#:
#: Enumerated per Design Spec §4 ``BLOCKED_IN_MEETING_TOOLS`` table.
#: Default-deny posture: when a new MCP tool is added to the global Nexus
#: surface, it does NOT automatically grant access to in-meeting-dm. The
#: in-meeting tool set is explicitly enumerated by the resolver (W3); this
#: frozenset is the disjointness check anchor.
BLOCKED_IN_MEETING_TOOLS: Final[frozenset[str]] = frozenset(
    {
        # --- Full personal vault access ---------------------------------
        "search_vault",
        "read_note",
        "nx_vault_multi_read",
        "nx_vault_multi_search",
        "nx_vault_query",
        "nx_vault_write",
        "vault_ask",
        # --- Email ------------------------------------------------------
        "search_email",
        "read_email",
        # --- Calendar ---------------------------------------------------
        "nx_calendar_read",
        "nx_calendar_write",
        "create_calendar_event",
        # --- Contacts ---------------------------------------------------
        "nx_contacts_read",
        "nx_contacts_search",
        "nx_contacts_add",
        "nx_contacts_update",
        # --- DB + heavy retrieval --------------------------------------
        "nx_db_query",
        # ``deep_research`` full mode is blocked; lightweight access is
        # exposed via the ``web_search`` wrapper tool in the curated set.
        "deep_research",
        "nx_context_gather",
        # --- Media + social -------------------------------------------
        "download_media",
        "instagram_ingest",
        "x_status",
        "x_sync_bookmarks",
        "youtube_playlists",
        "youtube_sync_playlist",
        "search_whatsapp",
        # --- Reference lookups (out of v0.1 in-meeting scope) ----------
        "bible_lookup",
        "strongs_lookup",
        # --- Vault-mutating + ticketing (TG-only in v0.2; never in-mtg) -
        "create_note",
        "create_reminder",
        "create_ticket",
        "flush_note_queue",
        "ingest_url",
        "share_note",
        "update_note",
        "update_ticket",
        "list_tickets",
        # --- Circular dispatch -----------------------------------------
        # ``brain_chat`` would invoke Brain's own chat which itself carries
        # the full Nexus surface -- transitive escalation.
        "brain_chat",
    }
)


def assert_in_meeting_tools_safe(tool_names: Iterable[str]) -> None:
    """Raise ``ValueError`` if any name in *tool_names* is in
    :data:`BLOCKED_IN_MEETING_TOOLS`.

    The cortex tool resolver (W3) calls this at boot for the
    ``in-meeting-dm`` transport's resolved tool set, enforcing
    Architectural Invariant #2.

    This helper checks only the BLOCKED set. Unknown-tool fail-closed
    behaviour belongs to the resolver itself, which explicitly enumerates
    the allowed tools and rejects any not in that enumeration.
    """
    names = set(tool_names)
    overlap = names & BLOCKED_IN_MEETING_TOOLS
    if overlap:
        raise ValueError(
            "in-meeting-dm transport attempted to register blocked tool(s): "
            f"{sorted(overlap)}. These are forbidden per BLOCKED_IN_MEETING_TOOLS "
            "(Architectural Invariant #2)."
        )


# ---------------------------------------------------------------------------
# Invariant 1 -- Separated Send Paths
# ---------------------------------------------------------------------------


def assert_separated_send_paths(session: object) -> None:
    """Verify *session* satisfies the separated-send-paths contract.

    Architectural Invariant #1 requires:

    * ``send_chat(to_user_id, message)`` -- private DM, ``to_user_id``
      is a required positional parameter (no broadcast default).
    * ``send_chat_public(message)`` -- public chat, a SEPARATE method.

    Raises ``ValueError`` if either method is missing, if ``send_chat``
    accepts a ``broadcast`` parameter, or if ``send_chat`` does not
    require ``to_user_id``. The ``Assistant`` calls this at ``start()``
    against the session handed to it by the consuming sidecar.
    """
    send_chat = getattr(session, "send_chat", None)
    send_chat_public = getattr(session, "send_chat_public", None)

    if send_chat is None or not callable(send_chat):
        raise ValueError(
            "session lacks send_chat; Invariant 1 requires a private-DM send "
            "path distinct from send_chat_public (see spec §5)."
        )

    # Inspect send_chat shape BEFORE checking for send_chat_public, because
    # a ``broadcast=`` parameter on send_chat is the canonical broken-API
    # shape and the most diagnostic error message to surface.
    try:
        sig: inspect.Signature | None = inspect.signature(send_chat)
    except (TypeError, ValueError):  # builtins / C-impls without signatures
        sig = None

    if sig is not None:
        params = sig.parameters
        if "broadcast" in params:
            raise ValueError(
                "session.send_chat exposes a 'broadcast' parameter; "
                "Invariant 1 forbids any broadcast= path. Public messages "
                "MUST go through send_chat_public."
            )

        # ``to_user_id`` must be present as a required (non-default) param.
        to_user_id_param = params.get("to_user_id")
        if to_user_id_param is None:
            raise ValueError(
                "session.send_chat lacks required 'to_user_id' parameter; "
                "Invariant 1 requires explicit per-recipient addressing."
            )
        if to_user_id_param.default is not inspect.Parameter.empty:
            raise ValueError(
                "session.send_chat.to_user_id has a default value; "
                "Invariant 1 requires it be a required positional (no "
                "implicit broadcast)."
            )

    if send_chat_public is None or not callable(send_chat_public):
        raise ValueError(
            "session lacks send_chat_public; Invariant 1 requires a separate "
            "public-chat send path (see spec §5)."
        )


# ---------------------------------------------------------------------------
# Invariant 3 -- Per-Thread Memory Isolation
# ---------------------------------------------------------------------------

_PUBLIC_THREAD_SENTINEL: Final[str] = "__public__"


def thread_memory_key(
    *,
    meeting_id: str,
    persona_id: str | None,
    public: bool = False,
) -> str:
    """Return the per-thread memory key for a ``(meeting, sender)`` pair.

    Private DM thread:
        ``thread_memory_key(meeting_id="m1", persona_id="alice")``
        -> deterministic key keyed on (m1, alice)

    Public mention thread:
        ``thread_memory_key(meeting_id="m1", persona_id=None, public=True)``
        -> deterministic key keyed on (m1, public-sentinel)

    The public sentinel is structurally distinct from any persona id
    (it cannot collide with a participant literally named ``"public"``),
    so private threads from a sender named ``"public"`` do not commingle
    with the meeting-level public-mention thread. This is the
    Architectural Invariant #3 fail-safe.

    Also serves as the cortex prompt-cache namespace key, so a
    cache lookup from one ``(meeting, persona)`` thread cannot hit
    against another's stored entries.
    """
    if public:
        return f"mtg:{meeting_id}|thr:{_PUBLIC_THREAD_SENTINEL}"
    if persona_id is None:
        raise ValueError("thread_memory_key requires either persona_id or public=True")
    return f"mtg:{meeting_id}|persona:{persona_id}"


# ---------------------------------------------------------------------------
# Invariant 4 -- Visibility-Tag Fail-Closed
# ---------------------------------------------------------------------------

_SENTINEL: Final[object] = object()


def enforce_visibility_tag(event: object) -> None:
    """Raise :class:`PrivacyBoundaryViolation` if *event* lacks an
    ``is_private`` attribute or its value is ``None``.

    Architectural Invariant #4 -- fail-closed on visibility ambiguity.
    The Assistant calls this at the very top of ``on_private_chat()`` and
    ``on_public_mention()``. No silent default; ambiguity = refuse.
    """
    is_private = getattr(event, "is_private", _SENTINEL)
    if is_private is _SENTINEL or is_private is None:
        event_id = getattr(event, "id", "<unknown>")
        raise PrivacyBoundaryViolation(
            f"chat event lacks is_private visibility tag: event_id={event_id}"
        )


# ---------------------------------------------------------------------------
# Invariant 5 -- Admin Surface Isolation
# ---------------------------------------------------------------------------

# Admin command grammar from Design Spec §3 "Admin command syntax".
# Anchored on the first significant token so casual chat that happens to
# mention "mute" or "help" in a sentence does NOT trigger.
_ADMIN_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:"
    r"allowlist\s+(?:add|remove)\s+\S+(?:\s+persistent)?"
    r"|allowlist\s+show"
    r"|mode\s+(?:interactive|research)"
    r"|mute"
    r"|unmute"
    r"|help"
    r"|status"
    r")\s*$",
    re.IGNORECASE,
)


def is_admin_command_syntax(text: str) -> bool:
    """Return True if *text* matches the admin command grammar
    (spec §3 "Admin command syntax").

    Leading and trailing whitespace are tolerated; otherwise the entire
    string must match. Casual conversational text containing one of these
    words (e.g. *"mute the music please"*) is intentionally NOT matched.
    """
    if not isinstance(text, str):
        return False
    return _ADMIN_COMMAND_RE.match(text.strip()) is not None


def assert_not_admin_in_meeting(
    text: str,
    *,
    transport_kind: Literal["tg-owner", "tg-cohost", "in-meeting-dm", "in-meeting-public"],
) -> None:
    """Raise :class:`PrivacyBoundaryViolation` if *text* matches the admin
    command grammar AND *transport_kind* is an in-meeting transport.

    Architectural Invariant #5 -- admin commands route EXCLUSIVELY through
    TG transport. Per ``[[Meeting Platform Admin Surface Isolation]]``
    (Cyril S25 verbatim: *"i will never want to expose my @cody commands
    inside the chat interface on the meeting platform"*).

    The Assistant calls this in ``on_private_chat()`` after
    ``enforce_visibility_tag()`` succeeds. The caller surfaces a polite
    user-facing reply ("admin commands not supported here") instead of
    letting the exception propagate to the user.
    """
    if transport_kind in ("in-meeting-dm", "in-meeting-public") and (is_admin_command_syntax(text)):
        raise PrivacyBoundaryViolation(
            "admin command syntax detected on in-meeting transport "
            f"(transport_kind={transport_kind!r}); admin surface is "
            "TG-only per Invariant 5."
        )


__all__ = [
    "BLOCKED_IN_MEETING_TOOLS",
    "assert_in_meeting_tools_safe",
    "assert_not_admin_in_meeting",
    "assert_separated_send_paths",
    "enforce_visibility_tag",
    "is_admin_command_syntax",
    "thread_memory_key",
]
