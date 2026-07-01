"""Profile search routes: /profile (HTML) and /profile/stream (SSE)."""

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import asyncpg
from anthropic import AsyncAnthropic, BadRequestError, RateLimitError
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from loguru import logger
from valkey.asyncio import Valkey

from odin import auth, cache, claude, db, fetch, history, pipeline, store
from odin.app import (
    get_anthropic_client,
    get_page_fetcher,
    get_search_aggregator,
    get_valkey_client,
    templates,
)
from odin.config import settings
from odin.identity import Requester
from odin.routes._shared import (
    ANON_COOKIE,
    ANON_COOKIE_MAX_AGE,
    MAX_QUERY_LEN,
    anon_cookie_id,
    csrf_token_value,
    request_ip,
    set_csrf_cookie_if_absent,
    user_email,
)
from odin.search import SearchAggregator

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    q: Annotated[str, Query(max_length=MAX_QUERY_LEN)],
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
    deep: Annotated[bool, Query()] = False,  # noqa: FBT002 — HTTP query param, not a behavior switch
) -> HTMLResponse:
    """Render the profile page; assign anonymous cookie on first visit."""
    user = auth.get_current_user(request)
    cookie_id = anon_cookie_id(request)
    requester = Requester(user_email(user), cookie_id, request_ip(request))
    used = await store.get_daily_count(valkey_client, requester)
    limit = settings.auth_daily_limit if user else settings.anon_daily_limit
    csrf = csrf_token_value(request)
    resp = templates.TemplateResponse(
        request,
        "profile.html",
        {
            "query": q,
            "deep": deep,
            "user": user,
            "used": used,
            "limit": limit,
            "auth_limit": settings.auth_daily_limit,
            "csrf_token": csrf,
        },
    )
    if not request.cookies.get(ANON_COOKIE):
        resp.set_cookie(
            ANON_COOKIE,
            cookie_id,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=ANON_COOKIE_MAX_AGE,
        )
    set_csrf_cookie_if_absent(request, resp, csrf)
    return resp


