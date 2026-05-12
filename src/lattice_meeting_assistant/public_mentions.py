"""Public-mention handler -- W6 surface for ``Assistant.on_public_mention``.

Lifts the rate-limit + allowlist + enabled-toggle decision logic out of
:class:`Assistant` into a focused helper so the routing path stays
readable. The handler is **decision-only** -- it returns one of three
verdicts (``allow`` / ``deny_rate_limit`` / ``deny_allowlist`` /
``deny_disabled``); the Assistant owns the actor spawn + cortex
dispatch.

Spec §3 lines 261-265 + spec §11 R5 (line 1128) -- the rate limit is
the loop-break defense for "Cody reply triggers another participant's
@cody mention". 30s default; bot @-mention detection (don't reply to
other bots) deferred to v0.2 per R5 mitigation entry.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .profile import AssistantProfile

#: Type alias for a monotonic clock function. ``time.monotonic`` is the
#: default; tests inject a controllable fake clock via the ``clock=``
#: parameter on :class:`PublicMentionHandler`.
ClockFn = Callable[[], float]

PublicMentionDecision = Literal[
    "allow",
    "deny_disabled",
    "deny_rate_limit",
    "deny_allowlist",
]


@dataclass(frozen=True)
class PublicMentionVerdict:
    """Result of :meth:`PublicMentionHandler.evaluate`.

    A frozen dataclass rather than a bare enum so we can carry diagnostic
    context (e.g. ``last_reply_at``) for observability without expanding
    the discriminator type.
    """

    decision: PublicMentionDecision
    reason: str
    # When ``decision == "deny_rate_limit"``, the timestamp (loop seconds)
    # of the most recent successful reply for the meeting. ``None`` for
    # any other decision.
    last_reply_at: float | None = None


class PublicMentionHandler:
    """Decide whether a public @-mention should yield a reply.

    Three policy gates, in order:

    1. ``profile.public_mentions_enabled is False`` -> ``deny_disabled``.
    2. ``profile.public_mention_allowlist is not None`` and
       ``event.sender_canonical_id`` NOT in the allowlist ->
       ``deny_allowlist``.
    3. ``now - last_reply_at[meeting_id] < profile.public_mention_rate_limit_per_meeting_s``
       -> ``deny_rate_limit``.

    Otherwise ``allow``.

    Per-meeting rate limit state lives on the handler instance so the
    same handler can serve multiple concurrent meetings in a single
    process -- the rate limit IS per-meeting per the spec (§11 R5
    "30s default").
    """

    def __init__(self, *, profile: AssistantProfile, clock: ClockFn | None = None) -> None:
        """Construct the handler.

        Parameters:

        * ``profile`` -- the active :class:`AssistantProfile`. The
          handler reads ``public_mentions_enabled``,
          ``public_mention_allowlist``, and
          ``public_mention_rate_limit_per_meeting_s`` from this profile.
        * ``clock`` -- optional callable returning a monotonic clock
          reading (seconds). Defaults to :func:`time.monotonic`.
          Tests pass a controllable fake clock to exercise the rate
          limit deterministically without sleeping.
        """
        self._profile = profile
        self._clock: ClockFn = clock if clock is not None else time.monotonic
        # Per-meeting last-reply-at timestamps. Keyed on meeting_id so
        # two meetings hosted by the same Assistant don't share rate
        # state (spec §11 R5 "30s default" is per-meeting).
        self._last_reply_at: dict[str, float] = {}

    @property
    def profile(self) -> AssistantProfile:
        """Read-only view of the bound profile (test affordance)."""
        return self._profile

    def evaluate(
        self,
        *,
        meeting_id: str,
        sender_canonical_id: str | None,
    ) -> PublicMentionVerdict:
        """Evaluate the three gates and return a verdict.

        Stateless apart from the per-meeting rate-limit dict; the
        caller MUST invoke :meth:`record_reply` after a successful
        reply so future evaluations apply the rate-limit window.

        Parameters:

        * ``meeting_id`` -- the meeting where the @-mention occurred.
        * ``sender_canonical_id`` -- resolved canonical persona id of
          the sender, or ``None`` when unresolved. Allowlist check
          treats ``None`` as not-allowlisted when an allowlist is set.

        Returns a :class:`PublicMentionVerdict` describing the decision.
        """
        # Gate 1: enabled toggle.
        if not self._profile.public_mentions_enabled:
            return PublicMentionVerdict(
                decision="deny_disabled",
                reason="profile.public_mentions_enabled=False",
            )

        # Gate 2: allowlist override. ``None`` = anyone-can-mention.
        allowlist = self._profile.public_mention_allowlist
        if allowlist is not None:
            if sender_canonical_id is None or sender_canonical_id not in allowlist:
                return PublicMentionVerdict(
                    decision="deny_allowlist",
                    reason=(
                        f"sender_canonical_id={sender_canonical_id!r} not in "
                        f"public_mention_allowlist (size={len(allowlist)})"
                    ),
                )

        # Gate 3: per-meeting rate limit.
        last = self._last_reply_at.get(meeting_id)
        if last is not None:
            elapsed = self._clock() - last
            window = self._profile.public_mention_rate_limit_per_meeting_s
            if elapsed < window:
                return PublicMentionVerdict(
                    decision="deny_rate_limit",
                    reason=(f"within rate-limit window: elapsed={elapsed:.2f}s < window={window}s"),
                    last_reply_at=last,
                )

        return PublicMentionVerdict(decision="allow", reason="all gates passed")

    def record_reply(self, *, meeting_id: str) -> None:
        """Stamp the moment we successfully replied in ``meeting_id``.

        Must be called AFTER a reply has been queued/sent for the
        per-meeting rate limit to apply to subsequent @-mentions.

        Parameters:

        * ``meeting_id`` -- the meeting whose rate-limit clock to reset.
        """
        self._last_reply_at[meeting_id] = self._clock()

    def last_reply_at(self, *, meeting_id: str) -> float | None:
        """Return the loop-clock reading of the last recorded reply, or
        ``None`` if no reply has been recorded for ``meeting_id``.
        """
        return self._last_reply_at.get(meeting_id)


__all__ = [
    "ClockFn",
    "PublicMentionDecision",
    "PublicMentionHandler",
    "PublicMentionVerdict",
]
