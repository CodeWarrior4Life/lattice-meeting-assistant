"""Brain Nexus API client -- httpx wrapper for Brain-backed tools.

The 5 in-meeting curated tools that touch Nexus (search_past_meetings,
search_public_references, web_search) AND all 6 TG-owner Nexus
wrappers (W3.6 -- Sub-D) call this client. Resolver (W3.7 -- Sub-D)
accepts ``brain_mcp: BrainMCPClient | None``; ``None`` disables the
Brain-backed subset (curated set degrades to transcript-only).

Discipline protocols enforced:

* **S19 Nexus API HTTP Client UA Requirement** -- non-curl HTTP clients
  to ``nexus.obsidian-inc.com`` MUST set ``User-Agent: curl/8.7.1`` or
  Cloudflare WAF returns 403. Required for every request from this
  client.

* **S26 Nexus Tickets API Auth Pattern** -- POST endpoints require
  ``Authorization: Bearer <token>``; X-API-Key returns 403 on POST.
  All Brain MCP tool endpoints are POST; we send Bearer.

Status codes propagate via :class:`BrainMCPError` carrying the HTTP
status + body excerpt so the calling tool can decide whether to
surface a graceful-degradation message or pass through. Tools wrap
this error in their dispatcher (``ToolResultPart(is_error=True)``).
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx


class BrainMCPError(RuntimeError):
    """Raised when the Brain Nexus API returns a non-2xx status or
    otherwise fails to fulfil an MCP tool invocation.

    Carries ``status_code`` and ``body_excerpt`` for diagnostics; the
    dispatcher converts to ``ToolResultPart(is_error=True)`` so the
    cortex agent loop can decide whether to retry or back off.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# Required per S19 protocol -- non-curl clients hit CF WAF rule 1010.
_REQUIRED_USER_AGENT: str = "curl/8.7.1"

# Default request timeout (seconds). Async tool calls are bounded by
# the cortex agent loop's ``deadline_s`` too; this is a safety net
# in case the loop forgot to set one.
_DEFAULT_TIMEOUT_S: float = 30.0


class BrainMCPClient:
    """Async httpx client for Brain Nexus MCP tool endpoints.

    Each ``nx_*`` / ``deep_research`` / ``vault_ask`` method maps to a
    Brain endpoint of the form ``{base_url}/api/mcp/{tool_name}``
    (the canonical MCP-over-HTTP shape Brain exposes). Responses are
    JSON dicts the calling tool re-shapes into its own return payload.

    ``_transport`` is a test seam: pass ``httpx.MockTransport`` for
    unit tests; production callers omit it (httpx picks the default).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        _transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_token:
            raise ValueError(
                "BrainMCPClient: api_token must be a non-empty string. "
                "Use ``brain_mcp=None`` in the resolver to disable Brain-backed "
                "tools instead of passing an empty token."
            )
        # Strip any trailing slash so endpoint concatenation is predictable.
        self.base_url: str = base_url.rstrip("/")
        self._headers: dict[str, str] = {
            "User-Agent": _REQUIRED_USER_AGENT,
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._timeout = timeout_s
        self._transport = _transport

    @property
    def default_headers(self) -> Mapping[str, str]:
        """Read-only view of the headers sent on every request."""
        return dict(self._headers)

    async def _post(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/api/mcp/{tool_name}"
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            headers=self._headers,
        ) as client:
            try:
                response = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                raise BrainMCPError(
                    f"Brain MCP {tool_name!r} request failed: {exc}",
                ) from exc

        if response.status_code >= 400:
            body_excerpt = response.text[:256]
            raise BrainMCPError(
                f"Brain MCP {tool_name!r} returned HTTP {response.status_code}: {body_excerpt!r}",
                status_code=response.status_code,
            )

        try:
            json_obj: Any = response.json()
        except ValueError as exc:
            raise BrainMCPError(
                f"Brain MCP {tool_name!r} returned non-JSON body: {exc}",
                status_code=response.status_code,
            ) from exc
        if not isinstance(json_obj, dict):
            raise BrainMCPError(
                f"Brain MCP {tool_name!r} returned non-object JSON: {type(json_obj).__name__}",
                status_code=response.status_code,
            )
        # Cast through Any to satisfy strict mypy.
        result: dict[str, Any] = dict(json_obj)
        return result

    # -----------------------------------------------------------------
    # In-meeting curated tool endpoints (W3.3-W3.5 consume these)
    # -----------------------------------------------------------------

    async def nx_vault_search(
        self,
        *,
        query: str,
        filters: Mapping[str, Any] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search the vault by query + optional structured filters.

        ``SearchPastMeetingsTool`` (W3.3) calls this with
        ``filters={'series_id': <id>}`` when configured to scope by
        series; the in-meeting curated wrapper expects the result list
        to carry meeting-shaped frontmatter fields.
        """
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if filters is not None:
            payload["filters"] = dict(filters)
        return await self._post("nx_vault_search", payload)

    async def nx_references_search(
        self,
        *,
        query: str,
        paths: tuple[str, ...] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search across reference docs (scoped subset of vault).

        ``SearchPublicReferencesTool`` (W3.4) restricts ``paths`` to
        ``profile.knowledge.public_references`` so the in-meeting
        transport never sees a personal-vault path returned.
        """
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if paths is not None:
            payload["paths"] = list(paths)
        return await self._post("nx_references_search", payload)

    async def deep_research(
        self,
        *,
        query: str,
        mode: str = "lightweight",
    ) -> dict[str, Any]:
        """Web/research lookup.

        ``WebSearchTool`` (W3.5) calls this with ``mode='lightweight'``
        per spec §9 OQ3. The full ``deep_research`` is in
        ``BLOCKED_IN_MEETING_TOOLS`` (heavyweight); the lightweight
        wrapper is what the in-meeting transport exposes.
        """
        payload: dict[str, Any] = {"query": query, "mode": mode}
        return await self._post("deep_research", payload)


__all__ = [
    "BrainMCPClient",
    "BrainMCPError",
]
