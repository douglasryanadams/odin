"""Odin web application."""

import os
from typing import Annotated

from fastapi import Depends, FastAPI

import searxng

app = FastAPI()


def get_searxng_url() -> str:
    """Return the SearXNG base URL from environment."""
    return os.getenv("SEARXNG_URL", "http://searxng:8080")


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
    return await searxng.search(q, base_url)
