"""Shared data models for the profile pipeline."""

from typing import Literal

from pydantic import BaseModel

Category = Literal["person", "place", "event", "other"]


class ProfileHighlight(BaseModel):
    """A single highlight or lowlight entry."""

    title: str
    description: str


class TimelineEntry(BaseModel):
    """A single entry on the profile timeline."""

    date: str
    event: str


class Citation(BaseModel):
    """A source page the synthesizer cited when building the profile."""

    url: str
    title: str
    snippet: str


class Profile(BaseModel):
    """A structured profile for a search subject."""

    name: str
    category: Category
    summary: str
    highlights: list[ProfileHighlight]
    lowlights: list[ProfileHighlight]
    timeline: list[TimelineEntry]
    citations: list[Citation] = []
