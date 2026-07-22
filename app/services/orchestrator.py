"""M10 orchestrator: run the whole pipeline as one call.

This is where the stages built in isolation become a product. It takes raw text
and a model, and returns the rewritten document, the verification verdict, the
changelog, and an audit trail assembled from every stage's own report.

The flow, one line each:

    ingest -> segment -> rewrite (protect, generate, verify, restore) -> verify
    -> changelog

Two commitments hold the run together:

- The audit trail is assembled from what each stage recorded while it ran, not
  reconstructed afterwards. Every StageReport is carried through.
- Partial failure isolation. A segment that cannot be rewritten safely keeps its
  original text and is counted, rather than sinking the run. Fidelity is never
  traded for it: the original text carries all its facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMProvider
from app.pipeline.base import Document, RunContext, StageReport
from app.pipeline.changelog import Changelog, changelog_for_documents
from app.pipeline.rewrite import RewriteStage
from app.pipeline.segment import Segmenter
from app.pipeline.verify import VerificationReport, verify
from app.prompts import Discipline, PromptRegistry, StyleVariant


@dataclass(frozen=True)
class RunResult:
    """Everything one run produced."""

    original: Document  # segmented, pre-rewrite
    rewritten: Document
    verification: VerificationReport
    changelog: Changelog
    reports: tuple[StageReport, ...]  # the audit trail, one entry per stage
    failed_segments: int

    @property
    def ok(self) -> bool:
        """True when the output is valid and fidelity held (the hard gate)."""
        return self.verification.passed

    def _report_dict(self, report: StageReport) -> dict[str, Any]:
        return {
            "stage": report.stage,
            "ok": report.ok,
            "notes": report.notes,
            "messages": list(report.messages),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failed_segments": self.failed_segments,
            "rewritten_text": "\n\n".join(s.text for s in self.rewritten.segments),
            "verification": self.verification.to_dict(),
            "changelog": self.changelog.to_dict(),
            "audit_trail": [self._report_dict(r) for r in self.reports],
        }


def _ingest(text: str) -> Document:
    """Turn raw text into a Document.

    A passthrough for now. Parsing docx, Markdown, and LaTeX into text is a
    separate concern handled at import and export time.
    """
    return Document(text=text)


def run_pipeline(
    text: str,
    ctx: RunContext,
    provider: LLMProvider,
    *,
    style: StyleVariant = StyleVariant.MODERN_INTERDISCIPLINARY,
    discipline: Discipline | None = None,
    registry: PromptRegistry | None = None,
    max_workers: int = 4,
) -> RunResult:
    """Run ingest, segment, rewrite, verify, and changelog, and return the lot."""

    original = _ingest(text)
    segmented = Segmenter().run(original, ctx)

    rewritten = RewriteStage(
        provider,
        style=style,
        discipline=discipline,
        registry=registry,
        max_workers=max_workers,
        isolate_failures=True,
    ).run(segmented, ctx)

    verification = verify(segmented, rewritten, ctx)
    changelog = changelog_for_documents(segmented, rewritten)

    # The audit trail: the segment and rewrite reports the document already
    # carries, plus the verify and changelog reports.
    reports = rewritten.reports + (
        verification.to_stage_report(),
        changelog.to_stage_report(),
    )
    rewrite_report = rewritten.reports[-1]
    failed_segments = int(rewrite_report.notes.get("failed", 0))

    return RunResult(
        original=segmented,
        rewritten=rewritten,
        verification=verification,
        changelog=changelog,
        reports=reports,
        failed_segments=failed_segments,
    )
