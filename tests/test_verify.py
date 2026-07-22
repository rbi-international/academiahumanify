"""M8 verify stage tests: the hard gate, the soft flags, and a drifting rewrite."""

from __future__ import annotations

from app.pipeline.base import Document, RunContext, Section, Segment
from app.pipeline.verify import verify


def _seg(index: int, text: str, section: Section | None = None, frozen: bool = False) -> Segment:
    return Segment(index=index, text=text, section=section, frozen=frozen,
                   kind="heading" if frozen else "paragraph")


def _docs(original_segments: list[Segment], rewritten_segments: list[Segment]) -> tuple:
    return (
        Document(text="", segments=tuple(original_segments)),
        Document(text="", segments=tuple(rewritten_segments)),
    )


def _run(original_segments: list[Segment], rewritten_segments: list[Segment]):
    o, r = _docs(original_segments, rewritten_segments)
    return verify(o, r, RunContext())


def test_faithful_rewrite_passes_cleanly() -> None:
    original = "The method improved accuracy by 12.4% on dataset [17]."
    rewritten = "The method lifted accuracy by 12.4% on dataset [17]."
    report = _run([_seg(0, original)], [_seg(0, rewritten)])
    assert report.passed
    assert not report.fidelity_failures
    assert not report.claim_flags


def test_missing_citation_is_a_hard_failure() -> None:
    original = "The result held [17] across every run of the study."
    rewritten = "The result held across every run of the study."  # citation dropped
    report = _run([_seg(0, original)], [_seg(0, rewritten)])
    assert not report.passed
    kinds = {f.kind for f in report.fidelity_failures}
    assert "missing_protected_span" in kinds


def test_changed_frozen_segment_is_a_hard_failure() -> None:
    report = _run(
        [_seg(0, "## Methods", frozen=True)],
        [_seg(0, "## Approach", frozen=True)],  # a frozen heading must not change
    )
    assert not report.passed
    assert report.fidelity_failures[0].kind == "frozen_changed"


def test_strengthened_claim_is_flagged_softly() -> None:
    original = "The data may suggest an association between exercise and mood."
    rewritten = "The data demonstrates an association between exercise and mood."
    report = _run([_seg(0, original)], [_seg(0, rewritten)])
    assert report.passed  # soft: does not fail the hard gate
    strengthened = [f for f in report.claim_flags if f.kind == "strengthened"]
    assert strengthened
    assert strengthened[0].before_hedge and strengthened[0].after_hedge


def test_weakened_claim_is_flagged() -> None:
    original = "The trial demonstrates that the drug reduces relapse."
    rewritten = "The trial may suggest that the drug reduces relapse."
    report = _run([_seg(0, original)], [_seg(0, rewritten)])
    assert report.passed
    assert any(f.kind == "weakened" for f in report.claim_flags)


def test_dropped_claim_is_flagged() -> None:
    original = "The framework indicates a limitation. The results show a clear gain in accuracy."
    rewritten = "The results show a clear gain in accuracy."  # first claim gone
    report = _run([_seg(0, original)], [_seg(0, rewritten)])
    assert any(f.kind == "dropped" for f in report.claim_flags)


def test_sentence_count_deviation_is_flagged() -> None:
    original = "One. Two. Three. Four. Five. Six."
    rewritten = "One and two and three and four and five and six all at once."
    report = _run([_seg(0, original)], [_seg(0, rewritten)])
    assert report.sentence_flags
    assert report.sentence_flags[0].before == 6


def test_methods_tolerance_is_tighter_than_discussion() -> None:
    # A two-sentence drop out of five: within the default tolerance (2.5), but
    # past the tighter Methods tolerance (1.0).
    original = "Alpha runs. Beta runs. Gamma runs. Delta runs. Epsilon runs."
    rewritten = "Alpha runs. Beta and gamma run. Delta and epsilon run."
    discussion = _run(
        [_seg(0, original, section=Section.DISCUSSION)],
        [_seg(0, rewritten, section=Section.DISCUSSION)],
    )
    methods = _run(
        [_seg(0, original, section=Section.METHODS)],
        [_seg(0, rewritten, section=Section.METHODS)],
    )
    assert not discussion.sentence_flags
    assert methods.sentence_flags


def test_soft_failures_do_not_fail_the_hard_gate() -> None:
    # Claim drift and sentence change together, but nothing protected was lost.
    original = "We ran three trials. The data may suggest a benefit for the group."
    rewritten = "The data demonstrates a benefit."
    report = _run([_seg(0, original)], [_seg(0, rewritten)])
    assert report.passed
    assert report.claim_flags  # drift was recorded, just not gated


def test_segment_count_mismatch_is_structural() -> None:
    report = _run([_seg(0, "A."), _seg(1, "B.")], [_seg(0, "A and B.")])
    assert not report.passed
    assert report.fidelity_failures[0].kind == "segment_count_mismatch"


def test_deliberately_drifting_rewrite_reports_everything() -> None:
    # Strengthens a claim, moves the sentence count, keeps the citation.
    original = (
        "We collected the data over two seasons. "
        "The analysis may suggest a weak link to rainfall [4]. "
        "We note the limits of the sample."
    )
    rewritten = "The analysis proves a strong link to rainfall [4]."
    report = _run([_seg(0, original, section=Section.RESULTS)],
                  [_seg(0, rewritten, section=Section.RESULTS)])
    # Citation survived, so the hard gate holds.
    assert report.passed
    # But the soft gates light up: a strengthened claim and a big structure change.
    assert any(f.kind == "strengthened" for f in report.claim_flags)
    assert report.sentence_flags


def test_report_serialises_and_makes_a_stage_report() -> None:
    report = _run([_seg(0, "The data may suggest a benefit [1].")],
                  [_seg(0, "The data demonstrates a benefit [1].")])
    d = report.to_dict()
    assert set(d) == {"passed", "fidelity_failures", "claim_flags", "sentence_flags"}
    stage = report.to_stage_report()
    assert stage.stage == "verify"
    assert stage.notes["claim_flags"] >= 1
