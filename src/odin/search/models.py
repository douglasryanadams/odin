"""Neutral search-result model shared by every search backend."""

from pydantic import BaseModel


class SearchResult(BaseModel):
    """A single search result from any backend."""

    url: str
    title: str
    content: str = ""
    engines: list[str] = []
