# Claude (Anthropic) API

Odin uses the [Anthropic API](https://platform.claude.com/docs/en/home) for four pipeline stages, all in `src/odin/claude.py`.

## Stages and models

| Stage | Function | Model |
|---|---|---|
| Classify a query (person / place / event / other) | `categorize()` | `claude-haiku-4-5-20251001` |
| Generate 3–5 search queries | `generate_queries()` | `claude-haiku-4-5-20251001` |
| Select up to 5 URLs from search results | `select_urls()` | `claude-haiku-4-5-20251001` |
| Synthesize the structured `Profile` | `synthesize()` | `claude-sonnet-4-6` |

Model IDs are pinned as `_HAIKU` and `_SONNET` constants. Sonnet is reserved for synthesis — long input, structured output, multi-source reasoning.

## Structured output via tool-use

Every call uses tool-use instead of asking for JSON in prose:

1. Define a tool schema (e.g. `_CATEGORIZE_TOOL`).
2. Pass `tools=[<schema>]` and `tool_choice={"type": "tool", "name": <tool_name>}` so the model *must* invoke the named tool.
3. Pull the `tool_use` block from `response.content` with `_find_tool_block(content, name)`.
4. Validate / cast the payload (e.g., `Profile(**block.input)`).

Missing tool block → `RuntimeError`. Errors don't pass silently.

| Function | System prompt | Tool schema | Tool name |
|---|---|---|---|
| `categorize` | `_CATEGORIZE_SYSTEM` | `_CATEGORIZE_TOOL` | `categorize_result` |
| `generate_queries` | `_GENERATE_QUERIES_SYSTEM` | `_GENERATE_QUERIES_TOOL` | `generate_queries_result` |
| `select_urls` | `_SELECT_URLS_SYSTEM` | `_SELECT_URLS_TOOL` | `select_urls_result` |
| `synthesize` | `_SYNTHESIZE_SYSTEM` | `_CREATE_PROFILE_TOOL` | `create_profile` |

## Prompt caching

`select_urls` and `synthesize` pass their system prompt as a structured block with `cache_control: {"type": "ephemeral"}`. The shorter prompts pass system as a plain string and skip caching.

## Auth

`AsyncAnthropic()` reads `ANTHROPIC_API_KEY` from the environment automatically. `docker-compose.yml` declares the variable in `web.environment` (no value), passing through whatever the host has set — typically from `.env`. Tests override `get_anthropic_client` via `app.dependency_overrides`.

## Failure modes handled

- Missing `tool_use` block → `RuntimeError(f"<stage>: no tool_use block in response")`.
- Failed page fetch → `fetch._fetch_one` substitutes `f"Error fetching URL: {exc}"` so synthesis sees a deterministic string instead of propagating `httpx.HTTPError`.
- `trafilatura` returns nothing → fall back to raw `response.text`, capped at `CONTENT_LIMIT = 10_000` chars.

## Upstream docs

<https://platform.claude.com/docs/en/home> — model IDs, the `messages` API, tool-use, prompt caching, pricing.
