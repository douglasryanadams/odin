"""Shared data models for the profile pipeline."""

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["person", "place", "event", "other"]


class ProfileHighlight(BaseModel):
    """A single highlight or lowlight entry.

    Rendered in the profile page as a click-to-expand row: `description` is the
    one-line phrase shown at rest, `detail` is the longer note revealed on click.
    `title` is the short headline tag shown alongside the description.
    """

    title: str
    description: str
    detail: str


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


class Caveat(BaseModel):
    """A single audit caveat: short headline + expanded note."""

    brief: str
    detail: str


class Assessment(BaseModel):
    """Confidence, sentiment, bias and alignment judgments about a profile."""

    confidence: float = Field(ge=0, le=1)
    public_sentiment: float = Field(ge=-1, le=1)
    subject_political_bias: float = Field(ge=-1, le=1)
    source_political_bias: float = Field(ge=-1, le=1)
    law_chaos: float = Field(ge=-1, le=1)
    good_evil: float = Field(ge=-1, le=1)
    caveats: list[Caveat]
