"""Odin web application."""

import json
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

import log
import searxng

log.setup()
app = FastAPI()
templates = Jinja2Templates(directory="templates")


def get_searxng_url() -> str:
    """Return the SearXNG base URL from environment."""
    return os.getenv("SEARXNG_URL", "http://searxng:8080")


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    base_url: Annotated[str, Depends(get_searxng_url)],
    q: str | None = None,
) -> HTMLResponse:
    """Render the search page, with results if a query is provided."""
    results = None
    if q:
        logger.debug("index search query={!r}", q)
        raw = await searxng.search(q, base_url)
        results = json.dumps([r.model_dump() for r in raw], indent=2)
    return templates.TemplateResponse(
        request, "index.html", {"query": q, "results": results}
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.get("/search")
async def search(
    q: str,
    base_url: Annotated[str, Depends(get_searxng_url)],
) -> list[searxng.SearchResult]:
    """Search SearXNG and return results."""
    logger.debug("search request query={!r}", q)
    results = await searxng.search(q, base_url)
    logger.debug("search complete query={!r} results={}", q, len(results))
    return results
