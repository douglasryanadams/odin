"""Odin web application."""

import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from odin import log, pipeline

log.setup()
app = FastAPI()
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def get_searxng_url() -> str:
    """Return the SearXNG base URL from environment."""
    return os.getenv("SEARXNG_URL", "http://searxng:8080")


def get_anthropic_client() -> AsyncAnthropic:
    """Return an Anthropic client, reading ANTHROPIC_API_KEY from the environment."""
    return AsyncAnthropic()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the home page with the profile search form."""
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, q: str) -> HTMLResponse:
    """Render the profile page for a given query."""
    return templates.TemplateResponse(request, "profile.html", {"query": q})


@app.get("/profile/stream")
async def profile_stream(
    q: str,
    searxng_url: Annotated[str, Depends(get_searxng_url)],
    anthropic: Annotated[AsyncAnthropic, Depends(get_anthropic_client)],
) -> StreamingResponse:
    """Stream profile pipeline progress as Server-Sent Events."""

    async def event_generator() -> AsyncGenerator[str, None]:
        async for event in pipeline.build_profile(q, searxng_url, anthropic):
            payload = {"type": event.stage, **event.data}
            yield f"data: {json.dumps(payload)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(event_generator(), media_type="text/event-stream")
