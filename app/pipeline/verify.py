"""M8 verify stage: check the finished rewrite against the original.

This runs after restore, on the final text, and answers two different kinds of
question with two different consequences:

- Hard gate. Did any protected content go missing, or did a frozen segment
  change? Every citation, number, and equation in the original must still be
  present, and headings, tables, and references must be byte-identical. A hard
  failure means something slipped past the rewrite stage's own integrity check,
  which is a bug: the run should fail. This stage does not raise; it reports
  `passed = False` and lets the orchestrator decide.

- Soft gate. Did a claim change strength, or did the sentence count move more
  than the section allows? These are flagged for the author to review. They
  never block, and this stage never raises on them.

The claim-drift check is deeper than a single max-hedge comparison: it aligns
each original claim to its closest match in the rewrite by subject and object
overlap, then compares hedge strength per pair, and separately flags claims that
look dropped or added.

Deterministic, no model. Reuses M1 (protection) to enumerate protected spans, M4
(claims) for drift, and M3 (sentence splitting) for structure.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from app.core.protection import protect
from app.pipeline.base import Document, RunContext, Section, StageReport
from app.pipeline.claims import Claim, extract_claims
from app.pipeline.stylometry import split_sentences

# Methods and Results carry the reproducibility burden, so their structure is
# held tighter: a smaller sentence-count swing is tolerated before it is flagged.
_SECTION_SENTENCE_TOLERANCE: dict[Section, float] = {
    Section.METHODS: 0.2,
    Section.RESULTS: 0.2,
}
_DEFAULT_SENTENCE_TOLERANCE = 0.5

# How much subject-plus-object overlap counts as "the same claim".
_CLAIM_MATCH_THRESHOLD = 0.3


@dataclass(frozen=True)
class FidelityFailure:
    """A hard-gate breach: protected content lost, or a frozen segment changed."""

    segment_index: int
    kind: str  # missing_protected_span | frozen_changed | segment_count_mismatch
    detail: str


@dataclass(frozen=True)
class ClaimDriftFlag:
    """A soft-gate claim change, for the author to review."""

    segment_index: int
    kind: str  # strengthened | weakened | dropped | added
    before: str | None
    after: str | None
    before_hedge: str | None
    after_hedge: str | None


@dataclass(frozen=True)
class SentenceFlag:
    """A soft-gate structural change: sentence count moved past the tolerance."""

    segment_index: int
    section: str | None
    before: int
    after: int
    tolerance: float


@dataclass(frozen=True)
class VerificationReport:
    """The full verdict. `passed` is the hard gate only; flags are advisory."""

    passed: bool
    fidelity_failures: tuple[FidelityFailure, ...]
    claim_flags: tuple[ClaimDriftFlag, ...]
    sentence_flags: tuple[SentenceFlag, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "fidelity_failures": [asdict(f) for f in self.fidelity_failures],
            "claim_flags": [asdict(f) for f in self.claim_flags],
            "sentence_flags": [asdict(f) for f in self.sentence_flags],
        }

    def to_stage_report(self) -> StageReport:
        messages: list[str] = []
        if not self.passed:
            messages.append(f"hard gate failed: {len(self.fidelity_failures)} fidelity issue(s)")
        return StageReport(
            stage="verify",
            ok=self.passed,
            notes={
                "passed": self.passed,
                "fidelity_failures": len(self.fidelity_failures),
                "claim_flags": len(self.claim_flags),
                "sentence_flags": len(self.sentence_flags),
            },
            messages=tuple(messages),
        )


def _tokens(*parts: str) -> set[str]:
    text = " ".join(parts).lower()
    return {t for t in text.replace(",", " ").split() if t}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _missing_protected_spans(index: int, original: str, rewritten: str) -> list[FidelityFailure]:
    """Every protected span in the original must still be present in the rewrite.

    A secondary, content-level safety net. The primary integrity gate is the
    rewrite stage, which verifies placeholders before restoring. This catches a
    restore bug or a downstream mutation that dropped real content.
    """

    required = Counter(protect(original).mapping.values())
    failures: list[FidelityFailure] = []
    for span, count in required.items():
        present = rewritten.count(span)
        if present < count:
            failures.append(
                FidelityFailure(
                    segment_index=index,
                    kind="missing_protected_span",
                    detail=f"{span!r} present {present}x, expected at least {count}x",
                )
            )
    return failures


def _claim_drift(
    index: int, before: list[Claim], after: list[Claim]
) -> list[ClaimDriftFlag]:
    """Align claims by subject and object overlap, then compare hedge strength.

    Matched pairs that changed strength are strengthened or weakened. Original
    claims with no match are flagged dropped; rewrite claims with no match are
    flagged added. All soft.
    """

    flags: list[ClaimDriftFlag] = []
    matched: set[int] = set()

    for oc in before:
        best_i = -1
        best_score = 0.0
        for i, nc in enumerate(after):
            if i in matched:
                continue
            score = _jaccard(_tokens(oc.subject, oc.object), _tokens(nc.subject, nc.object))
            if score > best_score:
                best_score = score
                best_i = i
        if best_i >= 0 and best_score >= _CLAIM_MATCH_THRESHOLD:
            matched.add(best_i)
            nc = after[best_i]
            if nc.hedge > oc.hedge:
                kind = "strengthened"
            elif nc.hedge < oc.hedge:
                kind = "weakened"
            else:
                continue
            flags.append(
                ClaimDriftFlag(
                    segment_index=index,
                    kind=kind,
                    before=oc.sentence,
                    after=nc.sentence,
                    before_hedge=oc.hedge.name,
                    after_hedge=nc.hedge.name,
                )
            )
        else:
            flags.append(
                ClaimDriftFlag(
                    segment_index=index,
                    kind="dropped",
                    before=oc.sentence,
                    after=None,
                    before_hedge=oc.hedge.name,
                    after_hedge=None,
                )
            )

    for i, nc in enumerate(after):
        if i not in matched:
            flags.append(
                ClaimDriftFlag(
                    segment_index=index,
                    kind="added",
                    before=None,
                    after=nc.sentence,
                    before_hedge=None,
                    after_hedge=nc.hedge.name,
                )
            )
    return flags


def _sentence_flag(
    index: int, section: Section | None, original: str, rewritten: str
) -> list[SentenceFlag]:
    before = len(split_sentences(original))
    after = len(split_sentences(rewritten))
    if before == 0:
        return []
    tolerance = _SECTION_SENTENCE_TOLERANCE.get(section, _DEFAULT_SENTENCE_TOLERANCE)  # type: ignore[arg-type]
    if abs(after - before) > tolerance * before:
        return [
            SentenceFlag(
                segment_index=index,
                section=section.value if section else None,
                before=before,
                after=after,
                tolerance=tolerance,
            )
        ]
    return []


def _verify_unit(
    index: int,
    section: Section | None,
    frozen: bool,
    original: str,
    rewritten: str,
    fidelity: list[FidelityFailure],
    claims: list[ClaimDriftFlag],
    sentences: list[SentenceFlag],
) -> None:
    if frozen:
        if original != rewritten:
            fidelity.append(
                FidelityFailure(index, "frozen_changed", "frozen segment was modified")
            )
        return
    fidelity.extend(_missing_protected_spans(index, original, rewritten))
    claims.extend(_claim_drift(index, extract_claims(original), extract_claims(rewritten)))
    sentences.extend(_sentence_flag(index, section, original, rewritten))


def verify(original: Document, rewritten: Document, ctx: RunContext) -> VerificationReport:
    """Verify `rewritten` against `original`, returning a structured report.

    Never raises. Hard-gate breaches set `passed = False`; soft flags are
    collected for review. When both documents carry segments they are compared
    segment by segment; otherwise the whole text is compared as one unit.
    """

    fidelity: list[FidelityFailure] = []
    claims: list[ClaimDriftFlag] = []
    sentences: list[SentenceFlag] = []

    o_segs = original.segments
    r_segs = rewritten.segments

    if o_segs and r_segs:
        if len(o_segs) != len(r_segs):
            fidelity.append(
                FidelityFailure(
                    -1,
                    "segment_count_mismatch",
                    f"{len(o_segs)} original segments, {len(r_segs)} rewritten",
                )
            )
        else:
            for o, r in zip(o_segs, r_segs, strict=True):
                frozen = o.frozen or r.frozen
                _verify_unit(
                    o.index, o.section, frozen, o.text, r.text, fidelity, claims, sentences
                )
    else:
        _verify_unit(0, None, False, original.text, rewritten.text, fidelity, claims, sentences)

    return VerificationReport(
        passed=not fidelity,
        fidelity_failures=tuple(fidelity),
        claim_flags=tuple(claims),
        sentence_flags=tuple(sentences),
    )
