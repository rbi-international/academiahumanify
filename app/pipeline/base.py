"""Pipeline contracts shared by every stage.

Why this file exists: the whole design rests on stages being small, pure, and
composable. A stage takes a Document plus a RunContext and returns a *new*
Document with one StageReport appended. It never mutates what it was handed.
That immutability is what lets the change log be assembled from what each stage
recorded while it ran, rather than reconstructed by diffing afterwards.

Nothing here knows about the LLM. These carriers are deterministic data.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class Intensity(Enum):
    """How hard the rewrite is allowed to push.

    CONSERVATIVE is the floor: Methods and Results are pinned here regardless of
    the user's choice, because reproducibility outranks flow in those sections.
    """

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    ENHANCED = "enhanced"


class Section(Enum):
    """Canonical paper sections.

    We only need the ones that change behaviour. Anything unrecognised stays
    OTHER and simply inherits the global intensity. METHODS and RESULTS are the
    two that force CONSERVATIVE.
    """

    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    RELATED_WORK = "related_work"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSION = "conclusion"
    REFERENCES = "references"
    ACKNOWLEDGEMENTS = "acknowledgements"
    OTHER = "other"


# Sections where flow matters less than exactness. Forced to CONSERVATIVE.
_REPRODUCIBILITY_SECTIONS = frozenset({Section.METHODS, Section.RESULTS})


def resolve_intensity(section: Section | None, requested: Intensity) -> Intensity:
    """Return the intensity a segment may actually use.

    Methods and Results are clamped to CONSERVATIVE. This is a hard product rule
    (fidelity invariant 3), so it lives here in the deterministic core rather
    than in a prompt the model could ignore.
    """

    if section in _REPRODUCIBILITY_SECTIONS:
        return Intensity.CONSERVATIVE
    return requested


@dataclass(frozen=True)
class Segment:
    """One unit of the document after segmentation.

    A segment is either rewritable prose or a frozen block (heading, equation,
    table, caption, reference) that must pass through byte-identical. Frozen
    segments never reach the model.
    """

    index: int
    text: str
    section: Section | None = None
    heading: bool = False
    frozen: bool = False
    kind: str = "paragraph"

    def with_text(self, text: str) -> Segment:
        """Return a copy carrying new text. Frozen segments refuse to change."""
        if self.frozen and text != self.text:
            raise ValueError(f"segment {self.index} is frozen and cannot be rewritten")
        return replace(self, text=text)


@dataclass(frozen=True)
class StageReport:
    """What a stage did, recorded as it ran.

    `notes` is free-form structured detail (counts, flags, timings). The change
    log and the audit trail are built from these, so a stage should record here
    anything a later reader would need to explain the output.
    """

    stage: str
    ok: bool = True
    notes: dict[str, Any] = field(default_factory=dict)
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class Document:
    """The carrier that flows through the pipeline.

    Immutable by convention: stages return a new Document via the helpers below
    rather than editing in place. `reports` accumulates one entry per stage.
    """

    text: str
    segments: tuple[Segment, ...] = ()
    reports: tuple[StageReport, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_segments(self, segments: tuple[Segment, ...], report: StageReport) -> Document:
        return replace(self, segments=tuple(segments), reports=self.reports + (report,))

    def with_report(self, report: StageReport) -> Document:
        return replace(self, reports=self.reports + (report,))


@dataclass(frozen=True)
class RunContext:
    """Per-run settings and identity that a stage may read but not change."""

    run_id: str = "local"
    intensity: Intensity = Intensity.BALANCED
    # A paragraph of the author's own past writing, used later for voice matching.
    voice_sample: str | None = None


@runtime_checkable
class Stage(Protocol):
    """The contract every pipeline stage implements.

    A stage is a pure function of (Document, RunContext). It returns a new
    Document with its own StageReport appended and must not mutate the input.
    """

    name: str

    def run(self, doc: Document, ctx: RunContext) -> Document: ...
