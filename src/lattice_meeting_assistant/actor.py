"""Per-thread ``ChatThreadActor`` -- spec §7 concurrency Layer 2.

One actor instance is spawned per ``(meeting_id, persona_id)`` private
DM thread, or per ``(meeting_id, "public")`` public-mention thread.
Each actor owns a single worker task that drains a bounded FIFO queue
and dispatches messages to cortex serially. Multiple actors run in
parallel; serialization is per-thread, not per-meeting.

Spec §7 references (Design Spec lines 828-999):

* Three-layer concurrency diagram (lines 832-854).
* ``ChatThreadActor`` internals + pseudocode (lines 856-932).
* Holding-message logic (lines 934-954) -- lands in W4.2.
* Backpressure semantics (lines 956-975) -- ``Assistant`` side lands
  in Part B / W4.6; actor-side ``enqueue`` returns ``False`` here.
* Lifecycle table (lines 977-987) -- W4.5 adds idle/drain/shutdown.
* Global semaphore (lines 989-995) -- wired in Part B / W4.6 via the
  ``cortex_call`` closure.

The actor is decoupled from the cortex registry via a
closure-injected ``cortex_call`` callable. W4.6 / Part B substitutes
the real semaphore-acquired closure; W4 unit tests pass a stub.

``session`` is typed as ``object`` (rather than the contracts
``MeetingSession``) for the same reason ``transcript_buffer: object``
is in :mod:`tools.resolver`: keep the actor decoupled from the
contracts shape and assert at the boundary (here: at the moment we
call ``session.send_chat`` / ``session.send_chat_public``). The
production wiring threads a real ``MeetingSession`` through; the
tests pass a ``MagicMock``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any


def _suppress_cancelled_error() -> contextlib.AbstractContextManager[None]:
    """Context manager that swallows :class:`asyncio.CancelledError`.

    Used during cleanup of racing tasks so a cancellation propagating
    out of an awaited sub-task does not mask the original exception.
    """
    return contextlib.suppress(asyncio.CancelledError)


from .config import AssistantConfig
from .exceptions import CortexUnavailable
from .tools.base import CortexTool
from .types import ChatEvent, ConversationTurn

logger = logging.getLogger(__name__)


# Placeholder filler pool. W5 wires the persona profile filler pool per
# Cody Voice Identity protocol; v0.1 uses a tiny in-line dict so the
# actor can degrade gracefully before that lands.
_FILLER_POOL: dict[str, str] = {
    "one_moment": "one moment",
    "having_trouble_thinking_right_now": "having trouble thinking right now",
}


def _filler(key: str) -> str:
    """Return a stall string from the v0.1 filler pool.

    Falls back to the literal key if a caller asks for one that is not
    yet registered -- still safe to send to the user (never raises).
    """
    return _FILLER_POOL.get(key, key.replace("_", " "))


def _event_to_turn(event: ChatEvent) -> ConversationTurn:
    """Translate inbound ``ChatEvent`` to a ``user`` history turn."""
    return ConversationTurn(role="user", content=event.text, ts=event.ts)


def _assistant_turn(text: str) -> ConversationTurn:
    """Build an ``assistant`` history turn from a reply string."""
    return ConversationTurn(
        role="assistant",
        content=text,
        ts=datetime.now(timezone.utc),
    )


class ChatThreadActor:
    """One per ``(meeting_id, persona_id)`` or ``(meeting_id, 'public')``.

    Single worker task drains a bounded FIFO queue and dispatches to
    cortex serially. The ``cortex_call`` closure is the only path the
    actor uses to talk to cortex; Part B's :class:`Assistant` injects
    a semaphore-acquired closure here.

    The second element of :attr:`key` is either a ``CanonicalPersonaId``
    (string) for a private-DM actor or the literal ``"public"`` for
    the per-meeting public-mention singleton. Typed as ``str`` to keep
    the actor decoupled from the canonical-id validator that lives in
    ``lattice_meeting.persona``.
    """

    def __init__(
        self,
        *,
        key: tuple[str, str],
        cortex_call: Callable[..., Awaitable[Any]],
        session: object,
        config: AssistantConfig,
        tool_set: list[CortexTool],
        system_prompt_renderer: Callable[[], str],
    ) -> None:
        self.key = key
        self._cortex_call = cortex_call
        self._session = session
        self._config = config
        self._tool_set = tool_set
        self._system_prompt_renderer = system_prompt_renderer

        # Bounded FIFO queue; spec §3 default per_thread_queue_depth=5.
        self._queue: asyncio.Queue[ChatEvent] = asyncio.Queue(maxsize=config.per_thread_queue_depth)
        self._history: list[ConversationTurn] = []
        self._worker: asyncio.Task[None] | None = None
        self._idle_since: float | None = None
        self._stopping = False

    # -----------------------------------------------------------------
    # Public surface
    # -----------------------------------------------------------------

    def start(self) -> None:
        """Spawn the worker task. Idempotent: a second call is a no-op."""
        if self._worker is not None and not self._worker.done():
            return
        self._stopping = False
        self._worker = asyncio.create_task(
            self._worker_loop(), name=f"actor:{self.key[0]}:{self.key[1]}"
        )

    async def enqueue(self, event: ChatEvent) -> bool:
        """Append ``event`` to the FIFO queue.

        Returns ``True`` on success, ``False`` when the queue is full
        (per spec §7 line 883-889 -- caller surfaces a backpressure
        reply on ``False``).
        """
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    @property
    def queue_depth(self) -> int:
        """Current number of pending events in the FIFO queue.

        Read-only observability hook for the :class:`Assistant`
        backpressure reply path (W4.6 / Part B) and for tests.
        """
        return self._queue.qsize()

    @property
    def is_queue_full(self) -> bool:
        """Predicate companion to :attr:`queue_depth`.

        ``True`` iff a further :meth:`enqueue` call would return
        ``False``. Cheap, side-effect-free; safe to call from the
        Assistant's ``on_private_chat`` hot path.
        """
        return self._queue.full()

    def history_snapshot(self) -> list[ConversationTurn]:
        """Return a shallow copy of the in-memory conversation history.

        For tests + observability. Production callers should not mutate
        the returned list.
        """
        return list(self._history)

    async def wait_idle(self, *, timeout: float = 5.0) -> None:
        """Wait until the queue is empty AND no event is mid-dispatch.

        Test-only convenience. Production code uses :meth:`drain` for
        shutdown semantics.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            if self._queue.empty() and self._idle_since is not None:
                return
            if asyncio.get_event_loop().time() >= deadline:
                raise asyncio.TimeoutError(f"actor {self.key} did not idle within {timeout}s")
            await asyncio.sleep(0.005)

    async def shutdown(self) -> None:
        """Cancel the worker task and wait for it to settle."""
        self._stopping = True
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except (asyncio.CancelledError, Exception):  # pragma: no cover
            pass
        self._worker = None

    # -----------------------------------------------------------------
    # Worker internals
    # -----------------------------------------------------------------

    async def _worker_loop(self) -> None:
        """Drain queue → dispatch → reply, forever (until cancelled).

        Mirrors spec §7 pseudocode (lines 891-914). W4.2 swaps the
        bare ``_dispatch`` call for ``_dispatch_with_holding_message``.
        """
        while True:
            self._idle_since = asyncio.get_event_loop().time()
            event = await self._queue.get()
            self._idle_since = None
            try:
                reply = await self._dispatch_with_holding_message(event)
                await self._send_reply(event, reply)
            except CortexUnavailable:
                fallback = _filler("having_trouble_thinking_right_now")
                await self._send_reply(event, fallback)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("actor %s dispatch error", self.key)
                # Never expose a stack trace to the user; send a
                # generic graceful fallback.
                fallback = _filler("having_trouble_thinking_right_now")
                try:
                    await self._send_reply(event, fallback)
                except Exception:  # pragma: no cover
                    logger.exception("actor %s fallback send failed", self.key)

    async def _send_reply(self, event: ChatEvent, text: str) -> None:
        """Route ``text`` via the session's separated send paths.

        Public-mention actors broadcast via ``send_chat_public``;
        private-DM actors use ``send_chat(to_user_id=..., message=...)``
        per Architectural Invariant 1.
        """
        if self.key[1] == "public":
            await self._session.send_chat_public(text)  # type: ignore[attr-defined]
        else:
            await self._session.send_chat(  # type: ignore[attr-defined]
                to_user_id=event.sender_user_id,
                message=text,
            )

    async def _dispatch_with_holding_message(self, event: ChatEvent) -> str:
        """Race the dispatch task against the holding-message threshold.

        Spec §7 lines 934-954: if cortex does not return within
        ``config.holding_message_after_ms``, send a filler stall
        message to the user AND continue awaiting the real reply.

        Implementation detail: ``asyncio.wait_for`` cancels the wrapped
        task on timeout, so we cannot use it directly. Instead we
        spawn ``_dispatch`` as a free-standing task and race it against
        an ``asyncio.sleep`` timer via ``asyncio.wait``. On timeout we
        send the filler and keep awaiting the dispatch task.
        """
        dispatch_task = asyncio.create_task(self._dispatch(event))
        threshold_s = self._config.holding_message_after_ms / 1000.0
        timer_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(threshold_s))
        try:
            done, _pending = await asyncio.wait(
                {dispatch_task, timer_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if dispatch_task in done:
                # Cortex returned before threshold -- cancel timer,
                # return its result directly.
                timer_task.cancel()
                with _suppress_cancelled_error():
                    await timer_task
                return dispatch_task.result()
            # Timer fired first -- send the filler, then await the
            # real reply.
            await self._send_filler(event, _filler("one_moment"))
            return await dispatch_task
        except BaseException:
            # Defensive cleanup: if the worker is cancelled mid-race
            # we MUST cancel the dispatch task so it does not leak.
            if not dispatch_task.done():
                dispatch_task.cancel()
                with _suppress_cancelled_error():
                    await dispatch_task
            if not timer_task.done():
                timer_task.cancel()
                with _suppress_cancelled_error():
                    await timer_task
            raise

    async def _send_filler(self, event: ChatEvent, text: str) -> None:
        """Send a stall string via the same routed path as a real reply.

        Separate from :meth:`_send_reply` because callers must not
        record the filler in history -- it is a UX nudge, not a turn.
        """
        if self.key[1] == "public":
            await self._session.send_chat_public(text)  # type: ignore[attr-defined]
        else:
            await self._session.send_chat(  # type: ignore[attr-defined]
                to_user_id=event.sender_user_id,
                message=text,
            )

    async def _dispatch(self, event: ChatEvent) -> str:
        """Call cortex with current history + this event; update history.

        Mirrors spec §7 pseudocode (lines 916-931). History compaction
        (W4.4) hooks here; W4.1 ships the bare round-trip.
        """
        user_turn = _event_to_turn(event)
        result = await self._cortex_call(
            consumer="lattice-meeting-assistant",
            task=event.tier or self._config.default_tier,
            cache_namespace=self.key,
            system_prompt=self._system_prompt_renderer(),
            conversation=self._history + [user_turn],
            tools=self._tool_set,
        )
        text = str(result.text)
        self._history.append(user_turn)
        self._history.append(_assistant_turn(text))
        return text


__all__ = ["ChatThreadActor"]
