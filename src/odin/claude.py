"""Claude API client functions for the profile pipeline."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from anthropic import (
    APIConnectionError,
    AsyncAnthropic,
    InternalServerError,
    RateLimitError,
)
from anthropic.types import Message
from loguru import logger

from odin.config import settings
from odin.models import (
    Assessment,
    Category,
    Caveat,
    Citation,
    Profile,
    ProfileHighlight,
    TimelineEntry,
)
from odin.search import SearchResult

# Transient, retryable SDK errors: rate limits, 5xx, and connection/timeout
# issues (APITimeoutError subclasses APIConnectionError). Anything else (bad
# requests, auth, missing tool blocks) is a permanent failure — retrying it
# would just waste the bound.
_RETRYABLE_EXCEPTIONS = (RateLimitError, InternalServerError, APIConnectionError)
_RETRY_BASE_DELAY_SECONDS = 1.0


async def _create_with_retries(stage: str, request: Callable[[], Awaitable[Message]]) -> Message:
    """Run a Claude request, retrying transient errors with exponential backoff.

    Bounded by settings.claude_max_retries; backoff doubles each attempt
    starting at _RETRY_BASE_DELAY_SECONDS. Each retry and the final exhaustion
    are logged with the stage name so failures are attributable per call site.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await request()
        except _RETRYABLE_EXCEPTIONS as exc:
            if attempt > settings.claude_max_retries:
                logger.error(
                    "claude stage={} exhausted retries attempts={} error={}",
                    stage,
                    attempt,
                    exc,
                )
                raise
            delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "claude retry stage={} attempt={} delay={:.1f}s error={}",
                stage,
                attempt,
                delay,
                exc,
            )
            await asyncio.sleep(delay)


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


@dataclass(frozen=True)
class _AssessOutput:
    public_sentiment: float
    subject_political_bias: float
    source_political_bias: float
    law_chaos: float
    good_evil: float
    caveats: list[Caveat]


@dataclass(frozen=True)
class _ToolCallSpec:
    """The fixed shape of one Claude call.

    Bundles the model, token budget, system prompt, and the single tool
    Claude is forced to use. Each Claude-calling function builds one of these
    as a module-level constant (`_CATEGORIZE_CALL` and its siblings, defined
    alongside the tool schemas below) and hands it to `_call_tool` with that
    call's messages. Bundling the static shape keeps `_call_tool`'s signature
    small, and means the tool's name and the `tool_choice` name — which must
    always match — are derived from one place rather than kept in sync by hand.
    """

    model: str
    max_tokens: int
    system: str | list[dict[str, Any]]
    tool: dict[str, Any]
    error_context: str


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
    "- summary: a 3-5 paragraph article-style overview. Open with who/what/when in the lede;\n"
    "  use the body paragraphs to expand on significance, context, and complications. Separate\n"
    "  paragraphs with a blank line (\\n\\n).\n"
    "- 3-5 highlights (notable achievements, positive aspects, key facts). Each highlight has\n"
    "  three fields:\n"
    "    title       — short headline tag, e.g. 'Algorithm A (1843)'.\n"
    "    description — one-line summary phrase shown at rest in the UI.\n"
    "    detail      — 2-4 sentences explaining context, significance, or evidence; this is\n"
    "                  revealed when the user clicks the row.\n"
    "- 0-3 lowlights (controversies, failures, criticisms — only if well-documented), with the\n"
    "  same three fields as highlights.\n"
    "- A chronological timeline of 4-6 truly significant events. Prefer fewer, weightier\n"
    "  entries over an exhaustive chronology.\n"
    "- citations: the URLs of source pages whose content materially informed the profile.\n"
    "  Only list URLs you actually drew from; skip sources you ignored.\n"
    "Be factual and cite specific details from the provided content.\n"
    "Respond using the create_profile tool."
)

_ASSESS_SYSTEM = (
    "You are an analyst auditing a freshly synthesized profile and the source pages it drew from.\n"
    "Score the following on the listed scales, then list short caveats:\n"
    "- public_sentiment (-1..+1): aggregate public sentiment toward the subject (-1 negative,\n"
    "  +1 positive, 0 neutral or mixed).\n"
    "- subject_political_bias (-1..+1): the subject's own political lean (-1 left, +1 right,\n"
    "  0 centrist or apolitical).\n"
    "- source_political_bias (-1..+1): aggregate political lean of the cited sources as a set.\n"
    "- law_chaos (-1..+1): D&D alignment axis (-1 lawful, +1 chaotic).\n"
    "- good_evil (-1..+1): D&D alignment axis (-1 evil, +1 good).\n"
    "- caveats: 1-4 specific limitations or biases that apply to THIS page's data. Each\n"
    "  caveat has two fields:\n"
    "    brief  — one-line headline phrase, e.g. 'Sources skew Anglo-American.'\n"
    "    detail — 1-2 sentences of supporting explanation, revealed on click.\n"
    "  Avoid generic disclaimers. If you cannot find anything noteworthy, return one item\n"
    "  with a brief like 'No significant audit findings.' and a short detail explaining why.\n"
    "Respond using the assess_profile tool."
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
                        "detail": {"type": "string"},
                    },
                    "required": ["title", "description", "detail"],
                },
            },
            "lowlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["title", "description", "detail"],
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


