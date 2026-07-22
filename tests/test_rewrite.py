"""M7 rewrite stage tests, end to end against the stub and small fakes.

Covers the mask/verify/restore loop, frozen bypass, the forced-conservative rule
for Methods and Results, retry-then-succeed, hard failure after the cap, ordered
concurrent reassembly, the voice directive, and the report counts.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.protection import protect
from app.llm.base import TokenUsage
from app.llm.stub import StubProvider
from app.pipeline.base import Document, Intensity, RunContext, Section, Segment
from app.pipeline.rewrite import RewriteError, RewriteStage

CITED = "The method improved accuracy by 12.4% on dataset [17] (p < 0.05)."


def _doc(*segments: Segment) -> Document:
    return Document(text="", segments=tuple(segments))


def _prose(index: int, text: str, section: Section | None = None) -> Segment:
    return Segment(index=index, text=text, section=section, frozen=False, kind="paragraph")


def test_echo_rewrite_preserves_placeholders_and_restores() -> None:
    provider = StubProvider()  # echoes the masked text
    out = RewriteStage(provider, max_workers=1).run(
        _doc(_prose(0, CITED)), RunContext(intensity=Intensity.BALANCED)
    )
    # Echo then restore returns the original text, and integrity held.
    assert out.segments[0].text == CITED
    assert out.reports[-1].notes["rewritten"] == 1


def test_frozen_segments_bypass_the_model() -> None:
    # This provider would corrupt anything it touched. It must never be called.
    provider = StubProvider(default_response="CORRUPTED no tokens")
    heading = Segment(
        index=0,
        text="## Methods",
        section=Section.METHODS,
        heading=True,
        frozen=True,
        kind="heading",
    )
    out = RewriteStage(provider, max_workers=1).run(_doc(heading), RunContext())
    assert out.segments[0].text == "## Methods"  # byte-identical passthrough
    assert provider.usage.calls == 0
    assert out.reports[-1].notes["frozen"] == 1


def test_non_identity_rewrite_flows_through_and_restores_facts() -> None:
    # A fake model that upper-cases the prose. Placeholders are already
    # upper-case so they survive, and the citation and number come back exact.
    class UpperProvider:
        name = "upper"

        def __init__(self) -> None:
            self.usage = TokenUsage()

        def complete(self, prompt: str, system: str | None = None, **opts: Any) -> str:
            return prompt.upper()

    out = RewriteStage(UpperProvider(), max_workers=1).run(
        _doc(_prose(0, "the method improved accuracy by 12.4% on dataset [17].")),
        RunContext(intensity=Intensity.BALANCED),
    )
    text = out.segments[0].text
    assert "12.4%" in text and "[17]" in text  # facts restored exactly
    assert "THE METHOD IMPROVED ACCURACY BY" in text  # prose was transformed


def test_retry_then_success_records_the_extra_attempt() -> None:
    p = protect(CITED)  # deterministic, so the stage masks to the same tokens
    broken = p.masked.replace(p.order[0], "", 1)  # first attempt drops a token
    provider = StubProvider(scripted=[broken, p.masked])
    out = RewriteStage(provider, max_workers=1, max_attempts=3).run(
        _doc(_prose(0, CITED)), RunContext()
    )
    assert out.segments[0].text == CITED  # the good second attempt restores it
    assert out.reports[-1].notes["retries"] == 1
    assert provider.usage.calls == 2


def test_hard_fail_after_max_attempts_raises() -> None:
    provider = StubProvider(default_response="no tokens at all")
    with pytest.raises(RewriteError):
        RewriteStage(provider, max_workers=1, max_attempts=3).run(
            _doc(_prose(0, CITED)), RunContext()
        )
    assert provider.usage.calls == 3  # tried the full cap, then failed hard


def test_methods_and_results_forced_conservative() -> None:
    provider = StubProvider()  # echo
    out = RewriteStage(provider, max_workers=1).run(
        _doc(_prose(0, CITED, section=Section.METHODS)),
        RunContext(intensity=Intensity.ENHANCED),  # user asked for the strongest
    )
    refs = out.reports[-1].notes["prompt_refs"]
    assert any("system/intensity/conservative" in r for r in refs)
    assert not any("system/intensity/enhanced" in r for r in refs)


def test_segments_are_reassembled_in_order_under_concurrency() -> None:
    provider = StubProvider()  # echo, deterministic regardless of order
    segments = [_prose(i, f"Sentence number {i} on dataset [1{i}].") for i in range(6)]
    out = RewriteStage(provider, max_workers=4).run(_doc(*segments), RunContext())
    for i, seg in enumerate(out.segments):
        assert seg.index == i
        assert f"number {i}" in seg.text  # no cross-contamination between workers


def test_voice_sample_is_included_in_the_prompt() -> None:
    captured: dict[str, Any] = {}

    class CaptureProvider:
        name = "capture"

        def __init__(self) -> None:
            self.usage = TokenUsage()

        def complete(self, prompt: str, system: str | None = None, **opts: Any) -> str:
            captured["system"] = system
            return prompt  # echo

    voice = (
        "We ran the study on a small cohort. The effect was modest but clear. "
        "We do not claim more than the data support. Others may read it differently."
    )
    RewriteStage(CaptureProvider(), max_workers=1).run(
        _doc(_prose(0, CITED)),
        RunContext(intensity=Intensity.BALANCED, voice_sample=voice),
    )
    assert "Match the author's voice" in captured["system"]
    assert "for feel" in captured["system"]


def test_report_records_segment_counts() -> None:
    provider = StubProvider()
    out = RewriteStage(provider, max_workers=1).run(
        _doc(
            Segment(index=0, text="# Title", heading=True, frozen=True, kind="heading"),
            _prose(1, CITED),
        ),
        RunContext(),
    )
    notes = out.reports[-1].notes
    assert notes["segments"] == 2
    assert notes["frozen"] == 1
    assert notes["rewritten"] == 1
