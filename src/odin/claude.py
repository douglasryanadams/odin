"""Claude API client functions for the profile pipeline."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, get_args

from anthropic import (
    APIConnectionError,
    AsyncAnthropic,
    InternalServerError,
    RateLimitError,
)
from anthropic.types import Message
from loguru import logger
from pydantic import ValidationError

from odin.config import settings
from odin.models import (
    Assessment,
    Category,
    Caveat,
    Citation,
    Connection,
    Location,
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


_CATEGORIES = get_args(Category)


@dataclass(frozen=True)
class _CategorizeOutput:
    """The categorize tool's parsed output.

    This is the one Claude-tool-use result that flows to the frontend with no
    Pydantic model downstream to catch a value outside the schema — it goes
    straight into an SSE event the browser renders verbatim. Validate it here,
    at the boundary, rather than let an off-schema string travel silently.
    """

    category: Category

    def __post_init__(self) -> None:
        if self.category not in _CATEGORIES:
            msg = f"categorize: unexpected category {self.category!r} from Claude"
            raise RuntimeError(msg)


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
    locations: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


@dataclass(frozen=True)
class _AssessOutput:
    public_sentiment: float
    subject_political_bias: float
    source_political_bias: float
    law_chaos: float
    good_evil: float
    caveats: list[Caveat]


@dataclass(frozen=True)
class _IdentifyGapsOutput:
    queries: list[dict[str, str]]


@dataclass(frozen=True)
class _FindConnectionsOutput:
    """Raw connection candidates, before citation resolution drops the ungrounded ones.

    Unlike `_SynthesizeOutput`'s nested lists, `connections` stays untyped
    dicts here — `find_connections` must inspect each candidate's `citations`
    individually to resolve and dedupe them, so there's no single pydantic
    boundary to hand the raw list to wholesale.
    """

    connections: list[dict[str, Any]]


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
    "- locations: 3-15 key places tied to the subject, for a map. Favor more locations\n"
    "  when the subject's life or story touches many places — aim for at least 3-6,\n"
    "  up to 15. Each has:\n"
    "    name      — the place name, e.g. 'Warsaw, Poland'.\n"
    "    latitude, longitude — decimal degrees, at city or landmark granularity. Never a\n"
    "                  street address.\n"
    "    caption   — short context for the pin, e.g. 'Birthplace' or 'Site of the 1986\n"
    "                  disaster'.\n"
    "  For a person: birthplace, places of major accomplishment, where they lived or died.\n"
    "  For a place or event: the geography of what happened, including locations tied to\n"
    "  every major party or side involved (e.g. both combatant nations in a war, not\n"
    "  just one). If the subject is a private individual rather than a public figure,\n"
    "  omit any location that would reveal a private residence — return an empty list if\n"
    "  no location is appropriate to share.\n"
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

_IDENTIFY_GAPS_SYSTEM = (
    "You are a research assistant reviewing a draft profile built from an initial round of\n"
    "research on a search subject. Identify up to 2 real gaps — aspects of the subject that\n"
    "remain unexplored or thinly covered in the draft — and propose one targeted follow-up\n"
    "search query for each gap that would help close it.\n"
    "For each gap, also provide a brief reason phrase (one sentence or less) naming what\n"
    "aspect is missing or thin — for example 'early career not covered' or\n"
    "'post-2010 activity absent from draft'. The reason will be shown to the user to explain\n"
    "why the follow-up search is being run.\n"
    "If the draft already covers the subject comprehensively, return an empty list: do not\n"
    "invent a gap just to have something to report.\n"
    "Respond using the identify_gaps_result tool."
)

_FIND_CONNECTIONS_SYSTEM = (
    "You are a research analyst comparing multiple independently-sourced pages about the same\n"
    "subject against each other — looking for patterns a reader skimming one source at a time\n"
    "would miss. Identify up to 5 genuine connections, each one of:\n"
    "- corroboration: two or more sources independently support the same claim\n"
    "- contradiction: sources disagree on a fact, date, attribution, or interpretation\n"
    "- link: a substantive relationship that only becomes visible when sources are read\n"
    "  together, e.g. a person named in one source turns out to be central to an event\n"
    "  described in another\n"
    "Each connection has four fields:\n"
    "    kind      — corroboration, contradiction, or link\n"
    "    assertion — the connection itself, stated plainly in one or two sentences\n"
    "    detail    — 2-4 sentences: what each source says and how they relate\n"
    "    citations — the URLs of the *at least two distinct* source pages this connection\n"
    "                bridges. A claim resting on a single source is not a cross-source\n"
    "                connection — leave it out.\n"
    "Only report connections you can support with specific content from the provided pages.\n"
    "If you find no genuine cross-source connections, return an empty list — do not invent\n"
    "one just to have something to report.\n"
    "Respond using the find_connections_result tool."
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
            "locations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                        "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                        "caption": {"type": "string"},
                    },
                    "required": ["name", "latitude", "longitude", "caption"],
                },
                "maxItems": 15,
                "description": (
                    "3-15 key places tied to the subject, for a map. Empty if none are "
                    "appropriate to share."
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


_IDENTIFY_GAPS_TOOL: dict[str, Any] = {
    "name": "identify_gaps_result",
    "description": (
        "Report follow-up search queries that would close coverage gaps in a draft profile, "
        "or none if the draft already looks comprehensive."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "reason": {
                            "type": "string",
                            "description": (
                                "Brief phrase naming the gap — what aspect is missing or thin. "
                                "One sentence or less."
                            ),
                        },
                    },
                    "required": ["query", "reason"],
                },
                "maxItems": 2,  # mirrors pipeline.DEEP_MODE_MAX_ROUNDS — the loop's hard cap
                "description": (
                    "0-2 targeted follow-up search queries, one per identified gap. "
                    "Each item pairs a search query with a brief reason explaining what "
                    "aspect of the subject is missing or thinly covered. "
                    "Empty if the draft already covers the subject comprehensively."
                ),
            }
        },
        "required": ["queries"],
    },
}


_FIND_CONNECTIONS_TOOL: dict[str, Any] = {
    "name": "find_connections_result",
    "description": (
        "Report corroborations, contradictions, and links found across multiple sources, "
        "each grounded in the specific source pages it bridges."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "connections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["corroboration", "contradiction", "link"],
                        },
                        "assertion": {"type": "string"},
                        "detail": {"type": "string"},
                        "citations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "description": (
                                "URLs of the at least two distinct source pages this "
                                "connection bridges. A connection grounded in only one "
                                "source is not a cross-source connection."
                            ),
                        },
                    },
                    "required": ["kind", "assertion", "detail", "citations"],
                },
                "maxItems": 5,
                "description": (
                    "0-5 genuine cross-source connections. Empty if none survive scrutiny."
                ),
            }
        },
        "required": ["connections"],
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
_IDENTIFY_GAPS_CALL = _ToolCallSpec(
    model=_HAIKU,
    max_tokens=400,
    system=_IDENTIFY_GAPS_SYSTEM,
    tool=_IDENTIFY_GAPS_TOOL,
    error_context="identify_gaps",
)
_FIND_CONNECTIONS_CALL = _ToolCallSpec(
    model=_SONNET,
    max_tokens=2048,
    system=_cached_system(_FIND_CONNECTIONS_SYSTEM),
    tool=_FIND_CONNECTIONS_TOOL,
    error_context="find_connections",
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
        locations=_parse_locations(parsed.locations),
    )


def _parse_locations(raw_locations: list[dict[str, Any]]) -> list[Location]:
    """Validate each candidate location, dropping any with out-of-range or missing fields.

    A single malformed location (e.g. Claude emitting a latitude outside
    -90..90) shouldn't sink the whole profile — drop it the same way a
    citation that doesn't resolve gets dropped, rather than letting a
    pydantic ValidationError propagate out of synthesize.
    """
    locations: list[Location] = []
    for raw in raw_locations:
        try:
            locations.append(Location(**raw))
        except ValidationError as exc:
            logger.debug("dropping invalid location {!r}: {}", raw, exc)
    return locations


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


async def identify_gaps(
    client: AsyncAnthropic,
    query: str,
    category: Category,
    profile: Profile,
) -> list[tuple[str, str]]:
    """Propose up to 2 follow-up queries that would close gaps in a draft profile.

    Feeds Claude the same formatted draft `assess` reads — a structured,
    cheap-to-send signal that's far more focused for gap-spotting than raw
    page content would be. An empty result means the draft already looks
    comprehensive; the deep pipeline's round loop relies on that to stop.
    """
    logger.debug("identify_gaps query={!r} category={}", query, category)
    profile_block = _format_profile_for_assess(profile)
    user_message = f"Subject: {query}\nCategory: {category}\n\nDraft profile:\n{profile_block}"
    response = await _create_with_retries(
        "identify_gaps",
        lambda: _call_tool(
            client,
            _IDENTIFY_GAPS_CALL,
            messages=[{"role": "user", "content": user_message}],
        ),
    )
    parsed = _IdentifyGapsOutput(**response)  # type:ignore[reportCallIssue]
    return [(item["query"], item["reason"]) for item in parsed.queries]


def _resolve_connection_citations(
    citation_urls: list[str], lookup: dict[str, SearchResult]
) -> list[Citation]:
    """Resolve a candidate connection's cited URLs to distinct fetched sources.

    Mirrors `_make_citation_lookup`'s trailing-slash handling, then dedupes by
    the resolved source's own URL — citing the same source through two URL
    variants must not look like two distinct sources. Returns fewer than two
    entries when the candidate doesn't actually bridge two distinct sources;
    `find_connections` drops those candidates entirely.
    """
    resolved: dict[str, SearchResult] = {}
    for url in citation_urls:
        source = lookup.get(url)
        if source is not None:
            resolved[source.url] = source
    return [Citation(url=s.url, title=s.title, snippet=s.content) for s in resolved.values()]


_CONNECTION_MIN_DISTINCT_SOURCES = 2


async def find_connections(
    client: AsyncAnthropic,
    query: str,
    category: Category,
    content: dict[str, str],
    sources: list[SearchResult],
) -> list[Connection]:
    """Look for corroboration, contradiction, and links across multiple sources.

    The cross-source connection is the highest fabrication-risk artifact in
    the product — an LLM is good at inventing plausible, false links. So this
    is the one place grounding is enforced per-claim rather than per-profile:
    each candidate's citations are resolved the same way `synthesize` resolves
    whole-profile citations, then any candidate that doesn't bridge at least
    two *distinct* fetched sources is dropped before it ever ships. "A
    connection without its supporting citations does not ship."
    """
    logger.debug(
        "find_connections query={!r} category={} sources={}", query, category, len(content)
    )
    sections = "\n\n".join(f"--- {url} ---\n{text}" for url, text in content.items())
    user_message = f"Subject: {query}\n\nSource content:\n{sections}"
    response = await _create_with_retries(
        "find_connections",
        lambda: _call_tool(
            client,
            _FIND_CONNECTIONS_CALL,
            messages=[{"role": "user", "content": user_message}],
        ),
    )
    parsed = _FindConnectionsOutput(**response)  # type:ignore[reportCallIssue]
    lookup = _make_citation_lookup(sources, content)
    connections: list[Connection] = []
    for raw in parsed.connections:
        citations = _resolve_connection_citations(raw["citations"], lookup)
        if len(citations) < _CONNECTION_MIN_DISTINCT_SOURCES:
            continue
        connections.append(
            Connection(
                kind=raw["kind"],
                assertion=raw["assertion"],
                detail=raw["detail"],
                citations=citations,
            )
        )
    logger.debug("find_connections grounded={}/{}", len(connections), len(parsed.connections))
    return connections
