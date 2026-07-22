"""M2 segmenter tests.

Covers heading classification across formats, section carry-forward, freezing,
and the no-heading fallback. Two named regression tests guard the roman-numeral
strip bug and the numbered-list-item misread.
"""

from __future__ import annotations

from app.pipeline.base import Document, Intensity, RunContext, Section
from app.pipeline.segment import Segmenter, classify_heading, segment


def _sections(text: str) -> list:
    segs, _ = segment(text)
    return segs


def test_classifies_numbered_headings() -> None:
    segs = _sections("1. Introduction\n\nWe study the problem.\n\n2.1 Related Work\n\nPrior art.")
    headings = [s for s in segs if s.heading]
    assert [s.text for s in headings] == ["1. Introduction", "2.1 Related Work"]
    assert headings[0].section is Section.INTRODUCTION
    assert headings[1].section is Section.RELATED_WORK


def test_roman_heading_keeps_leading_letter() -> None:
    """Regression: 'I. Introduction' once became 'ntroduction' because a roman
    character class ate the leading letter. The title must survive intact."""
    is_heading, title = classify_heading("I. Introduction")
    assert is_heading
    assert title == "Introduction"
    # And a plain word starting with a roman letter is not a roman heading.
    assert classify_heading("Introduction")[1] == "Introduction"  # via title-case
    segs = _sections("IV. Results\n\nThe model improved accuracy.")
    assert segs[0].heading and segs[0].section is Section.RESULTS


def test_classifies_markdown_headings() -> None:
    segs = _sections("## Methods\n\nWe describe the protocol.")
    assert segs[0].heading and segs[0].section is Section.METHODS
    assert segs[0].text == "## Methods"


def test_classifies_all_caps_headings() -> None:
    segs = _sections("MATERIALS AND METHODS\n\nSamples were prepared.")
    assert segs[0].heading and segs[0].section is Section.METHODS


def test_classifies_title_case_headings() -> None:
    segs = _sections("Related Work\n\nSeveral groups have studied this.")
    assert segs[0].heading and segs[0].section is Section.RELATED_WORK


def test_section_carries_forward() -> None:
    text = (
        "## Methods\n\nFirst paragraph of methods.\n\n"
        "Second paragraph of methods.\n\n"
        "## Results\n\nA results paragraph."
    )
    segs = _sections(text)
    prose = [s for s in segs if not s.heading]
    assert prose[0].section is Section.METHODS
    assert prose[1].section is Section.METHODS
    assert prose[2].section is Section.RESULTS


def test_numbered_list_item_is_not_a_heading() -> None:
    """Regression: a numbered sentence must not be read as a heading."""
    is_heading, _ = classify_heading("1. We ran the experiment three times and averaged.")
    assert not is_heading
    segs = _sections("1. We ran the experiment three times and averaged the runs.")
    assert not segs[0].heading and segs[0].kind == "paragraph"


def test_freezes_references_equations_and_captions() -> None:
    text = (
        "## Results\n\n"
        "$$E = mc^2$$\n\n"
        "Figure 1: the observed trend over time.\n\n"
        "## References\n\n"
        "[1] Smith, J. A paper. Journal, 2020.\n\n"
        "[2] Doe, R. Another paper. Journal, 2019."
    )
    segs = _sections(text)
    by_kind = {s.kind for s in segs if s.frozen}
    assert "equation" in by_kind
    assert "caption" in by_kind
    assert "reference" in by_kind
    # Every block under References is frozen and tagged as the References section.
    refs = [s for s in segs if s.section is Section.REFERENCES and not s.heading]
    assert refs and all(s.frozen and s.kind == "reference" for s in refs)


def test_no_headings_disables_section_awareness() -> None:
    text = "A first paragraph with no heading.\n\nA second paragraph, still no heading."
    segs, section_aware = segment(text)
    assert not section_aware
    assert all(s.section is None for s in segs)
    # The stage reports the disabled awareness for the audit trail.
    doc = Segmenter().run(Document(text=text), RunContext(intensity=Intensity.BALANCED))
    report = doc.reports[-1]
    assert report.notes["section_aware"] is False
    assert report.messages
