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


class Profile(BaseModel):
    """A structured profile for a search subject."""

    name: str
    category: Category
    summary: str
    highlights: list[ProfileHighlight]
    lowlights: list[ProfileHighlight]
    timeline: list[TimelineEntry]
