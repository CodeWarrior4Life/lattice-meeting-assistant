"""``CortexTool`` ABC + cortex 0.6.0 adapter helpers.

Every concrete tool (W3.2-W3.5 in-meeting curated + W3.6 TG-owner Nexus
wrappers in Sub-D) subclasses :class:`CortexTool`. The Assistant builds
a per-transport tool registry via :func:`resolve_tool_set`
(in :mod:`.resolver`) and passes the resulting list of
:class:`lattice_cortex.ToolSpec` to
:class:`lattice_cortex.AgentSession.run` along with the
:func:`dispatch_tool_call` handler.

Cortex 0.6.0 tool-use surface (verified against
``G:/My Drive/Projects Merge/lattice-cortex/src/lattice_cortex/``):

* ``ToolSpec(name, description, input_schema, cache_breakpoint=False)``
  -- the static description provider adapters serialize to the
  wire format.
* ``ToolCallPart(call_id, tool_name, arguments)`` -- emitted by the
  model when it invokes a tool.
* ``ToolResultPart(call_id, content, is_error=False)`` -- what the
  ``tool_handler`` returns; flows back as a ``user`` message.
* ``AgentSession.run(..., tools=[...], tool_handler=...)`` -- iterates
  the tool-use loop until the model emits a non-tool-call response.
"""

from __future__ import annotations

import abc
import json
from typing import Mapping

from lattice_cortex import TextPart, ToolCallPart, ToolResultPart, ToolSpec


class CortexTool(abc.ABC):
    """Abstract base for all cortex tools registered by the Assistant.

    Concrete subclasses set the ``name`` + ``description`` class
    attributes, implement the ``input_schema`` property (a JSON-Schema
    fragment that the provider adapter forwards to the LLM), and
    implement the async :meth:`invoke` method that performs the work.

    Per spec §4 "Tool implementation pattern":

    * ``name`` is the cortex tool registration name (stable across
      v0.1; consumers reference by name).
    * ``description`` is the model-facing description the LLM reads
      when deciding whether to invoke the tool.
    * ``input_schema`` is a JSON-Schema-fragment ``dict``; the cortex
      provider adapter (Anthropic / OpenAI / OpenRouter) translates
      it to the wire shape. Pydantic-derived schemas are accepted;
      we don't constrain shape beyond JSON-Schema compatibility.
    * ``invoke(arguments)`` MUST be ``async`` and return a JSON-
      serializable mapping. The runtime (``dispatch_tool_call``)
      serializes the result into a :class:`ToolResultPart`.

    Implementations SHOULD NOT raise on user-facing errors; instead
    return a result mapping with an ``error`` key. The runtime maps
    raised exceptions to ``ToolResultPart(is_error=True)`` so a single
    misbehaving tool does not abort the agent loop.
    """

    #: Cortex tool registration name (subclass MUST override).
    name: str = ""
    #: Model-facing description (subclass MUST override).
    description: str = ""

    @property
    @abc.abstractmethod
    def input_schema(self) -> dict[str, object]:
        """JSON-Schema fragment describing tool arguments.

        Returned object is the ``input_schema`` field of the
        :class:`lattice_cortex.ToolSpec`; provider adapters serialize
        it to the wire format.
        """

    @abc.abstractmethod
    async def invoke(self, arguments: dict[str, object]) -> Mapping[str, object]:
        """Execute the tool. Return a JSON-serializable mapping.

        ``arguments`` is the raw mapping the model passed in its
        :class:`ToolCallPart`. The runtime does NOT pre-validate; tools
        validate as needed and may raise :class:`ValueError` on bad
        input (the dispatcher will wrap it as ``is_error=True``).
        """


def build_tool_spec(tool: CortexTool) -> ToolSpec:
    """Adapter: build a :class:`lattice_cortex.ToolSpec` from a
    :class:`CortexTool` instance.

    Spec §4 "Tool implementation pattern": the Assistant calls this
    for each resolved tool and passes the resulting list of
    :class:`ToolSpec` to :meth:`lattice_cortex.AgentSession.run`.
    """
    return ToolSpec(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
    )


async def dispatch_tool_call(
    call: ToolCallPart,
    registry: Mapping[str, CortexTool],
) -> ToolResultPart:
    """Dispatch a model-emitted :class:`ToolCallPart` against the
    per-transport tool registry.

    Returns a :class:`ToolResultPart` suitable for the cortex
    :class:`AgentSession` tool-use loop. Failure modes:

    * Unknown ``tool_name`` -> ``is_error=True`` with a clear message.
    * Tool raises -> ``is_error=True`` with ``str(exc)`` payload.
    * Tool returns successfully -> ``is_error=False`` with the
      JSON-serialized return value as the lone :class:`TextPart`.

    The cortex :class:`AgentSession` re-feeds these results to the
    model on the next turn; the model then either decides it has
    enough information to respond or invokes more tools.
    """
    tool = registry.get(call.tool_name)
    if tool is None:
        return ToolResultPart(
            call_id=call.call_id,
            is_error=True,
            content=(
                TextPart(text=f"unknown tool: {call.tool_name!r} (not in resolved registry)"),
            ),
        )

    try:
        result = await tool.invoke(dict(call.arguments))
    except Exception as exc:  # noqa: BLE001 -- intentional broad catch
        return ToolResultPart(
            call_id=call.call_id,
            is_error=True,
            content=(TextPart(text=f"{type(exc).__name__}: {exc}"),),
        )

    try:
        payload = json.dumps(dict(result), default=str)
    except (TypeError, ValueError) as exc:
        return ToolResultPart(
            call_id=call.call_id,
            is_error=True,
            content=(TextPart(text=f"tool returned non-serializable payload: {exc}"),),
        )

    return ToolResultPart(
        call_id=call.call_id,
        is_error=False,
        content=(TextPart(text=payload),),
    )


__all__ = ["CortexTool", "build_tool_spec", "dispatch_tool_call"]
