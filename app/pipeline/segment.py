"""M2 segmenter: split a draft into paragraphs, tag each with its section,
freeze what must not move.

Why this matters: intensity and protection are section-aware. Methods and
Results are held to a stricter standard than the Discussion, and the References
list must never enter the rewrite path at all. To act on any of that we first
need to know, for every paragraph, which section it belongs to and whether it is
prose we may rewrite or a frozen block (heading, equation, table, caption,
reference) that passes through byte-identical.

Two real bugs are locked by named regression tests below:

  1. A roman-numeral character class once doubled as a stripper and ate the
     leading "I" of "Introduction". Here the numeral and the title are captured
     as separate groups and the title is used verbatim, never stripped.
  2. A numbered list item ("1. We ran the experiment...") was read as a heading.
     Headings are now required to be short and title-like, not sentences.

Deterministic, no model. Pure regex and rules.
"""

from __future__ import annotations

import re

from app.pipeline.base import Document, RunContext, Section, Segment, StageReport

# Canonical section keywords -> Section. Order does not matter; the first
# keyword found in the normalised heading wins via the explicit lookups below.
_SECTION_KEYWORDS: tuple[tuple[tuple[str, ...], Section], ...] = (
    (("abstract",), Section.ABSTRACT),
    (("introduction",), Section.INTRODUCTION),
    (("related work", "background", "prior work", "literature"), Section.RELATED_WORK),
    (
        ("method", "methods", "methodology", "materials and methods",
         "experimental setup", "approach", "materials"),
        Section.METHODS,
    ),
    (("result", "results", "findings", "evaluation", "experiments"), Section.RESULTS),
    (("discussion",), Section.DISCUSSION),
    (("conclusion", "concluding", "conclusions"), Section.CONCLUSION),
    (("references", "bibliography", "works cited"), Section.REFERENCES),
    (("acknowledgement", "acknowledgment", "acknowledgements",
      "acknowledgments"), Section.ACKNOWLEDGEMENTS),
)

_CANONICAL_ROMAN = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")
_ROMAN_HEADING = re.compile(r"^([IVXLCDM]+)\.?\s+(.+)$")
_CAPTION = re.compile(r"^(?:Table|Tab\.|Figure|Fig\.)\s*\d+", re.IGNORECASE)
_MATH_BLOCK = re.compile(
    r"^(?:\$\$.+\$\$|\\\[.+\\\]|\$[^$]+\$|\\begin\{[^}]*\}.*\\end\{[^}]*\})$",
    re.DOTALL,
)
_TABLE_ENV = re.compile(r"\\begin\{(?:table|tabular)\*?\}")

# Small function words that stay lower-case inside a title-case heading.
_TITLE_STOPWORDS = frozenset(
    {"a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with",
     "at", "by", "from", "as", "into", "per", "via"}
)

_MAX_HEADING_WORDS = 8


def _canonical_section(title: str) -> Section:
    """Map a heading's title text to a canonical Section.

    Matches on the normalised title so "3. Materials and Methods:" and
    "METHODS" both land on METHODS. Anything unrecognised is OTHER, which simply
    inherits the global intensity later.
    """

    norm = title.strip().rstrip(":.").lower()
    for keywords, section in _SECTION_KEYWORDS:
        for kw in keywords:
            # Whole-word match so "results" is not found inside "resultsxyz".
            if re.search(rf"\b{re.escape(kw)}\b", norm):
                return section
    return Section.OTHER


def _looks_like_title(title: str) -> bool:
    """A heading title is short and not a sentence.

    This is the guard that stops numbered list items from being read as
    headings: a real heading is a handful of words, starts with a capital, and
    does not end in sentence punctuation.
    """

    title = title.strip()
    if not title or title[0].islower():
        return False
    if title[-1] in ".!?;":
        return False
    words = title.split()
    return 1 <= len(words) <= _MAX_HEADING_WORDS


def _is_title_case_line(line: str) -> bool:
    """True for a standalone title-case line like 'Related Work'.

    Every significant word is capitalised (stopwords may stay lower-case), the
    first and last word are capitalised, and there is no terminal punctuation.
    """

    line = line.strip()
    if not line or line[-1] in ".!?;:" or "\n" in line:
        return False
    words = line.split()
    if not (1 <= len(words) <= _MAX_HEADING_WORDS):
        return False
    if not words[0][0].isupper() or not words[-1][0].isupper():
        return False
    for w in words:
        first = w[0]
        if first.isupper():
            continue
        if w.lower() in _TITLE_STOPWORDS:
            continue
        return False
    return True


