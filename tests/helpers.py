"""Shared test helper factories for building mock Anthropic API responses."""

import json
import re
from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

_JSON_LD_PATTERN = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)


def json_ld_blocks(body: str) -> list[dict[str, Any]]:
    """Extract every JSON-LD <script> block from a rendered page."""
    return [json.loads(match) for match in _JSON_LD_PATTERN.findall(body)]


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
