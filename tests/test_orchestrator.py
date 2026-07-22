"""M10 orchestrator tests: a full run, the audit trail, and failure isolation."""

from __future__ import annotations

import json
from typing import Any

from app.llm.base import TokenUsage
from app.llm.stub import StubProvider
from app.pipeline.base import Intensity, RunContext, Section
from app.services import run_pipeline
from app.services.orchestrator import RunResult

PAPER = """# Introduction

It was observed that the utilisation of the method improved accuracy by 12.4% on dataset [17].

## Methods

We collected data from 30 subjects. The procedure was repeated three times.

## Results

The effect was significant (p < 0.05). The model may suggest a link to rainfall.

## References

[1] Smith, J. A relevant paper. Journal of Things, 2020.
"""


def _run(provider: Any = None, **kwargs: Any) -> RunResult:
    provider = provider or StubProvider()  # echo
    return run_pipeline(PAPER, RunContext(intensity=Intensity.BALANCED), provider, **kwargs)


def test_full_paper_run_end_to_end() -> None:
    result = _run()
    assert result.ok
    assert result.failed_segments == 0
    # Every stage recorded a report: segment, rewrite, verify, changelog.
    stages = [r.stage for r in result.reports]
    assert stages == ["segment", "rewrite", "verify", "changelog"]
    # The document was segmented and section-aware.
    assert any(s.section is Section.METHODS for s in result.rewritten.segments)


def test_frozen_segments_survive_the_run_byte_identical() -> None:
    result = _run()
    frozen_pairs = [
        (o.text, r.text)
        for o, r in zip(result.original.segments, result.rewritten.segments, strict=True)
        if o.frozen
    ]
    assert frozen_pairs  # there are headings and references
    for original_text, rewritten_text in frozen_pairs:
        assert original_text == rewritten_text


def test_echo_run_passes_verification_cleanly() -> None:
    result = _run()
    # Echo returns the text unchanged, so nothing drifted and nothing was lost.
    assert result.verification.passed
    assert not result.verification.fidelity_failures


def test_audit_trail_carries_stage_notes() -> None:
    result = _run()
    by_stage = {r.stage: r for r in result.reports}
    assert by_stage["segment"].notes["section_aware"] is True
    assert by_stage["rewrite"].notes["frozen"] >= 1
    assert "passed" in by_stage["verify"].notes
    assert "summary" in by_stage["changelog"].notes


def test_partial_failure_isolation_keeps_the_run_alive() -> None:
    # A provider that corrupts one specific segment and echoes the rest.
    class _Poison:
        name = "poison"

        def __init__(self) -> None:
            self.usage = TokenUsage()

        def complete(self, prompt: str, system: str | None = None, **opts: Any) -> str:
            if "POISON" in prompt:
                return "this reply carries no protected tokens at all"
            return prompt

    text = (
        "The first paragraph is clean and mentions dataset [17].\n\n"
        "The second paragraph contains POISON and also cites [42] here.\n\n"
        "The third paragraph is fine and reports a gain of 5%."
    )
    result = run_pipeline(text, RunContext(), _Poison())

    # The run completed rather than raising.
    assert result.failed_segments == 1
    # The poisoned segment kept its original text, so its citation is intact.
    poisoned = [s for s in result.rewritten.segments if "POISON" in s.text]
    assert poisoned and "[42]" in poisoned[0].text
    # Fidelity held for the whole document.
    assert result.verification.passed
    assert result.ok


def test_result_serialises_to_json() -> None:
    result = _run()
    payload = json.dumps(result.to_dict())  # must be JSON-serialisable
    data = json.loads(payload)
    assert data["ok"] is True
    assert set(data) >= {
        "ok", "failed_segments", "rewritten_text", "verification", "changelog", "audit_trail"
    }
    assert len(data["audit_trail"]) == 4


def test_methods_run_uses_conservative_intensity() -> None:
    result = _run()
    refs = result.reports[1].notes["prompt_refs"]  # the rewrite report
    # A Methods segment exists, so its conservative prompt must have been used.
    assert any("system/intensity/conservative" in r for r in refs)
