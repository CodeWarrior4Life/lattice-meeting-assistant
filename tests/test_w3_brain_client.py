"""Tests for ``BrainMCPClient`` -- httpx wrapper for Brain Nexus API.

Per Plan task W3.3 step 2 + S19 Nexus API HTTP Client UA Requirement
protocol: non-curl HTTP clients to nexus.obsidian-inc.com MUST set
``User-Agent: curl/8.7.1`` or Cloudflare WAF returns 403.

Auth header: ``Authorization: Bearer <token>`` per S26 Nexus Tickets
API Auth Pattern protocol.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from lattice_meeting_assistant.brain_client import (
    BrainMCPClient,
    BrainMCPError,
)


def test_brain_client_init_sets_required_headers() -> None:
    """Constructed client carries UA + auth header on its httpx client."""
    client = BrainMCPClient(
        base_url="https://nexus.example.com",
        api_token="tok_abc",
    )
    headers = client.default_headers
    assert headers.get("User-Agent") == "curl/8.7.1"
    assert headers.get("Authorization") == "Bearer tok_abc"


def test_brain_client_init_rejects_empty_token() -> None:
    """Empty token -> ValueError; never silently send unauthenticated."""
    with pytest.raises(ValueError, match="api_token"):
        BrainMCPClient(base_url="https://nexus.example.com", api_token="")


def test_brain_client_init_normalizes_base_url() -> None:
    """Trailing slash on base_url tolerated; client strips it."""
    client = BrainMCPClient(
        base_url="https://nexus.example.com/",
        api_token="tok",
    )
    assert client.base_url == "https://nexus.example.com"


async def test_brain_client_nx_vault_search_posts_to_endpoint() -> None:
    """``nx_vault_search`` POSTs ``{query, ...}`` to the right path."""

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={"results": [{"path": "Meetings/2026-05-01.md", "snippet": "..."}]},
        )

    transport = httpx.MockTransport(handler)
    client = BrainMCPClient(
        base_url="https://nexus.example.com",
        api_token="tok",
        _transport=transport,
    )

    result = await client.nx_vault_search(query="series:abc kickoff")

    assert captured["method"] == "POST"
    assert "nx_vault_search" in captured["url"]
    assert captured["headers"].get("user-agent") == "curl/8.7.1"
    assert captured["headers"].get("authorization") == "Bearer tok"
    assert "kickoff" in captured["body"]
    assert isinstance(result, dict)
    assert len(result["results"]) == 1


async def test_brain_client_handles_403_as_error() -> None:
    """HTTP 403 from Brain raises ``BrainMCPError`` with status."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    transport = httpx.MockTransport(handler)
    client = BrainMCPClient(
        base_url="https://nexus.example.com",
        api_token="tok",
        _transport=transport,
    )

    with pytest.raises(BrainMCPError, match="403"):
        await client.nx_vault_search(query="anything")


async def test_brain_client_handles_5xx_as_error() -> None:
    """HTTP 5xx from Brain raises ``BrainMCPError``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server fault")

    transport = httpx.MockTransport(handler)
    client = BrainMCPClient(
        base_url="https://nexus.example.com",
        api_token="tok",
        _transport=transport,
    )
    with pytest.raises(BrainMCPError, match="500"):
        await client.nx_vault_search(query="anything")


async def test_brain_client_nx_references_search_endpoint() -> None:
    """``nx_references_search`` uses the references endpoint."""

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(handler)
    client = BrainMCPClient(
        base_url="https://nexus.example.com",
        api_token="tok",
        _transport=transport,
    )
    await client.nx_references_search(query="quantum entanglement")
    assert "nx_references_search" in captured["url"]


async def test_brain_client_deep_research_endpoint() -> None:
    """``deep_research`` POSTs to /api/research with mode param."""

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"summary": "lightweight result"})

    transport = httpx.MockTransport(handler)
    client = BrainMCPClient(
        base_url="https://nexus.example.com",
        api_token="tok",
        _transport=transport,
    )
    await client.deep_research(query="anything", mode="lightweight")
    assert "lightweight" in captured["body"]
