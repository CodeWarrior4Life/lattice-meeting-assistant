"""W5.4 -- Admin command parser + dispatcher + auth check.

Spec §3 lines 424-440 admin grammar:

* ``allowlist add <id>`` (session) / ``allowlist add <id> persistent`` (write-back)
* ``allowlist remove <id>``
* ``allowlist show``
* ``mode <interactive|research>`` (session-scoped tier change)
* ``mute`` / ``unmute``
* ``help`` / ``status``

Spec §3 lines 447-448 auth: ``AdminAuthorizationDenied`` raises when the
ratifying user is not in ``profile.admins``.

The parser returns a typed :class:`AdminCommand` value or ``None`` (no
admin grammar match). The dispatcher executes the parsed command against
the live assistant state -- session-scoped flags mutate in-process only;
``persistent`` allowlist edits route through ``brain_mcp.nx_vault_write``
(covered in W5.5).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant import (
    AdminAuthorizationDenied,
    AssistantConfig,
    AssistantProfile,
    KnowledgeAccessConfig,
)
from lattice_meeting_assistant.admin import (
    AdminCommand,
    AdminCommandDispatcher,
    parse_admin_command,
)
from lattice_meeting_assistant.brain_client import BrainMCPClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    dm_allowlist: tuple[str, ...] = (),
    admins: tuple[str, ...] = ("cyril-grosse",),
    source_vault_note: str
    | None = "02_Projects/Lattice/lattice-meeting-assistant/Profiles/test.yaml",
) -> AssistantProfile:
    knowledge = KnowledgeAccessConfig(
        allow_personal_vault=False,
        enable_past_meetings_search=True,
        enable_public_references_tool=True,
        enable_web_search=True,
        public_references=("References/",),
    )
    return AssistantProfile(
        profile_id="test-profile",
        series_id="series-x",
        dm_allowlist=dm_allowlist,
        admins=admins,
        knowledge=knowledge,
        source_vault_note=source_vault_note,
    )


def _make_brain() -> MagicMock:
    m = MagicMock(spec=BrainMCPClient)
    m.nx_vault_write = AsyncMock(return_value={"ok": True})
    m.nx_read_note = AsyncMock(
        return_value={
            "content": "schema_version: 1\nprofile_id: test-profile\n",
            "frontmatter": {},
        }
    )
    return m


def _make_dispatcher(
    *,
    profile: AssistantProfile,
    brain: MagicMock | None = None,
    session_id: str = "sess-1",
) -> tuple[AdminCommandDispatcher, dict[str, Any]]:
    """Construct the dispatcher with a captured session-state dict so
    tests can assert mutations to session-scoped flags without needing
    the full :class:`Assistant` shell.
    """
    state: dict[str, Any] = {
        "muted": False,
        "tier_override": None,
    }
    brain_mcp = brain if brain is not None else _make_brain()
    dispatcher = AdminCommandDispatcher(
        profile_holder=_ProfileHolder(profile),
        brain_mcp=brain_mcp,
        session_state=state,
        session_id=session_id,
    )
    return dispatcher, state


class _ProfileHolder:
    """Mutable holder so dispatcher can swap the profile after persistent edits."""

    def __init__(self, profile: AssistantProfile) -> None:
        self.profile = profile


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_allowlist_add_session() -> None:
    cmd = parse_admin_command("allowlist add user-x")
    assert cmd is not None
    assert cmd.verb == "allowlist_add"
    assert cmd.args == ("user-x",)
    assert cmd.persistent is False
    assert cmd.raw_text == "allowlist add user-x"


def test_parse_allowlist_add_persistent() -> None:
    cmd = parse_admin_command("allowlist add user-x persistent")
    assert cmd is not None
    assert cmd.verb == "allowlist_add"
    assert cmd.args == ("user-x",)
    assert cmd.persistent is True


def test_parse_allowlist_remove() -> None:
    cmd = parse_admin_command("allowlist remove user-x")
    assert cmd is not None
    assert cmd.verb == "allowlist_remove"
    assert cmd.args == ("user-x",)
    assert cmd.persistent is False


def test_parse_allowlist_remove_persistent() -> None:
    cmd = parse_admin_command("allowlist remove user-x persistent")
    assert cmd is not None
    assert cmd.verb == "allowlist_remove"
    assert cmd.args == ("user-x",)
    assert cmd.persistent is True


def test_parse_allowlist_show() -> None:
    cmd = parse_admin_command("allowlist show")
    assert cmd is not None
    assert cmd.verb == "allowlist_show"
    assert cmd.args == ()


def test_parse_mode_interactive() -> None:
    cmd = parse_admin_command("mode interactive")
    assert cmd is not None
    assert cmd.verb == "mode"
    assert cmd.args == ("interactive",)


def test_parse_mode_research() -> None:
    cmd = parse_admin_command("mode research")
    assert cmd is not None
    assert cmd.verb == "mode"
    assert cmd.args == ("research",)


def test_parse_mute_unmute() -> None:
    assert parse_admin_command("mute") is not None
    assert parse_admin_command("mute").verb == "mute"
    assert parse_admin_command("unmute") is not None
    assert parse_admin_command("unmute").verb == "unmute"


def test_parse_help() -> None:
    cmd = parse_admin_command("help")
    assert cmd is not None
    assert cmd.verb == "help"


def test_parse_status() -> None:
    cmd = parse_admin_command("status")
    assert cmd is not None
    assert cmd.verb == "status"


def test_parse_returns_none_for_non_admin_text() -> None:
    """Casual text containing a verb word does NOT match the grammar."""
    assert parse_admin_command("can you mute the music?") is None
    assert parse_admin_command("help me understand this") is None
    assert parse_admin_command("status update on the project") is None
    assert parse_admin_command("") is None
    assert parse_admin_command("random gibberish") is None


def test_parse_case_insensitive_on_verbs() -> None:
    """Verbs are case-insensitive; canonical-id args preserve case."""
    cmd = parse_admin_command("ALLOWLIST ADD User-Camel")
    assert cmd is not None
    assert cmd.verb == "allowlist_add"
    assert cmd.args == ("User-Camel",)


def test_parse_tolerates_leading_trailing_whitespace() -> None:
    cmd = parse_admin_command("   allowlist add x   ")
    assert cmd is not None
    assert cmd.verb == "allowlist_add"
    assert cmd.args == ("x",)


# ---------------------------------------------------------------------------
# Auth check
# ---------------------------------------------------------------------------


async def test_dispatch_raises_when_caller_not_admin() -> None:
    """Non-admin caller -> AdminAuthorizationDenied."""
    profile = _make_profile(admins=("cyril-grosse",))
    dispatcher, _state = _make_dispatcher(profile=profile)

    with pytest.raises(AdminAuthorizationDenied):
        await dispatcher.dispatch(
            parse_admin_command("allowlist show"),
            ratifying_user="some-stranger",
        )


async def test_dispatch_succeeds_when_caller_in_admins() -> None:
    """Admin caller -> verb executes."""
    profile = _make_profile(admins=("cyril-grosse",))
    dispatcher, _state = _make_dispatcher(profile=profile)

    result = await dispatcher.dispatch(
        parse_admin_command("allowlist show"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True


async def test_dispatch_raises_on_none_command() -> None:
    """Dispatcher gets ``None`` (no parse match) -> ValueError, not silent."""
    profile = _make_profile()
    dispatcher, _state = _make_dispatcher(profile=profile)

    with pytest.raises(ValueError, match="None"):
        await dispatcher.dispatch(None, ratifying_user="cyril-grosse")


# ---------------------------------------------------------------------------
# Verb dispatch -- session-scoped
# ---------------------------------------------------------------------------


async def test_dispatch_mode_interactive_sets_tier_override() -> None:
    """``mode interactive`` writes to session_state['tier_override']."""
    profile = _make_profile()
    dispatcher, state = _make_dispatcher(profile=profile)

    result = await dispatcher.dispatch(
        parse_admin_command("mode interactive"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True
    assert state["tier_override"] == "interactive"


async def test_dispatch_mode_research_sets_tier_override() -> None:
    profile = _make_profile()
    dispatcher, state = _make_dispatcher(profile=profile)

    result = await dispatcher.dispatch(
        parse_admin_command("mode research"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True
    assert state["tier_override"] == "research"


async def test_dispatch_mute_toggles_session_flag_on() -> None:
    profile = _make_profile()
    dispatcher, state = _make_dispatcher(profile=profile)

    await dispatcher.dispatch(
        parse_admin_command("mute"),
        ratifying_user="cyril-grosse",
    )
    assert state["muted"] is True


async def test_dispatch_unmute_toggles_session_flag_off() -> None:
    profile = _make_profile()
    dispatcher, state = _make_dispatcher(profile=profile)
    state["muted"] = True  # pre-condition

    await dispatcher.dispatch(
        parse_admin_command("unmute"),
        ratifying_user="cyril-grosse",
    )
    assert state["muted"] is False


async def test_dispatch_help_returns_canonical_help_string_no_llm() -> None:
    """``help`` returns a stable string; no Brain or cortex call needed."""
    profile = _make_profile()
    brain = _make_brain()
    dispatcher, _state = _make_dispatcher(profile=profile, brain=brain)

    result = await dispatcher.dispatch(
        parse_admin_command("help"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True
    text = result.response_text.lower()
    # Help string MUST surface the verb list.
    for verb in ("allowlist", "mode", "mute", "unmute", "help", "status"):
        assert verb in text
    # No Brain calls.
    brain.nx_vault_write.assert_not_called()


async def test_dispatch_status_returns_observability_snapshot() -> None:
    """``status`` returns an observability summary string."""
    profile = _make_profile()
    dispatcher, state = _make_dispatcher(profile=profile)
    state["muted"] = True
    state["tier_override"] = "research"

    result = await dispatcher.dispatch(
        parse_admin_command("status"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True
    text = result.response_text.lower()
    assert "mute" in text or "muted" in text
    assert "research" in text  # current tier override surfaces


async def test_dispatch_allowlist_show_lists_current_members() -> None:
    profile = _make_profile(dm_allowlist=("alice", "bob"))
    dispatcher, _state = _make_dispatcher(profile=profile)

    result = await dispatcher.dispatch(
        parse_admin_command("allowlist show"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True
    assert "alice" in result.response_text
    assert "bob" in result.response_text


async def test_dispatch_allowlist_add_session_mutates_in_memory_only() -> None:
    """Session-scoped ``allowlist add X`` mutates the profile holder
    but does NOT call Brain nx_vault_write.
    """
    profile = _make_profile(dm_allowlist=())
    brain = _make_brain()
    dispatcher, _state = _make_dispatcher(profile=profile, brain=brain)

    result = await dispatcher.dispatch(
        parse_admin_command("allowlist add user-x"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True
    # Profile holder updated in place.
    assert "user-x" in dispatcher._profile_holder.profile.dm_allowlist
    # Mutation audit appended.
    history = dispatcher._profile_holder.profile.in_memory_mutations_history
    assert len(history) == 1
    assert history[0].action == "allowlist_add"
    assert history[0].target == "user-x"
    assert history[0].by == "cyril-grosse"
    # No Brain write.
    brain.nx_vault_write.assert_not_called()


async def test_dispatch_allowlist_remove_session_mutates_in_memory_only() -> None:
    profile = _make_profile(dm_allowlist=("user-x", "user-y"))
    brain = _make_brain()
    dispatcher, _state = _make_dispatcher(profile=profile, brain=brain)

    await dispatcher.dispatch(
        parse_admin_command("allowlist remove user-x"),
        ratifying_user="cyril-grosse",
    )
    assert "user-x" not in dispatcher._profile_holder.profile.dm_allowlist
    assert "user-y" in dispatcher._profile_holder.profile.dm_allowlist
    brain.nx_vault_write.assert_not_called()
