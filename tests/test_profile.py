"""Tests for the profile pipeline orchestrator."""

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from odin import pipeline as pipeline_module

_SEARXNG_BASE = "http://searxng:8080"
_SEARXNG_RESULTS = {
    "results": [
        {
            "url": "https://en.wikipedia.org/wiki/Marie_Curie",
            "title": "Marie Curie",
            "content": "...",
        },
        {"url": "https://nobelprize.org/curie", "title": "Nobel Prize - Curie", "content": "..."},
    ]
}
_PROFILE_INPUT: Mapping[str, object] = {
    "name": "Marie Curie",
    "category": "person",
    "summary": "A pioneering physicist and chemist.",
    "highlights": [{"title": "Nobel Prize", "description": "Won twice."}],
    "lowlights": [],
    "timeline": [{"date": "1903", "event": "First Nobel Prize in Physics"}],
}


def _tool_block(name: str, input_data: Mapping[str, object]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = "tool_abc123"
    block.name = name
    block.input = input_data
    return block


def _api_response(content: list[MagicMock], stop_reason: str = "end_turn") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    return resp


@pytest.fixture
def mock_client() -> MagicMock:
    """Return a mock AsyncAnthropic client with an async messages.create."""
    client = MagicMock()
    client.messages.create = AsyncMock()
    return client


def _standard_side_effects(queries: list[str]) -> list[MagicMock]:
    """Return the messages.create side_effect sequence for a full pipeline run."""
    return [
        _api_response([_tool_block("categorize_result", {"category": "person"})]),
        _api_response([_tool_block("generate_queries_result", {"queries": queries})]),
        _api_response(
            [
                _tool_block(
                    "select_urls_result", {"urls": ["https://en.wikipedia.org/wiki/Marie_Curie"]}
                )
            ]
        ),
        _api_response([_tool_block("create_profile", _PROFILE_INPUT)]),
    ]


@pytest.mark.asyncio
async def test_build_profile_yields_stages(mock_client: MagicMock) -> None:
    """build_profile() emits an event for each pipeline stage."""
    mock_client.messages.create.side_effect = _standard_side_effects(["q1", "q2"])

    with respx.mock:
        respx.get(f"{_SEARXNG_BASE}/search").mock(
            return_value=httpx.Response(200, json=_SEARXNG_RESULTS)
        )
        events = [
            e
            async for e in pipeline_module.build_profile("Marie Curie", _SEARXNG_BASE, mock_client)
        ]

    stages = [e.stage for e in events]
    assert "categorized" in stages
    assert "queries" in stages
    assert "searching" in stages
    assert "profile" in stages
    mock_client.messages.create.assert_called()


@pytest.mark.asyncio
async def test_build_profile_runs_parallel_searches(mock_client: MagicMock) -> None:
    """build_profile() calls SearXNG once per generated query."""
    queries = ["q1", "q2", "q3"]
    mock_client.messages.create.side_effect = _standard_side_effects(queries)

    with respx.mock:
        search_route = respx.get(f"{_SEARXNG_BASE}/search").mock(
            return_value=httpx.Response(200, json=_SEARXNG_RESULTS)
        )
        _ = [
            e
            async for e in pipeline_module.build_profile("Marie Curie", _SEARXNG_BASE, mock_client)
        ]

    assert search_route.call_count == len(queries)
