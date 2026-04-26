"""Shared test helper factories for building mock Anthropic API responses."""

from collections.abc import Mapping
from unittest.mock import MagicMock


def tool_block(name: str, input_data: Mapping[str, object]) -> MagicMock:
    """Return a mock tool_use content block with the given name and input."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = "tool_abc"
    block.name = name
    block.input = input_data
    return block


def api_response(content: list[MagicMock], stop_reason: str = "end_turn") -> MagicMock:
    """Return a mock Anthropic messages.create response."""
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    return resp
