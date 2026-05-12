"""Admin command parser + dispatcher.

Spec §3 lines 424-440. Admin commands route exclusively through the
TG transport per Architectural Invariant 5 (Meeting Platform Admin
Surface Isolation). In-meeting transports detect admin syntax via
``privacy.invariants.is_admin_command_syntax`` and reject with a stock
reply (see ``Assistant.on_private_chat`` -- W5.6).

Verb grammar (case-insensitive on verbs; canonical-id args preserve case):

    allowlist add <id>                # session-scoped
    allowlist add <id> persistent     # writes back to profile YAML
    allowlist remove <id>
    allowlist remove <id> persistent
    allowlist show
    mode <interactive|research>       # session-scoped tier change
    mute / unmute
    help / status

W5.4 ships the parser + dispatcher + auth check + session-scoped paths.
W5.5 wires the ``persistent`` write-back through Brain ``nx_vault_write``.
The dispatcher is consumed by ``Assistant.admin_command()`` (lands at
W5.6 onward).

Auth check: every ``dispatch()`` call verifies the ratifying user is in
``profile.admins`` before executing any verb. Non-admin callers raise
:class:`AdminAuthorizationDenied` -- no silent denial because the admin
surface is bilateral and the caller (BrainTGAdminTransport) needs the
diagnostic to surface back to the operator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Final, Literal

import yaml

from .brain_client import BrainMCPClient, BrainMCPError
from .exceptions import AdminAuthorizationDenied
from .profile import AssistantProfile
from .types import AdminCommandResult, CanonicalPersonaId, ProfileMutation


AdminVerb = Literal[
    "allowlist_add",
    "allowlist_remove",
    "allowlist_show",
    "mode",
    "mute",
    "unmute",
    "help",
    "status",
]


@dataclass(frozen=True)
class AdminCommand:
    """Parsed admin command. See :func:`parse_admin_command`.

    Fields:

    * ``verb`` -- normalized verb identifier (snake_case).
    * ``args`` -- tuple of positional arguments preserving case
      (e.g. canonical persona id, tier name).
    * ``persistent`` -- ``True`` when the trailing ``persistent`` keyword
      was supplied on an ``allowlist add/remove`` command. Other verbs
      always carry ``False``.
    * ``raw_text`` -- the original (trimmed) input string for audit
      logging.
    """

    verb: AdminVerb
    args: tuple[str, ...]
    persistent: bool
    raw_text: str


class AdminCommandError(RuntimeError):
    """Raised when an admin command cannot complete due to an external
    failure (Brain write 5xx, malformed profile YAML, etc.).

    Authorization failures use :class:`AdminAuthorizationDenied` instead;
    this exception is reserved for downstream/infrastructure faults the
    operator needs to act on. The exception message carries diagnostics
    suitable for the admin surface reply.
    """


# Anchored regex covering every verb in §3 lines 429-438. Verbs are
# case-insensitive; canonical-id args preserve case (no .lower() on the
# captured group). ``persistent`` keyword is optional on add/remove.
_ADMIN_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:"
    r"(?P<allowlist_addrem>allowlist)\s+(?P<addrem_verb>add|remove)\s+(?P<id>\S+)(?:\s+(?P<persistent>persistent))?"
    r"|(?P<allowlist_show>allowlist)\s+show"
    r"|(?P<mode>mode)\s+(?P<tier>interactive|research)"
    r"|(?P<mute>mute)"
    r"|(?P<unmute>unmute)"
    r"|(?P<help>help)"
    r"|(?P<status>status)"
    r")\s*$",
    re.IGNORECASE,
)


def parse_admin_command(text: str) -> AdminCommand | None:
    """Parse *text* into an :class:`AdminCommand`, or return ``None``.

    Returns ``None`` when *text* does not match the admin grammar
    (casual chat that happens to mention a verb word is intentionally
    NOT a match). Leading/trailing whitespace is tolerated; verbs are
    case-insensitive; canonical-id and tier args preserve case.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    m = _ADMIN_RE.match(stripped)
    if m is None:
        return None

    if m.group("allowlist_addrem"):
        addrem = (m.group("addrem_verb") or "").lower()
        verb: AdminVerb = "allowlist_add" if addrem == "add" else "allowlist_remove"
        canonical_id = m.group("id") or ""
        persistent = m.group("persistent") is not None
        return AdminCommand(
            verb=verb,
            args=(canonical_id,),
            persistent=persistent,
            raw_text=stripped,
        )
    if m.group("allowlist_show"):
        return AdminCommand(verb="allowlist_show", args=(), persistent=False, raw_text=stripped)
    if m.group("mode"):
        tier = (m.group("tier") or "").lower()
        return AdminCommand(verb="mode", args=(tier,), persistent=False, raw_text=stripped)
    if m.group("mute"):
        return AdminCommand(verb="mute", args=(), persistent=False, raw_text=stripped)
    if m.group("unmute"):
        return AdminCommand(verb="unmute", args=(), persistent=False, raw_text=stripped)
    if m.group("help"):
        return AdminCommand(verb="help", args=(), persistent=False, raw_text=stripped)
    if m.group("status"):
        return AdminCommand(verb="status", args=(), persistent=False, raw_text=stripped)
    return None  # unreachable -- regex guarantees one group hit


