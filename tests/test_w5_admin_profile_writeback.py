"""W5.5 -- Persistent allowlist write-back via Brain ``nx_vault_write``.

Spec §3 lines 429-440 (the ``persistent`` keyword in
``allowlist add <id> persistent`` / ``allowlist remove <id> persistent``).
The write-back round-trips the live :class:`AssistantProfile` through
YAML serialization and replaces the target vault note's full content via
Brain MCP. The in-memory mutations history MUST carry an audit entry per
mutation (``ProfileMutation`` with action + target + by + session_id).

The dispatcher writes ATOMICALLY -- it computes the new profile dataclass
first, then issues the Brain write. A Brain failure leaves the
in-memory mutation appended (already-applied) AND raises
:class:`AdminCommandError`; the caller surfaces the diagnostic to the
admin surface so the operator knows the vault is out of sync. (Production
v0.2 OQ: introduce a rollback path so in-memory and vault stay in sync on
Brain failure.)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from lattice_meeting_assistant import (
    AssistantProfile,
    KnowledgeAccessConfig,
)
from lattice_meeting_assistant.admin import (
    AdminCommandDispatcher,
    AdminCommandError,
    parse_admin_command,
)
from lattice_meeting_assistant.brain_client import BrainMCPClient, BrainMCPError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VAULT_PATH = "02_Projects/Lattice/lattice-meeting-assistant/Profiles/test-profile.yaml"


def _make_profile(
    *,
    dm_allowlist: tuple[str, ...] = (),
    admins: tuple[str, ...] = ("cyril-grosse",),
    source_vault_note: str | None = _VAULT_PATH,
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


class _ProfileHolder:
    def __init__(self, profile: AssistantProfile) -> None:
        self.profile = profile


def _make_brain(
    *,
    write_result: dict[str, Any] | None = None,
    write_exc: Exception | None = None,
) -> MagicMock:
    m = MagicMock(spec=BrainMCPClient)
    if write_exc is not None:
        m.nx_vault_write = AsyncMock(side_effect=write_exc)
    else:
        m.nx_vault_write = AsyncMock(return_value=write_result or {"ok": True})
    return m


def _make_dispatcher(
    *,
    profile: AssistantProfile,
    brain: MagicMock | None,
    session_id: str = "sess-1",
) -> tuple[AdminCommandDispatcher, _ProfileHolder]:
    holder = _ProfileHolder(profile)
    state: dict[str, Any] = {"muted": False, "tier_override": None}
    dispatcher = AdminCommandDispatcher(
        profile_holder=holder,  # type: ignore[arg-type]
        brain_mcp=brain,
        session_state=state,
        session_id=session_id,
    )
    return dispatcher, holder


# ---------------------------------------------------------------------------
# Persistent write-back path
# ---------------------------------------------------------------------------


async def test_allowlist_add_persistent_calls_brain_nx_vault_write() -> None:
    """``allowlist add X persistent`` invokes Brain ``nx_vault_write``."""
    profile = _make_profile(dm_allowlist=())
    brain = _make_brain()
    dispatcher, holder = _make_dispatcher(profile=profile, brain=brain)

    result = await dispatcher.dispatch(
        parse_admin_command("allowlist add user-x persistent"),
        ratifying_user="cyril-grosse",
    )
    assert result.ok is True
    brain.nx_vault_write.assert_awaited_once()
    call = brain.nx_vault_write.await_args
    # Vault path threaded through.
    assert call.kwargs["path"] == _VAULT_PATH
    # Content is YAML serialised profile carrying the new allowlist entry.
    body = call.kwargs["content"]
    parsed = yaml.safe_load(body)
    assert "user-x" in parsed["dm_allowlist"]


async def test_allowlist_add_persistent_includes_audit_history_in_yaml() -> None:
    """Serialised YAML contains the in-memory mutations history."""
    profile = _make_profile(dm_allowlist=())
    brain = _make_brain()
    dispatcher, holder = _make_dispatcher(profile=profile, brain=brain)

    await dispatcher.dispatch(
        parse_admin_command("allowlist add user-x persistent"),
        ratifying_user="cyril-grosse",
    )

    body = brain.nx_vault_write.await_args.kwargs["content"]
    parsed = yaml.safe_load(body)
    history = parsed["in_memory_mutations_history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["action"] == "allowlist_add"
    assert entry["target"] == "user-x"
    assert entry["by"] == "cyril-grosse"
    assert "persistent" in entry["session_id"]


async def test_allowlist_remove_persistent_calls_brain_nx_vault_write() -> None:
    """``allowlist remove X persistent`` writes the trimmed list."""
    profile = _make_profile(dm_allowlist=("user-x", "user-y"))
    brain = _make_brain()
    dispatcher, holder = _make_dispatcher(profile=profile, brain=brain)

    await dispatcher.dispatch(
        parse_admin_command("allowlist remove user-x persistent"),
        ratifying_user="cyril-grosse",
    )

    brain.nx_vault_write.assert_awaited_once()
    body = brain.nx_vault_write.await_args.kwargs["content"]
    parsed = yaml.safe_load(body)
    assert "user-x" not in parsed["dm_allowlist"]
    assert "user-y" in parsed["dm_allowlist"]


async def test_session_scoped_add_does_NOT_call_brain() -> None:
    """``allowlist add X`` without ``persistent`` keyword stays in-memory."""
    profile = _make_profile(dm_allowlist=())
    brain = _make_brain()
    dispatcher, holder = _make_dispatcher(profile=profile, brain=brain)

    await dispatcher.dispatch(
        parse_admin_command("allowlist add user-x"),
        ratifying_user="cyril-grosse",
    )

    brain.nx_vault_write.assert_not_called()
    # In-memory mutation still appended.
    assert "user-x" in holder.profile.dm_allowlist


async def test_session_scoped_remove_does_NOT_call_brain() -> None:
    profile = _make_profile(dm_allowlist=("user-x",))
    brain = _make_brain()
    dispatcher, holder = _make_dispatcher(profile=profile, brain=brain)

    await dispatcher.dispatch(
        parse_admin_command("allowlist remove user-x"),
        ratifying_user="cyril-grosse",
    )
    brain.nx_vault_write.assert_not_called()
    assert "user-x" not in holder.profile.dm_allowlist


# ---------------------------------------------------------------------------
# YAML round-trip safety
# ---------------------------------------------------------------------------


async def test_yaml_serialised_profile_round_trips_clean() -> None:
    """Written YAML loads back to an equivalent ``AssistantProfile`` shape."""
    profile = _make_profile(dm_allowlist=("alice",))
    brain = _make_brain()
    dispatcher, _holder = _make_dispatcher(profile=profile, brain=brain)

    await dispatcher.dispatch(
        parse_admin_command("allowlist add bob persistent"),
        ratifying_user="cyril-grosse",
    )

    body = brain.nx_vault_write.await_args.kwargs["content"]
    parsed = yaml.safe_load(body)

    # Frontmatter fields preserved.
    assert parsed["profile_id"] == "test-profile"
    assert parsed["schema_version"] == 1
    assert set(parsed["dm_allowlist"]) == {"alice", "bob"}
    assert parsed["admins"] == ["cyril-grosse"]
    assert parsed["knowledge"]["allow_personal_vault"] is False
    assert parsed["source_vault_note"] == _VAULT_PATH


# ---------------------------------------------------------------------------
# Brain failure surfaces
# ---------------------------------------------------------------------------


async def test_brain_500_raises_admin_command_error() -> None:
    """Brain non-2xx -> :class:`AdminCommandError` with diagnostic."""
    exc = BrainMCPError("Brain MCP 'nx_vault_write' returned HTTP 500: 'fault'", status_code=500)
    profile = _make_profile(dm_allowlist=())
    brain = _make_brain(write_exc=exc)
    dispatcher, _holder = _make_dispatcher(profile=profile, brain=brain)

    with pytest.raises(AdminCommandError, match="500"):
        await dispatcher.dispatch(
            parse_admin_command("allowlist add user-x persistent"),
            ratifying_user="cyril-grosse",
        )


async def test_persistent_without_brain_raises_admin_command_error() -> None:
    """Persistent verb fires without a wired Brain client -> raise."""
    profile = _make_profile(dm_allowlist=())
    dispatcher, _holder = _make_dispatcher(profile=profile, brain=None)

    with pytest.raises(AdminCommandError, match="brain_mcp"):
        await dispatcher.dispatch(
            parse_admin_command("allowlist add user-x persistent"),
            ratifying_user="cyril-grosse",
        )


async def test_persistent_without_source_vault_note_raises() -> None:
    """Profile lacks ``source_vault_note`` -> can't write back -> raise."""
    profile = _make_profile(dm_allowlist=(), source_vault_note=None)
    brain = _make_brain()
    dispatcher, _holder = _make_dispatcher(profile=profile, brain=brain)

    with pytest.raises(AdminCommandError, match="source_vault_note"):
        await dispatcher.dispatch(
            parse_admin_command("allowlist add user-x persistent"),
            ratifying_user="cyril-grosse",
        )
    # Brain MUST NOT have been called -- prerequisite check is first.
    brain.nx_vault_write.assert_not_called()