def classify_heading(block: str) -> tuple[bool, str | None]:
    """Decide whether a block is a heading and return its title text.

    Returns (is_heading, title). The title is what feeds section detection, and
    it is always taken from a capture group, never produced by stripping
    characters off the front of the line (the source of the old "ntroduction"
    bug).
    """

    if "\n" in block.strip():
        return False, None  # headings are single lines
    line = block.strip()

    m = _MARKDOWN_HEADING.match(line)
    if m:
        return True, m.group(2).strip()

    m = _NUMBERED_HEADING.match(line)
    if m and _looks_like_title(m.group(2)):
        return True, m.group(2).strip()

    m = _ROMAN_HEADING.match(line)
    if m and _CANONICAL_ROMAN.match(m.group(1)) and _looks_like_title(m.group(2)):
        return True, m.group(2).strip()

    # All-caps heading: INTRODUCTION, MATERIALS AND METHODS.
    if re.fullmatch(r"[A-Z][A-Z0-9 &/\-]{2,}", line) and any(c.isalpha() for c in line):
        if len(line.split()) <= _MAX_HEADING_WORDS:
            return True, line.strip()

    # Title-case heading: Related Work.
    if _is_title_case_line(line):
        return True, line.strip()

    return False, None


def _frozen_kind(block: str, section: Section | None) -> str | None:
    """Return the frozen kind for a non-heading block, or None if it is prose.

    Order matters: a block inside the References section is frozen as a
    reference regardless of its shape, because references never enter the
    rewrite path at all (fidelity invariant 2).
    """

    if section is Section.REFERENCES:
        return "reference"
    stripped = block.strip()
    if _CAPTION.match(stripped):
        return "caption"
    if _MATH_BLOCK.fullmatch(stripped):
        return "equation"
    if _TABLE_ENV.search(stripped):
        return "table"
    # Markdown table: at least one line fenced by pipes.
    for physical_line in stripped.splitlines():
        s = physical_line.strip()
        if s.startswith("|") and s.endswith("|") and len(s) > 1:
            return "table"
    return None


def segment(text: str) -> tuple[tuple[Segment, ...], bool]:
    """Split `text` into tagged, possibly-frozen segments.

    Returns the segments and whether section awareness was active (it is
    disabled, and reported, when the document has no headings at all).
    """

    blocks = re.split(r"\n[ \t]*\n", text)
    segments: list[Segment] = []
    current_section: Section | None = None
    heading_count = 0
    index = 0

    for raw in blocks:
        if not raw.strip():
            continue
        block = raw.strip()

        is_heading, title = classify_heading(block)
        if is_heading and title is not None:
            heading_count += 1
            current_section = _canonical_section(title)
            segments.append(
                Segment(
                    index=index,
                    text=block,
                    section=current_section,
                    heading=True,
                    frozen=True,
                    kind="heading",
                )
            )
            index += 1
            continue

        kind = _frozen_kind(block, current_section)
        segments.append(
            Segment(
                index=index,
                text=block,
                section=current_section,
                heading=False,
                frozen=kind is not None,
                kind=kind or "paragraph",
            )
        )
        index += 1

    section_aware = heading_count > 0
    if not section_aware:
        # No headings: strip any tentative section so nothing is treated as
        # section-specific, and let the caller report that awareness is off.
        segments = [
            Segment(index=s.index, text=s.text, section=None, heading=s.heading,
                    frozen=s.frozen, kind=s.kind)
            for s in segments
        ]

    return tuple(segments), section_aware


class Segmenter:
    """Pipeline stage wrapper around `segment`.

    Records what it found (segment count, heading count, frozen count, and
    whether section awareness was active) so the audit trail can explain later
    intensity and freezing decisions.
    """

    name = "segment"

    def run(self, doc: Document, ctx: RunContext) -> Document:
        segments, section_aware = segment(doc.text)
        frozen = sum(1 for s in segments if s.frozen)
        report = StageReport(
            stage=self.name,
            ok=True,
            notes={
                "segments": len(segments),
                "headings": sum(1 for s in segments if s.heading),
                "frozen": frozen,
                "section_aware": section_aware,
            },
            messages=()
            if section_aware
            else ("no headings found: section awareness disabled",),
        )
        return doc.with_segments(segments, report)