_ASSESS_TOOL: dict[str, Any] = {
    "name": "assess_profile",
    "description": ("Score the profile and source set on sentiment, bias, and alignment."),
    "input_schema": {
        "type": "object",
        "properties": {
            "public_sentiment": {"type": "number", "minimum": -1, "maximum": 1},
            "subject_political_bias": {"type": "number", "minimum": -1, "maximum": 1},
            "source_political_bias": {"type": "number", "minimum": -1, "maximum": 1},
            "law_chaos": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
                "description": "D&D law-chaos axis: -1 lawful, +1 chaotic.",
            },
            "good_evil": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
                "description": "D&D good-evil axis: -1 evil, +1 good.",
            },
            "caveats": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "brief": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["brief", "detail"],
                },
                "minItems": 1,
                "maxItems": 4,
            },
        },
        "required": [
            "public_sentiment",
            "subject_political_bias",
            "source_political_bias",
            "law_chaos",
            "good_evil",
            "caveats",
        ],
    },
}


def _cached_system(text: str) -> list[dict[str, Any]]:
    """Wrap a system prompt for prompt-caching, as the longer prompts below need."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


# Each constant below pairs one system prompt and tool schema (above) with its
# model, token budget, and error context — the complete, fixed shape of one
# Claude call. `_call_tool` takes one of these plus that call's messages.
_CATEGORIZE_CALL = _ToolCallSpec(
    model=_HAIKU,
    max_tokens=100,
    system=_CATEGORIZE_SYSTEM,
    tool=_CATEGORIZE_TOOL,
    error_context="categorize",
)
_GENERATE_QUERIES_CALL = _ToolCallSpec(
    model=_HAIKU,
    max_tokens=300,
    system=_GENERATE_QUERIES_SYSTEM,
    tool=_GENERATE_QUERIES_TOOL,
    error_context="generate_queries",
)
_SELECT_URLS_CALL = _ToolCallSpec(
    model=_HAIKU,
    max_tokens=300,
    system=_cached_system(_SELECT_URLS_SYSTEM),
    tool=_SELECT_URLS_TOOL,
    error_context="select_urls",
)
_SYNTHESIZE_CALL = _ToolCallSpec(
    model=_SONNET,
    max_tokens=4096,
    system=_cached_system(_SYNTHESIZE_SYSTEM),
    tool=_CREATE_PROFILE_TOOL,
    error_context="synthesize",
)
_ASSESS_CALL = _ToolCallSpec(
    model=_SONNET,
    max_tokens=1024,
    system=_cached_system(_ASSESS_SYSTEM),
    tool=_ASSESS_TOOL,
    error_context="assess",
)


def _make_citation_lookup(
    sources: list[SearchResult], content: dict[str, str]
) -> dict[str, SearchResult]:
    """Map citation URLs to SearchResults, covering trailing-slash variants.

    Claude cites the URL it sees as the content section header, which comes from
    `content.keys()`.  Those keys may differ from `sources` URLs by a trailing
    slash if `select_urls` normalised the URL slightly.  Index by both forms so
    either resolves to the same SearchResult.
    """
    exact: dict[str, SearchResult] = {s.url: s for s in sources}
    lookup: dict[str, SearchResult] = dict(exact)
    for content_url in content:
        if content_url in lookup:
            continue
        normalized = content_url.rstrip("/")
        for src in sources:
            if src.url.rstrip("/") == normalized:
                lookup[content_url] = src
                break
    return lookup


def _find_tool_block(content: list[Any], name: str) -> Any | None:  # noqa: ANN401
    return next(
        (b for b in content if getattr(b, "type", None) == "tool_use" and b.name == name),
        None,
    )


async def _call_tool(
    client: AsyncAnthropic, spec: _ToolCallSpec, *, messages: list[dict[str, Any]]
) -> Any:  # noqa: ANN401
    """Run one forced-tool Claude call and return the matching block's input.

    Every Claude call in this module shares this shape: pick one tool, force
    Claude to use it, then unpack the resulting `tool_use` block. Centralizing
    it here means "Claude answered without using the tool" — the one failure
    mode every caller has to handle — lives in one place instead of five, and
    is the natural seam for retry-on-transient-error logic later.

    Raises RuntimeError naming both the caller (`spec.error_context`) and the
    expected tool if no matching `tool_use` block comes back.
    """
    tool_name = spec.tool["name"]
    response = await client.messages.create(
        model=spec.model,
        max_tokens=spec.max_tokens,
        system=spec.system,  # type: ignore[arg-type]
        tools=[spec.tool],  # type: ignore[arg-type]
        tool_choice={"type": "tool", "name": tool_name},  # type: ignore[arg-type]
        messages=messages,  # type: ignore[arg-type]
    )
    block = _find_tool_block(list(response.content), tool_name)
    if block is None:
        msg = f"{spec.error_context}: no {tool_name} tool block in response"
        raise RuntimeError(msg)
    return block.input


async def categorize(client: AsyncAnthropic, query: str) -> Category:
    """Classify the query as person, place, event, or other."""
    logger.debug("categorize query={!r}", query)
    response = await _create_with_retries(
        "categorize",
        lambda: _call_tool(
            client,
            _CATEGORIZE_CALL,
            messages=[{"role": "user", "content": f"Categorize this search term: {query}"}],
        ),
    )
    return _CategorizeOutput(**response).category  # type:ignore[reportCallIssue]


async def generate_queries(client: AsyncAnthropic, query: str, category: Category) -> list[str]:
    """Generate 3-5 targeted search queries for the given subject."""
    logger.debug("generate_queries query={!r} category={}", query, category)
    response = await _create_with_retries(
        "generate_queries",
        lambda: _call_tool(
            client,
            _GENERATE_QUERIES_CALL,
            messages=[{"role": "user", "content": f"Subject: {query}\nCategory: {category}"}],
        ),
    )
    return _GenerateQueriesOutput(**response).queries  # type:ignore[reportCallIssue]


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
    response = await _create_with_retries(
        "select_urls",
        lambda: _call_tool(
            client,
            _SELECT_URLS_CALL,
            messages=[
                {"role": "user", "content": f"Subject: {query}\n\nSearch results:\n{formatted}"}
            ],
        ),
    )
    return _SelectUrlsOutput(**response).urls  # type:ignore[reportCallIssue]


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
    response = await _create_with_retries(
        "synthesize",
        lambda: _call_tool(
            client,
            _SYNTHESIZE_CALL,
            messages=[{"role": "user", "content": user_message}],
        ),
    )
    parsed = _SynthesizeOutput(**response)  # type:ignore[reportCallIssue]
    lookup = _make_citation_lookup(sources, content)
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


def _format_profile_for_assess(profile: Profile) -> str:
    lines = [
        f"Name: {profile.name}",
        f"Category: {profile.category}",
        f"Summary: {profile.summary}",
    ]
    if profile.highlights:
        lines.append("Highlights:")
        lines.extend(f"  - {entry.title}: {entry.description}" for entry in profile.highlights)
    if profile.lowlights:
        lines.append("Lowlights:")
        lines.extend(f"  - {entry.title}: {entry.description}" for entry in profile.lowlights)
    if profile.timeline:
        lines.append("Timeline:")
        lines.extend(f"  - {entry.date}: {entry.event}" for entry in profile.timeline)
    return "\n".join(lines)


async def assess(
    client: AsyncAnthropic,
    query: str,
    profile: Profile,
    content: dict[str, str],
) -> Assessment:
    """Score the profile and source set on sentiment, bias, and alignment."""
    logger.debug("assess query={!r} sources={}", query, len(content))
    profile_block = _format_profile_for_assess(profile)
    sections = "\n\n".join(f"--- {url} ---\n{text}" for url, text in content.items())
    user_message = f"Subject: {query}\n\nProfile:\n{profile_block}\n\nSource content:\n{sections}"
    response = await _create_with_retries(
        "assess",
        lambda: _call_tool(
            client,
            _ASSESS_CALL,
            messages=[{"role": "user", "content": user_message}],
        ),
    )
    parsed = _AssessOutput(**response)  # type:ignore[reportCallIssue]
    return Assessment(
        public_sentiment=parsed.public_sentiment,
        subject_political_bias=parsed.subject_political_bias,
        source_political_bias=parsed.source_political_bias,
        law_chaos=parsed.law_chaos,
        good_evil=parsed.good_evil,
        caveats=parsed.caveats,
    )
