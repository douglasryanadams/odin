"""Claude API client functions for the profile pipeline."""

from typing import Any, cast

import httpx
from anthropic import AsyncAnthropic

from odin.models import Category, Profile
from odin.searxng import SearchResult

_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"
_MAX_AGENTIC_ITERATIONS = 10
_WEB_FETCH_CONTENT_LIMIT = 50_000

_CATEGORIZE_SYSTEM = (
    "You are a search query classifier. Given a search term, determine whether it refers to:\n"
    "- person: a specific individual (living or historical)\n"
    "- place: a geographic location, city, country, or landmark\n"
    "- event: a historical event, occurrence, or phenomenon\n"
    "- other: anything that doesn't fit the above\n\n"
    "Respond using the categorize_result tool."
)

_GENERATE_QUERIES_SYSTEM = (
    "You are a research assistant. Generate 3-5 targeted search queries to gather comprehensive\n"
    "information about the given subject. Tailor queries to its category:\n"
    "- person: biography, achievements, controversies, timeline\n"
    "- place: history, geography, culture, notable facts\n"
    "- event: causes, timeline, participants, aftermath, significance\n"
    "- other: definition, context, history, significance\n\n"
    "Respond using the generate_queries_result tool."
)

_SELECT_URLS_SYSTEM = (
    "You are a research assistant selecting the most informative web pages for a profile.\n"
    "Given search results (URL, title, content snippet), select the 3-5 best URLs.\n"
    "Prefer: official sources, encyclopedias, major news outlets.\n"
    "Avoid: duplicate domains, paywalled sites, low-quality sources.\n\n"
    "Respond using the select_urls_result tool."
)

_SYNTHESIZE_SYSTEM = (
    "You are a research analyst building structured profiles from web content.\n"
    "Given a subject and URLs, fetch each page with web_fetch then create a structured profile.\n"
    "The profile must include:\n"
    "- A concise 2-3 sentence summary\n"
    "- 3-5 highlights (notable achievements, positive aspects, key facts)\n"
    "- 0-3 lowlights (controversies, failures, criticisms — only if well-documented)\n"
    "- A chronological timeline of key events\n"
    "Be factual and cite specific details from the fetched pages.\n"
    "Use create_profile when you have gathered sufficient information."
)

_CATEGORIZE_TOOL: dict[str, Any] = {
    "name": "categorize_result",
    "description": "Report the category of the search subject.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["person", "place", "event", "other"],
            }
        },
        "required": ["category"],
    },
}

_GENERATE_QUERIES_TOOL: dict[str, Any] = {
    "name": "generate_queries_result",
    "description": "Return targeted search queries for the subject.",
    "input_schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5,
            }
        },
        "required": ["queries"],
    },
}

_SELECT_URLS_TOOL: dict[str, Any] = {
    "name": "select_urls_result",
    "description": "Return the selected URLs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5,
            }
        },
        "required": ["urls"],
    },
}

_WEB_FETCH_TOOL: dict[str, Any] = {
    "name": "web_fetch",
    "description": "Fetch the full text content of a web page.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "The URL to fetch."}},
        "required": ["url"],
    },
}

_CREATE_PROFILE_TOOL: dict[str, Any] = {
    "name": "create_profile",
    "description": "Create a structured profile for the search subject.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "category": {"type": "string", "enum": ["person", "place", "event", "other"]},
            "summary": {"type": "string"},
            "highlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "description"],
                },
            },
            "lowlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "description"],
                },
            },
            "timeline": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "event": {"type": "string"},
                    },
                    "required": ["date", "event"],
                },
            },
        },
        "required": ["name", "category", "summary", "highlights", "lowlights", "timeline"],
    },
}


def _find_tool_block(content: list[Any], name: str) -> Any | None:  # noqa: ANN401
    return next(
        (b for b in content if getattr(b, "type", None) == "tool_use" and b.name == name),
        None,
    )


def _all_tool_blocks(content: list[Any]) -> list[Any]:
    return [b for b in content if getattr(b, "type", None) == "tool_use"]


