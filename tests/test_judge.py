"""LLM-judge tests, against the stub provider (no network)."""

from __future__ import annotations

from app.eval import JudgeVerdict, judge_rewrites
from app.llm.stub import StubProvider
from app.prompts import default_registry

_ORIGINAL = "The data may suggest a benefit."
_REWRITES = {"alpha": "The data may suggest a benefit.", "beta": "The data hints at a benefit."}


def test_judge_prompt_exists() -> None:
    assert default_registry().get("system/judge").text.strip()


def test_parses_a_valid_verdict() -> None:
    verdict = '{"ranking": ["beta", "alpha"], "best": "beta", ' \
              '"rationale": {"beta": "cleaner", "alpha": "wordier"}}'
    provider = StubProvider(default_response=verdict)
    result = judge_rewrites(_ORIGINAL, _REWRITES, provider)
    assert result.ok
    assert result.best_label == "beta"
    assert result.ranking == ("beta", "alpha")
    assert result.rationale["beta"] == "cleaner"


def test_json_wrapped_in_prose_is_still_parsed() -> None:
    reply = 'Sure, here is my call:\n{"ranking": ["alpha"], "best": "alpha"}\nHope that helps.'
    provider = StubProvider(default_response=reply)
    result = judge_rewrites(_ORIGINAL, {"alpha": "x"}, provider)
    assert result.best_label == "alpha"


def test_unknown_labels_are_dropped() -> None:
    verdict = '{"ranking": ["beta", "ghost"], "best": "ghost", "rationale": {"ghost": "n/a"}}'
    provider = StubProvider(default_response=verdict)
    result = judge_rewrites(_ORIGINAL, _REWRITES, provider)
    # "ghost" was never a candidate, so it is dropped and best falls back to the
    # head of the valid ranking.
    assert "ghost" not in result.ranking
    assert result.best_label == "beta"
    assert "ghost" not in result.rationale


def test_malformed_reply_degrades_to_no_opinion() -> None:
    provider = StubProvider(default_response="I cannot decide, sorry.")
    result = judge_rewrites(_ORIGINAL, _REWRITES, provider)
    assert not result.ok
    assert result.best_label is None
    assert isinstance(result, JudgeVerdict)
    assert result.raw  # the raw reply is kept for inspection
