"""Consumer-side Protocol definitions for downstream meeting subscribers.

This module defines the boundary contracts that downstream Lattice
libraries (``lattice-meeting-wrapup``, future analytics consumers, etc.)
will implement when they subscribe to meeting transcript/event streams.

The Assistant filters chat events at ingest time (``on_private_chat`` /
``on_public_mention``) BEFORE any registered consumer is invoked --
private DM text MUST NEVER reach implementations of these Protocols.

Architectural Invariant 1 (Separated Send Paths) covers the send side
(``session.send_chat`` vs ``session.send_chat_public``); these consumer
Protocols cover the SUBSCRIBE side of the boundary -- i.e. what a wrap-up
library or analytics consumer would receive as the "meeting source
corpus" stream.

Spec §5 line 710 (T3) names "wrap-up source corpus" as the canonical
target. The Protocol shape below is the consumer-side contract that
``lattice-meeting-wrapup`` v0.1 will implement when its primitive lands.

v0.1 design rationale: defining the Protocol here (consumer-of-the-
boundary) rather than waiting for ``lattice-meeting-wrapup`` to publish
its contract is deliberate -- the boundary lives on the Assistant side
(it is what the Assistant promises NOT to push private DM text into).
Even with zero implementations on disk today, the assertion that the
Assistant has no code path feeding any registered consumer is a strong
defensive guarantee against future regressions.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from lattice_meeting_contracts import TranscriptSegment


@runtime_checkable
class WrapupTranscriptConsumer(Protocol):
    """Consumer-side contract for wrap-up libraries that subscribe to
    meeting transcript events.

    The Assistant filters chat events BEFORE invoking any registered
    consumer; implementations of this Protocol will never receive a
    segment derived from a private DM. Public transcript content (audio-
    derived segments via :class:`~lattice_meeting_contracts.TranscriptBuffer`,
    or ``is_private=False`` chat events) is the only signal that flows
    here.

    The single method signature is minimal by design -- v0.1 wrap-up
    libraries only need to subscribe to the post-filter stream and apply
    their own synthesis pipeline. Higher-fidelity contracts (e.g.
    structured turn-by-turn metadata, speaker-attribution annotations)
    defer to v0.2+ when ``lattice-meeting-wrapup`` publishes its own
    consumer Protocol -- this Protocol acts as the v0.1 placeholder /
    backstop.
    """

    async def on_transcript_event(self, segment: TranscriptSegment) -> None:
        """Receive a single transcript segment.

        The Assistant guarantees: this method is NEVER called with a
        segment whose ``text`` derives from a private DM event. The
        Assistant has no code path that constructs a ``TranscriptSegment``
        from a chat event of any kind; the segments here come only from
        the adapter-owned :class:`~lattice_meeting_contracts.TranscriptBuffer`
        push side.
        """
        ...


__all__ = ["WrapupTranscriptConsumer"]