async def categorize(client: AsyncAnthropic, query: str) -> Category:
    """Classify the query as person, place, event, or other."""
    response = await client.messages.create(
        model=_HAIKU,
        max_tokens=100,
        system=_CATEGORIZE_SYSTEM,
        tools=[_CATEGORIZE_TOOL],  # type: ignore[arg-type]
        tool_choice={"type": "tool", "name": "categorize_result"},  # type: ignore[arg-type]
        messages=[{"role": "user", "content": f"Categorize this search term: {query}"}],
    )
    block = _find_tool_block(list(response.content), "categorize_result")
    if block is None:
        msg = "categorize: no tool_use block in response"
        raise RuntimeError(msg)
    return cast("Category", block.input["category"])


async def generate_queries(client: AsyncAnthropic, query: str, category: Category) -> list[str]:
    """Generate 3-5 targeted search queries for the given subject."""
    response = await client.messages.create(
        model=_HAIKU,
        max_tokens=300,
        system=_GENERATE_QUERIES_SYSTEM,
        tools=[_GENERATE_QUERIES_TOOL],  # type: ignore[arg-type]
        tool_choice={"type": "tool", "name": "generate_queries_result"},  # type: ignore[arg-type]
        messages=[{"role": "user", "content": f"Subject: {query}\nCategory: {category}"}],
    )
    block = _find_tool_block(list(response.content), "generate_queries_result")
    if block is None:
        msg = "generate_queries: no tool_use block in response"
        raise RuntimeError(msg)
    return cast("list[str]", block.input["queries"])


async def select_urls(
    client: AsyncAnthropic,
    query: str,
    results: list[SearchResult],
) -> list[str]:
    """Select the most relevant URLs from search results."""
    formatted = "\n".join(
        f"- URL: {r.url}\n  Title: {r.title}\n  Snippet: {r.content[:200]}" for r in results
    )
    response = await client.messages.create(
        model=_HAIKU,
        max_tokens=300,
        system=_SELECT_URLS_SYSTEM,
        tools=[_SELECT_URLS_TOOL],  # type: ignore[arg-type]
        tool_choice={"type": "tool", "name": "select_urls_result"},  # type: ignore[arg-type]
        messages=[{"role": "user", "content": f"Subject: {query}\n\nSearch results:\n{formatted}"}],
    )
    block = _find_tool_block(list(response.content), "select_urls_result")
    if block is None:
        msg = "select_urls: no tool_use block in response"
        raise RuntimeError(msg)
    return cast("list[str]", block.input["urls"])


async def synthesize(
    client: AsyncAnthropic,
    query: str,
    category: Category,
    urls: list[str],
) -> Profile:
    """Fetch URLs and synthesize a structured profile using an agentic loop."""
    url_list = "\n".join(f"- {u}" for u in urls)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Build a {category} profile for: {query}\n\n"
                f"Fetch these URLs to gather information:\n{url_list}"
            ),
        }
    ]

    for _ in range(_MAX_AGENTIC_ITERATIONS):
        response = await client.messages.create(
            model=_SONNET,
            max_tokens=4096,
            system=[  # type: ignore[arg-type]
                {
                    "type": "text",
                    "text": _SYNTHESIZE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_WEB_FETCH_TOOL, _CREATE_PROFILE_TOOL],  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )

        content = list(response.content)

        profile_block = _find_tool_block(content, "create_profile")
        if profile_block is not None:
            return Profile(**profile_block.input)

        tool_blocks = _all_tool_blocks(content)
        if not tool_blocks:
            msg = "synthesize: Claude stopped without creating a profile"
            raise RuntimeError(msg)

        messages.append({"role": "assistant", "content": content})

        tool_results: list[dict[str, Any]] = []
        async with httpx.AsyncClient() as http:
            for block in tool_blocks:
                if block.name == "web_fetch":
                    try:
                        fetched = await http.get(
                            block.input["url"],
                            follow_redirects=True,
                            timeout=10.0,
                        )
                        page_content = fetched.text[:_WEB_FETCH_CONTENT_LIMIT]
                    except httpx.HTTPError as exc:
                        page_content = f"Error fetching URL: {exc}"
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": page_content,
                        }
                    )

        messages.append({"role": "user", "content": tool_results})

    msg = "synthesize: exceeded maximum agentic iterations"
    raise RuntimeError(msg)