# Help text surfaced by the ``help`` verb. Mirrors the spec §3 grammar so
# the operator sees the full surface at a glance.
_HELP_TEXT: Final[str] = (
    "Admin commands (TG-only):\n"
    "  allowlist add <id>                # session-scoped\n"
    "  allowlist add <id> persistent     # writes back to profile YAML\n"
    "  allowlist remove <id> [persistent]\n"
    "  allowlist show\n"
    "  mode interactive | research       # session-scoped tier override\n"
    "  mute / unmute\n"
    "  help                              # this message\n"
    "  status                            # observability snapshot\n"
)


class _ProfileHolder:
    """Structural protocol -- a mutable container for the active profile.

    The dispatcher mutates ``self.profile`` after every allowlist edit
    so subsequent dispatches see the updated state. Production
    :class:`Assistant` exposes the live profile via a holder shape so
    the dispatcher can persist updates without coupling to the full
    Assistant surface.
    """

    profile: AssistantProfile


class AdminCommandDispatcher:
    """Dispatch parsed :class:`AdminCommand` values against assistant state.

    Construction:

    * ``profile_holder`` -- carries the live :class:`AssistantProfile`.
      The dispatcher mutates ``profile_holder.profile`` (rebinds to a
      new frozen dataclass via ``dataclasses.replace``) on every
      allowlist edit.
    * ``brain_mcp`` -- Brain MCP client used for the ``persistent``
      write-back path (``allowlist add/remove ... persistent``). May be
      ``None`` -- the dispatcher raises :class:`AdminCommandError` if a
      persistent verb fires without a wired client.
    * ``session_state`` -- a mutable mapping the dispatcher reads/writes
      session-scoped flags into: ``"muted"`` (bool), ``"tier_override"``
      (``"interactive"`` | ``"research"`` | None). The owning
      :class:`Assistant` consults this state at routing time.
    * ``session_id`` -- threaded into mutation audit entries.
    """

    def __init__(
        self,
        *,
        profile_holder: _ProfileHolder,
        brain_mcp: BrainMCPClient | None,
        session_state: dict[str, Any],
        session_id: str,
    ) -> None:
        self._profile_holder = profile_holder
        self._brain_mcp = brain_mcp
        self._session_state = session_state
        self._session_id = session_id

    @property
    def profile(self) -> AssistantProfile:
        return self._profile_holder.profile

    async def dispatch(
        self,
        command: AdminCommand | None,
        *,
        ratifying_user: CanonicalPersonaId,
    ) -> AdminCommandResult:
        """Execute *command* on behalf of *ratifying_user*.

        Raises:

        * :class:`AdminAuthorizationDenied` -- *ratifying_user* not in
          ``profile.admins``.
        * :class:`AdminCommandError` -- downstream/infrastructure
          failure during a persistent write-back.
        * ``ValueError`` -- *command* is ``None`` (caller passed an
          unparsed text without checking).
        """
        if command is None:
            raise ValueError(
                "AdminCommandDispatcher.dispatch: command is None -- caller "
                "must check parse_admin_command() return before dispatching."
            )

        if ratifying_user not in self.profile.admins:
            raise AdminAuthorizationDenied(
                f"ratifying user {ratifying_user!r} is not in profile.admins; "
                f"admins={list(self.profile.admins)!r}"
            )

        verb = command.verb
        if verb == "allowlist_add":
            return await self._do_allowlist_add(command, ratifying_user)
        if verb == "allowlist_remove":
            return await self._do_allowlist_remove(command, ratifying_user)
        if verb == "allowlist_show":
            return self._do_allowlist_show()
        if verb == "mode":
            return self._do_mode(command, ratifying_user)
        if verb == "mute":
            return self._do_mute(ratifying_user, on=True)
        if verb == "unmute":
            return self._do_mute(ratifying_user, on=False)
        if verb == "help":
            return AdminCommandResult(ok=True, response_text=_HELP_TEXT)
        if verb == "status":
            return self._do_status()
        # Unreachable -- AdminVerb literal exhausted above.
        raise ValueError(f"AdminCommandDispatcher: unhandled verb {verb!r}")

    # -----------------------------------------------------------------
    # Verb implementations
    # -----------------------------------------------------------------

    async def _do_allowlist_add(
        self,
        command: AdminCommand,
        ratifying_user: CanonicalPersonaId,
    ) -> AdminCommandResult:
        target = command.args[0]
        new_allowlist: tuple[str, ...]
        if target in self.profile.dm_allowlist:
            # Idempotent: re-adding is a no-op edit but still surfaces a reply.
            new_allowlist = self.profile.dm_allowlist
        else:
            new_allowlist = self.profile.dm_allowlist + (target,)

        mutation = self._mutation(
            action="allowlist_add",
            target=target,
            by=ratifying_user,
            scope="persistent" if command.persistent else "session",
        )

        new_history = self.profile.in_memory_mutations_history + (mutation,)
        new_profile = replace(
            self.profile,
            dm_allowlist=new_allowlist,
            in_memory_mutations_history=new_history,
        )
        self._profile_holder.profile = new_profile

        response = f"Added {target!r} to allowlist"
        if command.persistent:
            response += " (persistent)"
            await self._persist_profile(new_profile, mutation)
        else:
            response += " (session-scoped)"

        return AdminCommandResult(ok=True, response_text=response, mutation=mutation)

    async def _do_allowlist_remove(
        self,
        command: AdminCommand,
        ratifying_user: CanonicalPersonaId,
    ) -> AdminCommandResult:
        target = command.args[0]
        if target not in self.profile.dm_allowlist:
            return AdminCommandResult(
                ok=True,
                response_text=f"{target!r} not in allowlist (no-op)",
            )
        new_allowlist = tuple(x for x in self.profile.dm_allowlist if x != target)

        mutation = self._mutation(
            action="allowlist_remove",
            target=target,
            by=ratifying_user,
            scope="persistent" if command.persistent else "session",
        )
        new_history = self.profile.in_memory_mutations_history + (mutation,)
        new_profile = replace(
            self.profile,
            dm_allowlist=new_allowlist,
            in_memory_mutations_history=new_history,
        )
        self._profile_holder.profile = new_profile

        response = f"Removed {target!r} from allowlist"
        if command.persistent:
            response += " (persistent)"
            await self._persist_profile(new_profile, mutation)
        else:
            response += " (session-scoped)"

        return AdminCommandResult(ok=True, response_text=response, mutation=mutation)

    def _do_allowlist_show(self) -> AdminCommandResult:
        members = list(self.profile.dm_allowlist)
        if not members:
            text = "dm_allowlist: (empty)"
        else:
            text = "dm_allowlist:\n" + "\n".join(f"  - {m}" for m in members)
        return AdminCommandResult(ok=True, response_text=text)

    def _do_mode(
        self,
        command: AdminCommand,
        ratifying_user: CanonicalPersonaId,
    ) -> AdminCommandResult:
        tier = command.args[0]
        self._session_state["tier_override"] = tier
        mutation = self._mutation(
            action="mode_change",
            target=tier,
            by=ratifying_user,
            scope="session",
        )
        # Mode is session-scoped: append to in-memory history but no
        # persistent write-back.
        new_profile = replace(
            self.profile,
            in_memory_mutations_history=self.profile.in_memory_mutations_history + (mutation,),
        )
        self._profile_holder.profile = new_profile
        return AdminCommandResult(
            ok=True,
            response_text=f"mode -> {tier} (session-scoped)",
            mutation=mutation,
        )

    def _do_mute(
        self,
        ratifying_user: CanonicalPersonaId,
        *,
        on: bool,
    ) -> AdminCommandResult:
        self._session_state["muted"] = on
        action = "mute" if on else "unmute"
        mutation = self._mutation(
            action=action,
            target=None,
            by=ratifying_user,
            scope="session",
        )
        new_profile = replace(
            self.profile,
            in_memory_mutations_history=self.profile.in_memory_mutations_history + (mutation,),
        )
        self._profile_holder.profile = new_profile
        return AdminCommandResult(
            ok=True,
            response_text=f"{action}d (session-scoped)",
            mutation=mutation,
        )

    def _do_status(self) -> AdminCommandResult:
        muted = self._session_state.get("muted", False)
        tier_override = self._session_state.get("tier_override")
        history_len = len(self.profile.in_memory_mutations_history)
        text = (
            f"status: muted={muted} tier_override={tier_override or 'none'} "
            f"allowlist_size={len(self.profile.dm_allowlist)} "
            f"mutations_history={history_len}"
        )
        return AdminCommandResult(ok=True, response_text=text)

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _mutation(
        self,
        *,
        action: str,
        target: str | None,
        by: CanonicalPersonaId,
        scope: str,
    ) -> ProfileMutation:
        ts = datetime.now(timezone.utc).isoformat()
        return ProfileMutation(
            ts=ts,
            action=action,
            target=target,
            by=by,
            session_id=f"{self._session_id}:{scope}",
        )

    async def _persist_profile(
        self,
        new_profile: AssistantProfile,
        mutation: ProfileMutation,
    ) -> None:
        """Write *new_profile* back to its vault YAML via Brain MCP.

        Implementation of W5.5. Raises :class:`AdminCommandError` on
        Brain non-2xx or missing prerequisites (no brain_mcp wired, no
        profile_vault_path on the profile).
        """
        if self._brain_mcp is None:
            raise AdminCommandError(
                "persistent admin write requires a brain_mcp client; "
                "Assistant was constructed without one."
            )
        vault_path = new_profile.profile_vault_path
        if not vault_path:
            raise AdminCommandError(
                "persistent admin write requires profile.profile_vault_path to be set; "
                f"profile_id={new_profile.profile_id!r} has no vault path."
            )

        updated_yaml = _render_profile_yaml(new_profile)
        try:
            await self._brain_mcp.nx_vault_write(
                path=vault_path,
                content=updated_yaml,
            )
        except BrainMCPError as exc:
            raise AdminCommandError(
                f"Brain nx_vault_write failed for path={vault_path!r}: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# YAML rendering -- profile -> YAML string (PyYAML safe_dump).
# ---------------------------------------------------------------------------


def _render_profile_yaml(profile: AssistantProfile) -> str:
    """Serialize *profile* to YAML preserving field order.

    Uses PyYAML's ``safe_dump`` with ``sort_keys=False``. PyYAML does
    not preserve comments or anchors; v0.2 OQ tracks the round-trip
    upgrade to ``ruamel.yaml`` (see OQ-W5B-1 in the v0.2 OQ section).
    Field order mirrors :func:`profile.dump_profile_to_yaml`.
    """
    payload: dict[str, Any] = {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "series_id": profile.series_id,
        "dm_allowlist": list(profile.dm_allowlist),
        "admins": list(profile.admins),
        "dm_min_confidence": profile.dm_min_confidence,
        "allow_mapped_dm": profile.allow_mapped_dm,
        "allow_anonymous_dm": profile.allow_anonymous_dm,
        "public_mentions_enabled": profile.public_mentions_enabled,
        "public_mention_allowlist": (
            list(profile.public_mention_allowlist)
            if profile.public_mention_allowlist is not None
            else None
        ),
        "public_mention_rate_limit_per_meeting_s": (
            profile.public_mention_rate_limit_per_meeting_s
        ),
        "knowledge": {
            "allow_personal_vault": profile.knowledge.allow_personal_vault,
            "transcript_hot_window_seconds": (profile.knowledge.transcript_hot_window_seconds),
            "enable_transcript_search_tool": (profile.knowledge.enable_transcript_search_tool),
            "enable_past_meetings_search": (profile.knowledge.enable_past_meetings_search),
            "enable_public_references_tool": (profile.knowledge.enable_public_references_tool),
            "enable_web_search": profile.knowledge.enable_web_search,
            "public_references": list(profile.knowledge.public_references),
        },
        "series_match_binding": profile.series_match_binding,
        "series_match_confidence": profile.series_match_confidence,
        "profile_vault_path": profile.profile_vault_path,
        "in_memory_mutations_history": [
            {
                "ts": m.ts,
                "action": m.action,
                "target": m.target,
                "by": m.by,
                "session_id": m.session_id,
            }
            for m in profile.in_memory_mutations_history
        ],
    }
    result: str = yaml.safe_dump(payload, sort_keys=False)
    return result


__all__ = [
    "AdminCommand",
    "AdminCommandDispatcher",
    "AdminCommandError",
    "AdminVerb",
    "parse_admin_command",
]
