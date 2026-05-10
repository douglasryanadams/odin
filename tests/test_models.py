"""Tests for shared pydantic models in odin.models."""

import pytest
from pydantic import ValidationError

from odin.models import Assessment, Caveat, Profile, ProfileHighlight


def test_profile_highlight_carries_title_description_and_detail() -> None:
    """Highlights carry title, description, and detail.

    Used by the new profile layout: title (short tag), description (one-line
    brief), detail (expanded note revealed on click).
    """
    hl = ProfileHighlight(
        title="Algorithm A (1843)",
        description="First algorithm intended to be executed by a machine.",
        detail=(
            "Lovelace's Note G describes a procedure to compute the seventh "
            "Bernoulli number on Babbage's Analytical Engine. It is the "
            "earliest extant example of a program designed for a machine."
        ),
    )
    assert hl.title == "Algorithm A (1843)"
    assert hl.description.startswith("First algorithm")
    assert "Bernoulli number" in hl.detail


def test_profile_highlight_detail_is_required() -> None:
    """`detail` is required so the click-to-expand row always has body content."""
    with pytest.raises(ValidationError):
        ProfileHighlight(title="t", description="d")  # type: ignore[call-arg]


def test_caveat_model_has_brief_and_detail() -> None:
    """Caveats are now structured: a short headline plus a longer note."""
    c = Caveat(
        brief="'First programmer' claims contested.",
        detail="Several historians (Bromley 1990) attribute earlier programs to Babbage himself.",
    )
    assert c.brief.startswith("'First programmer'")
    assert "Bromley" in c.detail


def test_assessment_caveats_are_caveat_objects() -> None:
    """Assessment.caveats holds Caveat objects, not bare strings."""
    a = Assessment(
        confidence=0.9,
        public_sentiment=0.5,
        subject_political_bias=0.0,
        source_political_bias=0.0,
        law_chaos=-0.2,
        good_evil=0.7,
        caveats=[
            Caveat(
                brief="Sparse late-life records.",
                detail="Personal correspondence is fragmentary.",
            ),
        ],
    )
    assert len(a.caveats) == 1
    assert a.caveats[0].brief == "Sparse late-life records."
    assert a.caveats[0].detail.startswith("Personal correspondence")


def test_profile_summary_is_a_string_that_can_hold_multiple_paragraphs() -> None:
    """The summary stays a single string; the frontend splits on blank lines."""
    profile = Profile(
        name="Subject",
        category="other",
        summary="Paragraph one.\n\nParagraph two.\n\nParagraph three.",
        highlights=[],
        lowlights=[],
        timeline=[],
        citations=[],
    )
    assert profile.summary.count("\n\n") == 2
