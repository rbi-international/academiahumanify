"""Evaluation harness tests: fidelity gate, quality scoring, voice match."""

from __future__ import annotations

from app.eval import evaluate
from app.pipeline.stylometry import extract


def test_faithful_rewrite_passes_fidelity() -> None:
    original = "The utilisation of the method may suggest a benefit. It is important to note this."
    rewritten = "The method may suggest a benefit. We note this."
    ev = evaluate(original, rewritten)
    assert ev.fidelity.passed
    assert ev.eligible


def test_strengthened_claim_fails_the_gate() -> None:
    # "may suggest" (tentative) turned into "demonstrates" (definitive): overclaim.
    original = "The data may suggest an association between the two variables."
    rewritten = "The data demonstrates an association between the two variables."
    ev = evaluate(original, rewritten)
    assert ev.fidelity.claim_strengthened
    assert not ev.fidelity.passed
    assert not ev.eligible


def test_weakened_claim_is_flagged_but_not_gated() -> None:
    original = "The experiment demonstrates a causal link."
    rewritten = "The experiment may suggest a causal link."
    ev = evaluate(original, rewritten)
    assert ev.fidelity.claim_weakened
    # Weakening is drift, flagged, but not the cardinal sin, so it still passes.
    assert ev.fidelity.passed


def test_leftover_placeholder_fails_fidelity() -> None:
    ev = evaluate("The result was ⟦PA⟧ percent.", "The result was ⟦PA⟧ percent still masked.")
    assert not ev.fidelity.placeholders_ok
    assert not ev.fidelity.passed


def test_quality_rewards_removing_ai_diction() -> None:
    original = (
        "Moreover, we delve into a robust and comprehensive framework that "
        "leverages a seamless pipeline. It is important to note the results."
    )
    ai_heavy = original  # unchanged: still full of tells
    human = "We built a simple pipeline and tested it. The results held up."
    worse = evaluate(original, ai_heavy)
    better = evaluate(original, human)
    assert better.quality.score > worse.quality.score
    assert better.quality.ai_diction_after < worse.quality.ai_diction_after
    assert better.quality.tells_removed > 0


def test_voice_match_prefers_the_closer_style() -> None:
    # Author writes short, punchy sentences with little hedging.
    sample = (
        "We ran the test. It worked. We checked it twice. The numbers held. "
        "We report them plainly. No more, no less. The method is simple. It scales."
    )
    voice = extract(sample)
    original = "The methodology was utilised in order to obtain the result."
    close = "We used the method. We got the result."
    far = (
        "The methodology, which was carefully and comprehensively designed over a "
        "considerable period, was ultimately utilised in order to obtain a result."
    )
    near = evaluate(original, close, voice)
    distant = evaluate(original, far, voice)
    assert near.voice.available
    assert near.voice.score > distant.voice.score


def test_change_ratio_bounds() -> None:
    assert evaluate("same text here", "same text here").change_ratio == 0.0
    assert evaluate("alpha beta gamma", "delta epsilon zeta").change_ratio == 1.0


def test_no_voice_sample_leaves_voice_unavailable() -> None:
    ev = evaluate("The method works.", "The method works well.")
    assert not ev.voice.available
    assert ev.quality_rank == ev.quality.score  # ranking is quality-only


def test_to_dict_is_serialisable() -> None:
    ev = evaluate("The method works.", "The method works well.")
    d = ev.to_dict()
    assert set(d) >= {"eligible", "fidelity", "quality", "voice", "change_ratio", "quality_rank"}
    assert isinstance(d["fidelity"]["passed"], bool)