@router.get("/profile/stream")
async def profile_stream(  # noqa: PLR0913, C901
    request: Request,
    q: Annotated[str, Query(max_length=MAX_QUERY_LEN)],
    searcher: Annotated[SearchAggregator, Depends(get_search_aggregator)],
    anthropic: Annotated[AsyncAnthropic, Depends(get_anthropic_client)],
    fetcher: Annotated[fetch.PageFetcher, Depends(get_page_fetcher)],
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
    db_pool: Annotated[asyncpg.Pool, Depends(db.get_db_pool)],
    deep: Annotated[bool, Query()] = False,  # noqa: FBT002 — HTTP query param, not a behavior switch
) -> StreamingResponse:
    """Stream profile pipeline progress as Server-Sent Events."""
    user = auth.get_current_user(request)
    requester = Requester(
        user_email(user), request.cookies.get(ANON_COOKIE, ""), request_ip(request)
    )

    if await store.is_rate_limited(
        valkey_client,
        requester,
        anon_limit=settings.anon_daily_limit,
        auth_limit=settings.auth_daily_limit,
    ):

        async def _rate_limited() -> AsyncGenerator[str, None]:
            payload = {"type": "rate_limited", "redirect": "/login?reason=limit"}
            yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(_rate_limited(), media_type="text/event-stream")

    mode = "deep" if deep else "fast"

    async def event_generator() -> AsyncGenerator[str, None]:  # noqa: C901, PLR0912
        # Fast path 1: direct profile cache hit (exact or normalized query match).
        cached = await cache.get(valkey_client, q, mode)
        if cached is not None:
            async for chunk in _replay_cached(cached):
                yield chunk
            await _record_cached_query(db_pool, requester, q, _category_from(cached))
            return

        # Fast path 2: alias pointer → profile cache hit (0 LLM calls).
        canonical = await cache.get_canonical(valkey_client, q, mode)
        if canonical is not None:
            cached = await cache.get(valkey_client, canonical, mode)
            if cached is not None:
                async for chunk in _replay_cached(cached):
                    yield chunk
                await _record_cached_query(db_pool, requester, q, _category_from(cached))
                return
            # Alias pointer exists but profile expired — fall through without pre-categorizing.

        # Medium path: no alias pointer yet, so categorize early to check canonical cache.
        pre_cat = None
        if canonical is None:
            try:
                pre_cat = await claude.categorize(anthropic, q)
            except RateLimitError as exc:
                yield _service_unavailable_event(exc)
                return
            except BadRequestError as exc:
                if not pipeline.is_billing_error(exc):
                    raise
                yield _service_unavailable_event(exc)
                return
            if cache.normalize(pre_cat.canonical_name) != cache.normalize(q):
                cached = await cache.get(valkey_client, pre_cat.canonical_name, mode)
                if cached is not None:
                    async for chunk in _replay_cached(cached):
                        yield chunk
                    await _record_cached_query(db_pool, requester, q, _category_from(cached))
                    await cache.put_canonical(
                        valkey_client, q, pre_cat.canonical_name, pre_cat.aliases, mode
                    )
                    return

        # Slow path: run full pipeline (pre_cat avoids a double categorize call).
        pipeline_events = (
            pipeline.build_deep_profile(q, searcher, anthropic, fetcher, pre_categorized=pre_cat)
            if deep
            else pipeline.build_profile(q, searcher, anthropic, fetcher, pre_categorized=pre_cat)
        )
        collected: list[dict[str, Any]] = []
        async for chunk in _stream_pipeline(pipeline_events, collected):
            yield chunk
        if not _had_failure(collected):
            canonical_for_cache = (
                pre_cat.canonical_name if pre_cat is not None else (canonical or q)
            )
            await cache.put(valkey_client, canonical_for_cache, mode, collected)
            if pre_cat is not None:
                await cache.put_canonical(
                    valkey_client, q, pre_cat.canonical_name, pre_cat.aliases, mode
                )
        category = _category_from(collected) or "other"
        await _record_fresh_query(valkey_client, db_pool, requester, q, category)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _service_unavailable_event(exc: Exception) -> str:
    logger.warning("categorize failed before pipeline: {}", exc)
    payload = {"type": "service_unavailable", "message": pipeline.SERVICE_UNAVAILABLE_MESSAGE}
    return f"data: {json.dumps(payload)}\n\n"


async def _replay_cached(events: list[dict[str, Any]]) -> AsyncGenerator[str, None]:
    for payload in events:
        yield f"data: {json.dumps(payload)}\n\n"
    yield 'data: {"type": "done"}\n\n'


async def _stream_pipeline(
    pipeline_events: AsyncGenerator[pipeline.StageEvent, None],
    collected: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    async for event in pipeline_events:
        payload = {"type": event.stage, **event.data}
        collected.append(payload)
        yield f"data: {json.dumps(payload)}\n\n"
    yield 'data: {"type": "done"}\n\n'


def _category_from(events: list[dict[str, Any]]) -> str:
    for e in events:
        if e.get("type") == "categorized":
            value = e.get("category", "other")
            return value if isinstance(value, str) else "other"
    return "other"


def _had_failure(events: list[dict[str, Any]]) -> bool:
    return any(e.get("type") == "service_unavailable" for e in events)


async def _record_cached_query(
    db_pool: asyncpg.Pool, requester: Requester, q: str, category: str
) -> None:
    """Append the query to search history without consuming quota."""
    await history.push_history(db_pool, requester, query=q, category=category)


async def _record_fresh_query(
    valkey_client: Valkey, db_pool: asyncpg.Pool, requester: Requester, q: str, category: str
) -> None:
    """Consume daily quota and append the query to search history."""
    await store.record_query(valkey_client, requester)
    await _record_cached_query(db_pool, requester, q, category)
