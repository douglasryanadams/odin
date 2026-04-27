"""Claude API client functions for the profile pipeline."""

from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from loguru import logger

from odin.models import Category, Citation, Profile, ProfileHighlight, TimelineEntry
from odin.searxng import SearchResult


@dataclass(frozen=True)
class _CategorizeOutput:
    category: Category


@dataclass(frozen=True)
class _GenerateQueriesOutput:
    queries: list[str]


@dataclass(frozen=True)
class _SelectUrlsOutput:
    urls: list[str]


@dataclass(frozen=True)
class _SynthesizeOutput:
    name: str
    category: Category
    summary: str
    highlights: list[ProfileHighlight]
    lowlights: list[ProfileHighlight]
    timeline: list[TimelineEntry]
    citations: list[str]


_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"

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
    "Given search results with URL, title, snippet, and source engines, select up to 5 URLs.\n"
    "URLs found by multiple sources are more likely to be authoritative.\n"
    "Prefer: official sources, encyclopedias, major news outlets.\n"
    "Avoid: duplicate domains, paywalled sites, low-quality sources.\n\n"
    "Respond using the select_urls_result tool."
)

_SYNTHESIZE_SYSTEM = (
    "You are a research analyst building structured profiles from web content.\n"
    "Given a subject and pre-fetched content from multiple sources, create a structured profile.\n"
    "The profile must include:\n"
    "- A concise 2-3 sentence summary\n"
    "- 3-5 highlights (notable achievements, positive aspects, key facts)\n"
    "- 0-3 lowlights (controversies, failures, criticisms — only if well-documented)\n"
    "- A chronological timeline of key events\n"
    "- citations: the URLs of source pages whose content materially informed the profile.\n"
    "  Only list URLs you actually drew from; skip sources you ignored.\n"
    "Be factual and cite specific details from the provided content.\n"
    "Respond using the create_profile tool."
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
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "URLs of source pages whose content materially informed this profile."
                ),
            },
        },
        "required": [
            "name",
            "category",
            "summary",
            "highlights",
            "lowlights",
            "timeline",
            "citations",
        ],
    },
}


def _find_tool_block(content: list[Any], name: str) -> Any | None:  # noqa: ANN401
    return next(
        (b for b in content if getattr(b, "type", None) == "tool_use" and b.name == name),
        None,
    )


async def categorize(client: AsyncAnthropic, query: str) -> Category:
    """Classify the query as person, place, event, or other."""
    logger.debug("categorize query={!r}", query)
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
    return _CategorizeOutput(**block.input).category


async def generate_queries(client: AsyncAnthropic, query: str, category: Category) -> list[str]:
    """Generate 3-5 targeted search queries for the given subject."""
    logger.debug("generate_queries query={!r} category={}", query, category)
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
    return _GenerateQueriesOutput(**block.input).queries


def _format_result(r: SearchResult) -> str:
    lines = [f"- URL: {r.url}", f"  Title: {r.title}"]
    if r.engines:
        lines.append(f"  Found by: {', '.join(r.engines)}")
    lines.append(f"  Snippet: {r.content[:200]}")
    return "\n".join(lines)


async def select_urls(
    client: AsyncAnthropic,
    query: str,
    results: list[SearchResult],
) -> list[str]:
    """Select the most relevant URLs from search results."""
    logger.debug("select_urls query={!r} candidates={}", query, len(results))
    formatted = "\n".join(_format_result(r) for r in results)
    response = await client.messages.create(
        model=_HAIKU,
        max_tokens=300,
        system=[  # type: ignore[arg-type]
            {
                "type": "text",
                "text": _SELECT_URLS_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_SELECT_URLS_TOOL],  # type: ignore[arg-type]
        tool_choice={"type": "tool", "name": "select_urls_result"},  # type: ignore[arg-type]
        messages=[{"role": "user", "content": f"Subject: {query}\n\nSearch results:\n{formatted}"}],
    )
    block = _find_tool_block(list(response.content), "select_urls_result")
    if block is None:
        msg = "select_urls: no tool_use block in response"
        raise RuntimeError(msg)
    return _SelectUrlsOutput(**block.input).urls


async def synthesize(
    client: AsyncAnthropic,
    query: str,
    category: Category,
    content: dict[str, str],
    sources: list[SearchResult],
) -> Profile:
    """Synthesize a structured profile from pre-fetched page content."""
    logger.debug("synthesize query={!r} category={} sources={}", query, category, len(content))
    sections = "\n\n".join(f"--- {url} ---\n{text}" for url, text in content.items())
    user_message = f"Build a {category} profile for: {query}\n\nSource content:\n{sections}"
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
        tools=[_CREATE_PROFILE_TOOL],  # type: ignore[arg-type]
        tool_choice={"type": "tool", "name": "create_profile"},  # type: ignore[arg-type]
        messages=[{"role": "user", "content": user_message}],  # type: ignore[arg-type]
    )
    block = _find_tool_block(list(response.content), "create_profile")
    if block is None:
        msg = "synthesize: no create_profile tool block in response"
        raise RuntimeError(msg)
    parsed = _SynthesizeOutput(**block.input)
    lookup = {s.url: s for s in sources}
    citations = [
        Citation(url=lookup[u].url, title=lookup[u].title, snippet=lookup[u].content)
        for u in parsed.citations
        if u in lookup
    ]
    return Profile(
        name=parsed.name,
        category=parsed.category,
        summary=parsed.summary,
        highlights=parsed.highlights,
        lowlights=parsed.lowlights,
        timeline=parsed.timeline,
        citations=citations,
    )
